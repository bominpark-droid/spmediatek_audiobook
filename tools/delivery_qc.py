#!/usr/bin/env python3
"""SP미디어텍 오디오북 납품 전 자동 QC.

추출된 최종 음원(파일 또는 폴더)을 검사해 납품 기준 충족 여부를 판정한다.
  - 평균 레벨 (Integrated Loudness, LUFS)
  - 트루 피크 (기본 -3.0 dB 이하)
  - 노이즈 플로어 (RMS trough)
  - 파일 길이 (기본 70분 이하)
  - 시작/끝 헤드룸(무음 길이)
  - 샘플레이트/채널

사용:
  python3 tools/delivery_qc.py "납품폴더/"            # 폴더 전체
  python3 tools/delivery_qc.py 파일.wav 파일2.mp3      # 개별 파일
  python3 tools/delivery_qc.py "납품폴더/" --csv qc.csv
  python3 tools/delivery_qc.py "납품폴더/" --config qc_config.json

기준값은 --config 의 JSON으로 조정한다(없으면 아래 DEFAULTS).
기존에 문제없이 납품한 마스터를 먼저 측정해 우리 회사 기준으로 보정할 것.

의존성: ffmpeg/ffprobe (별도 파이썬 패키지 불필요)
종료코드: 전 파일 통과 0, 실패 있으면 1
"""

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULTS = {
    "peak_db_max": -3.0,          # 트루 피크 상한 (dBTP)
    "lufs_min": -23.0,            # 평균 레벨 하한 (LUFS)
    "lufs_max": -18.0,            # 평균 레벨 상한 (LUFS)
    "noise_floor_db_max": -60.0,  # 노이즈 플로어 상한 (dB, RMS trough)
    "duration_min_max": 70,       # 파일 길이 상한 (분)
    "head_silence_sec": [0.5, 2.0],   # 시작 무음 허용 범위 (초)
    "tail_silence_sec": [1.0, 3.0],   # 끝 무음 허용 범위 (초)
    "silence_threshold_db": -50,  # 무음으로 간주할 레벨
    "sample_rates": [44100, 48000],
    "channels": [1, 2],
}

AUDIO_EXT = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".aiff", ".aif"}


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def ffprobe_info(path):
    r = run(["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(path)])
    if r.returncode != 0:
        return None
    info = json.loads(r.stdout)
    audio = next((s for s in info.get("streams", [])
                  if s.get("codec_type") == "audio"), None)
    if not audio:
        return None
    return {
        "duration": float(info["format"].get("duration", 0)),
        "sample_rate": int(audio.get("sample_rate", 0)),
        "channels": int(audio.get("channels", 0)),
    }


def measure_loudness(path):
    """loudnorm 1차 패스로 Integrated LUFS + 트루 피크를 잰다."""
    r = run(["ffmpeg", "-hide_banner", "-i", str(path),
             "-af", "loudnorm=print_format=json", "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.DOTALL)
    if not m:
        return None, None
    data = json.loads(m.group(0))
    return float(data["input_i"]), float(data["input_tp"])


def measure_noise_floor(path):
    """astats의 RMS trough(가장 조용한 구간의 RMS)를 노이즈 플로어로 쓴다."""
    r = run(["ffmpeg", "-hide_banner", "-i", str(path),
             "-af", "astats=measure_perchannel=none", "-f", "null", "-"])
    m = re.search(r"RMS trough dB:\s*(-?[\d.]+|-inf)", r.stderr)
    if not m or m.group(1) == "-inf":
        return None
    return float(m.group(1))


def measure_head_tail_silence(path, duration, threshold_db):
    """silencedetect로 시작/끝 무음 길이를 잰다. (무음 없으면 0.0)"""
    r = run(["ffmpeg", "-hide_banner", "-i", str(path),
             "-af", f"silencedetect=noise={threshold_db}dB:d=0.1",
             "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)", r.stderr)]

    head = 0.0
    if starts and starts[0] <= 0.05:
        head = ends[0] if ends else duration

    tail = 0.0
    if starts:
        last = starts[-1]
        # 마지막 무음이 파일 끝까지 이어지는 경우 (end 로그가 없거나 파일 끝 근처)
        if len(ends) < len(starts) or (ends and duration - ends[-1] < 0.05 and starts[-1] > ends[-1] - 0.01):
            tail = duration - last
        elif ends and duration - ends[-1] < 0.05:
            tail = duration - starts[-1]
    return head, tail


def check_file(path, cfg):
    """한 파일을 검사해 (측정값 dict, 실패목록) 반환."""
    fails = []
    info = ffprobe_info(path)
    if info is None:
        return {"파일": path.name}, ["파일을 읽을 수 없음 (ffprobe 실패)"]

    lufs, peak = measure_loudness(path)
    noise = measure_noise_floor(path)
    head, tail = measure_head_tail_silence(
        path, info["duration"], cfg["silence_threshold_db"])

    dur_min = info["duration"] / 60.0

    def rng(v, lo, hi):
        return v is not None and lo <= v <= hi

    if not rng(lufs, cfg["lufs_min"], cfg["lufs_max"]):
        fails.append(f"평균레벨 {lufs} LUFS (기준 {cfg['lufs_min']}~{cfg['lufs_max']}) — 게인 조정으로 수정 가능")
    if peak is None or peak > cfg["peak_db_max"]:
        fails.append(f"트루피크 {peak} dB (기준 ≤{cfg['peak_db_max']}) — 게인/리미터로 수정 가능")
    if noise is not None and noise > cfg["noise_floor_db_max"]:
        fails.append(f"노이즈플로어 {noise} dB (기준 ≤{cfg['noise_floor_db_max']})")
    if dur_min > cfg["duration_min_max"]:
        fails.append(f"길이 {dur_min:.1f}분 (기준 ≤{cfg['duration_min_max']}분) — 챕터 경계에서 분할 필요")
    lo, hi = cfg["head_silence_sec"]
    if not rng(head, lo, hi):
        fails.append(f"시작 무음 {head:.2f}초 (기준 {lo}~{hi}초) — 패딩 조정으로 수정 가능")
    lo, hi = cfg["tail_silence_sec"]
    if not rng(tail, lo, hi):
        fails.append(f"끝 무음 {tail:.2f}초 (기준 {lo}~{hi}초) — 패딩 조정으로 수정 가능")
    if info["sample_rate"] not in cfg["sample_rates"]:
        fails.append(f"샘플레이트 {info['sample_rate']} (허용 {cfg['sample_rates']})")
    if info["channels"] not in cfg["channels"]:
        fails.append(f"채널 {info['channels']} (허용 {cfg['channels']})")

    row = {
        "파일": path.name,
        "길이(분)": f"{dur_min:.1f}",
        "평균레벨(LUFS)": lufs,
        "트루피크(dB)": peak,
        "노이즈플로어(dB)": noise,
        "시작무음(초)": f"{head:.2f}",
        "끝무음(초)": f"{tail:.2f}",
        "샘플레이트": info["sample_rate"],
        "채널": info["channels"],
        "판정": "PASS" if not fails else "FAIL",
        "실패사유": " / ".join(fails),
    }
    return row, fails


def collect_files(targets):
    files = []
    for t in targets:
        p = Path(t)
        if p.is_dir():
            files += sorted(x for x in p.rglob("*")
                            if x.suffix.lower() in AUDIO_EXT)
        elif p.is_file():
            files.append(p)
        else:
            print(f"! 경로 없음: {t}", file=sys.stderr)
    return files


def main():
    ap = argparse.ArgumentParser(description="오디오북 납품 QC")
    ap.add_argument("targets", nargs="+", help="검사할 파일 또는 폴더")
    ap.add_argument("--config", help="기준값 JSON (없으면 기본값)")
    ap.add_argument("--csv", help="결과 CSV 저장 경로")
    args = ap.parse_args()

    cfg = dict(DEFAULTS)
    if args.config:
        cfg.update(json.loads(Path(args.config).read_text(encoding="utf-8")))

    files = collect_files(args.targets)
    if not files:
        print("검사할 오디오 파일이 없습니다.", file=sys.stderr)
        sys.exit(2)

    rows, any_fail = [], False
    for f in files:
        print(f"검사 중: {f.name} ...", flush=True)
        row, fails = check_file(f, cfg)
        rows.append(row)
        if fails:
            any_fail = True

    print()
    print(f"{'판정':<5} {'파일':<40} {'길이(분)':>7} {'LUFS':>7} {'피크':>7} "
          f"{'노이즈':>7} {'시작무음':>7} {'끝무음':>7}")
    for r in rows:
        mark = "✓" if r["판정"] == "PASS" else "✗"
        print(f"{mark:<5} {r['파일']:<40} {r.get('길이(분)',''):>7} "
              f"{str(r.get('평균레벨(LUFS)','')):>7} {str(r.get('트루피크(dB)','')):>7} "
              f"{str(r.get('노이즈플로어(dB)','')):>7} {r.get('시작무음(초)',''):>7} "
              f"{r.get('끝무음(초)',''):>7}")
        if r["실패사유"]:
            print(f"      └ {r['실패사유']}")

    total, failed = len(rows), sum(1 for r in rows if r["판정"] == "FAIL")
    print(f"\n총 {total}개 중 통과 {total - failed} / 실패 {failed}")
    if failed:
        print("→ 실패 항목을 수정한 뒤 다시 돌려 전부 ✓가 되어야 납품합니다.")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as fp:
            w = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"CSV 저장: {args.csv}")

    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
