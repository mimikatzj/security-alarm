"""보안 브리핑 배치 진입점.

  python -m alarm.main            # 수집 → 카톡 발송 → 상태 저장
  python -m alarm.main --dry-run  # 카톡 대신 콘솔 출력, 상태 저장 안 함
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import warnings
from datetime import date, datetime, time, timedelta
from pathlib import Path

import yaml
from bs4 import MarkupResemblesLocatorWarning

from . import digest
from .collector import KST, Item, collect
from .filters import Section, load_sections, select
from .kakao import KakaoClient, KakaoError, truncate
from .state import SeenStore

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("alarm")
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)


def digest_url(day_str: str) -> str | None:
    """GitHub 에서 실행 중이면 다이제스트 파일의 웹 URL."""
    repo = os.getenv("GITHUB_REPOSITORY")
    if not repo:
        return None
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    branch = os.getenv("GITHUB_REF_NAME", "main")
    return f"{server}/{repo}/blob/{branch}/digests/{day_str}.md"


def _mark(it: Item) -> str:
    return "❗" if it.priority else ""


def build_messages(today, target, sections: list[Section], failed, cfg, full_url):
    """카톡 메시지 목록. [("text", dict) | ("list", dict)]
    1) 요약 텍스트  2) 섹션별 리스트(3건씩, 1건이면 텍스트)"""
    kcfg = cfg.get("kakao", {})
    max_msgs = kcfg.get("max_messages", 20)
    fallback_url = full_url or "https://www.boho.or.kr"

    total = sum(len(s.items) for s in sections)
    lines = [f"🛡️ 보안 브리핑 {digest.fmt_day(today)}", f"대상: {digest.fmt_day(target)} 게시글", ""]
    if total == 0:
        lines.append("새 소식이 없습니다.")
    for s in sections:
        if s.items:
            pc = s.priority_count
            lines.append(f"{s.label} {len(s.items)}건" + (f" (❗{pc})" if pc else ""))
    if failed:
        lines += ["", f"⚠️ 수집 실패: {', '.join(failed)}"]
    msgs = [("text", {"text": "\n".join(lines), "url": fallback_url, "button_title": "전체 목록"})]

    for sec in sections:
        chunks = [sec.items[i: i + 3] for i in range(0, len(sec.items), 3)]
        for n, chunk in enumerate(chunks, 1):
            if len(msgs) >= max_msgs:
                log.warning("max_messages(%d) 초과 — 나머지는 다이제스트에만 기록", max_msgs)
                return msgs
            header = sec.label if len(chunks) == 1 else f"{sec.label} ({n}/{len(chunks)})"
            if len(chunk) == 1:  # 리스트 템플릿은 최소 2건 필요
                it = chunk[0]
                msgs.append(("text", {
                    "text": f"{header}\n\n{_mark(it)}{it.title}\n- {it.source} · {digest.fmt_pub(it)}",
                    "url": it.link, "button_title": "원문 보기",
                }))
            else:
                msgs.append(("list", {
                    "header": header,
                    "header_url": fallback_url,
                    "rows": [(f"{_mark(i)}{i.title}",
                              f"{i.source} · {digest.fmt_pub(i)}", i.link) for i in chunk],
                    "button": ("전체 목록", full_url) if full_url else None,
                }))
    return msgs


def send_all(client: KakaoClient, msgs) -> None:
    for kind, m in msgs:
        if kind == "text":
            client.send_text(m["text"], m["url"], m["button_title"])
            continue
        try:
            client.send_list(m["header"], m["header_url"], m["rows"], m["button"])
        except KakaoError as exc:  # 리스트 템플릿 실패 시 건별 텍스트로 대체
            log.warning("리스트 전송 실패, 텍스트로 재시도: %s", exc)
            for title, desc, url in m["rows"]:
                client.send_text(f"{m['header']}\n\n{title}\n- {desc}", url, "원문 보기")


def print_messages(msgs) -> None:
    for kind, m in msgs:
        print("-" * 60)
        if kind == "text":
            print(m["text"], f"\n  [{m['button_title']}] {m['url']}")
        else:
            print(m["header"])
            for t, d, u in m["rows"]:
                print(f"  • {t}\n    {d}\n    {u}")


def export_new_refresh_token(token: str) -> None:
    """Actions 다음 스텝에서 Secret 을 갱신할 수 있도록 파일로 전달."""
    path = os.getenv("KAKAO_NEW_TOKEN_FILE")
    if path:
        Path(path).write_text(token, encoding="utf-8")
    elif os.getenv("GITHUB_ACTIONS"):
        log.warning("새 refresh token 이 발급됐지만 KAKAO_NEW_TOKEN_FILE 미설정 — 수동 갱신 필요")
    else:
        print(f"\n[!] 새 refresh token: {token}\n    KAKAO_REFRESH_TOKEN 을 이 값으로 바꿔주세요.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="보안뉴스·가이드 일일 브리핑")
    parser.add_argument("--config", default=str(ROOT / "config" / "sources.yaml"))
    parser.add_argument("--dry-run", action="store_true", help="카톡 발송/상태 저장 없이 출력만")
    parser.add_argument("--ignore-seen", action="store_true", help="이미 보낸 글도 포함")
    parser.add_argument("--date", type=date.fromisoformat,
                        help="대상 날짜 YYYY-MM-DD (기본: 어제, KST). 누락된 날 다시 보낼 때 사용")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    sources = cfg["sources"]
    today = datetime.now(KST).date()
    target = args.date or today - timedelta(days=1)
    start = datetime.combine(target, time.min, tzinfo=KST)
    end = start + timedelta(days=1)

    store = SeenStore(ROOT / "state" / "seen.json")
    per_source, failed = collect(sources, start, end)
    if not per_source:
        log.error("모든 소스 수집 실패")
        return 1

    sections, handled = select(per_source, sources, load_sections(cfg), cfg,
                               set() if args.ignore_seen else store.ids())
    total = sum(len(s.items) for s in sections)
    log.info("대상일 %s, 새 소식 %d건 (%s)", target, total,
             ", ".join(f"{s.label} {len(s.items)}(❗{s.priority_count})" for s in sections))

    day_str = target.isoformat()
    full_url = digest_url(day_str) if total else None
    msgs = build_messages(today, target, sections, failed, cfg, full_url)

    if args.dry_run:
        print_messages(msgs)
        return 0

    if total:
        digest.write(ROOT / "digests" / f"{day_str}.md",
                     digest.build_markdown(target, sections, failed))

    if total or cfg.get("kakao", {}).get("notify_when_empty", True):
        client = KakaoClient(
            os.environ["KAKAO_REST_API_KEY"],
            os.environ["KAKAO_REFRESH_TOKEN"],
            os.getenv("KAKAO_CLIENT_SECRET") or None,
        )
        try:
            client.refresh()
        finally:
            if client.new_refresh_token:
                export_new_refresh_token(client.new_refresh_token)
        send_all(client, msgs)
        log.info("카톡 %d건 발송 완료", len(msgs))

    # 발송 성공 후에만 기록 → 실패 시 다음 실행에 다시 포함됨
    store.add(handled, today)
    store.prune(today, cfg.get("state", {}).get("retention_days", 45))
    store.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
