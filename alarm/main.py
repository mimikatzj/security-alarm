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
from .kakao import TEXT_LIMIT, KakaoClient, truncate
from .state import SeenStore

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("alarm")
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)


def page_url(day_str: str | None = None) -> str | None:
    """GitHub Pages 주소 (https://<owner>.github.io/<repo>/<날짜>.html). GitHub 밖에서는 None.
    PAGES_URL 환경변수로 직접 지정할 수도 있다 (커스텀 도메인 등)."""
    base = os.getenv("PAGES_URL")
    if not base:
        repo = os.getenv("GITHUB_REPOSITORY")
        if not repo:
            return None
        owner, name = repo.split("/", 1)
        base = (f"https://{owner.lower()}.github.io" if name.lower() == f"{owner.lower()}.github.io"
                else f"https://{owner.lower()}.github.io/{name}")
    base = base.rstrip("/")
    return f"{base}/{day_str}.html" if day_str else f"{base}/"


def build_message(target, sections: list[Section], failed) -> str:
    """카톡 1건 본문 (최대 200자): 섹션별 건수 + 남는 자리에 주요 제목."""
    head = [f"🛡️ 보안 브리핑 · {target.month}/{target.day}({digest.WEEKDAYS[target.weekday()]}) 게시글"]
    total = sum(len(s.items) for s in sections)
    if total == 0:
        head.append("새 소식이 없습니다.")
    else:
        for s in sections:
            pc = s.priority_count
            head.append(f"{s.label} {len(s.items)}건" + (f" (❗{pc})" if pc else ""))
    if failed:
        head.append(f"⚠️ 수집 실패: {', '.join(failed)}")
    text = "\n".join(head)

    # 섹션별로 번갈아 상위 글 제목을 200자 안에서 덧붙임 (전체는 버튼으로)
    queues = [list(s.items) for s in sections if s.items]
    picks: list[Item] = []
    while any(queues):
        for q in queues:
            if q:
                picks.append(q.pop(0))
    body = ""
    for it in picks:
        line = f"\n{'❗' if it.priority else '·'}{truncate(it.title, 30)}"
        if len(text) + 1 + len(body) + len(line) > TEXT_LIMIT:
            break
        body += line
    return text + ("\n" + body if body else "")


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
    text = build_message(target, sections, failed)
    url = page_url(day_str) or "https://www.boho.or.kr"

    if args.dry_run:
        print("-" * 60)
        print(text, f"\n  [전체 목록 보기] {url}\n  ({len(text)}자 / {TEXT_LIMIT}자)")
        return 0

    if total:
        digest.write(ROOT / "digests" / f"{day_str}.md",
                     digest.build_markdown(target, sections, failed))
    digest.write_site(ROOT / "site", target, sections, failed)

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
        client.send_text(text, url, "전체 목록 보기")
        log.info("카톡 1건 발송 완료 → %s", url)

    # 발송 성공 후에만 기록 → 실패 시 다음 실행에 다시 포함됨
    store.add(handled, today)
    store.prune(today, cfg.get("state", {}).get("retention_days", 45))
    store.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
