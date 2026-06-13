# 정찰(1단계) 상태 보고

설계 문서 7장 1단계 = "10개 차트 페이지 접근성 확인". 현재 상태를 기록한다.

## 환경 제약 (핵심)

Claude Code 작업 컨테이너의 네트워크 정책이 **모든 외부 도서 사이트를 차단**한다.
직접 확인한 결과:

| 결과 | 호스트 |
|---|---|
| `403 host_not_allowed` | aladin.co.kr, yes24.com, product.kyobobook.co.kr, welaaa.com, millie.co.kr, audible.com |
| `403 host_not_allowed` | example.com (일반 호스트도 차단) |
| `200` | pypi.org, github.com (허용 목록) |

따라서 **이 컨테이너에서는 실제 HTML 구조·JS 렌더링·로그인 장벽을 직접 정찰할 수 없다.**
정찰은 외부망이 열린 GitHub Actions 러너에서 `daily-crawl` 워크플로를 수동 실행해
수행한다(코드 완성 + Actions 검증 방식, 박보민 승인).

## 차트별 사전 위험 평가 (설계 문서 기반 가정)

크롤러는 아래 가정으로 작성했고, 첫 Actions 실행에서 실제와 대조해 확정한다.

| 차트 | 가정 | 실패 시 동작 |
|---|---|---|
| aladin/ebook_best | 정적 HTML(`div.ss_book_box`). 안정성 높음 | 스냅샷 저장 + 보고 |
| yes24/general·ebook | SSR `#yesBestList` | 스냅샷 + 보고 |
| kyobo/general·ebook | 신규몰 SSR `li.prod_item` | JS 전환 의심 시 보고 |
| **kyobo_sam/audiobook** | sam 오디오북 베스트. **로그인 장벽 가능성 높음** | 후보 URL 3종 순차 시도 → 전부 실패 시 대체 경로 결정 요청 |
| **welaaa/audiobook** | SPA 가능성 | HTML→`__NEXT_DATA__` 2단 시도 → 실패 시 Playwright 검토 보고 |
| **millie/ebook·audiobook** | **앱 전용 가능성 높음** | 후보 URL 시도 → 실패 시 모바일웹·공개API·대체차트 결정 요청 |
| audible_us/best_sellers | 정적 HTML `li.productListItem` | 스냅샷 + 보고 |

## 다음 행동

1. 이 브랜치를 푸시한다.
2. (권한자) Actions에서 `daily-crawl` 수동 실행 → 어떤 차트가 실제 수집되는지 확정.
   - 실패 차트는 `logs/<날짜>_status.json` 의 사유 + `snapshots-*` 아티팩트로 진단.
3. kyobo_sam·welaaa·millie 결과에 따라 대체 경로/렌더링 방식 결정.

> 원칙: 수집 불가 소스가 있어도 가능한 소스부터 가동한다. 전체 구축을 멈추지 않는다.
