"""전체 목록 마크다운 다이제스트 (digests/YYYY-MM-DD.md)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from .collector import KST, Item

WEEKDAYS = "월화수목금토일"


def fmt_day(d: date) -> str:
    return f"{d.isoformat()} ({WEEKDAYS[d.weekday()]})"


def fmt_pub(it: Item) -> str:
    if not it.published:
        return "-"
    t = it.published.astimezone(KST)
    return t.strftime("%m/%d") if (t.hour, t.minute) == (0, 0) else t.strftime("%m/%d %H:%M")


def build_markdown(target: date, sections, failed: list[str]) -> str:
    total = sum(len(s.items) for s in sections)
    lines = [f"# 보안 브리핑 — {fmt_day(target)} 게시글", "", f"새 소식 {total}건 (❗ = 우선순위)", ""]
    if failed:
        lines += [f"> ⚠️ 수집 실패: {', '.join(failed)}", ""]
    for sec in sections:
        if not sec.items:
            continue
        lines += [f"## {sec.label} ({len(sec.items)})", ""]
        for it in sec.items:
            mark = "❗ " if it.priority else ""
            title = it.title.replace("[", "\\[").replace("]", "\\]")
            lines.append(f"- {mark}[{title}]({it.link}) — {it.source} · {fmt_pub(it)}")
            if it.summary:
                lines.append(f"  - {it.summary[:160]}")
        lines.append("")
    return "\n".join(lines)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
