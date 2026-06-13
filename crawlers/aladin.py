"""알라딘 — 전자책 베스트셀러.

크롤링 안정성이 높아 백업 소스 겸용 (설계 문서 2장 #6).

셀렉터 전략 (구조 변경 대응):
1) div.ss_book_box — 구 UI
2) li[class*="result_book"] / li[data-item-id] — 중간 UI
3) a[href*="ItemId="] 링크 기반 추출 — 최후 폴백 (구조 불문하고 동작)
4) __NEXT_DATA__ JSON (알라딘이 Next.js로 이전했을 경우 대비)
"""
import json
import re

from bs4 import BeautifulSoup

from . import common

BASE = "https://www.aladin.co.kr/shop/common/wbest.aspx"
PRODUCT_RE = re.compile(r"ItemId=(\d+)", re.I)


def _parse_ss_book_box(boxes) -> list[dict]:
    rows = []
    for box in boxes:
        title_a = box.select_one("a.bo3") or box.select_one("a[href*='ItemId']")
        if not title_a:
            continue
        href = title_a.get("href", "")
        m = PRODUCT_RE.search(href)
        item_id = m.group(1) if m else (box.get("itemid") or box.get("itemId") or "")
        # 저자·출판사: "홍길동 (지은이) | 출판사명 | 2026년 1월"
        author, publisher = "", ""
        for li in box.select("li"):
            t = common.clean(li.get_text(" "))
            if "|" in t and len(t) < 120:
                parts = [p.strip() for p in t.split("|")]
                author = parts[0].replace("(지은이)", "").replace("(엮은이)", "").strip()
                publisher = parts[1] if len(parts) > 1 else ""
                break
        rows.append(common.make_row(
            rank=len(rows) + 1, title=title_a.get_text(),
            author=author, publisher=publisher,
            product_id=item_id, url=href,
        ))
    return rows


def _link_fallback(soup: BeautifulSoup) -> list[dict]:
    """상품 링크(ItemId=) 기반 폴백 — 어떤 구조에서도 동작한다."""
    seen: set[str] = set()
    rows: list[dict] = []
    for a in soup.select("a[href*='ItemId=']"):
        href = a.get("href", "")
        m = PRODUCT_RE.search(href)
        if not m:
            continue
        item_id = m.group(1)
        if item_id in seen:
            continue
        title = common.clean(a.get_text())
        if len(title) < 2:
            continue
        seen.add(item_id)
        rows.append(common.make_row(
            rank=len(rows) + 1, title=title,
            product_id=item_id, url=href,
        ))
    return rows


def _next_data_fallback(soup: BeautifulSoup) -> list[dict]:
    script = soup.select_one("script#__NEXT_DATA__")
    if not script:
        return []
    try:
        data = json.loads(script.get_text())
    except Exception:
        return []
    found: list[dict] = []
    _walk(data, found)
    return found


def _walk(node, found: list, depth: int = 0):
    if depth > 20 or found:
        return
    title_keys = ("title", "bookTitle", "name", "prodName")
    if isinstance(node, list) and len(node) >= 10:
        if all(isinstance(x, dict) for x in node[:5]):
            keys = set().union(*(x.keys() for x in node[:5]))
            tk = next((k for k in title_keys if k in keys), None)
            if tk:
                for i, x in enumerate(node, 1):
                    found.append(common.make_row(
                        rank=i, title=str(x.get(tk, "")),
                        author=str(x.get("author") or x.get("authorName") or ""),
                        publisher=str(x.get("publisher") or x.get("publisherName") or ""),
                        product_id=str(x.get("itemId") or x.get("id") or ""),
                    ))
                return
    if isinstance(node, dict):
        for v in node.values():
            _walk(v, found, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _walk(v, found, depth + 1)


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

        # 1) 구 UI 셀렉터
        boxes = soup.select("div.ss_book_box")
        if boxes:
            rows.extend(_parse_ss_book_box(boxes))
            continue

        # 2) 중간 UI 셀렉터 변형들
        alt = (soup.select("li[data-item-id]") or
               soup.select("li[class*='result_book']") or
               soup.select("li[class*='book_item']") or
               soup.select("ul.list_book > li") or
               soup.select("ul.result_list > li"))
        if alt:
            # 각 li에서 ItemId 링크 추출
            for li in alt:
                a = li.select_one("a[href*='ItemId']") or li.select_one("a.bo3")
                if not a:
                    continue
                href = a.get("href", "")
                m = PRODUCT_RE.search(href)
                rows.append(common.make_row(
                    rank=len(rows) + 1, title=a.get_text(),
                    product_id=m.group(1) if m else "",
                    url=href,
                ))
            continue

        # 3) __NEXT_DATA__ 폴백
        nd = _next_data_fallback(soup)
        if nd:
            rows.extend(nd)
            continue

        # 4) 링크 기반 폴백
        lf = _link_fallback(soup)
        if len(lf) >= 5:
            rows.extend(lf)
            continue

        # 모두 실패
        common.save_snapshot(f"aladin_branch{branch_type}_p{page}.html", resp.text)
        if page == 1:
            raise RuntimeError(
                f"알라딘: 모든 셀렉터 실패(페이지 구조 변경 의심). "
                f"스냅샷 확인 후 셀렉터 업데이트 필요. (BranchType={branch_type}, page={page})"
            )
        break  # 2페이지 없는 경우는 1페이지 분량으로 진행

    return rows


def crawl_ebook() -> list[dict]:
    return _crawl_pages("5")


JOBS = [
    common.ChartJob("aladin", "ebook_best", "ebook", crawl_ebook),
]
