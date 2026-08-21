"""대본을 정답으로 놓고 음성을 강제 정렬(forced alignment)한다.

compare 는 STT가 받아쓴 결과를 대조하므로, STT가 틀린 것과 성우가 틀린 것을
끝내 구분하지 못한다. 정렬은 그 전제를 바꾼다 — 대본을 정답으로 주고
"이 오디오가 이 대본과 어디서 어긋나는가"만 묻는다. 모델이 단어를 새로
지어낼 수 없으니 가짜 오류가 원천적으로 생기지 않는다.

결과는 단어별 (시작, 끝, 확률)이고, 검수자는 확률이 낮거나 앞뒤 간격이
비정상인 지점만 들어보면 된다.

백엔드는 stable-ts(= Whisper 기반 정렬). 무거우므로 지연 import 한다:

    pip install stable-ts

분석 로직(find_suspects)은 백엔드와 분리돼 있어 stable-ts 없이도 검증된다.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import normalize as nz

# 이 확률 아래면 "대본대로 안 읽었을 가능성"으로 본다.
LOW_PROB = 0.40
# 단어 사이 무음이 이보다 길면 표시. 리테이크 흔적·문단 건너뜀 신호.
LONG_GAP = 2.0
# 문장 낭독 속도가 중앙값의 이 배수를 벗어나면 표시.
PACE_FAST = 1.6      # 너무 빠름 → 일부 건너뛰었을 수 있음
PACE_SLOW = 0.55     # 너무 느림 → 더듬음·반복·삽입


@dataclass
class Word:
    """정렬된 단어 하나."""
    text: str
    start: float
    end: float
    probability: float


@dataclass
class Suspect:
    """들어봐야 할 지점."""
    reason: str          # 낮은확률 | 긴무음 | 빠른낭독 | 느린낭독
    severity: str        # 높음 | 중간 | 낮음
    start: float
    end: float
    text: str
    sent_no: int
    detail: str = ""

    @property
    def timecode(self) -> str:
        return f"{_tc(self.start)} → {_tc(self.end)}"


@dataclass
class AlignResult:
    words: list[Word] = field(default_factory=list)
    suspects: list[Suspect] = field(default_factory=list)
    duration: float = 0.0

    def to_json(self, path: Path) -> Path:
        path.write_text(
            json.dumps(
                {
                    "duration": self.duration,
                    "words": [asdict(w) for w in self.words],
                    "suspects": [asdict(s) for s in self.suspects],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return path


def _tc(seconds: float) -> str:
    """00:12:34.5 형태. 검수자가 DAW에서 바로 찾아갈 수 있게."""
    h, rem = divmod(max(0.0, seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:04.1f}"


def align(audio: str | Path, script_text: str, *, model_name: str = "large-v3",
          language: str = "ko", faster: bool = True) -> AlignResult:
    """음성과 대본을 정렬한다. stable-ts 가 설치돼 있어야 한다.

    faster=True 면 faster-whisper 백엔드를 쓴다 (2~4배 빠르고 정확도는 동일).
    긴 챕터에서는 사실상 필수다.
    """
    try:
        import stable_whisper
    except ImportError as e:  # 설치 안내를 명확히 — 여기서 막히는 사람이 많다
        raise RuntimeError(
            "강제 정렬에는 stable-ts 가 필요합니다.\n"
            "    pip install -r qc/requirements-align.txt\n"
            "GPU 없이 CPU로도 되지만 large-v3 는 실시간의 몇 배가 걸립니다. "
            "먼저 --model medium 으로 한 챕터만 시험해 보세요."
        ) from e

    if faster:
        model = stable_whisper.load_faster_whisper(model_name)
    else:
        model = stable_whisper.load_model(model_name)

    # align() 은 대본을 정답으로 받아 타임스탬프만 추정한다. 받아쓰기가 아니다.
    result = model.align(str(audio), script_text, language=language)

    words = [
        Word(w.word, float(w.start), float(w.end), float(getattr(w, "probability", 1.0)))
        for seg in result.segments
        for w in seg.words
    ]
    duration = words[-1].end if words else 0.0
    return AlignResult(words=words,
                       suspects=find_suspects(words, script_text),
                       duration=duration)


def find_suspects(words: list[Word], script_text: str, *,
                  low_prob: float = LOW_PROB,
                  long_gap: float = LONG_GAP) -> list[Suspect]:
    """정렬 결과에서 확인이 필요한 지점을 뽑는다.

    stable-ts 없이도 검증 가능하도록 순수 함수로 분리해 뒀다.
    """
    if not words:
        return []
    suspects: list[Suspect] = []
    sents = nz.split_sentences(script_text)
    sent_of = _map_words_to_sentences(words, sents)

    suspects.extend(_low_prob_runs(words, sent_of, low_prob))
    suspects.extend(_long_gaps(words, sent_of, long_gap))
    suspects.extend(_pace_outliers(words, sents, sent_of))
    suspects.sort(key=lambda s: s.start)
    return suspects


def _map_words_to_sentences(words: list[Word], sents: list[nz.Sentence]) -> list[int]:
    """단어 i 가 몇 번째 문장에 속하는지. 정렬은 대본 순서를 지키므로 누적 길이로 센다."""
    if not sents:
        return [0] * len(words)
    out: list[int] = []
    si, consumed = 0, 0
    for w in words:
        budget = len(nz.normalize(sents[si].text).text)
        while si < len(sents) - 1 and consumed >= budget:
            si += 1
            consumed = 0
            budget = len(nz.normalize(sents[si].text).text)
        out.append(sents[si].no)
        consumed += len(nz.normalize(w.text).text)
    return out


def _low_prob_runs(words: list[Word], sent_of: list[int],
                   threshold: float) -> list[Suspect]:
    """확률이 낮은 단어가 연달아 나오는 구간. 한 단어짜리 흔들림은 노이즈다."""
    out: list[Suspect] = []
    i = 0
    while i < len(words):
        if words[i].probability >= threshold:
            i += 1
            continue
        j = i
        while j + 1 < len(words) and words[j + 1].probability < threshold:
            j += 1
        run = words[i:j + 1]
        worst = min(w.probability for w in run)
        out.append(Suspect(
            reason="낮은확률",
            severity="높음" if len(run) >= 3 or worst < 0.2 else "중간",
            start=run[0].start,
            end=run[-1].end,
            text="".join(w.text for w in run).strip(),
            sent_no=sent_of[i],
            detail=f"{len(run)}단어 연속, 최저 {worst:.2f}",
        ))
        i = j + 1
    return out


def _long_gaps(words: list[Word], sent_of: list[int], threshold: float) -> list[Suspect]:
    out: list[Suspect] = []
    for i in range(len(words) - 1):
        gap = words[i + 1].start - words[i].end
        if gap < threshold:
            continue
        out.append(Suspect(
            reason="긴무음",
            severity="높음" if gap >= threshold * 2 else "낮음",
            start=words[i].end,
            end=words[i + 1].start,
            text=f"…{words[i].text} ▮ {words[i + 1].text}…",
            sent_no=sent_of[i],
            detail=f"{gap:.1f}초 무음",
        ))
    return out


def _pace_outliers(words: list[Word], sents: list[nz.Sentence],
                   sent_of: list[int]) -> list[Suspect]:
    """문장별 낭독 속도가 튀는 곳. 누락은 빠르게, 더듬음·반복은 느리게 나타난다."""
    by_sent: dict[int, list[Word]] = {}
    for w, no in zip(words, sent_of):
        by_sent.setdefault(no, []).append(w)

    paces: dict[int, float] = {}
    for no, ws in by_sent.items():
        span = ws[-1].end - ws[0].start
        chars = sum(len(w.text.strip()) for w in ws)
        if span > 0.5 and chars >= 8:      # 너무 짧은 문장은 통계가 무의미
            paces[no] = chars / span
    if len(paces) < 5:
        return []

    median = statistics.median(paces.values())
    out: list[Suspect] = []
    for no, pace in paces.items():
        ratio = pace / median
        if ratio < PACE_FAST and ratio > PACE_SLOW:
            continue
        ws = by_sent[no]
        fast = ratio >= PACE_FAST
        out.append(Suspect(
            reason="빠른낭독" if fast else "느린낭독",
            severity="중간",
            start=ws[0].start,
            end=ws[-1].end,
            text="".join(w.text for w in ws).strip()[:60],
            sent_no=no,
            detail=("평균 대비 {:.1f}배 빠름 — 일부 건너뛰었을 수 있음" if fast
                    else "평균 대비 {:.1f}배 느림 — 더듬음·반복 확인").format(
                        ratio if fast else 1 / ratio),
        ))
    return out
