# 오디오북·도서 차트 데이터 수집 에이전트

설계 문서 v1.0 구현. **1단계: 수집·적재 전용** (분석은 데이터 축적 후 별도 에이전트).

## 무엇을 하는가

매일 04:00 KST에 GitHub Actions가 7개 플랫폼·10개 차트를 크롤링해 CSV로 적재하고
git에 커밋·푸시한다. 박보민의 일상 운영 작업량은 0분/일이 목표다.

원본은 이 저장소의 CSV(`data/`)다. Google Sheets에는 주간 요약(TOP 10 + 신규 진입)만
폰 확인용으로 푸시한다.

## 디렉토리

```
crawlers/        플랫폼별 크롤러 (1플랫폼 1파일, 독립 실행)
  common.py      공통 유틸 — 정중한 요청, robots.txt, CSV 저장, 스키마
  aladin.py / yes24.py / kyobo.py / kyobo_sam.py / welaaa.py / millie.py / audible_us.py
run_all.py       전체 오케스트레이터 (작업 단위 격리 실행)
summary.py       주간 요약 → Google Sheets 푸시
selftest.py      네트워크 없이 돌리는 구조 점검
data/YYYY/MM/    수집 CSV (YYYY-MM-DD_<platform>_<slug>.csv)
logs/            수집 상태(JSON)·로그. snapshots/ 는 파싱 실패 진단용(git 미포함)
.github/workflows/  daily-crawl.yml, weekly-summary.yml
```

## 수집 대상 (10개 차트)

| platform | chart | 비고 |
|---|---|---|
| aladin | ebook_best | 안정성 높음, 1호 크롤러 |
| yes24 | general_best / ebook_best | |
| kyobo | general_best / ebook_best | SSR HTML 가정 |
| kyobo_sam | audiobook_best | **접근성 확인 대상** — 로그인 장벽 시 대체 경로 시도 |
| welaaa | audiobook_best | SPA 가능성 — HTML→__NEXT_DATA__ 2단 시도 |
| millie | ebook_best / audiobook_best | **접근성 확인 대상** — 앱 전용 가능성 |
| audible_us | best_sellers | 영문 |

`kyobo_sam`·`welaaa`·`millie`는 로그인/JS 장벽 가능성이 있어, 실패해도 나머지 수집은
계속되고 실패 사유와 HTML 스냅샷을 남긴다. 막힌 소스 때문에 전체를 멈추지 않는다.

## 운영

- **자동**: 매일 04:00 KST 크롤링 → 커밋. 매주 월 06:00 KST 요약 → Sheets.
- **실패 알림**: 크롤러가 하나라도 실패하면 잡이 실패하고 GitHub Actions 기본 이메일 알림이
  발송된다(GitHub 알림 설정에서 Actions 실패 알림 ON 필요).
- **수동 실행/검증**: Actions 탭 → `daily-crawl` → Run workflow.
- **크롤러 수리**: 실패 알림 수신 → "OO 크롤러 깨졌어, 고쳐줘" → 첨부된 snapshots 아티팩트로 진단·수정.

## Google Sheets 연동 (선택)

1. `docs/apps_script_template.gs` 를 spmediatek Google 계정의 Apps Script에 배포(웹앱, "모든 사용자" 접근).
2. 배포 URL을 저장소 Secret `SHEETS_WEBHOOK_URL` 에 등록.
3. 미설정이어도 워크플로는 실패하지 않고 `logs/summary_preview.json` 만 남긴다.

## 검증 메모 (중요)

Claude Code 작업 컨테이너는 외부 네트워크가 도서 사이트로 차단(`host_not_allowed`)되어
실제 크롤링을 로컬에서 못 돌린다. 따라서:

- **로컬**: `python selftest.py` 로 구조(모듈·스키마·CSV·요약)만 점검 (전체 통과 확인됨).
- **실제 크롤링·파싱·정찰**: GitHub Actions `daily-crawl` 첫 수동 실행 로그/아티팩트로 검증.
  러너는 외부망이 열려 있어 어떤 차트가 실제로 수집되는지 거기서 확정된다.

자세한 정찰 상태는 `docs/RECON.md` 참고.
