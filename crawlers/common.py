"""공통 유틸리티 — 정중한 HTTP 요청, robots.txt 확인, CSV 저장.

크롤링 매너 원칙 (설계 문서 6장):
- 요청 간 2~5초 간격
- robots.txt 확인 및 존중
- User-Agent 명시
- 공개 페이지만 수집 (로그인 영역 우회 금지)
"""
from __future__ import annotations

import csv
import datetime
import logging
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib import robotparser
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"
SNAPSHOT_DIR = LOG_DIR / "snapshots"  # 파싱 실패 시 원본 HTML 저장 (git에는 미포함)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 "
    "SPBookDataBot/1.0 (book chart research; contact: bominpark@hotmail.com)"
)

FIELDS = [
    "date", "platform", "chart", "rank", "title", "author", "publisher",
    "category", "rating", "review_count", "product_id", "url",
]

MIN_DELAY = 2.0
MAX_DELAY = 5.0

log = logging.getLogger("crawler")

_last_request_at = 0.0
_robots_cache: dict[str, robotparser.RobotFileParser | None] = {}


@dataclass
class ChartJob:
    """차트 1개 = 수집 작업 1개. 작업 단위로 성공/실패를 독립 처리한다."""
    platform: str   # 예: yes24
    chart: str      # 예: general_best
    slug: str       # CSV 파일명용 짧은 이름. 예: general
    func: Callable[[], list[dict]]


def today_kst() -> datetime.date:
    return datetime.datetime.now(ZoneInfo("Asia/Seoul")).date()


def polite_sleep() -> None:
    """직전 요청으로부터 2~5초가 지나도록 대기한다 (사이트 무관 전역 적용)."""
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    wait = random.uniform(MIN_DELAY, MAX_DELAY) - elapsed
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def robots_allowed(url: str) -> bool:
    """robots.txt를 확인한다. robots.txt 자체를 못 읽으면 허용으로 간주(기록만)."""
    origin = "{0.scheme}://{0.netloc}".format(urlparse(url))
    if origin not in _robots_cache:
        rp = robotparser.RobotFileParser()
        try:
            resp = requests.get(
                origin + "/robots.txt",
                headers={"User-Agent": USER_AGENT},
                timeout=15,
            )
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
                _robots_cache[origin] = rp
            else:
                _robots_cache[origin] = None
        except requests.RequestException as e:
            log.warning("robots.txt 확인 실패(%s): %s — 허용으로 간주", origin, e)
            _robots_cache[origin] = None
    rp = _robots_cache[origin]
    if rp is None:
        return True
    return rp.can_fetch(USER_AGENT, url) or rp.can_fetch("*", url)


def fetch(url: str, *, params: dict | None = None, headers: dict | None = None,
          timeout: int = 25) -> requests.Response:
    """매너 원칙(간격·robots·UA)을 적용한 GET 요청."""
    if not robots_allowed(url):
        raise PermissionError(f"robots.txt 비허용: {url} — 이 차트는 수집하지 않는다")
    polite_sleep()
    h = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.5",
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    }
    if headers:
        h.update(headers)
    resp = requests.get(url, params=params, headers=h, timeout=timeout)
    resp.raise_for_status()
    return resp


def save_snapshot(name: str, content: str | bytes) -> Path:
    """파싱 실패 진단용으로 응답 원본을 저장한다. Actions 아티팩트로 업로드됨."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{today_kst()}_{name}"
    mode = "wb" if isinstance(content, bytes) else "w"
    with open(path, mode, encoding=None if isinstance(content, bytes) else "utf-8") as f:
        f.write(content)
    return path


def clean(text: str | None) -> str:
    """공백 정리. None은 빈 문자열로 (추정·생성 금지 원칙)."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def to_int(text: str | None) -> str:
    """'1,234개' 같은 문자열에서 정수만 추출. 실패 시 빈 값."""
    if text is None:
        return ""
    m = re.search(r"[\d,]+", str(text))
    return m.group().replace(",", "") if m else ""


def to_float(text: str | None) -> str:
    if text is None:
        return ""
    m = re.search(r"\d+(?:\.\d+)?", str(text))
    return m.group() if m else ""


def make_row(rank: int, title: str, *, author: str = "", publisher: str = "",
             category: str = "", rating: str = "", review_count: str = "",
             product_id: str = "", url: str = "") -> dict:
    """스키마에 맞는 행 생성. date/platform/chart는 저장 시점에 채워진다."""
    return {
        "rank": rank,
        "title": clean(title),
        "author": clean(author),
        "publisher": clean(publisher),
        "category": clean(category),
        "rating": to_float(rating),
        "review_count": to_int(review_count),
        "product_id": clean(product_id),
        "url": clean(url),
    }


def write_csv(rows: list[dict], date: datetime.date, platform: str,
              chart: str, slug: str) -> Path:
    """data/YYYY/MM/YYYY-MM-DD_<platform>_<slug>.csv 로 저장."""
    out_dir = DATA_DIR / f"{date:%Y}" / f"{date:%m}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{date:%Y-%m-%d}_{platform}_{slug}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            full = {"date": f"{date:%Y-%m-%d}", "platform": platform, "chart": chart}
            full.update(row)
            writer.writerow({k: full.get(k, "") for k in FIELDS})
    return path
