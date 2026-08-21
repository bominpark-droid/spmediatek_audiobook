"""qc 패키지 구조 점검 — 음원·모델 없이 실행한다.

강제 정렬(qc.align.align)은 stable-ts 와 실제 음원이 있어야 하므로 여기서
검증할 수 없다. 대신 백엔드와 분리해 둔 분석 로직(find_suspects)은 합성
데이터로 점검한다. compare 쪽은 전부 순수 함수라 여기서 완전히 검증된다.

사용: python qc_selftest.py
"""
import csv
import re
import sys
import tempfile
import time
from pathlib import Path

from qc import compare as cp
from qc import normalize as nz
from qc import report as rp
from qc.align import AlignResult, Word, find_suspects

FAIL = []
SAMPLES = Path(__file__).resolve().parent / "qc" / "samples"


def check(name, cond, detail=""):
    mark = "OK " if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        FAIL.append(name)


def test_numbers():
    check("한자어 2024→이천이십사", nz.sino_read(2024) == "이천이십사")
    check("한자어 1000→천 (일천 아님)", nz.sino_read(1000) == "천")
    check("한자어 15→십오", nz.sino_read(15) == "십오")
    check("한자어 110000→십일만", nz.sino_read(110000) == "십일만")
    check("한자어 0→영", nz.sino_read(0) == "영")
    check("고유어 23→스물세", nz.native_read(23) == "스물세")
    check("고유어 20→스무", nz.native_read(20) == "스무")
    check("고유어 100→없음", nz.native_read(100) is None)
    check("낱자 010→공일공", nz.digitwise_read("010") == "공일공")

    check("단위 '개'→고유어 우선", nz.number_readings("3", "개 있다")[0] == "세")
    check("단위 '년'→한자어 우선", nz.number_readings("3", "년 동안")[0] == "삼")
    check("두 읽기 모두 후보로 보존", set(nz.number_readings("3", "개 있다")) >= {"세", "삼"})
    check("소수 3.14→삼점일사", nz.number_readings("3.14", "")[0] == "삼점일사")
    check("자릿점 1,200 처리", nz.number_readings("1,200", "원")[0] == "천이백")


def test_normalize():
    n = nz.normalize('그는 "어디 가?"라고 물었다.')
    check("문장부호·공백 제거", n.text == "그는어디가라고물었다", n.text)

    n = nz.normalize("한국(韓國)의 밤")
    check("한자 기본 제거", n.text == "한국의밤", n.text)
    n = nz.normalize("한국(韓國)의 밤", keep_hanja=True)
    check("keep_hanja 옵션", "韓國" in n.text, n.text)

    n = nz.normalize("라디오(radio)에서", drop_parens=True)
    check("drop_parens 괄호 제거", n.text == "라디오에서", n.text)

    raw = "1998년 여름"
    n = nz.normalize(raw)
    check("숫자 읽기 반영", n.text.startswith("천구백구십팔"), n.text)
    s, e = n.origin(0, 6)          # '천구백구십팔' 6음절 → 원본 '1998'
    check("원본 위치 역추적(숫자)", raw[s:e] == "1998", repr(raw[s:e]))
    s, e = n.origin(0, 7)          # + '년'
    check("원본 위치 역추적(단위 포함)", raw[s:e] == "1998년", repr(raw[s:e]))
    s, e = n.origin(len(n.text), len(n.text) + 1)
    check("범위 밖 조회 안전", 0 <= s <= e <= len(raw), f"{s},{e}")

    n = nz.normalize("AI 시대")
    check("영문 약어 사전", n.text == "에이아이시대", n.text)
    check("약어는 soft 아님", not any(v.soft for v in n.variants))
    n = nz.normalize("Michael 이라는 사람")
    check("모르는 영단어는 soft 표시", any(v.soft for v in n.variants))

    # 위치 매핑이 원본 길이를 벗어나지 않아야 리포트가 깨지지 않는다
    raw = "제1장 2024년 AI(인공지능) 이야기입니다."
    n = nz.normalize(raw)
    ok = all(0 <= a <= b <= len(raw) for a, b in zip(n.src_start, n.src_end))
    check("위치 매핑 범위 유효", ok)


def test_sentences():
    sents = nz.split_sentences('첫 문장이다. "둘째!" 셋째?\n넷째')
    check("문장 분할 4개", len(sents) == 4, f"{[s.text for s in sents]}")
    starts = nz.sentence_index(sents)
    check("위치→문장 역추적", nz.locate(sents, starts, 0).no == 1)


def test_align_opcodes():
    ops = cp.aligned_opcodes("가나다라마", "가나마")
    rebuilt = "".join("가나다라마"[i1:i2] for t, i1, i2, _, _ in ops if t == "equal")
    check("정렬 opcode 일치 구간 정확", rebuilt == "가나마", rebuilt)

    # 앵커 경로(긴 입력)와 직접 경로(짧은 입력)의 결과가 같아야 한다
    base = "".join(chr(0xAC00 + (i * 37) % 11172) for i in range(6000))
    mutated = base[:3000] + base[3050:]
    saved = cp.DIRECT_LIMIT
    try:
        cp.DIRECT_LIMIT = 10 ** 9
        direct = cp.aligned_opcodes(base, mutated)
        cp.DIRECT_LIMIT = saved
        anchored = cp.aligned_opcodes(base, mutated)
    finally:
        cp.DIRECT_LIMIT = saved
    d_eq = sum(i2 - i1 for t, i1, i2, _, _ in direct if t == "equal")
    a_eq = sum(i2 - i1 for t, i1, i2, _, _ in anchored if t == "equal")
    check("앵커 정렬이 직접 정렬과 동등", a_eq == d_eq, f"{a_eq} vs {d_eq}")

    # 앵커가 전혀 없는 반복 텍스트에서도 멈추지 않아야 한다
    t0 = time.perf_counter()
    cp.aligned_opcodes("가나" * 8000, "가나" * 7990)
    check("반복 텍스트에서 무한정 느려지지 않음", time.perf_counter() - t0 < 20,
          f"{time.perf_counter() - t0:.1f}초")


def test_compare_suppression():
    """표기 차이는 걸러지고 진짜 오독만 남아야 한다."""
    # 대표 읽기가 그대로 맞는 경우 — 차이 자체가 생기지 않는다
    r = cp.compare("1998년 7월, 그 날 이후.", "천구백구십팔년 칠월 그날이후")
    check("숫자·띄어쓰기 차이 전부 억제", not r.findings, [f.kind for f in r.findings])
    check("표기차이만 있으면 일치율 100%", r.match_rate == 1.0, f"{r.match_rate:.2%}")

    # 대표 읽기('제한장')가 틀린 경우 — 변이형 후보로 되살려야 한다
    r = cp.compare("제1장 스무 살", "제일장 스무살")
    check("서수 읽기 변이 허용(제1장→제일장)", not r.findings,
          [(f.script_text, f.stt_text) for f in r.findings])
    check("변이형 억제 건수 집계", r.suppressed >= 1, str(r.suppressed))
    check("억제분을 일치로 계산", r.match_rate == 1.0, f"{r.match_rate:.2%}")

    r = cp.compare("24시간 편의점", "이십사시간 편의점")
    check("고유어/한자어 혼용 허용", not r.findings)


def test_compare_detection():
    r = cp.compare("그해 여름은 유난히 길었다.", "그해 여름은 유난히 짧았다")
    check("오독(대치) 탐지", [f.kind for f in r.findings] == ["대치"],
          [f.kind for f in r.findings])

    r = cp.compare("첫 문장이다. 둘째 문장이다. 셋째 문장이다.",
                   "첫 문장이다 셋째 문장이다")
    kinds = [f.kind for f in r.findings]
    check("문장 누락 탐지", "누락" in kinds, kinds)
    check("문장 누락은 심각도 높음",
          any(f.severity == "높음" for f in r.findings if f.kind == "누락"))

    r = cp.compare("그 낡은 코트를 입고", "그 낡은 낡은 코트를 입고")
    check("반복(삽입) 탐지", [f.kind for f in r.findings] == ["삽입"],
          [f.kind for f in r.findings])

    r = cp.compare("Michael 이 왔다", "마이클이 왔다")
    check("영문 고유명사는 확인필요로 강등",
          all(f.severity == "확인필요" for f in r.findings),
          [f.severity for f in r.findings])

    # 완전히 동일하면 아무것도 나오지 않아야 한다
    same = "바람이 언덕 너머로 흘렀다. 아무 일도 없었다."
    check("동일 입력은 무보고", not cp.compare(same, same).findings)


def test_compare_samples():
    """동봉한 샘플로 전 구간 동작 확인."""
    script = (SAMPLES / "sample_script.txt").read_text(encoding="utf-8")
    stt = (SAMPLES / "sample_stt.txt").read_text(encoding="utf-8")
    r = cp.compare(script, stt)
    check("샘플: 어절 diff 기준선 존재", r.naive_diffs > 10, str(r.naive_diffs))
    check("샘플: 확인 대상이 기준선보다 훨씬 적음",
          len(r.findings) < r.naive_diffs / 3,
          f"{len(r.findings)} vs {r.naive_diffs}")
    kinds = {f.kind for f in r.findings}
    check("샘플: 세 유형 모두 탐지", kinds >= {"대치", "누락", "삽입"}, str(kinds))
    check("샘플: 심어둔 오독('짧았다') 지목",
          any("짧았" in f.stt_text for f in r.findings))
    check("샘플: 심어둔 누락('편지 한 통') 지목",
          any("편지 한 통" in f.script_text for f in r.findings))

    r2 = cp.compare(script, stt, drop_parens=True)
    check("샘플: drop_parens 로 원어 병기 오탐 제거",
          len(r2.findings) < len(r.findings), f"{len(r2.findings)} vs {len(r.findings)}")


def test_find_suspects():
    """정렬 결과 분석 — stable-ts 없이 합성 데이터로 점검."""
    script = " ".join(f"문장{i}이 여기 있다." for i in range(1, 13))
    words, t = [], 0.0
    for i in range(60):
        words.append(Word(f"단어{i}", t, t + 0.3, 0.95))
        t += 0.35
    check("정상 구간은 무보고", not find_suspects(words, script))

    bad = list(words)
    for i in (20, 21, 22):
        bad[i] = Word(bad[i].text, bad[i].start, bad[i].end, 0.11)
    sus = find_suspects(bad, script)
    check("낮은 확률 연속 구간 탐지",
          any(s.reason == "낮은확률" and s.severity == "높음" for s in sus),
          [s.reason for s in sus])

    gapped = list(words)
    shifted = [Word(w.text, w.start + 5, w.end + 5, w.probability) for w in gapped[30:]]
    sus = find_suspects(gapped[:30] + shifted, script)
    check("긴 무음 탐지", any(s.reason == "긴무음" for s in sus),
          [s.reason for s in sus])
    gap = next((s for s in sus if s.reason == "긴무음"), None)
    check("타임코드 형식", bool(gap and re.fullmatch(r"\d\d:\d\d:\d\d\.\d",
          gap.timecode.split(" → ")[0])), gap.timecode if gap else "")

    check("빈 입력 안전", find_suspects([], script) == [])


def test_reports():
    script = (SAMPLES / "sample_script.txt").read_text(encoding="utf-8")
    stt = (SAMPLES / "sample_stt.txt").read_text(encoding="utf-8")
    r = cp.compare(script, stt)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        csv_path = rp.write_compare_csv(r, out / "a.csv")
        with open(csv_path, encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        check("CSV 헤더", rows[0][:3] == ["확인", "심각도", "유형"], str(rows[0][:3]))
        check("CSV 행 수 = 확인 대상 수", len(rows) - 1 == len(r.findings))

        html_path = rp.write_compare_html(r, script, out / "a.html")
        h = html_path.read_text(encoding="utf-8")
        check("HTML 표시 개수 = 확인 대상 수",
              len(re.findall(r"<mark ", h)) == len(r.findings))
        # 대본이 훼손되면 검수 도구로 못 쓴다. 태그를 걷어내면 원문과 같아야 한다.
        import html as H
        art = re.search(r"<article>(.*)</article>", h, re.S).group(1)
        plain = H.unescape(re.sub(r"<[^>]+>", "", art))
        check("HTML 안에서 대본 원문 보존", plain == script)

        align_csv = rp.write_align_csv(
            AlignResult(words=[Word("가", 0, 1, 0.1)],
                        suspects=find_suspects([Word("가", 0, 1, 0.1)], "가.")),
            out / "b.csv")
        check("정렬 CSV 생성", align_csv.exists())


def test_cli():
    from qc.__main__ import build_parser
    p = build_parser()
    a = p.parse_args(["compare", "--script", "s.txt", "--stt", "t.txt"])
    check("CLI compare 기본값", a.out == "out" and not a.drop_parens)
    a = p.parse_args(["align", "--audio", "a.wav", "--script", "s.txt"])
    check("CLI align 기본 모델", a.model == "large-v3" and a.language == "ko")


if __name__ == "__main__":
    print("=== qc 구조 자체 점검 (음원·모델 불필요) ===")
    test_numbers()
    test_normalize()
    test_sentences()
    test_align_opcodes()
    test_compare_suppression()
    test_compare_detection()
    test_compare_samples()
    test_find_suspects()
    test_reports()
    test_cli()
    print("=" * 40)
    if FAIL:
        print(f"실패 {len(FAIL)}건: {FAIL}")
        sys.exit(1)
    print("전체 통과 — compare 는 검증 완료. align 은 실제 음원으로 확인 필요.")
