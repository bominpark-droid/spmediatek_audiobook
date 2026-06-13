"""Audible US — Best Sellers.

글로벌 트렌드 + 스토리팝용 (설계 문서 2장 #10).
목록: li.productListItem / 제목: h3 내 링크 / 저자: li.authorLabel a
ASIN은 상품 링크(/pd/<slug>/<ASIN>)에서 추출.
"""
import re

from bs4 import BeautifulSoup

from . import common

URL = "https://www.audible.com/adblbestsellers"


def crawl_bestsellers() -> list[dict]:
    resp = common.fetch(URL, params={"pageSize": 50},
                        headers={"Accept-Language": "en-US,en;q=0.9"})
    soup = BeautifulSoup(resp.text, "lxml")
    items = soup.select("li.productListItem")
    if not items:
        common.save_snapshot("audible_bestsellers.html", resp.text)
        raise RuntimeError("목록(li.productListItem)을 찾지 못함 — 페이지 구조 변경 의심")

    rows: list[dict] = []
    for li in items:
        title_a = li.select_one("h3 a") or li.select_one("a.bc-link[href*='/pd/']")
        if not title_a:
            continue
        href = title_a.get("href", "").split("?")[0]
        if href.startswith("/"):
            href = "https://www.audible.com" + href
        m = re.search(r"/pd/[^/]+/(B[A-Z0-9]{9})", href) or re.search(r"/(B[A-Z0-9]{9})", href)
        asin = m.group(1) if m else ""
        author_el = li.select_one("li.authorLabel a") or li.select_one(".authorLabel")
        rating_el = li.select_one("li.ratingsLabel span.bc-pub-offscreen")
        review_el = li.select_one("li.ratingsLabel span.bc-color-secondary")
        rows.append(common.make_row(
            rank=len(rows) + 1,
            title=title_a.get_text(),
            author=author_el.get_text(" ") if author_el else "",
            rating=rating_el.get_text() if rating_el else "",
            review_count=review_el.get_text() if review_el else "",
            product_id=asin,
            url=href,
        ))
    return rows


JOBS = [
    common.ChartJob("audible_us", "best_sellers", "bestsellers", crawl_bestsellers),
]
