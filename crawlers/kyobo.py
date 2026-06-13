"""교보문고 — 종합 베스트셀러 / 전자책 베스트.

교보문고 신규 사이트(product.kyobobook.co.kr)는 Next.js 기반 SSR/CSR 혼합.
파싱 전략 (순서대로 시도):
1) __NEXT_DATA__ JSON 내 상품 배열 추출 (가장 안정적)
2) HTML 셀렉터: li.prod_item, [data-product-id] 등
3) 상세 링크(/detail/) 기반 폴백

전자책 베스트 URL:
- /bestseller/ebook 은 404 확인됨 → 후보 URL 순차 시도
- 교보 전자책 베스트는 /kyobo-product-front/ 경로나 쿼리 파라미터일 가능성

교보 오디오북(sam):
- kyobo_sam.py 참조 (store.kyobobook.co.kr 경로 시도)
"""
import json
import re

from bs4 import BeautifulSoup

from . import common

GENERAL_URL = "https://product.kyobobook.co.kr/bestseller/online"

EBOOK_CANDIDATES = [
    "https://product.kyobobook.co.kr/bestseller/eBook",
    "https://product.kyobobook.co.kr/bestseller/e-book",
    "https://product.kyobobook.co.kr/bestseller/online?saleCmdtClstCode=004",
    "https://product.kyobobook.co.kr/bestseller/online?type=ebook",
    "https://product.kyobobook.co.kr/bestseller/",
]

TITLE_KEYS = ("title", "cmdtName", "prodName", "saleCmdtName", "name", "bookTitle")
AUTHOR_KEYS = ("author", "authorName", "wrtrName", "publisherAuthorName")
PUBLISHER_KEYS = ("publisher", "publisherName", "pbcmName")
ID_KEYS = ("saleCmdtId", "cmdtId", "prodId", "id", "itemId")


def _walk(node, found: list, depth: int = 0):
    """__NEXT_DATA__ JSON 재귀 탐색 — 도서 목록 배열을 찾으면 rows로 변환."""
    if depth > 25 or found:
        return
    if isinstance(node, list) and len(node) >= 10:
        if all(isinstance(x, dict) for x in node[:5]):
            keys = set().union(*(x.keys() for x in node[:5]))
            tk = next((k for k in TITLE_KEYS if k in keys), None)
            if tk:
                for i, x in enumerate(node, 1):
                    pid = str(next((x.get(k) or "" for k in ID_KEYS if x.get(k)), ""))
                    author = str(next((x.get(k) or "" for k in AUTHOR_KEYS if x.get(k)), ""))
                    publisher = str(next((x.get(k) or "" for k in PUBLISHER_KEYS if x.get(k)), ""))
                    url = (x.get("url") or x.get("linkUrl") or
                           (f"https://product.kyobobook.co.kr/detail/{pid}" if pid else ""))
                    found.append(common.make_row(
                        rank=i, title=str(x.get(tk, "")),
                        author=author, publisher=publisher,
                        product_id=pid, url=url,
                    ))
                return
    if isinstance(node, dict):
        for v in node.values():
            _walk(v, found, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _walk(v, found, depth + 1)


def _extract_next_data(soup: BeautifulSoup) -> list[dict]:
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


def _parse_author_line(item) -> tuple[str, str]:
    el = item.select_one(".prod_author") or item.select_one(".author")
    if not el:
        return "", ""
    text = common.clean(el.get_text(" "))
    parts = [p.strip() for p in re.split(r"[·ㆍ|]", text)]
    author = parts[0] if parts else ""
    publisher = ""
    if len(parts) >= 2:
        publisher = parts[-2] if re.match(r"\d{4}", parts[-1]) else parts[-1]
    return author, publisher


def _html_fallback(soup: BeautifulSoup, label: str) -> list[dict]:
    selectors = [
        "li.prod_item",
        "li[data-product-id]",
        "li[class*='item']",
        "ul.prod_list > li",
        "ul.best_list > li",
    ]
    rows: list[dict] = []
    for sel in selectors:
        items = soup.select(sel)
        if not items:
            continue
        for item in items:
            link = (item.select_one("a[href*='/detail/']") or
                    item.select_one("a.prod_info") or
                    item.select_one(".prod_name a"))
            name_el = item.select_one(".prod_name") or item.select_one(".name") or link
            if not name_el:
                continue
            href = link.get("href", "") if link else ""
            m = re.search(r"/detail/(S?\w+)", href)
            author, publisher = _parse_author_line(item)
            rows.append(common.make_row(
                rank=len(rows) + 1, title=name_el.get_text(),
                author=author, publisher=publisher,
                product_id=m.group(1) if m else "",
                url=href,
            ))
        if rows:
            return rows
    return rows


def _crawl(url: str, label: str) -> list[dict]:
    resp = common.fetch(url)
    soup = BeautifulSoup(resp.text, "lxml")

    # 1) __NEXT_DATA__ (SSR JSON)
    rows = _extract_next_data(soup)
    if len(rows) >= 10:
        return rows

    # 2) HTML 셀렉터 폴백
    rows = _html_fallback(soup, label)
    if len(rows) >= 5:
        return rows

    common.save_snapshot(f"kyobo_{label}.html", resp.text)
    raise RuntimeError(
        f"교보 {label}: __NEXT_DATA__ 및 HTML 모두 파싱 실패 "
        f"({url}) — 스냅샷 확인 후 JS 렌더링(Playwright) 도입 여부 결정 필요"
    )


def _crawl_ebook() -> list[dict]:
    errors = []
    for url in EBOOK_CANDIDATES:
        try:
            resp = common.fetch(url)
        except Exception as e:
            errors.append(f"{url} → {e}")
            continue
        soup = BeautifulSoup(resp.text, "lxml")
        rows = _extract_next_data(soup)
        if len(rows) >= 10:
            return rows
        rows = _html_fallback(soup, "ebook")
        if len(rows) >= 5:
            return rows
        errors.append(f"{url} → 응답 받았으나 파싱 0건")
    common.save_snapshot("kyobo_ebook_all_failed.html", "\n".join(errors))
    raise RuntimeError(
        "교보 전자책 베스트: 모든 URL 실패 — URL 경로 재탐색 필요. 시도: " + " | ".join(errors)
    )


def crawl_general() -> list[dict]:
    return _crawl(GENERAL_URL, "general")


def crawl_ebook() -> list[dict]:
    return _crawl_ebook()


JOBS = [
    common.ChartJob("kyobo", "general_best", "general", crawl_general),
    common.ChartJob("kyobo", "ebook_best", "ebook", crawl_ebook),
]
