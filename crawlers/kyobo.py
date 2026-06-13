"""교보문고 — 종합 베스트셀러 / 전자책 베스트 (Playwright 렌더링).

requests 방식은 실패(general=JS렌더링, ebook=URL 404)했으므로 실제 브라우저로 렌더링한다.
- 종합: /bestseller/online (200 확인됨, JS로 목록 생성) → 렌더 후 파싱
- 전자책: URL 미확인 → 종합 페이지에서 'eBook/전자책' 탭 링크를 발견해 이동, 후보 URL 병행

파싱은 렌더된 DOM에서:
1) 상품 상세 링크(/detail/...) 순서 기반 추출 (구조 변경에 강함)
2) li.prod_item 등 셀렉터 폴백
"""
import re

from bs4 import BeautifulSoup

from . import browser, common

GENERAL_URL = "https://product.kyobobook.co.kr/bestseller/online"
BASE = "https://product.kyobobook.co.kr"
DETAIL_RE = re.compile(r"/detail/(S\d+)")


def _parse_rendered(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []
    seen: set[str] = set()

    # 1) 상품 카드(li.prod_item 등)에서 제목+저자 함께 추출 시도
    for item in soup.select("li.prod_item, li[class*='prod'], ul.prod_list > li"):
        link = item.select_one("a[href*='/detail/']")
        name_el = item.select_one(".prod_name") or item.select_one(".title") or link
        if not link or not name_el:
            continue
        href = link.get("href", "")
        m = DETAIL_RE.search(href)
        pid = m.group(1) if m else href
        if pid in seen:
            continue
        seen.add(pid)
        author_el = item.select_one(".prod_author") or item.select_one(".author")
        rows.append(common.make_row(
            rank=len(rows) + 1, title=name_el.get_text(),
            author=author_el.get_text(" ") if author_el else "",
            product_id=m.group(1) if m else "",
            url=href if href.startswith("http") else BASE + href,
        ))
    if len(rows) >= 10:
        return rows

    # 2) 폴백: 페이지의 모든 상세 링크를 순서대로 (제목 텍스트 보유한 것만)
    rows, seen = [], set()
    for a in soup.select("a[href*='/detail/']"):
        href = a.get("href", "")
        m = DETAIL_RE.search(href)
        if not m or m.group(1) in seen:
            continue
        title = common.clean(a.get_text())
        if len(title) < 2:
            continue
        seen.add(m.group(1))
        rows.append(common.make_row(
            rank=len(rows) + 1, title=title, product_id=m.group(1),
            url=href if href.startswith("http") else BASE + href,
        ))
    return rows


def crawl_general() -> list[dict]:
    html = browser.render(GENERAL_URL, wait_selector="a[href*='/detail/']")
    rows = _parse_rendered(html)
    if len(rows) >= 10:
        return rows
    common.save_snapshot("kyobo_general_rendered.html", html)
    raise RuntimeError("교보 종합: 렌더링 후에도 목록 파싱 실패 — 스냅샷 확인 필요")


def crawl_ebook() -> list[dict]:
    # 1) 종합 페이지에서 'eBook/전자책' 탭 링크 발견 시도
    html = browser.render(GENERAL_URL, wait_selector="a[href*='/detail/']")
    tab = browser.find_nav_link(html, BASE, ["eBook", "ebook", "전자책"])
    candidates = [c for c in [tab,
                              "https://product.kyobobook.co.kr/bestseller/online?targetClass=ebook",
                              "https://ebook-product.kyobobook.co.kr/bestseller"] if c]
    errors = []
    for url in candidates:
        try:
            html = browser.render(url, wait_selector="a[href*='/detail/']")
        except Exception as e:
            errors.append(f"{url} → {e}")
            continue
        rows = _parse_rendered(html)
        if len(rows) >= 10:
            return rows
        errors.append(f"{url} → 파싱 {len(rows)}건")
    common.save_snapshot("kyobo_ebook_rendered.html", html if candidates else "no candidate")
    raise RuntimeError("교보 전자책: 탭 발견/렌더 모두 실패 — 시도: " + " | ".join(errors))


JOBS = [
    common.ChartJob("kyobo", "general_best", "general", crawl_general, experimental=True),
    common.ChartJob("kyobo", "ebook_best", "ebook", crawl_ebook, experimental=True),
]
