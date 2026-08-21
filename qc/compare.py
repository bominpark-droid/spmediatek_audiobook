"""대본 ↔ STT 음절 단위 대조.

기존 방식(어절 단위 diff)이 실패하는 이유는 두 가지다.

  1. 한국어 STT는 띄어쓰기를 신뢰할 수 없다. 어절 단위로 비교하면 WER 수준
     (CER의 2~3배)의 차이가 그대로 리포트에 쏟아진다.
  2. 숫자·영문 표기 차이가 오독으로 잡힌다.

여기서는 normalize 로 양쪽을 같은 읽기 형태의 음절열로 바꾼 뒤, 음절 단위로
정렬하고, 남은 차이 중 '변이형으로 설명되는 것'을 다시 걷어낸다.

정렬은 고유 n-gram 앵커로 긴 텍스트를 토막 낸 뒤 구간별로 SequenceMatcher 를
돌린다. difflib 를 통짜로 돌리면 '이/는/다' 같은 흔한 음절 때문에 책 한 권
분량에서 실용적이지 않게 느려진다.
"""
from __future__ import annotations

import re
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from itertools import product

from . import normalize as nz

# 누락 구간이 문장 경계를 넘었는지 판단할 때 쓴다.
_SENT_END = re.compile(r"[.!?…\n]")

# 앵커 n-gram 길이. 너무 짧으면 우연한 일치로 잘못 고정되고, 너무 길면
# 오독이 잦은 구간에서 앵커를 못 잡는다. 못 잡으면 절반씩 줄여가며 재시도한다.
ANCHOR_N = 16
MIN_ANCHOR_N = 4
# 이 길이 아래면 앵커링 없이 바로 비교한다. difflib 은 반복이 많은 텍스트에서
# 급격히 느려지므로 한 번에 넘기는 양을 묶어 둔다.
DIRECT_LIMIT = 2500
# 차이 사이의 일치 구간이 이보다 짧으면 한 건으로 합친다.
# (오독 한 번이 여러 opcode 로 쪼개지는 것을 막는다)
MERGE_GAP = 4
# 변이형 후보 조합 상한. 폭발 방지.
MAX_COMBOS = 64
# 이 길이 이상 누락되면 문단 통째 누락으로 본다.
BIG_DROP = 30

Opcode = tuple[str, int, int, int, int]


def aligned_opcodes(a, b, *, n: int = ANCHOR_N) -> list[Opcode]:
    """두 시퀀스(음절 문자열 또는 어절 리스트)의 정렬 결과를 opcode 로 돌려준다."""
    return _coalesce(_segment(a, b, n, 0, 0))


def _segment(a, b, n: int, oa: int, ob: int) -> list[Opcode]:
    """앵커로 토막 내며 재귀 정렬. 좌표는 항상 전체 기준(oa/ob 오프셋)으로 돌려준다."""
    if not a and not b:
        return []
    if not a:
        return [("insert", oa, oa, ob, ob + len(b))]
    if not b:
        return [("delete", oa, oa + len(a), ob, ob)]
    if len(a) <= DIRECT_LIMIT and len(b) <= DIRECT_LIMIT:
        return _shift(_direct(a, b), oa, ob)

    anchors = _anchors(a, b, n)
    if anchors:
        ops: list[Opcode] = []
        pa = pb = 0
        for ia, ib in anchors:
            ops.extend(_segment(a[pa:ia], b[pb:ib], n, oa + pa, ob + pb))
            ops.append(("equal", oa + ia, oa + ia + n, ob + ib, ob + ib + n))
            pa, pb = ia + n, ib + n
        ops.extend(_segment(a[pa:], b[pb:], n, oa + pa, ob + pb))
        return ops

    if n > MIN_ANCHOR_N:
        return _segment(a, b, max(MIN_ANCHOR_N, n // 2), oa, ob)

    # 앵커가 하나도 없다 = 같은 표현이 계속 반복되는 텍스트. 최적 정렬을 포기하고
    # 비례 분할로 작업량을 묶는다. 경계에서 약간 손해를 보지만 멈추지는 않는다.
    ha = len(a) // 2
    hb = max(0, min(len(b), round(len(b) * ha / len(a))))
    return (_segment(a[:ha], b[:hb], n, oa, ob)
            + _segment(a[ha:], b[hb:], n, oa + ha, ob + hb))


def _direct(a, b) -> list[Opcode]:
    # autojunk 는 200개 넘는 시퀀스에서 자주 나오는 원소를 통째로 무시해버린다.
    # 한국어 음절('이','는','다')에는 치명적이라 반드시 끈다.
    return SequenceMatcher(None, a, b, autojunk=False).get_opcodes()


def _shift(ops: list[Opcode], da: int, db: int) -> list[Opcode]:
    return [(t, i1 + da, i2 + da, j1 + db, j2 + db) for t, i1, i2, j1, j2 in ops]


def _coalesce(ops: list[Opcode]) -> list[Opcode]:
    """인접한 같은 종류 opcode 를 합친다."""
    out: list[Opcode] = []
    for op in ops:
        if op[1] == op[2] and op[3] == op[4]:
            continue
        if out and out[-1][0] == op[0] and out[-1][2] == op[1] and out[-1][4] == op[3]:
            t, i1, _, j1, _ = out[-1]
            out[-1] = (t, i1, op[2], j1, op[4])
        else:
            out.append(op)
    return out


def _anchors(a, b, n: int) -> list[tuple[int, int]]:
    """양쪽에서 딱 한 번씩만 나오는 n-gram을 찾아 정렬 기준점으로 삼는다.

    patience diff 와 같은 발상. 흔한 음절 조합에 정렬이 끌려가는 것을 막고,
    긴 텍스트를 독립적으로 처리 가능한 토막으로 나눈다.
    """
    pos_a = _unique_positions(a, n)
    if not pos_a:
        return []
    pos_b = _unique_positions(b, n)
    pairs = sorted((pos_a[g], pos_b[g]) for g in pos_a.keys() & pos_b.keys())
    if not pairs:
        return []

    # b 쪽도 증가하도록 최장 증가 부분수열만 남긴다 (순서 뒤집힘 방지).
    tails: list[int] = []
    back: list[int] = []
    parent: list[int] = []
    for idx, (_, jb) in enumerate(pairs):
        k = bisect_left(tails, jb)
        if k == len(tails):
            tails.append(jb)
            back.append(idx)
        else:
            tails[k] = jb
            back[k] = idx
        parent.append(back[k - 1] if k else -1)
    chain: list[int] = []
    cur = back[-1] if back else -1
    while cur != -1:
        chain.append(cur)
        cur = parent[cur]
    chain.reverse()

    # 겹치는 앵커는 버린다 — 앵커 구간은 그대로 'equal' 로 확정되므로
    # 서로 n 이상 떨어져 있어야 한다.
    out: list[tuple[int, int]] = []
    for idx in chain:
        ia, ib = pairs[idx]
        if out and (ia < out[-1][0] + n or ib < out[-1][1] + n):
            continue
        out.append((ia, ib))
    return out


def _unique_positions(s, n: int) -> dict:
    """딱 한 번만 나오는 n-gram → 그 위치. 문자열도 어절 리스트도 받는다."""
    as_str = isinstance(s, str)
    counts: dict = defaultdict(int)
    first: dict = {}
    for i in range(len(s) - n + 1):
        g = s[i:i + n] if as_str else tuple(s[i:i + n])
        counts[g] += 1
        if g not in first:
            first[g] = i
    return {g: first[g] for g, c in counts.items() if c == 1}


@dataclass
class Finding:
    """검수자가 실제로 들어봐야 할 지점 한 건."""
    kind: str            # 대치 | 누락 | 삽입
    severity: str        # 높음 | 중간 | 낮음 | 확인필요
    script_text: str     # 대본 원문 발췌
    stt_text: str        # STT 원문 발췌
    sent_no: int
    sent_text: str
    src_start: int       # 대본 원문 문자 위치
    src_end: int
    note: str = ""


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    suppressed: int = 0            # 변이형으로 설명돼 걸러낸 가짜 오류
    script_syllables: int = 0
    stt_syllables: int = 0
    matched_syllables: int = 0
    naive_diffs: int = 0           # 정규화 없이 어절 단위로 비교했을 때의 차이 수

    @property
    def match_rate(self) -> float:
        return self.matched_syllables / self.script_syllables if self.script_syllables else 0.0

    @property
    def reduction(self) -> float:
        """가짜 오류가 몇 % 줄었는지. 도입 효과를 보여주는 값."""
        if not self.naive_diffs:
            return 0.0
        return 1 - len(self.findings) / self.naive_diffs


def naive_word_diffs(script_raw: str, stt_raw: str) -> int:
    """지금까지 쓰던 방식 — 원문을 어절로 쪼개 그대로 diff 했을 때의 차이 수.

    개선 효과를 수치로 보여주기 위한 기준선이다. 어절 수가 많으면 여기서도
    difflib 이 느려지므로 같은 앵커링 정렬을 쓴다(앵커 길이는 어절 기준).
    """
    a, b = script_raw.split(), stt_raw.split()
    ops = aligned_opcodes(a, b, n=6)
    return sum(1 for t, *_ in ops if t != "equal")


def compare(script_raw: str, stt_raw: str, *, drop_parens: bool = False,
            keep_hanja: bool = False) -> Report:
    """대본과 STT 결과를 대조해 확인이 필요한 지점만 추린다."""
    script = nz.normalize(script_raw, drop_parens=drop_parens, keep_hanja=keep_hanja)
    stt = nz.normalize(stt_raw, drop_parens=False, keep_hanja=keep_hanja)

    ops = aligned_opcodes(script.text, stt.text)
    matched = sum(i2 - i1 for t, i1, i2, _, _ in ops if t == "equal")

    report = Report(
        script_syllables=len(script.text),
        stt_syllables=len(stt.text),
        matched_syllables=matched,
        naive_diffs=naive_word_diffs(script_raw, stt_raw),
    )

    # 변이형 억제를 병합보다 먼저 한다. 순서를 바꾸면 "24→이십사" 같은 표기차이가
    # 옆의 진짜 누락과 한 덩어리로 묶여, 억제도 안 되고 유형도 틀리게 나온다.
    kept: list[_Diff] = []
    for d in _raw_diffs(ops):
        if _explained_by_variant(script, stt, d):
            report.suppressed += 1
            # 다르게 읽었을 뿐 내용은 맞으므로 일치로 센다. 이걸 빼면
            # 숫자가 많은 원고에서 일치율이 실제보다 훨씬 낮게 나온다.
            report.matched_syllables += d.i2 - d.i1
        else:
            kept.append(d)

    sents = nz.split_sentences(script.raw)
    starts = nz.sentence_index(sents)
    for d in _merge(kept):
        report.findings.append(_build(script, stt, sents, starts, d))
    return report


@dataclass
class _Diff:
    i1: int
    i2: int
    j1: int
    j2: int
    left_margin: int     # 앞쪽 일치 구간 길이 (변이형 검사 시 확장 가능 폭)
    right_margin: int


def _raw_diffs(ops: list[Opcode]) -> list[_Diff]:
    """opcode 목록에서 차이 구간만 뽑는다. 앞뒤 일치 구간 길이를 margin 으로 함께 기록.

    margin 은 변이형 검사에서 비교 범위를 좌우로 넓힐 때 쓴다. 일치 구간이라
    양쪽을 같은 폭만큼 넓혀도 대응이 유지된다.
    """
    diffs: list[_Diff] = []
    for k, (tag, i1, i2, j1, j2) in enumerate(ops):
        if tag == "equal":
            continue
        left = ops[k - 1][2] - ops[k - 1][1] if k and ops[k - 1][0] == "equal" else 0
        right = (ops[k + 1][2] - ops[k + 1][1]
                 if k + 1 < len(ops) and ops[k + 1][0] == "equal" else 0)
        diffs.append(_Diff(i1, i2, j1, j2, left, right))
    return diffs


def _merge(diffs: list[_Diff]) -> list[_Diff]:
    """가까이 붙은 차이를 한 건으로 합친다. 오독 한 번이 여러 건으로 쪼개지는 걸 막는다."""
    out: list[_Diff] = []
    for d in diffs:
        if out and d.i1 - out[-1].i2 <= MERGE_GAP and d.j1 - out[-1].j2 <= MERGE_GAP:
            prev = out[-1]
            prev.i2, prev.j2, prev.right_margin = d.i2, d.j2, d.right_margin
        else:
            out.append(d)
    return out


def _explained_by_variant(script: nz.Normalized, stt: nz.Normalized,
                          d: _Diff) -> bool:
    """이 차이가 '다르게 읽었을 뿐'으로 설명되면 True.

    "2024년"을 대표 읽기 '이천이십사'로 정규화해 뒀는데 성우가 실제로는
    '이천이십사'가 아닌 다른 허용 읽기로 읽었을 때, 이를 오독으로 잡지 않기
    위한 장치다. 겹치는 변이형 구간의 후보를 모두 대입해 본다.
    """
    spans = [v for v in script.variants if v.start < d.i2 and v.end > d.i1]
    if not spans:
        return False

    # 변이형 구간 전체를 덮도록 좌우로 넓힌다. 일치 구간이라 양쪽을 같은
    # 폭만큼 넓혀도 대응이 유지된다.
    lo = min([d.i1] + [v.start for v in spans])
    hi = max([d.i2] + [v.end for v in spans])
    left = min(d.i1 - lo, d.left_margin)
    right = min(hi - d.i2, d.right_margin)
    a1, a2 = d.i1 - left, d.i2 + right
    b1, b2 = d.j1 - left, d.j2 + right
    if b1 < 0 or b2 > len(stt.text):
        return False

    target = stt.text[b1:b2]
    inner = [v for v in spans if v.start >= a1 and v.end <= a2]
    if not inner:
        return False

    combos = 1
    for v in inner:
        combos *= len(v.alternatives)
    if combos > MAX_COMBOS:
        inner = inner[:1]

    for choice in product(*[v.alternatives for v in inner]):
        parts, cur = [], a1
        for v, alt in zip(inner, choice):
            parts.append(script.text[cur:v.start])
            parts.append(alt)
            cur = v.end
        parts.append(script.text[cur:a2])
        if "".join(parts) == target:
            return True
    return False


def _snap(raw: str, start: int, end: int, *, max_pad: int = 12,
          extra_words: int = 0) -> tuple[int, int]:
    """표시용 구간을 어절 경계까지 넓힌다. 문맥 없이 음절 조각만 보여주면 못 읽는다.

    extra_words 는 삽입·누락용. 한쪽이 빈 구간이라 그것만 보여주면 무엇이
    빠지고 더해졌는지 알 수 없으므로, 양쪽에 같은 폭의 문맥을 붙인다.
    줄바꿈은 넘지 않는다 — 다른 문단을 끌어오면 오히려 헷갈린다.
    """
    limit = max(0, start - max_pad)
    while start > limit and not raw[start - 1].isspace():
        start -= 1
    limit = min(len(raw), end + max_pad)
    while end < limit and not raw[end].isspace():
        end += 1

    for _ in range(extra_words):
        while start > 0 and raw[start - 1] in " \t":
            start -= 1
        while start > 0 and not raw[start - 1].isspace():
            start -= 1
        while end < len(raw) and raw[end] in " \t":
            end += 1
        while end < len(raw) and not raw[end].isspace():
            end += 1
    return start, end


def _build(script: nz.Normalized, stt: nz.Normalized, sents: list[nz.Sentence],
           starts: list[int], d: _Diff) -> Finding:
    dropped, added = d.i2 - d.i1, d.j2 - d.j1
    if not added:
        kind = "누락"
    elif not dropped:
        kind = "삽입"
    else:
        kind = "대치"

    s_start, s_end = script.origin(d.i1, d.i2)
    t_start, t_end = stt.origin(d.j1, d.j2)
    sent = nz.locate(sents, starts, s_start)
    # 정렬 경계는 음절 단위라 어절 중간에서 끊긴다. 표시할 때는 어절까지 넓혀야
    # '오(radio' 대신 '라디오(radio)에서는' 처럼 사람이 읽을 수 있는 형태가 된다.
    pad = 0 if kind == "대치" else 1
    s_start, s_end = _snap(script.raw, s_start, s_end, extra_words=pad)
    t_start, t_end = _snap(stt.raw, t_start, t_end, extra_words=pad)

    soft = any(v.soft and v.start < d.i2 and v.end > d.i1 for v in script.variants)
    crosses_sentence = bool(_SENT_END.search(script.raw[s_start:s_end]))
    note = ""
    if soft:
        # 영문 고유명사는 한글 표기를 기계적으로 알 수 없다. 오독으로 단정하지 않는다.
        severity = "확인필요"
        note = "외래어·영문 읽기라 자동 판별 불가 — 직접 들어볼 것"
    elif kind == "누락":
        if dropped >= BIG_DROP or crosses_sentence:
            severity = "높음"
            note = (f"{dropped}음절 누락 — 문장·문단 통째 건너뜀 의심"
                    if crosses_sentence else f"{dropped}음절 연속 누락")
        else:
            # 1~2음절 누락은 조사 탈락 등 STT 잡음일 때가 많다.
            severity = "중간" if dropped >= 3 else "낮음"
    elif kind == "대치":
        # 대치는 실제 오독의 대표적 형태라 기본을 높게 잡는다.
        severity = "높음" if max(dropped, added) >= 4 else "중간"
    else:  # 삽입 — 리테이크 잔여물·더듬음
        severity = "중간" if added >= 3 else "낮음"

    return Finding(
        kind=kind,
        severity=severity,
        script_text=nz.strip_for_display(script.raw[s_start:s_end]),
        stt_text=nz.strip_for_display(stt.raw[t_start:t_end]),
        sent_no=sent.no if sent else 0,
        sent_text=nz.strip_for_display(sent.text) if sent else "",
        src_start=s_start,
        src_end=s_end,
        note=note,
    )
