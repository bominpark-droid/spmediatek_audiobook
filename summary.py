"""주간 요약 → Google Sheets 푸시.

설계 문서 4장: 주 1회, 각 차트 TOP 10 + 신규 진입 도서만 푸시 (폰 확인용).
전체 데이터는 Sheets에 넣지 않는다 (셀 한도).

동작:
1) data/ 에서 차트별 최신 CSV를 찾아 TOP 10 추출
2) 약 7일 전 같은 차트 CSV와 비교해 '신규 진입' 도서 계산
3) SHEETS_WEBHOOK_URL(Apps Script 웹앱) 이 있으면 POST, 없으면 미리보기 JSON만 저장

전체 데이터는 GitHub의 CSV가 원본이므로 Sheets 실패는 자산 손실이 아니다.
"""
from __future__ import annotations

import csv
import datetime
import json
import os
from collections import defaultdict
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"
TOP_N = 10
LOOKBACK_DAYS = 7


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _all_csvs() -> list[Path]:
    return sorted(DATA_DIR.glob("**/*.csv"))


def _key(path: Path) -> str:
    """파일명 'YYYY-MM-DD_platform_slug.csv' 에서 platform_slug(차트 식별) 추출."""
    stem = path.stem
    return stem.split("_", 1)[1] if "_" in stem else stem


def _date_of(path: Path) -> str:
    return path.stem.split("_", 1)[0]


def build_summary() -> dict:
    by_chart: dict[str, list[Path]] = defaultdict(list)
    for p in _all_csvs():
        by_chart[_key(p)].append(p)

    charts = []
    for chart_key, paths in sorted(by_chart.items()):
        paths.sort(key=_date_of)
        latest = paths[-1]
        latest_rows = _read_csv(latest)
        top = latest_rows[:TOP_N]

        # 신규 진입: 최신 TOP_N 중, LOOKBACK_DAYS 이전(또는 그에 가장 가까운 과거) 회차에
        # 없던 제목. 비교 대상이 없으면 신규 판정을 생략한다(첫 수집 주에는 모두 신규로 보지 않음).
        latest_date = datetime.date.fromisoformat(_date_of(latest))
        prev_path = None
        for p in reversed(paths[:-1]):
            d = datetime.date.fromisoformat(_date_of(p))
            if (latest_date - d).days >= LOOKBACK_DAYS:
                prev_path = p
                break
        if prev_path is None and len(paths) > 1:
            prev_path = paths[0]  # 7일치가 아직 없으면 가장 오래된 회차와 비교

        new_entries = []
        if prev_path is not None:
            prev_titles = {r["title"] for r in _read_csv(prev_path)}
            new_entries = [r["title"] for r in top if r["title"] not in prev_titles]

        platform = top[0]["platform"] if top else chart_key
        chart_id = top[0]["chart"] if top else ""
        charts.append({
            "platform": platform,
            "chart": chart_id,
            "key": chart_key,
            "date": _date_of(latest),
            "top": [
                {"rank": r["rank"], "title": r["title"], "author": r["author"],
                 "url": r["url"]}
                for r in top
            ],
            "new_entries": new_entries,
            "compared_with": _date_of(prev_path) if prev_path else None,
        })

    return {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "top_n": TOP_N,
        "charts": charts,
    }


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not list(_all_csvs()):
        print("data/ 에 CSV가 없음 — 요약 생략 (아직 수집 전)")
        return 0

    summary = build_summary()
    preview = LOG_DIR / "summary_preview.json"
    preview.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"요약 생성: 차트 {len(summary['charts'])}개 → {preview.name}")

    url = os.environ.get("SHEETS_WEBHOOK_URL", "").strip()
    if not url:
        print("SHEETS_WEBHOOK_URL 미설정 — 미리보기 JSON만 저장하고 종료 (정상)")
        return 0

    try:
        resp = requests.post(url, json=summary, timeout=30)
        resp.raise_for_status()
        print(f"Google Sheets 푸시 완료: HTTP {resp.status_code}")
    except requests.RequestException as e:
        # Sheets 실패는 자산 손실이 아니므로 잡을 실패시키지 않는다(원본은 CSV).
        print(f"Google Sheets 푸시 실패(무시 가능, 원본은 CSV에 보존): {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
