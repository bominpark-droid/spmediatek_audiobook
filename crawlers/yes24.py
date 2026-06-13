"""예스24 — 종합 베스트 / 전자책 베스트.

베스트셀러 페이지: /product/category/bestseller?categoryNumber=...
- 001: 종합(국내도서)
- 017: eBook
목록은 ul#yesBestList 아래 li (data-goods-no 속성 보유).
"""
import re

from bs4 import BeautifulSoup

from . import common

BASE = "https://www.yes24.com/product/category/bestseller"


def _crawl(category_number: str, label: str) -> list[dict]:
    resp = common.fetch(BASE, params={
        "categoryNumber": category_number,
        "pageNumber": 1,
        "pageSize": 100,
    })
    soup = BeautifulSoup(resp.text, "lxml")
    items = soup.select("#yesBestList li[data-goods-no]") or soup.select("#yesBestList > li")
    if not items:
        common.save_snapshot(f"yes24_{label}.html", resp.text)
        raise RuntimeError("목록(#yesBestList li)을 찾지 못함 — 페이지 구조 변경 의심")

    rows: list[dict] = []
    for li in items:
        name_a = li.select_one("a.gd_name")
        if not name_a:
            continue
        href = name_a.get("href", "")
        if href.startswith("/"):
            href = "https://www.yes24.com" + href
        goods_no = li.get("data-goods-no", "")
        if not goods_no:
            m = re.search(r"/goods/(\d+)", href)
            goods_no = m.group(1) if m else ""
        author_el = li.select_one(".info_auth") or li.select_one(".authPub.info_auth")
        pub_el = li.select_one(".info_pub") or li.select_one(".authPub.info_pub")
        rating_el = li.select_one(".rating_grade .yes_b") or li.select_one("em.yes_b")
        review_el = li.select_one(".rating_rvCount em") or li.select_one(".rating_rvCount")
        rows.append(common.make_row(
            rank=len(rows) + 1,
            title=name_a.get_text(),
            author=author_el.get_text(" ") if author_el else "",
            publisher=pub_el.get_text(" ") if pub_el else "",
            rating=rating_el.get_text() if rating_el else "",
            review_count=review_el.get_text() if review_el else "",
            product_id=goods_no,
            url=href,
        ))
    return rows


def crawl_general() -> list[dict]:
    return _crawl("001", "general")


def crawl_ebook() -> list[dict]:
    return _crawl("017", "ebook")


JOBS = [
    common.ChartJob("yes24", "general_best", "general", crawl_general),
    common.ChartJob("yes24", "ebook_best", "ebook", crawl_ebook),
]
