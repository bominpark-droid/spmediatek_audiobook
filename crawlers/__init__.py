# 플랫폼별 크롤러 모듈. 각 모듈은 JOBS(ChartJob 목록)를 노출한다.
# 모듈 하나가 깨져도 나머지는 정상 동작한다 (run_all.py에서 작업 단위로 격리).
CRAWLER_MODULES = [
    "aladin",      # 안정성 높음 — 1호 크롤러
    "yes24",
    "kyobo",
    "audible_us",
    "kyobo_sam",   # 접근성 확인 대상
    "welaaa",
    "millie",      # 접근성 확인 대상
]
