"""밀리의서재 — 전자책 / 오디오북 인기 순위 (Playwright 렌더링).

requests는 200을 받지만 SPA라 빈 HTML(파싱 0건). 실제 브라우저로 렌더링하면
JS가 목록을 그린다. 렌더 후 도서 상세 링크를 순서대로 추출한다.
오디오북은 베스트셀러 페이지의 '오디오북' 탭/필터를 발견해 이동한다.
"""
import re

from bs4 import BeautifulSoup

from . import browser, common

HOME = "https://www.millie.co.kr"
EBOOK_URL = "https://www.millie.co.kr/v3/bestseller"
AUDIO_CANDIDATES = [
    "https://www.millie.co.kr/v3/bestseller/audiobook",
    "https://www.millie.co.kr/v3/bestseller?category=audiobook",
]
DETAIL_RE = re.compile(r"(?:bookDetail|/book/|/v3/book/)\D*(\d{4,})")


def _parse(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []
    seen: set[str] = set()
    for a in soup.select("a[href*='bookDetail'], a[href*='/book/'], a[href*='/v3/book/']"):
        href = a.get("href", "")
        m = DETAIL_RE.search(href) or re.search(r"(\d{4,})", href)
        pid = m.group(1) if m else href
        title = common.clean(a.get_text())
        if not title or len(title) < 2 or pid in seen:
            continue
        seen.add(pid)
        rows.append(common.make_row(
            rank=len(rows) + 1, title=title, product_id=pid,
            url=href if href.startswith("http") else HOME + href,
        ))
    return rows


def crawl_ebook() -> list[dict]:
    html = browser.render(EBOOK_URL, wait_selector="a[href*='bookDetail'], a[href*='/book/']")
    rows = _parse(html)
    if len(rows) >= 10:
        return rows
    common.save_snapshot("millie_ebook_rendered.html", html)
    raise RuntimeError("밀리 전자책: 렌더링 후에도 파싱 실패 — 스냅샷 확인 필요")


def crawl_audiobook() -> list[dict]:
    # 전자책 페이지에서 '오디오북' 탭 발견 시도 + 후보 URL 병행
    html = browser.render(EBOOK_URL, wait_selector="a[href*='bookDetail'], a[href*='/book/']")
    tab = browser.find_nav_link(html, HOME, ["오디오북", "오디오", "audio"])
    errors = []
    for url in [u for u in [tab, *AUDIO_CANDIDATES] if u]:
        try:
            html = browser.render(url, wait_selector="a[href*='bookDetail'], a[href*='/book/']")
        except Exception as e:
            errors.append(f"{url} → {e}")
            continue
        rows = _parse(html)
        if len(rows) >= 10:
            return rows
        errors.append(f"{url} → 파싱 {len(rows)}건")
    common.save_snapshot("millie_audiobook_rendered.html", html)
    raise RuntimeError("밀리 오디오북: 렌더링 후에도 실패 — 시도: " + " | ".join(errors))


JOBS = [
    common.ChartJob("millie", "ebook_best", "ebook", crawl_ebook, experimental=True),
    common.ChartJob("millie", "audiobook_best", "audiobook", crawl_audiobook, experimental=True),
]
