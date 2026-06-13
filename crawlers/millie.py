"""밀리의서재 — 전자책 인기 순위 / 오디오북 인기 순위.

설계 문서 2장 #8·#9: 웹 접근 가능 여부 구축 시 확인 대상.
앱 중심 서비스라 웹 차트가 비공개일 수 있다. 후보 URL을 시도하고
실패 시 스냅샷과 함께 보고한다 (전체 수집은 계속 진행).
"""
import json
import re

from bs4 import BeautifulSoup

from . import common

CANDIDATES = {
    "ebook": [
        "https://www.millie.co.kr/v3/bestseller",
        "https://millie.co.kr/v3/bestseller",
    ],
    "audiobook": [
        "https://www.millie.co.kr/v3/bestseller/audiobook",
        "https://millie.co.kr/v3/bestseller/audiobook",
    ],
}


def _parse(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []
    # 상세 페이지 링크(/v3/bookDetail/<id>) 기반 일반 파싱
    seen = set()
    for a in soup.select("a[href*='bookDetail'], a[href*='/v3/book/']"):
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
    if rows:
        return rows
    # SPA인 경우 초기 상태 JSON에서 추출 시도
    for script in soup.select("script"):
        text = script.get_text()
        if "bestseller" not in text.lower():
            continue
        for m in re.finditer(r'"title"\s*:\s*"([^"]+)"', text):
            rows.append(common.make_row(rank=len(rows) + 1, title=m.group(1)))
        if len(rows) >= 10:
            return rows
        rows = []
    return rows


def _crawl(kind: str) -> list[dict]:
    errors = []
    for url in CANDIDATES[kind]:
        try:
            resp = common.fetch(url)
        except Exception as e:
            errors.append(f"{url} → {e}")
            continue
        rows = _parse(resp.text)
        if len(rows) >= 10:
            return rows
        common.save_snapshot(f"millie_{kind}.html", resp.text)
        errors.append(f"{url} → 응답은 받았으나 목록 파싱 {len(rows)}건")
    raise RuntimeError(
        f"밀리의서재 {kind} 차트 접근 실패 — 앱 전용/JS 렌더링 가능성. "
        "스냅샷 확인 후 대안(모바일 웹·공개 API·대체 차트) 결정 필요. "
        "시도 내역: " + " | ".join(errors)
    )


def crawl_ebook() -> list[dict]:
    return _crawl("ebook")


def crawl_audiobook() -> list[dict]:
    return _crawl("audiobook")


JOBS = [
    common.ChartJob("millie", "ebook_best", "ebook", crawl_ebook),
    common.ChartJob("millie", "audiobook_best", "audiobook", crawl_audiobook),
]
