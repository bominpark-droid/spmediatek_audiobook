"""윌라(welaaa) — 오디오북 인기 차트.

오디오북 전문 플랫폼으로 오디오북 인기 데이터의 핵심 (설계 문서 2장 #7).
웹이 SPA(Next.js 등)일 가능성이 있어 두 단계로 시도한다:
1) HTML 내 목록 직접 파싱
2) __NEXT_DATA__ JSON 안에서 제목/저자 배열 추출
모두 실패하면 스냅샷과 함께 실패 보고한다.
"""
import json
import re

from bs4 import BeautifulSoup

from . import common

CANDIDATES = [
    "https://www.welaaa.com/audiobook/best",
    "https://www.welaaa.com/best",
    "https://www.welaaa.com/category/audiobook",
]


def _extract_from_next_data(soup: BeautifulSoup) -> list[dict]:
    """__NEXT_DATA__ JSON에서 도서 목록으로 보이는 배열을 탐색한다."""
    script = soup.select_one("script#__NEXT_DATA__")
    if not script:
        return []
    try:
        data = json.loads(script.get_text())
    except json.JSONDecodeError:
        return []

    found: list[dict] = []

    def walk(node):
        if isinstance(node, list) and len(node) >= 10:
            # 제목 필드를 가진 dict 배열이면 차트 목록 후보로 본다
            if all(isinstance(x, dict) for x in node[:5]):
                keys = set().union(*(x.keys() for x in node[:5]))
                title_key = next((k for k in ("title", "name", "contentName", "displayTitle") if k in keys), None)
                if title_key and not found:
                    for i, x in enumerate(node, 1):
                        found.append(common.make_row(
                            rank=i,
                            title=str(x.get(title_key, "")),
                            author=str(x.get("author") or x.get("authorName") or ""),
                            product_id=str(x.get("id") or x.get("contentId") or ""),
                        ))
                    return
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return found


def crawl_audiobook() -> list[dict]:
    errors = []
    for url in CANDIDATES:
        try:
            resp = common.fetch(url)
        except Exception as e:
            errors.append(f"{url} → {e}")
            continue
        soup = BeautifulSoup(resp.text, "lxml")
        # 1) 일반 HTML 목록 시도 — 상품 링크 다수 발견 시 사용
        links = soup.select("a[href*='/audiobook/'], a[href*='/content/']")
        rows: list[dict] = []
        seen = set()
        for a in links:
            title = common.clean(a.get_text())
            href = a.get("href", "")
            m = re.search(r"/(\d+)(?:$|\?)", href)
            pid = m.group(1) if m else href
            if not title or len(title) < 2 or pid in seen:
                continue
            seen.add(pid)
            if href.startswith("/"):
                href = "https://www.welaaa.com" + href
            rows.append(common.make_row(rank=len(rows) + 1, title=title,
                                        product_id=pid, url=href))
        if len(rows) >= 10:
            return rows
        # 2) __NEXT_DATA__ JSON 시도
        rows = _extract_from_next_data(soup)
        if len(rows) >= 10:
            return rows
        common.save_snapshot(f"welaaa_{url.rstrip('/').split('/')[-1]}.html", resp.text)
        errors.append(f"{url} → 응답은 받았으나 목록 파싱 {len(rows)}건")
    raise RuntimeError(
        "윌라 오디오북 차트 파싱 실패 — JS 렌더링 필요 가능성(Playwright 검토). "
        "시도 내역: " + " | ".join(errors)
    )


JOBS = [
    common.ChartJob("welaaa", "audiobook_best", "audiobook", crawl_audiobook),
]
