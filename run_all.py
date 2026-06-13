"""전체 크롤러 실행 오케스트레이터.

- 차트(작업) 단위로 격리 실행: 하나가 깨져도 나머지는 계속 진행
- 결과를 logs/YYYY-MM-DD_status.json + logs/crawl.log 에 기록
- 실패가 하나라도 있으면 종료 코드 1 (GitHub Actions 실패 알림 트리거)
"""
import importlib
import json
import logging
import sys
import traceback

from crawlers import CRAWLER_MODULES, common


def main() -> int:
    common.LOG_DIR.mkdir(parents=True, exist_ok=True)
    date = common.today_kst()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(common.LOG_DIR / "crawl.log", encoding="utf-8"),
        ],
    )
    log = logging.getLogger("run_all")
    results = []

    for mod_name in CRAWLER_MODULES:
        try:
            mod = importlib.import_module(f"crawlers.{mod_name}")
            jobs = mod.JOBS
        except Exception as e:
            log.error("[%s] 모듈 로드 실패: %s", mod_name, e)
            results.append({"job": mod_name, "ok": False, "error": f"모듈 로드 실패: {e}"})
            continue

        for job in jobs:
            name = f"{job.platform}/{job.chart}"
            tag = " [공사중]" if job.experimental else ""
            try:
                rows = job.func()
                if not rows:
                    raise RuntimeError("0건 수집 — 파싱 결과 없음")
                path = common.write_csv(rows, date, job.platform, job.chart, job.slug)
                log.info("[%s]%s OK — %d건 → %s", name, tag, len(rows),
                         path.relative_to(common.ROOT))
                results.append({"job": name, "ok": True, "rows": len(rows),
                                "experimental": job.experimental,
                                "file": str(path.relative_to(common.ROOT))})
            except Exception as e:
                log.error("[%s]%s 실패: %s", name, tag, e)
                log.debug(traceback.format_exc())
                results.append({"job": name, "ok": False,
                                "experimental": job.experimental, "error": str(e)})

    # 정식 가동(experimental=False) 차트 실패만 알림 대상. 공사 중 실패는 기록만.
    prod_failed = sum(1 for r in results if not r["ok"] and not r.get("experimental"))
    exp_failed = sum(1 for r in results if not r["ok"] and r.get("experimental"))
    status = {
        "date": f"{date:%Y-%m-%d}",
        "ok": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "prod_failed": prod_failed,     # 워크플로 알림 게이트가 이 값을 읽는다
        "exp_failed": exp_failed,
        "results": results,
    }
    status_path = common.LOG_DIR / f"{date:%Y-%m-%d}_status.json"
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

    log.info("=" * 50)
    log.info("수집 완료: 성공 %d / 실패 %d (정식 실패 %d, 공사중 실패 %d)",
             status["ok"], status["failed"], prod_failed, exp_failed)
    for r in results:
        if not r["ok"]:
            mark = "공사중" if r.get("experimental") else "정식"
            log.info("  실패(%s) → %s: %s", mark, r["job"], r["error"])
    # 정식 차트가 깨졌을 때만 잡 실패 → 이메일 알림. 공사 중 실패는 통과.
    return 1 if prod_failed else 0


if __name__ == "__main__":
    sys.exit(main())
