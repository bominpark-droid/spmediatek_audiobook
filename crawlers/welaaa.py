"""윌라(welaaa) — 오디오북 인기 차트 (Playwright 렌더링).

requests 방식은 403(봇 차단) + 일부 URL 404로 실패. 실제 브라우저로 접근하면
403을 통과할 가능성이 높다. 홈에서 '랭킹/베스트' 링크를 발견해 이동하고,
렌더된 DOM에서 오디오북 상세 링크를 순서대로 추출한다.
"""
import re

from bs4 import BeautifulSoup

from . import browser, common

HOME = "https://www.welaaa.com"
CANDIDATES = [
    "https://www.welaaa.com/audiobook/ranking",
    "https://www.welaaa.com/ranking",
    "https://www.welaaa.com/audiobook",
    "https://www.welaaa.com",
]
LINK_RE = re.compile(r"/(?:audiobook|content|detail)/(\d+)")


def _parse(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []
    seen: set[str] = set()
    for a in soup.select("a[href*='/audiobook/'], a[href*='/content/'], a[href*='/detail/']"):
        href = a.get("href", "")
        m = LINK_RE.search(href)
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


def crawl_audiobook() -> list[dict]:
    errors = []
    for url in CANDIDATES:
        try:
            html = browser.render(url, wait_selector="a[href*='/audiobook/'], a[href*='/content/']")
        except Exception as e:
            errors.append(f"{url} → {e}")
            continue
        # 홈이면 랭킹 링크를 찾아 한 번 더 이동
        if url == HOME:
            nav = browser.find_nav_link(html, HOME, ["랭킹", "베스트", "인기", "ranking"])
            if nav:
                try:
                    html = browser.render(nav, wait_selector="a[href*='/audiobook/']")
                except Exception as e:
                    errors.append(f"{nav} → {e}")
        rows = _parse(html)
        if len(rows) >= 10:
            return rows
        common.save_snapshot(f"welaaa_{url.rstrip('/').split('/')[-1] or 'home'}.html", html)
        errors.append(f"{url} → 파싱 {len(rows)}건")
    raise RuntimeError("윌라 오디오북: 렌더링 후에도 실패 — 시도: " + " | ".join(errors))


JOBS = [
    common.ChartJob("welaaa", "audiobook_best", "audiobook", crawl_audiobook, experimental=True),
]
