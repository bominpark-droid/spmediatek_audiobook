"""밀리의서재 — 전자책 / 오디오북 인기 순위.

1차 실행 결과: 응답은 받았으나 파싱 0건 (SPA, JS 렌더링).
2차 시도 전략:
1) 밀리 내부 API 엔드포인트 직접 호출 (JSON 반환)
2) __NEXT_DATA__ / 인라인 JSON 추출
3) 전부 실패 시 모바일 웹 URL 시도
"""
import json
import re

from bs4 import BeautifulSoup

from . import common

# 밀리 웹앱이 내부적으로 호출하는 API 후보
API_CANDIDATES = {
    "ebook": [
        "https://www.millie.co.kr/v3/api/bestseller?genre=all&page=1&size=50",
        "https://www.millie.co.kr/v3/bestseller?format=json",
        "https://api.millie.co.kr/v2/bestseller?type=ebook&size=50",
        "https://www.millie.co.kr/v3/bestseller",
        "https://m.millie.co.kr/v3/bestseller",
    ],
    "audiobook": [
        "https://www.millie.co.kr/v3/api/bestseller/audiobook?page=1&size=50",
        "https://www.millie.co.kr/v3/bestseller/audiobook?format=json",
        "https://api.millie.co.kr/v2/bestseller?type=audiobook&size=50",
        "https://www.millie.co.kr/v3/bestseller/audiobook",
        "https://m.millie.co.kr/v3/bestseller/audiobook",
    ],
}

TITLE_KEYS = ("title", "bookTitle", "contentName", "name", "b_title")


def _parse_json_response(data) -> list[dict]:
    """API가 JSON을 직접 반환할 때 파싱."""
    if not isinstance(data, (dict, list)):
        return []
    found: list[dict] = []

    def walk(node, depth=0):
        if depth > 15 or found:
            return
        if isinstance(node, list) and len(node) >= 5:
            if all(isinstance(x, dict) for x in node[:3]):
                keys = set().union(*(x.keys() for x in node[:3]))
                tk = next((k for k in TITLE_KEYS if k in keys), None)
                if tk:
                    for i, x in enumerate(node, 1):
                        pid = str(x.get("id") or x.get("bookId") or x.get("contentId") or "")
                        found.append(common.make_row(
                            rank=i, title=str(x.get(tk, "")),
                            author=str(x.get("author") or x.get("authorName") or ""),
                            publisher=str(x.get("publisher") or x.get("publisherName") or ""),
                            product_id=pid,
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


def _parse_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    # __NEXT_DATA__ / __NUXT__ / 인라인 JSON 시도
    for script in soup.select("script"):
        src = script.get_text()
        if not any(k in src for k in ("bestseller", "title", "bookTitle")):
            continue
        # 인라인 JSON 배열 추출 시도
        for m in re.finditer(r"\[(\{[^\[\]]{20,}\}(?:,\{[^\[\]]{20,}\})+)\]", src):
            try:
                arr = json.loads("[" + m.group(1) + "]")
                rows = _parse_json_response(arr)
                if len(rows) >= 5:
                    return rows
            except Exception:
                continue
    # 링크 기반 폴백
    rows: list[dict] = []
    seen: set[str] = set()
    for a in soup.select("a[href*='bookDetail'], a[href*='/v3/book/'], a[href*='/book/']"):
        title = common.clean(a.get_text())
        href = a.get("href", "")
        m = re.search(r"(\d{5,})", href)
        pid = m.group(1) if m else href
        if not title or len(title) < 2 or pid in seen:
            continue
        seen.add(pid)
        if href.startswith("/"):
            href = "https://www.millie.co.kr" + href
        rows.append(common.make_row(rank=len(rows) + 1, title=title,
                                    product_id=pid, url=href))
    return rows


def _crawl(kind: str) -> list[dict]:
    errors = []
    for url in API_CANDIDATES[kind]:
        try:
            resp = common.fetch(url, headers={
                "Accept": "application/json, text/html, */*",
                "Referer": "https://www.millie.co.kr/",
            })
        except Exception as e:
            errors.append(f"{url} → {e}")
            continue

        # JSON API 응답인지 먼저 확인
        ct = resp.headers.get("content-type", "")
        if "json" in ct:
            try:
                data = resp.json()
                rows = _parse_json_response(data)
                if rows:
                    return rows
            except Exception:
                pass

        # HTML 응답이면 파싱 시도
        rows = _parse_html(resp.text)
        if len(rows) >= 10:
            return rows

        errors.append(f"{url} → 응답({resp.status_code}) 파싱 {len(rows)}건")

    common.save_snapshot(f"millie_{kind}_failed.html", "\n".join(errors))
    raise RuntimeError(
        f"밀리의서재 {kind}: 내부 API 및 HTML 파싱 모두 실패. "
        "앱 전용 인증(토큰) 필요 가능성 — 공개 API 또는 대체 차트 결정 필요. "
        "시도: " + " | ".join(errors)
    )


def crawl_ebook() -> list[dict]:
    return _crawl("ebook")


def crawl_audiobook() -> list[dict]:
    return _crawl("audiobook")


JOBS = [
    common.ChartJob("millie", "ebook_best", "ebook", crawl_ebook),
    common.ChartJob("millie", "audiobook_best", "audiobook", crawl_audiobook),
]
