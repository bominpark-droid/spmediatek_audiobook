"""윌라(welaaa) — 오디오북 인기 차트.

1차 실행 결과: 모든 후보 URL에서 403 Forbidden (봇 차단 또는 JS 렌더링 필요).
2차 시도 전략:
1) 브라우저와 동일한 요청 헤더 세트로 강화 (Referer, sec-* 헤더)
2) 모바일 웹 URL 시도
3) __NEXT_DATA__ / SPA JSON 추출
4) 전부 실패 시: Playwright 도입 권고와 함께 보고
"""
import json
import re

from bs4 import BeautifulSoup

from . import common

CANDIDATES = [
    "https://www.welaaa.com/audiobook/ranking",
    "https://www.welaaa.com/ranking",
    "https://www.welaaa.com/audiobook/best",
    "https://m.welaaa.com/audiobook/best",
    "https://m.welaaa.com/ranking",
    "https://www.welaaa.com/category/audiobook",
]

# 브라우저와 최대한 동일하게 — 403 우회용
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


def _extract_from_next_data(soup: BeautifulSoup) -> list[dict]:
    script = soup.select_one("script#__NEXT_DATA__")
    if not script:
        return []
    try:
        data = json.loads(script.get_text())
    except Exception:
        return []

    found: list[dict] = []

    def walk(node, depth=0):
        if depth > 20 or found:
            return
        if isinstance(node, list) and len(node) >= 10:
            if all(isinstance(x, dict) for x in node[:5]):
                keys = set().union(*(x.keys() for x in node[:5]))
                tk = next((k for k in ("title", "name", "contentName", "displayTitle") if k in keys), None)
                if tk:
                    for i, x in enumerate(node, 1):
                        found.append(common.make_row(
                            rank=i, title=str(x.get(tk, "")),
                            author=str(x.get("author") or x.get("authorName") or ""),
                            product_id=str(x.get("id") or x.get("contentId") or ""),
                        ))
                    return
        if isinstance(node, dict):
            for v in node.values():
                walk(v, depth + 1)
        elif isinstance(node, list):
            for v in node:
                walk(v, depth + 1)

    walk(data)
    return found


def crawl_audiobook() -> list[dict]:
    errors = []
    for url in CANDIDATES:
        try:
            resp = common.fetch(url, headers=BROWSER_HEADERS)
        except Exception as e:
            errors.append(f"{url} → {e}")
            continue

        soup = BeautifulSoup(resp.text, "lxml")

        # 1) __NEXT_DATA__ JSON
        rows = _extract_from_next_data(soup)
        if len(rows) >= 10:
            return rows

        # 2) 일반 HTML — 오디오북 링크 기반
        seen: set[str] = set()
        link_rows: list[dict] = []
        for a in soup.select("a[href*='/audiobook/'], a[href*='/content/'], a[href*='/detail/']"):
            title = common.clean(a.get_text())
            href = a.get("href", "")
            m = re.search(r"/(\d+)(?:$|\?)", href)
            pid = m.group(1) if m else href
            if not title or len(title) < 2 or pid in seen:
                continue
            seen.add(pid)
            if href.startswith("/"):
                href = "https://www.welaaa.com" + href
            link_rows.append(common.make_row(rank=len(link_rows) + 1, title=title,
                                              product_id=pid, url=href))
        if len(link_rows) >= 10:
            return link_rows

        common.save_snapshot(f"welaaa_{url.rstrip('/').split('/')[-1]}.html", resp.text)
        errors.append(f"{url} → 파싱 {len(link_rows)}건")

    raise RuntimeError(
        "윌라 오디오북 차트: 모든 URL 접근 실패 또는 파싱 0건. "
        "강화된 브라우저 헤더로도 403 지속 시 Playwright(JS 렌더링) 도입 필요. "
        "시도 내역: " + " | ".join(errors)
    )


JOBS = [
    common.ChartJob("welaaa", "audiobook_best", "audiobook", crawl_audiobook),
]
