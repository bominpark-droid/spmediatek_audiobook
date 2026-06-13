"""교보문고 오디오북 — kyobo_sam (오디오북 인기 차트).

기존 sam.kyobobook.co.kr 서비스는 store.kyobobook.co.kr 로 이전된 것으로 보임.
store.kyobobook.co.kr 경로를 우선 시도하고, 실패 시 product.kyobobook.co.kr 경로 시도.
모두 실패하면 스냅샷과 함께 보고 (전체 수집은 계속 진행).

1차 실행 결과:
- store.kyobobook.co.kr/category/domestic/audio/home → 404 확인됨
- 아래 후보 URL은 store 내 다른 경로를 순차 시도
"""
import json
import re

from bs4 import BeautifulSoup

from . import common

CANDIDATES = [
    "https://store.kyobobook.co.kr/category/domestic/audio",
    "https://store.kyobobook.co.kr/category/domestic/audio/best",
    "https://store.kyobobook.co.kr/best/audio",
    "https://store.kyobobook.co.kr/bestseller/audio",
    "https://product.kyobobook.co.kr/bestseller/audio",
    "https://product.kyobobook.co.kr/category/bestseller/audio",
]

TITLE_KEYS = ("title", "cmdtName", "prodName", "saleCmdtName", "name")


def _walk(node, found: list, depth: int = 0):
    if depth > 25 or found:
        return
    if isinstance(node, list) and len(node) >= 5:
        if all(isinstance(x, dict) for x in node[:3]):
            keys = set().union(*(x.keys() for x in node[:3]))
            tk = next((k for k in TITLE_KEYS if k in keys), None)
            if tk:
                for i, x in enumerate(node, 1):
                    pid = str(x.get("saleCmdtId") or x.get("cmdtId") or x.get("id") or "")
                    found.append(common.make_row(
                        rank=i, title=str(x.get(tk, "")),
                        author=str(x.get("author") or x.get("authorName") or ""),
                        publisher=str(x.get("publisher") or x.get("publisherName") or ""),
                        product_id=pid,
                        url=f"https://product.kyobobook.co.kr/detail/{pid}" if pid else "",
                    ))
                return
    if isinstance(node, dict):
        for v in node.values():
            _walk(v, found, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _walk(v, found, depth + 1)


def _try_parse(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    # __NEXT_DATA__ 우선
    script = soup.select_one("script#__NEXT_DATA__")
    if script:
        try:
            data = json.loads(script.get_text())
            found: list[dict] = []
            _walk(data, found)
            if found:
                return found
        except Exception:
            pass
    # HTML 셀렉터
    for sel in ("li.prod_item", "li[data-product-id]", "ul.best_list > li"):
        items = soup.select(sel)
        rows: list[dict] = []
        for item in items:
            link = item.select_one("a[href*='/detail/']") or item.select_one("a")
            name_el = item.select_one(".prod_name") or item.select_one(".name") or link
            if not name_el:
                continue
            href = link.get("href", "") if link else ""
            m = re.search(r"/detail/(S?\w+)", href)
            rows.append(common.make_row(
                rank=len(rows) + 1, title=name_el.get_text(),
                product_id=m.group(1) if m else "", url=href,
            ))
        if rows:
            return rows
    return []


def crawl_audiobook() -> list[dict]:
    errors = []
    for url in CANDIDATES:
        try:
            resp = common.fetch(url)
        except Exception as e:
            errors.append(f"{url} → {e}")
            continue
        rows = _try_parse(resp.text)
        if rows:
            return rows
        common.save_snapshot(f"kyobo_sam_{url.rstrip('/').split('/')[-1]}.html", resp.text)
        errors.append(f"{url} → 응답 받았으나 파싱 0건")
    raise RuntimeError(
        "교보 오디오북 차트: 모든 URL 실패. store.kyobobook.co.kr 경로 변경 또는 "
        "로그인 장벽 가능성. 스냅샷 확인 후 URL 재탐색 필요. 시도: " + " | ".join(errors)
    )


JOBS = [
    common.ChartJob("kyobo_sam", "audiobook_best", "audiobook", crawl_audiobook),
]
