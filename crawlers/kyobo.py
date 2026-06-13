"""교보문고 — 종합 베스트셀러 / 전자책 베스트.

신규 교보 사이트(product.kyobobook.co.kr)는 SSR이라 HTML에 목록이 포함된다.
도서 블록: li.prod_item / 제목: .prod_name (또는 a.prod_info 내부)
저자 줄: .prod_author — "저자 · 출판사 · 날짜" 형태.
구조가 바뀌었거나 JS 전용 렌더링으로 전환된 경우 스냅샷을 남기고 실패 보고한다.
"""
import re

from bs4 import BeautifulSoup

from . import common

GENERAL_URL = "https://product.kyobobook.co.kr/bestseller/online"
EBOOK_URL = "https://product.kyobobook.co.kr/bestseller/ebook"


def _parse_author_line(item) -> tuple[str, str]:
    el = item.select_one(".prod_author")
    if not el:
        return "", ""
    text = common.clean(el.get_text(" "))
    parts = [p.strip() for p in re.split(r"[·ㆍ]", text)]
    author = parts[0] if parts else ""
    # 마지막 토큰이 날짜(2026.06.01 등)이면 그 앞이 출판사
    publisher = ""
    if len(parts) >= 2:
        publisher = parts[-2] if re.match(r"\d{4}", parts[-1]) else parts[-1]
    return author, publisher


def _crawl(url: str, label: str, pages: int = 2) -> list[dict]:
    rows: list[dict] = []
    for page in range(1, pages + 1):
        resp = common.fetch(url, params={"page": page, "per": 50})
        soup = BeautifulSoup(resp.text, "lxml")
        items = soup.select("li.prod_item")
        if not items:
            common.save_snapshot(f"kyobo_{label}_p{page}.html", resp.text)
            if page == 1:
                raise RuntimeError(
                    "도서 블록(li.prod_item)을 찾지 못함 — JS 렌더링 전환 또는 구조 변경 의심"
                )
            break  # 2페이지가 없는 차트는 1페이지 분량만 저장
        for item in items:
            name_el = item.select_one(".prod_name") or item.select_one(".prod_info")
            link = item.select_one("a.prod_info") or item.select_one(".prod_name a") or item.select_one("a[href*='/detail/']")
            if not name_el:
                continue
            href = link.get("href", "") if link else ""
            m = re.search(r"/detail/(S\d+)", href)
            product_id = m.group(1) if m else ""
            author, publisher = _parse_author_line(item)
            rating_el = item.select_one(".review_klover_text") or item.select_one(".prod_grade")
            review_el = item.select_one(".review_desc") or item.select_one(".prod_review_count")
            rows.append(common.make_row(
                rank=len(rows) + 1,
                title=name_el.get_text(),
                author=author,
                publisher=publisher,
                rating=rating_el.get_text() if rating_el else "",
                review_count=review_el.get_text() if review_el else "",
                product_id=product_id,
                url=href,
            ))
    return rows


def crawl_general() -> list[dict]:
    return _crawl(GENERAL_URL, "general")


def crawl_ebook() -> list[dict]:
    return _crawl(EBOOK_URL, "ebook")


JOBS = [
    common.ChartJob("kyobo", "general_best", "general", crawl_general),
    common.ChartJob("kyobo", "ebook_best", "ebook", crawl_ebook),
]
