"""Playwright 기반 렌더링 헬퍼 — JS 렌더링/봇 차단 사이트용.

requests로 안 되는 사이트(교보·윌라·밀리)는 실제 브라우저(Chromium)를 띄워
페이지를 렌더링한 뒤 DOM을 파싱한다. 브라우저는 무겁기 때문에 단일 인스턴스를
재사용하고, run_all 종료 시 shutdown()으로 정리한다.

매너 원칙(robots.txt·요청 간격)은 common 정책을 그대로 따른다.
Playwright는 지연 import — 미설치 환경(예: 로컬 self-test)에서도 모듈 로드는 된다.
"""
from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from . import common

log = logging.getLogger("browser")

_playwright = None
_browser = None
_context = None

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _ensure_browser():
    """Chromium을 한 번만 띄워 재사용한다."""
    global _playwright, _browser, _context
    if _context is not None:
        return _context
    from playwright.sync_api import sync_playwright  # 지연 import
    _playwright = sync_playwright().start()
    _browser = _playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
    )
    _context = _browser.new_context(
        user_agent=UA,
        locale="ko-KR",
        viewport={"width": 1366, "height": 900},
        extra_http_headers={"Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.5"},
    )
    return _context


def render(url: str, *, wait_selector: str | None = None,
           wait_until: str = "networkidle", timeout: int = 30000,
           scroll: bool = True) -> str:
    """URL을 브라우저로 렌더링해 최종 HTML을 반환한다.

    - wait_selector: 이 셀렉터가 나타날 때까지 대기(목록 로딩 보장용, 선택)
    - scroll: 무한스크롤/지연로딩 대비로 페이지를 끝까지 내려본다
    """
    if not common.robots_allowed(url):
        raise PermissionError(f"robots.txt 비허용: {url}")
    common.polite_sleep()
    ctx = _ensure_browser()
    page = ctx.new_page()
    try:
        page.goto(url, wait_until=wait_until, timeout=timeout)
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=8000)
            except Exception:
                pass  # 셀렉터가 안 떠도 렌더된 DOM은 반환해 폴백 파싱 시도
        if scroll:
            for _ in range(6):
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(600)
        return page.content()
    finally:
        page.close()


def find_nav_link(html: str, base_url: str, keywords: list[str]) -> str | None:
    """렌더된 페이지에서 텍스트에 keyword가 포함된 네비게이션 링크의 href를 찾는다.

    교보 전자책/오디오 탭처럼 URL을 모를 때 허브 페이지에서 탭 링크를 발견하는 용도.
    """
    soup = BeautifulSoup(html, "lxml")
    for a in soup.select("a[href]"):
        text = common.clean(a.get_text())
        href = a.get("href", "")
        if not href or href.startswith("#"):
            continue
        if any(k in text for k in keywords):
            if href.startswith("/"):
                from urllib.parse import urljoin
                href = urljoin(base_url, href)
            if href.startswith("http"):
                return href
    return None


def shutdown() -> None:
    """브라우저·Playwright 정리. run_all 종료 시 호출."""
    global _playwright, _browser, _context
    try:
        if _context:
            _context.close()
        if _browser:
            _browser.close()
        if _playwright:
            _playwright.stop()
    except Exception as e:
        log.warning("브라우저 정리 중 예외(무시): %s", e)
    finally:
        _playwright = _browser = _context = None
