# DB시트 + QC시트 통합 계획 (대표 요청 2026-08-06)

## 현재 구조 (파악 완료)

두 개의 스프레드시트 + 세 개의 스크립트가 얽혀 있음:

1. **SP QC 대시보드 마스터** (시트 ID 1mj6SAGFkm...)
   - 정본: 도서정보 탭 (약칭·출판사·도서명·검수단계·폴더·캐스팅·메모 등 AA~AD열까지)
   - 바인딩 스크립트 = 메인 시스템 (Code.gs v2.9 + Admin/Index/Eng/Pub/Login HTML)
   - 관리자·성우·엔지니어·검수자·출판사 대시보드 전부 여기서 서빙
   - 프로젝트DB를 "출판사 공개용 진행현황"으로 읽고 제한된 열만 씀
     (D단계, K~V 체크 완료/기한, AC 공개메모 — G/F/I열 접근 금지 원칙)

2. **SP미디어텍_프로젝트DB** (시트 ID 15S7CXLH...)
   - 프로젝트DB 탭: A ID / B 출판사 / C 도서명 / D 단계(1-10) / E 마감 /
     F 성우 / G 내부메모 / H 담당자 / I 출판사이메일 / K~V 체크 6종(완료,기한) /
     AB 전달처이메일 / AC 공개메모 / (Z·AD… 링크류는 구 대시보드용)
   - 바인딩 스크립트 (이번에 받은 "이메일 자동화" Code.gs):
     * 매일 8시 checkStageChanges — 단계 변경 메일
     * 매일 9시 sendReminderEmails — 마감 하루 전 메일
     * 링크가 **구 GitHub Pages 대시보드**(bominpark-droid.github.io)로 감
   - 구 대시보드(리포 index.html)가 gviz로 직접 읽음 (예전 시스템)

## 발견된 문제

- **알림 이중 발송 위험**: QC 스크립트의 dailyPublisherDigest(매일 8시, 마감 D-3/D-1/D0/경과 +
  단계변경 + 메모변경, 새 로그인 페이지 안내)와 프로젝트DB 스크립트(8시 단계변경 + 9시 마감 D-1,
  구 대시보드 링크 안내)가 **같은 출판사에게 겹쳐 나감**. QC 쪽 ㉗ 진단 메뉴도 이를 경고하고 있음.
- 도서를 두 시트에 이중 등록해야 하고, 이름이 다르면 연결 실패 (syncBooks로 땜질 중)
- 같은 도서명·차수별 ID 중복 문제 (pdbRowOrThrow_의 v2.2 주석 참조)

## 통합 방향 (단계별)

### 1단계 — 관리자 대시보드 UX 개선 (AdminIndex.html 수신 후)
- 홈: 전 도서 1줄 요약 보드, 알림에서 '판정 대기' 분리
- 도서 관리: 조회 요약 우선, 편집 폼 접기
- 통합과 무관하게 먼저 배포 가능

### 2단계 — 데이터 통합 (프로젝트DB → QC 마스터로 흡수)
- QC 도서정보에 열 추가: 진행단계(1-10), 납품마감(이미 E열 있음 — 통일),
  체크 6종 완료/기한 12열, 출판사 공개메모
- 마이그레이션 메뉴: 프로젝트DB 값을 P열 매칭 기준으로 1회 복사
- Code.gs의 pdb* 함수들을 로컬 열 읽기/쓰기로 교체
  (readProdForPub_/readProdForAdmin_/adminSetStep/adminSetCheck/adminSetCheckDue/
   adminSetProdMemo/markPdbCheckForBook_/collectDues_/buildDigest_/syncBooks/adminAddBook)
- 프로젝트DB 시트는 백업으로 동결 (삭제하지 않음, 읽기만 중단)

### 3단계 — 알림 일원화
- 프로젝트DB 바인딩 스크립트의 트리거 전부 삭제 (그쪽 편집기에서)
- QC dailyPublisherDigest가 유일한 출판사 알림 채널이 됨
- 구 GitHub Pages 대시보드는 은퇴 (이미 "예전 대시보드"로 확인됨)

## 대기 중
- ★ AdminIndex.html 원본 (이전 전달분은 PubIndex.html 중복이었음)
