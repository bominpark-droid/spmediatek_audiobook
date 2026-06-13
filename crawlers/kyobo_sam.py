"""교보문고 sam — 오디오북 인기 차트.

설계 문서 2장 #3: 로그인 없이 접근 가능한지 구축 시 확인 대상.
sam 차트가 비공개일 가능성이 있어 후보 URL을 순차 시도하고,
모두 실패하면 스냅샷과 함께 실패 보고한다 (전체 수집은 계속 진행).
대체 경로: 교보 오디오북 카테고리 베스트.
"""
import re

from bs4 import BeautifulSoup

from . import common

# 후보 1: 교보 디지털(sam) 오디오북 베스트 / 후보 2: 일반몰 오디오북 카테고리 베스트
CANDIDATES = [
    "https://sam.kyobobook.co.kr/best/audiobook",
    "https://product.kyobobook.co.kr/bestseller/audio",
    "https://product.kyobobook.co.kr/category/best/audio",
]


def _try_parse(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    items = soup.select("li.prod_item")
    rows: list[dict] = []
    for item in items:
        name_el = item.select_one(".prod_name") or item.select_one("a[href*='/detail/']")
        if not name_el:
            continue
        link = item.select_one("a[href*='/detail/']")
        href = link.get("href", "") if link else ""
        m = re.search(r"/detail/(S\d+)", href)
        author_el = item.select_one(".prod_author")
        rows.append(common.make_row(
            rank=len(rows) + 1,
            title=name_el.get_text(),
            author=author_el.get_text(" ") if author_el else "",
            product_id=m.group(1) if m else "",
            url=href,
        ))
    return rows


def crawl_audiobook() -> list[dict]:
    errors = []
    for url in CANDIDATES:
        try:
            resp = common.fetch(url)
        except Exception as e:  # 404, 로그인 리다이렉트 등 — 다음 후보 시도
            errors.append(f"{url} → {e}")
            continue
        rows = _try_parse(resp.text)
        if rows:
            return rows
        common.save_snapshot(f"kyobo_sam_{url.split('/')[-1]}.html", resp.text)
        errors.append(f"{url} → 응답은 받았으나 목록 파싱 0건")
    raise RuntimeError(
        "교보 sam 오디오북 차트 접근 실패 — 로그인 장벽 또는 URL 변경 가능성. "
        "스냅샷 확인 후 대체 경로 결정 필요. 시도 내역: " + " | ".join(errors)
    )


JOBS = [
    common.ChartJob("kyobo_sam", "audiobook_best", "audiobook", crawl_audiobook),
]
