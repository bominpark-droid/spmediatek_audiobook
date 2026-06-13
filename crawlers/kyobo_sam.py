"""교보문고 오디오북 — kyobo_sam (오디오북 인기 차트, Playwright 렌더링).

기존 sam.kyobobook.co.kr 은 이전된 것으로 보이며 후보 URL이 모두 404였다.
실제 브라우저로 교보 종합 베스트 페이지를 연 뒤 '오디오' 관련 탭/카테고리 링크를
발견해 이동하고, 렌더된 DOM에서 상품 상세 링크를 추출한다.
"""
import re

from bs4 import BeautifulSoup

from . import browser, common

BASE = "https://product.kyobobook.co.kr"
HUB = "https://product.kyobobook.co.kr/bestseller/online"
STORE_CANDIDATES = [
    "https://store.kyobobook.co.kr/bestseller/audio",
    "https://store.kyobobook.co.kr/category/audio",
]
DETAIL_RE = re.compile(r"/detail/(S\d+)")


def _parse(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []
    seen: set[str] = set()
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


def crawl_audiobook() -> list[dict]:
    errors = []
    # 1) 허브(종합 베스트)에서 '오디오북' 탭 링크 발견
    try:
        html = browser.render(HUB, wait_selector="a[href*='/detail/']")
        tab = browser.find_nav_link(html, BASE, ["오디오북", "오디오"])
    except Exception as e:
        tab = None
        errors.append(f"{HUB} → {e}")

    for url in [u for u in [tab, *STORE_CANDIDATES] if u]:
        try:
            html = browser.render(url, wait_selector="a[href*='/detail/']")
        except Exception as e:
            errors.append(f"{url} → {e}")
            continue
        rows = _parse(html)
        if len(rows) >= 10:
            return rows
        common.save_snapshot(f"kyobo_sam_{url.rstrip('/').split('/')[-1]}.html", html)
        errors.append(f"{url} → 파싱 {len(rows)}건")

    raise RuntimeError(
        "교보 오디오북: 오디오 탭 발견/렌더 모두 실패 — 로그인 장벽 가능성. "
        "시도: " + " | ".join(errors)
    )


JOBS = [
    common.ChartJob("kyobo_sam", "audiobook_best", "audiobook", crawl_audiobook, experimental=True),
]
