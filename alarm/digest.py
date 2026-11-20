"""전체 목록: 마크다운(digests/) + 웹 페이지(site/, GitHub Pages)."""
from __future__ import annotations

from datetime import date
from html import escape
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


# ---------------------------------------------------------------- 웹 페이지 (GitHub Pages)

_CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#e5e5e5;--link:#0b57d0;--pri:#c62828;--card:#fafafa}
@media (prefers-color-scheme:dark){:root{--bg:#121212;--fg:#e8e8e8;--muted:#9a9a9a;--line:#2c2c2c;--link:#8ab4f8;--pri:#ff6b6b;--card:#1b1b1b}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic",sans-serif}
main{max-width:760px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:1.3rem;margin:0 0 4px}
.sub{color:var(--muted);font-size:.9rem;margin:0 0 20px}
.warn{background:var(--card);border-left:3px solid var(--pri);padding:8px 12px;margin:0 0 16px;font-size:.9rem}
h2{font-size:1.05rem;margin:28px 0 8px;padding-bottom:6px;border-bottom:1px solid var(--line)}
h2 small{color:var(--muted);font-weight:normal}
ul{list-style:none;margin:0;padding:0}
li{padding:10px 0;border-bottom:1px solid var(--line)}
li a{color:var(--link);text-decoration:none;font-weight:600}
li a:hover{text-decoration:underline}
.pri{color:var(--pri);margin-right:4px}
.meta{color:var(--muted);font-size:.82rem;margin-top:2px}
.sum{color:var(--muted);font-size:.85rem;margin-top:4px}
.empty{color:var(--muted)}
footer{margin-top:32px;font-size:.85rem}
footer a{color:var(--link)}
"""


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='robots' content='noindex,nofollow'>"
        f"<title>{escape(title)}</title><style>{_CSS}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )


def build_html(target: date, sections, failed: list[str]) -> str:
    total = sum(len(s.items) for s in sections)
    pc = sum(s.priority_count for s in sections)
    out = [f"<h1>보안 브리핑 · {fmt_day(target)}</h1>",
           f"<p class='sub'>게시글 {total}건" + (f" · ❗우선 {pc}건" if pc else "") + "</p>"]
    if failed:
        out.append(f"<p class='warn'>⚠️ 수집 실패: {escape(', '.join(failed))}</p>")
    for sec in sections:
        out.append(f"<h2>{escape(sec.label)} <small>{len(sec.items)}건</small></h2>")
        if not sec.items:
            out.append("<p class='empty'>새 글 없음</p>")
            continue
        out.append("<ul>")
        for it in sec.items:
            mark = "<span class='pri'>❗</span>" if it.priority else ""
            summ = f"<div class='sum'>{escape(it.summary[:160])}</div>" if it.summary else ""
            out.append(
                f"<li>{mark}<a href='{escape(it.link)}' target='_blank' rel='noopener'>{escape(it.title)}</a>"
                f"<div class='meta'>{escape(it.source)} · {fmt_pub(it)}</div>{summ}</li>")
        out.append("</ul>")
    out.append("<footer><a href='./'>지난 브리핑 보기</a></footer>")
    return _page(f"보안 브리핑 {target.isoformat()}", "".join(out))


def build_index(site_dir: Path) -> str:
    days = sorted((p.stem for p in site_dir.glob("????-??-??.html")), reverse=True)
    rows = "".join(
        f"<li><a href='{d}.html'>{fmt_day(date.fromisoformat(d))}</a></li>" for d in days
    ) or "<li class='empty'>아직 없음</li>"
    return _page("보안 브리핑", f"<h1>보안 브리핑</h1><p class='sub'>날짜별 목록</p><ul>{rows}</ul>")


def write_site(site_dir: Path, target: date, sections, failed: list[str]) -> None:
    write(site_dir / f"{target.isoformat()}.html", build_html(target, sections, failed))
    write(site_dir / "index.html", build_index(site_dir))
