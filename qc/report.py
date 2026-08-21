"""검수 결과 출력 — 콘솔 요약, CSV 체크리스트, HTML 대본 하이라이트.

CSV는 엑셀로 열어 검수자가 체크하며 쓰고, HTML은 대본 위에 의심 구간을
표시해 앞뒤 문맥과 함께 보게 한다. 실제 검수는 결국 '어디를 들어볼지'를
정하는 일이라, 위치와 문맥이 리포트 품질의 전부다.
"""
from __future__ import annotations

import csv
import html
from pathlib import Path

from .align import AlignResult
from .compare import Finding, Report

SEVERITY_ORDER = {"높음": 0, "중간": 1, "확인필요": 2, "낮음": 3}
_COLORS = {
    "누락": "#e11d48", "삽입": "#2563eb", "대치": "#d97706",
    "낮은확률": "#d97706", "긴무음": "#7c3aed",
    "빠른낭독": "#e11d48", "느린낭독": "#2563eb",
}


def print_compare(report: Report, *, limit: int = 40) -> None:
    """콘솔 요약. 먼저 이걸 보고 CSV/HTML로 넘어간다."""
    print("=" * 66)
    print("대본 ↔ STT 대조 결과")
    print("=" * 66)
    print(f"  대본 음절수      : {report.script_syllables:,}")
    print(f"  STT 음절수       : {report.stt_syllables:,}")
    print(f"  음절 일치율      : {report.match_rate:.1%}")
    print()
    print(f"  기존 방식(어절 diff) 차이 : {report.naive_diffs:,}건")
    print(f"  정규화 후 걸러낸 표기차이 : {report.suppressed:,}건")
    print(f"  실제 확인 대상            : {len(report.findings):,}건", end="")
    if report.naive_diffs:
        print(f"   ({report.reduction:.1%} 감소)")
    else:
        print()
    print("-" * 66)

    if not report.findings:
        print("  확인이 필요한 지점이 없습니다.")
        return

    by_sev: dict[str, int] = {}
    for f in report.findings:
        by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
    print("  심각도: " + "  ".join(
        f"{k} {by_sev[k]}건" for k in sorted(by_sev, key=lambda s: SEVERITY_ORDER.get(s, 9))))
    print("-" * 66)

    ordered = sorted(report.findings,
                     key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.src_start))
    for f in ordered[:limit]:
        print(f"[{f.severity}] {f.kind}  (문장 {f.sent_no}, 원고 {f.src_start:,}자 지점)")
        print(f"    대본 : {_ellipsis(f.script_text) or '(없음)'}")
        print(f"    낭독 : {_ellipsis(f.stt_text) or '(없음)'}")
        if f.note:
            print(f"    비고 : {f.note}")
        print()
    if len(ordered) > limit:
        print(f"  … 외 {len(ordered) - limit}건. 전체는 CSV/HTML 참고.")


def print_align(result: AlignResult, *, limit: int = 40) -> None:
    print("=" * 66)
    print("강제 정렬 결과")
    print("=" * 66)
    print(f"  정렬된 단어 수 : {len(result.words):,}")
    print(f"  오디오 길이    : {result.duration / 60:.1f}분")
    print(f"  확인 대상      : {len(result.suspects):,}건")
    print("-" * 66)
    if not result.suspects:
        print("  확인이 필요한 지점이 없습니다.")
        return
    ordered = sorted(result.suspects,
                     key=lambda s: (SEVERITY_ORDER.get(s.severity, 9), s.start))
    for s in ordered[:limit]:
        print(f"[{s.severity}] {s.reason}  {s.timecode}  (문장 {s.sent_no})")
        print(f"    {_ellipsis(s.text)}")
        if s.detail:
            print(f"    비고 : {s.detail}")
        print()
    if len(ordered) > limit:
        print(f"  … 외 {len(ordered) - limit}건. 전체는 CSV/JSON 참고.")


def write_compare_csv(report: Report, path: Path) -> Path:
    """엑셀로 열어 쓰는 검수 체크리스트. '확인' 열은 비워 두고 검수자가 채운다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["확인", "심각도", "유형", "문장번호", "원고위치",
                    "대본", "낭독(STT)", "문장 전체", "비고"])
        for x in sorted(report.findings,
                        key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.src_start)):
            w.writerow(["", x.severity, x.kind, x.sent_no, x.src_start,
                        x.script_text, x.stt_text, x.sent_text, x.note])
    return path


def write_align_csv(result: AlignResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["확인", "심각도", "사유", "시작", "끝", "타임코드",
                    "문장번호", "내용", "비고"])
        for s in sorted(result.suspects,
                        key=lambda s: (SEVERITY_ORDER.get(s.severity, 9), s.start)):
            w.writerow(["", s.severity, s.reason, f"{s.start:.2f}", f"{s.end:.2f}",
                        s.timecode, s.sent_no, s.text, s.detail])
    return path


def write_compare_html(report: Report, script_raw: str, path: Path, *,
                       title: str = "오디오북 검수 리포트") -> Path:
    """대본 위에 의심 구간을 표시한 단일 HTML. 외부 자원 없이 그대로 열린다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    findings = sorted(report.findings, key=lambda f: f.src_start)
    body, cursor = [], 0
    for idx, f in enumerate(findings):
        start = max(f.src_start, cursor)
        end = max(f.src_end, start + 1)
        body.append(html.escape(script_raw[cursor:start]))
        marked = html.escape(script_raw[start:end]) or "▮"
        tip = html.escape(f"{f.kind}/{f.severity} · 낭독: {f.stt_text or '(없음)'}")
        body.append(
            f'<mark id="f{idx}" class="k-{f.kind}" title="{tip}">{marked}</mark>'
        )
        cursor = end
    body.append(html.escape(script_raw[cursor:]))

    rows = "\n".join(
        f'<li class="s-{f.severity}"><a href="#f{idx}">'
        f'<b>{html.escape(f.severity)}</b> {html.escape(f.kind)} '
        f'<span class="sn">문장 {f.sent_no}</span><br>'
        f'<span class="sc">대본: {html.escape(f.script_text or "(없음)")}</span><br>'
        f'<span class="st">낭독: {html.escape(f.stt_text or "(없음)")}</span>'
        + (f'<br><span class="nt">{html.escape(f.note)}</span>' if f.note else "")
        + "</a></li>"
        for idx, f in enumerate(findings)
    ) or "<li>확인이 필요한 지점이 없습니다.</li>"

    legend = " ".join(
        f'<span class="lg"><i style="background:{c}"></i>{k}</span>'
        for k, c in list(_COLORS.items())[:3]
    )
    path.write_text(_HTML.format(
        title=html.escape(title),
        legend=legend,
        naive=f"{report.naive_diffs:,}",
        suppressed=f"{report.suppressed:,}",
        kept=f"{len(report.findings):,}",
        rate=f"{report.match_rate:.1%}",
        rows=rows,
        script="".join(body),
    ), encoding="utf-8")
    return path


def _ellipsis(text: str, limit: int = 70) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "…"


_HTML = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; --bg:#fff; --fg:#18181b; --mut:#71717a;
           --line:#e4e4e7; --panel:#fafafa; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#18181b; --fg:#f4f4f5; --mut:#a1a1aa; --line:#3f3f46; --panel:#232327; }}
  }}
  * {{ box-sizing:border-box }}
  body {{ margin:0; background:var(--bg); color:var(--fg); display:flex;
         font:15px/1.8 -apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif; }}
  aside {{ width:340px; flex:none; border-right:1px solid var(--line);
           height:100vh; overflow:auto; background:var(--panel); }}
  main {{ flex:1; height:100vh; overflow:auto; padding:32px 40px; }}
  h1 {{ font-size:17px; margin:0 0 4px; padding:20px 18px 0; }}
  .stat {{ padding:0 18px 14px; color:var(--mut); font-size:13px; }}
  .stat b {{ color:var(--fg); }}
  .lg {{ margin-right:10px; white-space:nowrap; font-size:12px; }}
  .lg i {{ display:inline-block; width:9px; height:9px; border-radius:2px;
           margin-right:4px; vertical-align:middle; }}
  ul {{ list-style:none; margin:0; padding:0 10px 40px; }}
  li a {{ display:block; padding:10px 12px; border-radius:8px; text-decoration:none;
          color:inherit; border-left:3px solid transparent; font-size:13px;
          line-height:1.6; }}
  li a:hover {{ background:var(--bg); }}
  .s-높음 a {{ border-left-color:#e11d48 }}
  .s-중간 a {{ border-left-color:#d97706 }}
  .s-확인필요 a {{ border-left-color:#7c3aed }}
  .s-낮음 a {{ border-left-color:var(--line) }}
  .sn {{ color:var(--mut) }}
  .sc, .st, .nt {{ color:var(--mut); font-size:12px; }}
  .nt {{ color:#7c3aed }}
  article {{ max-width:760px; white-space:pre-wrap; word-break:keep-all; }}
  mark {{ background:none; padding:1px 0; border-bottom:2px solid; cursor:help; }}
  mark:target {{ background:rgba(234,179,8,.28) }}
  .k-누락 {{ border-color:#e11d48; color:#e11d48 }}
  .k-삽입 {{ border-color:#2563eb; color:#2563eb }}
  .k-대치 {{ border-color:#d97706; color:#d97706 }}
</style>
<aside>
  <h1>{title}</h1>
  <div class="stat">
    기존 방식 <b>{naive}</b>건 → 표기차이 <b>{suppressed}</b>건 제외 →
    확인 대상 <b>{kept}</b>건<br>음절 일치율 <b>{rate}</b><br><br>{legend}
  </div>
  <ul>{rows}</ul>
</aside>
<main><article>{script}</article></main>
"""
