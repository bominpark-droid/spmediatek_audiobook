# spmediatek_audiobook

SP미디어텍 오디오북 사내 도구 모음.

## 도서 차트 대시보드

교보·예스24·알라딘·윌라·밀리·오더블 차트를 매일 수집해 `data/` 에 쌓고
`index.html` 대시보드로 본다.

```bash
python run_all.py     # 전체 수집 (GitHub Actions 가 매일 04:00 KST 자동 실행)
python summary.py     # 주간 요약 생성
python selftest.py    # 네트워크 없이 구조 점검
```

## 오디오북 검수 도구 — [`qc/`](qc/README.md)

대본과 녹음을 대조해 성우의 오독·누락·삽입을 찾는다. STT 결과를 그대로
diff 하면 차이의 97%가 표기 차이·STT 오인식이라 쓸 수 없다. 양쪽을 같은
읽기 형태로 정규화해 음절 단위로 대조하고, 대본을 정답으로 음성을 강제
정렬한다.

```bash
python -m qc compare --script 원고.txt --stt stt.txt --out out/   # 추가 설치 불필요
python -m qc align --audio ch01.wav --script 원고.txt --out out/  # stable-ts 필요
python qc_selftest.py                                             # 구조 점검
```

자세한 내용은 [`qc/README.md`](qc/README.md).
