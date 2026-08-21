"""한국어 대본/STT 정규화 — 표기 차이를 지워 '진짜 오독'만 남긴다.

대본과 STT 출력을 그대로 비교하면 차이의 대부분이 성우 오독이 아니라
표기 방식 차이다. 실제로 검수 리포트를 오염시키는 것들:

    대본 "2024년"     ↔  STT "이천이십사 년"    (숫자)
    대본 "AI"         ↔  STT "에이아이"         (영문)
    대본 "그 날 이후" ↔  STT "그날이후"         (띄어쓰기)
    대본 '"어디 가?"' ↔  STT "어디 가"          (문장부호)

그래서 비교 전에 양쪽을 같은 '읽기 형태'로 바꾼다:
  1. 문장부호·따옴표·대시 제거
  2. 숫자·영문을 한글 읽기로 변환
  3. 공백 전부 제거 — 한국어 STT의 띄어쓰기는 신뢰할 수 없다
  4. 음절 단위 시퀀스로 비교

한국어 수사는 문맥 의존적이라 하나로 확정할 수 없다("3번"은 세 번/삼 번 둘 다
가능). 그래서 대표 읽기 하나를 고르되 가능한 읽기를 variants 로 함께 남기고,
compare 단계에서 어느 하나라도 STT와 맞으면 오류가 아닌 것으로 처리한다.
이 '변이형 허용'이 가짜 오류를 줄이는 핵심 장치다.
"""
from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field

# ── 한자어 수사 (일, 이, 삼 …) ────────────────────────────────────────────
SINO_DIGITS = ["영", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]
SINO_POS = ["", "십", "백", "천"]
SINO_BIG = ["", "만", "억", "조", "경"]

# ── 고유어 수사 (하나, 둘, 셋 …) — 99까지만 존재 ─────────────────────────
NATIVE_ONES = ["", "하나", "둘", "셋", "넷", "다섯", "여섯", "일곱", "여덟", "아홉"]
NATIVE_TENS = ["", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔"]
# 단위명사 앞에서는 관형사형을 쓴다: 한 개, 두 명, 세 번, 스무 살
NATIVE_ONES_ATTR = ["", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉"]
NATIVE_TENS_ATTR = ["", "열", "스무", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔"]

# 뒤에 오면 한자어로 읽는 단위. (2024년 → 이천이십사 년)
SINO_UNITS = {
    "년", "월", "일", "분", "초", "원", "달러", "엔", "위안", "유로", "퍼센트", "프로",
    "도", "층", "호", "번지", "세기", "주", "개월", "주년", "학년", "교시", "인분",
    "미터", "센티", "킬로", "그램", "리터", "평", "회", "차", "위", "쪽", "페이지",
}
# 뒤에 오면 고유어로 읽는 단위. (3개 → 세 개)
NATIVE_UNITS = {
    "개", "명", "살", "시", "마리", "그루", "채", "대", "벌", "켤레", "자루", "송이",
    "가지", "사람", "시간", "달", "군데", "곳", "잔", "병", "상자", "봉지", "장",
    "권", "켤", "판", "척", "통", "번",
}

# 영문 약어 읽기. 자주 나오는 것만 사전으로 두고, 나머지는 알파벳 낱자로 읽는다.
ALPHABET = {
    "A": "에이", "B": "비", "C": "씨", "D": "디", "E": "이", "F": "에프", "G": "지",
    "H": "에이치", "I": "아이", "J": "제이", "K": "케이", "L": "엘", "M": "엠",
    "N": "엔", "O": "오", "P": "피", "Q": "큐", "R": "알", "S": "에스", "T": "티",
    "U": "유", "V": "브이", "W": "더블유", "X": "엑스", "Y": "와이", "Z": "지",
}
ENGLISH_WORDS = {
    "OK": "오케이", "TV": "티브이", "PC": "피시", "AI": "에이아이", "IT": "아이티",
    "CEO": "씨이오", "SNS": "에스엔에스", "DNA": "디엔에이", "UN": "유엔",
    "USB": "유에스비", "CD": "씨디", "DVD": "디브이디", "IQ": "아이큐",
    "VIP": "브이아이피", "SF": "에스에프", "PD": "피디", "MC": "엠씨",
    "GDP": "지디피", "KTX": "케이티엑스", "SUV": "에스유브이", "NO": "노",
}

# 제거 대상 문장부호. 성우가 소리 내지 않는 것들.
PUNCT = r"""!"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~‘’“”„‟…·—–―ㆍ「」『』〈〉《》【】〔〕"""
_PUNCT_RE = re.compile(f"[{PUNCT}]")
_HANJA_RE = re.compile(r"[一-鿿]")
_SPACE_RE = re.compile(r"\s+")

# 토큰: 숫자(소수·자릿점 포함) | 영문 | 그 외 한 글자
_TOKEN_RE = re.compile(r"\d[\d,]*(?:\.\d+)?|[A-Za-z]+|.", re.S)

# 문장 분할 — 종결부호 또는 빈 줄 기준. 대사 따옴표 뒤 종결도 잡는다.
_SENT_RE = re.compile(r'[^.!?…\n]*(?:[.!?…]+["\'”’)\]]*|\n+|$)', re.S)


def sino_read(n: int) -> str:
    """한자어 수사로 읽는다. 2024 → 이천이십사, 1000 → 천 (일천 아님)."""
    if n == 0:
        return "영"
    groups: list[str] = []
    idx = 0
    while n > 0:
        g = n % 10000
        if g:
            groups.append(_sino_group(g) + SINO_BIG[idx])
        n //= 10000
        idx += 1
    return "".join(reversed(groups))


def _sino_group(g: int) -> str:
    """1~9999 한 덩어리를 읽는다. 앞자리 1은 생략한다(십오, 백삼)."""
    out = []
    for pos in range(3, -1, -1):
        d = (g // 10 ** pos) % 10
        if d == 0:
            continue
        if d == 1 and pos > 0:
            out.append(SINO_POS[pos])
        else:
            out.append(SINO_DIGITS[d] + SINO_POS[pos])
    return "".join(out)


def native_read(n: int, *, attributive: bool = True) -> str | None:
    """고유어 수사로 읽는다. 99를 넘으면 고유어가 없으므로 None."""
    if n <= 0 or n > 99:
        return None
    tens, ones = divmod(n, 10)
    t = (NATIVE_TENS_ATTR if attributive else NATIVE_TENS)[tens]
    o = (NATIVE_ONES_ATTR if attributive else NATIVE_ONES)[ones]
    # 스무는 단독으로 쓰이지 않는다: 스무 살(O) / 스물(단독) — 스물하나는 '스물'+'하나'
    if tens == 2 and ones and attributive:
        t = "스물"
    return t + o


def digitwise_read(digits: str) -> str:
    """자릿수를 낱자로 읽는다. 전화번호·연도 낭독 대비. 010 → 공일공."""
    return "".join("공" if c == "0" else SINO_DIGITS[int(c)] for c in digits)


def number_readings(token: str, next_text: str) -> list[str]:
    """숫자 토큰의 가능한 읽기를 대표값부터 순서대로 돌려준다.

    뒤따르는 단위명사로 한자어/고유어를 판단하되, 확정이 어려우므로
    나머지 후보도 함께 남긴다. 이 후보들이 compare 단계에서
    가짜 오류를 걸러내는 데 쓰인다.
    """
    body = token.replace(",", "")
    readings: list[str] = []

    if "." in body:  # 소수: 3.14 → 삼 점 일사
        whole, frac = body.split(".", 1)
        base = sino_read(int(whole)) if whole else "영"
        readings.append(base + "점" + digitwise_read(frac))
        return readings

    try:
        n = int(body)
    except ValueError:
        return [body]

    sino = sino_read(n)
    native = native_read(n)
    unit = _leading_unit(next_text)

    if unit in NATIVE_UNITS and native:
        readings = [native, sino]
    elif unit in SINO_UNITS:
        readings = [sino] + ([native] if native else [])
    else:
        readings = [sino] + ([native] if native else [])

    # 0으로 시작하거나 4자리 넘는 숫자는 낱자 낭독 가능성도 있다 (연도·번호)
    if len(body) >= 3 and (body[0] == "0" or len(body) >= 5):
        readings.append(digitwise_read(body))
    if native and n <= 99:
        alt = native_read(n, attributive=False)
        if alt and alt not in readings:
            readings.append(alt)
    return _dedup(readings)


def _leading_unit(text: str) -> str:
    """숫자 바로 뒤에 붙은 한글 단위명사를 최대 2음절까지 본다."""
    s = text.lstrip()
    m = re.match(r"[가-힣]{1,2}", s)
    if not m:
        return ""
    word = m.group()
    if word in SINO_UNITS or word in NATIVE_UNITS:
        return word
    return word[:1]


def english_readings(token: str) -> tuple[list[str], bool]:
    """영문 토큰의 읽기 후보와 '불확실' 여부를 돌려준다.

    약어는 낱자 읽기가 정확하지만 일반 단어(고유명사 등)는 한글 표기를
    기계적으로 알 수 없다. 그런 토큰은 soft=True 로 표시해서, 여기서 난
    차이는 오독이 아니라 '확인 필요'로 낮춰 보고한다.
    """
    upper = token.upper()
    if upper in ENGLISH_WORDS:
        return _dedup([ENGLISH_WORDS[upper], _spell_out(upper)]), False
    if len(token) <= 3 and token.isupper():
        return [_spell_out(upper)], False
    return [_spell_out(upper)], True


def _spell_out(word: str) -> str:
    return "".join(ALPHABET.get(c, "") for c in word)


def _dedup(items: list[str]) -> list[str]:
    seen, out = set(), []
    for it in items:
        if it and it not in seen:
            seen.add(it)
            out.append(it)
    return out


@dataclass
class VariantSpan:
    """정규화 결과 중 '다르게 읽힐 수도 있는' 구간.

    start/end 는 정규화된 문자열에서의 위치, alternatives 는 대표 읽기를
    포함한 모든 후보. soft=True 면 읽기 자체를 신뢰할 수 없다는 뜻.
    """
    start: int
    end: int
    alternatives: list[str]
    src_start: int
    src_end: int
    soft: bool = False
    kind: str = ""  # number | english


@dataclass
class Normalized:
    """정규화 결과. 원본 위치를 잃지 않는 것이 리포트 품질을 좌우한다."""
    text: str                       # 공백·부호 없는 음절열
    src_start: list[int]            # text[i] 가 유래한 원본 문자 시작 인덱스
    src_end: list[int]              # 〃 끝 인덱스(배타적)
    variants: list[VariantSpan] = field(default_factory=list)
    raw: str = ""

    def origin(self, i: int, j: int) -> tuple[int, int]:
        """정규화 구간 [i, j) 에 대응하는 원본 문자 구간을 돌려준다."""
        if not self.text:
            return (0, 0)
        if i >= len(self.text):                       # 문자열 끝 뒤 (삽입 지점)
            last = len(self.src_end) - 1
            return (self.src_end[last], self.src_end[last])
        j = max(j, i + 1)
        return (self.src_start[i], self.src_end[min(j, len(self.text)) - 1])


def normalize(raw: str, *, drop_parens: bool = False,
              keep_hanja: bool = False) -> Normalized:
    """대본/STT 텍스트를 비교용 음절열로 바꾼다.

    drop_parens: 괄호 안 내용을 통째로 버린다. 원고에 한자·원어 병기가 많고
        성우가 그걸 읽지 않는 책이면 켜라. 기본값은 유지(=읽는다고 가정)인데,
        읽지 않는데 유지하면 '누락'으로, 읽는데 버리면 '삽입'으로 잡히므로
        첫 챕터에서 어느 쪽인지 확인하고 정하는 게 좋다.
    keep_hanja: 한자를 남긴다. 기본값은 제거 — 한글 병기가 일반적이고
        한자 자체를 소리 내어 읽는 경우는 드물다.
    """
    if drop_parens:
        raw_work = _blank_parens(raw)
    else:
        raw_work = raw

    out: list[str] = []
    src_s: list[int] = []
    src_e: list[int] = []
    variants: list[VariantSpan] = []

    pos = 0
    for m in _TOKEN_RE.finditer(raw_work):
        tok = m.group()
        pos = m.start()
        if tok.isspace() or _PUNCT_RE.fullmatch(tok):
            continue
        if not keep_hanja and _HANJA_RE.fullmatch(tok):
            continue

        if tok[0].isdigit():
            reads = number_readings(tok, raw_work[m.end():m.end() + 4])
            _emit_variant(out, src_s, src_e, variants, reads, pos, m.end(),
                          soft=False, kind="number")
        elif tok[0].isascii() and tok[0].isalpha():
            reads, soft = english_readings(tok)
            _emit_variant(out, src_s, src_e, variants, reads, pos, m.end(),
                          soft=soft, kind="english")
        else:
            out.append(tok)
            src_s.append(pos)
            src_e.append(m.end())

    return Normalized("".join(out), src_s, src_e, variants, raw)


def _emit_variant(out, src_s, src_e, variants, readings, start, end, *,
                  soft, kind) -> None:
    """대표 읽기를 본문에 넣고, 나머지 후보는 VariantSpan 으로 기록한다."""
    primary = readings[0] if readings else ""
    begin = len(out)
    for ch in primary:
        out.append(ch)
        src_s.append(start)
        src_e.append(end)
    if len(readings) > 1 or soft:
        variants.append(VariantSpan(begin, len(out), readings, start, end,
                                    soft=soft, kind=kind))


def _blank_parens(raw: str) -> str:
    """괄호 안을 공백으로 바꾼다. 길이를 유지해야 원본 인덱스가 안 틀어진다."""
    chars = list(raw)
    depth = 0
    for i, ch in enumerate(chars):
        if ch in "([{（〔":
            depth += 1
            chars[i] = " "
        elif ch in ")]}）〕":
            if depth:
                chars[i] = " "
            depth = max(0, depth - 1)
        elif depth:
            chars[i] = " "
    return "".join(chars)


@dataclass
class Sentence:
    no: int
    start: int
    end: int
    text: str


def split_sentences(raw: str) -> list[Sentence]:
    """원본 텍스트를 문장으로 나눈다. 리포트에서 위치를 짚어주는 용도."""
    sents: list[Sentence] = []
    for m in _SENT_RE.finditer(raw):
        text = m.group()
        if not text.strip():
            continue
        sents.append(Sentence(len(sents) + 1, m.start(), m.end(), text.strip()))
    if not sents and raw.strip():
        sents.append(Sentence(1, 0, len(raw), raw.strip()))
    return sents


def sentence_index(sents: list[Sentence]) -> list[int]:
    """bisect 용 시작 오프셋 배열."""
    return [s.start for s in sents]


def locate(sents: list[Sentence], starts: list[int], src_pos: int) -> Sentence | None:
    """원본 문자 위치가 속한 문장을 찾는다."""
    if not sents:
        return None
    i = bisect_right(starts, src_pos) - 1
    return sents[max(0, i)]


def strip_for_display(text: str) -> str:
    """리포트 출력용 — 줄바꿈을 공백으로 접는다."""
    return _SPACE_RE.sub(" ", text).strip()
