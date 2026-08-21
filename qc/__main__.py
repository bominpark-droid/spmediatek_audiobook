"""오디오북 검수 CLI.

    # 1단계 — 이미 뽑아둔 STT 결과를 대본과 대조 (정규화 + 음절 정렬)
    python -m qc compare --script 원고.txt --stt stt.txt --out out/

    # 2단계 — 대본을 정답으로 음성을 강제 정렬 (stable-ts 필요)
    python -m qc align --audio ch01.wav --script 원고.txt --out out/

두 단계 모두 out/ 에 콘솔 요약 + CSV 체크리스트를 남긴다.
compare 는 추가로 대본 하이라이트 HTML을 만든다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import report as rp
from .compare import compare


def _read(path: Path) -> str:
    if not path.exists():
        sys.exit(f"파일을 찾을 수 없습니다: {path}")
    for enc in ("utf-8", "utf-8-sig", "cp949", "euc-kr"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    sys.exit(f"인코딩을 알 수 없습니다: {path} (utf-8 또는 cp949로 저장해 주세요)")


def cmd_compare(args: argparse.Namespace) -> int:
    script_raw = _read(Path(args.script))
    stt_raw = _read(Path(args.stt))
    result = compare(script_raw, stt_raw,
                     drop_parens=args.drop_parens, keep_hanja=args.keep_hanja)
    rp.print_compare(result, limit=args.limit)

    out = Path(args.out)
    stem = Path(args.script).stem
    csv_path = rp.write_compare_csv(result, out / f"{stem}_검수.csv")
    html_path = rp.write_compare_html(result, script_raw, out / f"{stem}_검수.html",
                                      title=f"{stem} 검수 리포트")
    print("-" * 66)
    print(f"  체크리스트 : {csv_path}")
    print(f"  대본 표시  : {html_path}")
    return 0


def cmd_align(args: argparse.Namespace) -> int:
    from .align import align  # torch 를 끌고 오므로 이 명령에서만 부른다

    script_raw = _read(Path(args.script))
    if not Path(args.audio).exists():
        sys.exit(f"음원을 찾을 수 없습니다: {args.audio}")
    try:
        result = align(args.audio, script_raw, model_name=args.model,
                       language=args.language, faster=not args.no_faster)
    except RuntimeError as e:   # 설치 안내는 트레이스백 없이 그대로 보여준다
        sys.exit(str(e))
    rp.print_align(result, limit=args.limit)

    out = Path(args.out)
    stem = Path(args.audio).stem
    out.mkdir(parents=True, exist_ok=True)
    csv_path = rp.write_align_csv(result, out / f"{stem}_정렬.csv")
    json_path = result.to_json(out / f"{stem}_정렬.json")
    print("-" * 66)
    print(f"  체크리스트 : {csv_path}")
    print(f"  정렬 원본  : {json_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="qc", description="오디오북 대본 대조 검수")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compare", help="STT 결과를 대본과 대조 (1단계)")
    c.add_argument("--script", required=True, help="대본 텍스트 파일")
    c.add_argument("--stt", required=True, help="STT 결과 텍스트 파일")
    c.add_argument("--out", default="out", help="리포트 저장 폴더 (기본: out)")
    c.add_argument("--limit", type=int, default=40, help="콘솔에 출력할 건수")
    c.add_argument("--drop-parens", action="store_true",
                   help="괄호 안 내용을 안 읽는 책일 때 켠다")
    c.add_argument("--keep-hanja", action="store_true",
                   help="한자를 그대로 두고 비교한다 (기본은 제거)")
    c.set_defaults(func=cmd_compare)

    a = sub.add_parser("align", help="대본 기준 강제 정렬 (2단계)")
    a.add_argument("--audio", required=True, help="음원 파일 (wav/mp3/m4a)")
    a.add_argument("--script", required=True, help="대본 텍스트 파일")
    a.add_argument("--out", default="out", help="리포트 저장 폴더 (기본: out)")
    a.add_argument("--model", default="large-v3", help="Whisper 모델 (기본: large-v3)")
    a.add_argument("--language", default="ko")
    a.add_argument("--no-faster", action="store_true",
                   help="faster-whisper 대신 원본 whisper 백엔드를 쓴다")
    a.add_argument("--limit", type=int, default=40)
    a.set_defaults(func=cmd_align)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
