"""알라딘 — 전자책 베스트셀러.

크롤링 안정성이 높아 백업 소스 겸용 (설계 문서 2장 #6).
목록 페이지의 도서 블록은 div.ss_book_box (itemId 속성 보유).
"""
from bs4 import BeautifulSoup

from . import common

BASE = "https://www.aladin.co.kr/shop/common/wbest.aspx"


def _parse_author_line(box) -> tuple[str, str]:
    """'저자 (지은이) | 출판사 | 2026년 1월' 형태의 정보 줄에서 저자/출판사 추출."""
    for li in box.select("li"):
        text = common.clean(li.get_text(" "))
        if "(지은이)" in text or ("|" in text and "원" not in text):
            parts = [p.strip() for p in text.split("|")]
            author = parts[0].replace("(지은이)", "").strip() if parts else ""
            publisher = parts[1] if len(parts) > 1 else ""
            return author, publisher
    return "", ""


def _crawl_pages(branch_type: str, pages: int = 2) -> list[dict]:
    rows: list[dict] = []
    for page in range(1, pages + 1):
        resp = common.fetch(BASE, params={
            "BestType": "Bestseller",
            "BranchType": branch_type,
            "CID": "0",
            "page": page,
        })
        soup = BeautifulSoup(resp.text, "lxml")
        boxes = soup.select("div.ss_book_box")
        if not boxes:
            common.save_snapshot(f"aladin_branch{branch_type}_p{page}.html", resp.text)
            raise RuntimeError(
                f"도서 블록(div.ss_book_box)을 찾지 못함 — 페이지 구조 변경 의심 (page={page})"
            )
        for box in boxes:
            title_a = box.select_one("a.bo3")
            if not title_a:
                continue
            author, publisher = _parse_author_line(box)
            item_id = box.get("itemid") or box.get("itemId") or ""
            href = title_a.get("href", "")
            if not item_id and "ItemId=" in href:
                item_id = href.split("ItemId=")[-1].split("&")[0]
            rows.append(common.make_row(
                rank=len(rows) + 1,
                title=title_a.get_text(),
                author=author,
                publisher=publisher,
                product_id=item_id,
                url=href,
            ))
    return rows


def crawl_ebook() -> list[dict]:
    # BranchType=5 = 전자책. 구조 변경 시 스냅샷으로 진단.
    return _crawl_pages("5")


JOBS = [
    common.ChartJob("aladin", "ebook_best", "ebook", crawl_ebook),
]
