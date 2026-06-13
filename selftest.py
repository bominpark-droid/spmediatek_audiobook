"""네트워크 없이 실행하는 구조 점검.

이 환경은 도서 사이트로 못 나가므로(host_not_allowed) 실제 크롤링은 GitHub Actions
에서 검증한다. 여기서는 네트워크가 필요 없는 부분만 점검한다:
- 모든 크롤러 모듈 import 및 JOBS 형식
- 유틸 함수(clean/to_int/to_float)
- CSV 스키마 라운드트립
- 합성 데이터로 주간 요약 생성

사용: python selftest.py
"""
import importlib
import sys
import tempfile
from pathlib import Path

from crawlers import CRAWLER_MODULES, common

FAIL = []


def check(name, cond, detail=""):
    mark = "OK " if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        FAIL.append(name)


def test_modules():
    seen = set()
    total_jobs = 0
    for mod_name in CRAWLER_MODULES:
        mod = importlib.import_module(f"crawlers.{mod_name}")
        jobs = getattr(mod, "JOBS", None)
        check(f"{mod_name}: JOBS 존재", isinstance(jobs, list) and len(jobs) > 0)
        for job in jobs or []:
            total_jobs += 1
            key = (job.platform, job.chart)
            check(f"{mod_name}: {job.platform}/{job.chart} 형식",
                  bool(job.platform and job.chart and job.slug and callable(job.func)))
            check(f"{mod_name}: {key} 중복 없음", key not in seen)
            seen.add(key)
    check("총 작업 수 = 10 (설계 문서 10개 차트)", total_jobs == 10,
          f"실제 {total_jobs}개")


def test_helpers():
    check("clean 공백정리", common.clean("  a\n b ") == "a b")
    check("clean None→빈값", common.clean(None) == "")
    check("to_int '1,234개'→1234", common.to_int("1,234개") == "1234")
    check("to_int None→빈값", common.to_int(None) == "")
    check("to_float '평점 4.5'→4.5", common.to_float("평점 4.5") == "4.5")
    row = common.make_row(1, " 책제목 ", author="저자", review_count="12개")
    check("make_row 스키마/정리", row["title"] == "책제목" and row["review_count"] == "12"
          and row["publisher"] == "")


def test_csv_roundtrip():
    import csv
    import datetime
    rows = [common.make_row(1, "가나다", author="홍길동", url="http://x/1"),
            common.make_row(2, "라마바", publisher="출판사")]
    with tempfile.TemporaryDirectory() as d:
        orig = common.DATA_DIR
        common.DATA_DIR = Path(d)
        try:
            path = common.write_csv(rows, datetime.date(2026, 6, 14),
                                    "aladin", "ebook_best", "ebook")
            with open(path, encoding="utf-8-sig") as f:
                got = list(csv.DictReader(f))
            check("CSV 파일명 규칙", path.name == "2026-06-14_aladin_ebook.csv")
            check("CSV 헤더=스키마", list(got[0].keys()) == common.FIELDS)
            check("CSV date/platform/chart 채움",
                  got[0]["date"] == "2026-06-14" and got[0]["platform"] == "aladin"
                  and got[0]["chart"] == "ebook_best")
            check("CSV 빈 필드 유지", got[1]["author"] == "")
        finally:
            common.DATA_DIR = orig


def test_summary():
    import csv
    import datetime
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        import summary as sm
        sm.DATA_DIR = base / "data"
        sm.LOG_DIR = base / "logs"
        sm.DATA_DIR.mkdir(parents=True)

        def write(date, titles):
            sub = sm.DATA_DIR / "2026" / "06"
            sub.mkdir(parents=True, exist_ok=True)
            p = sub / f"{date}_aladin_ebook.csv"
            with open(p, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=common.FIELDS)
                w.writeheader()
                for i, t in enumerate(titles, 1):
                    w.writerow({"date": date, "platform": "aladin",
                                "chart": "ebook_best", "rank": i, "title": t})
        # 1주 간격 두 회차: 신규 진입 '신간' 1건이 잡혀야 함
        write("2026-06-07", [f"책{i}" for i in range(1, 11)])
        write("2026-06-14", ["신간"] + [f"책{i}" for i in range(1, 10)])
        out = sm.build_summary()
        chart = out["charts"][0]
        check("요약 TOP_N", len(chart["top"]) == 10)
        check("요약 신규 진입 감지", chart["new_entries"] == ["신간"],
              f"got {chart['new_entries']}")


if __name__ == "__main__":
    print("=== 구조 자체 점검 (네트워크 불필요) ===")
    test_modules()
    test_helpers()
    test_csv_roundtrip()
    test_summary()
    print("=" * 40)
    if FAIL:
        print(f"실패 {len(FAIL)}건: {FAIL}")
        sys.exit(1)
    print("전체 통과 — 코드 구조 정상. 실제 크롤링은 Actions에서 검증.")
