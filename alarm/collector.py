"""소스별 수집기 (RSS + RSS 없는 게시판 전용 파서) 및 정규화."""
from __future__ import annotations

import calendar
import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
HEADERS = {
    # 일부 사이트(BleepingComputer 등)는 봇 UA 를 403 처리하므로 브라우저 UA 사용
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}
TIMEOUT = 20

# "2026-11-19", "2026.11.19", "2026-11-19 17:25:11" 처럼 타임존 없는 날짜(국내 사이트) → KST
_NAIVE_DATE_RE = re.compile(
    r"^(\d{4})[-./](\d{1,2})[-./](\d{1,2})\.?(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$"
)
_WS_RE = re.compile(r"\s+")


@dataclass
class Item:
    source: str
    track: str
    region: str
    title: str
    link: str
    published: datetime | None
    summary: str = ""
    score: int = 0
    priority: int = 0   # 0 = 일반, 클수록 우선 (priority_rules 의 level)

    @property
    def uid(self) -> str:
        return self.link or f"{self.source}:{self.title}"


# ---------------------------------------------------------------- 유틸

def clean_text(raw: str | None) -> str:
    if not raw:
        return ""
    text = BeautifulSoup(html.unescape(raw), "html.parser").get_text(" ")
    return _WS_RE.sub(" ", text).strip()


def parse_naive_kst(raw: str) -> datetime | None:
    m = _NAIVE_DATE_RE.match(raw.strip())
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    try:
        return datetime(y, mo, d, h, mi, s, tzinfo=KST)
    except ValueError:
        return None


def normalize_link(link: str) -> str:
    link = html.unescape(link.strip())
    # 카카오 메시지 링크는 등록 도메인 기준이라 https 로 통일 (THN 피드가 http 링크를 줌)
    return "https://" + link[7:] if link.startswith("http://") else link


def _get(url: str) -> requests.Response:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r


# ---------------------------------------------------------------- 수집기

def fetch_rss(src: dict) -> list[dict]:
    resp = _get(src["url"])
    feed = feedparser.parse(resp.content)
    if not feed.entries:
        raise ValueError(f"피드 항목 없음 (content-type={resp.headers.get('content-type')})")
    out = []
    for e in feed.entries:
        out.append({
            "title": e.get("title"),
            "link": e.get("link") or "",
            "published": _rss_date(e),
            "summary": e.get("summary"),
        })
    return out


def _rss_date(entry) -> datetime | None:
    for key in ("published", "updated"):
        raw = (entry.get(key) or "").strip()
        if not raw:
            continue
        naive = parse_naive_kst(raw)
        if naive:
            return naive
        parsed = entry.get(f"{key}_parsed")
        if parsed:
            return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    return None


def fetch_pipc_board(src: dict) -> list[dict]:
    """개인정보보호위원회 게시판 (보도자료 BS074, 안내서 BS217 공통 구조)."""
    soup = BeautifulSoup(_get(src["url"]).text, "html.parser")
    out = []
    for tr in soup.select("table tbody tr"):
        a = tr.select_one("td.boardTitle a")
        if not a:
            continue
        for badge in a.select("span.new"):
            badge.decompose()
        date = None
        for td in tr.find_all("td"):
            date = parse_naive_kst(td.get_text(strip=True)) or date
        out.append({
            "title": a.get_text(" "),
            "link": urljoin(src["url"], a.get("href", "")),
            "published": date,
        })
    if not out:
        raise ValueError("게시글 목록을 찾지 못함 (페이지 구조 변경 가능성)")
    return out


_MSIT_DATE_RE = re.compile(r"""\$\('#td_'\+'REG_DT'\+'_(\d+)'\)\.html\('([^']*)'\)""")


def fetch_msit_board(src: dict) -> list[dict]:
    """과학기술정보통신부 보도자료.
    목록 표의 등록일 칸은 비어 있고, 페이지 하단 스크립트가
    $('#td_'+'REG_DT'+'_0').html('Nov 19, 2026') 형태로 채운다 → 주석을 걷어내고 그 값을 읽는다."""
    text = _get(src["url"]).text
    script = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    script = re.sub(r"(?m)^\s*//.*$", "", script)
    dates: dict[int, datetime] = {}
    for idx, raw in _MSIT_DATE_RE.findall(script):
        d = _parse_msit_date(raw)
        if d:
            dates[int(idx)] = d

    soup = BeautifulSoup(text, "html.parser")
    out = []
    for a in soup.select("div.toggle > a[href*='view.do']"):
        title = a.select_one("p.title")
        if not title:
            continue
        m = re.search(r"td_NTT_SJ_(\d+)", title.get("id", ""))
        out.append({
            "title": title.get_text(" "),
            "link": urljoin(src["url"], a["href"]),
            "published": dates.get(int(m.group(1))) if m else None,
        })
    if not out:
        raise ValueError("게시글 목록을 찾지 못함 (페이지 구조 변경 가능성)")
    return out


def _parse_msit_date(raw: str) -> datetime | None:
    """요청 언어에 따라 'Nov 19, 2026' / '2026. 11. 19' / '2026-11-19' 로 온다."""
    raw = raw.strip()
    try:
        return datetime.strptime(raw, "%b %d, %Y").replace(tzinfo=KST)
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})\D*", raw)
    if m:
        try:
            return datetime(*map(int, m.groups()), tzinfo=KST)
        except ValueError:
            return None
    return None


def fetch_fsec_board(src: dict) -> list[dict]:
    """금융보안원 게시판. 목록은 /bbs/list JSON API 로 불러온다 (menuNo = URL 마지막 숫자)."""
    parsed = urlparse(src["url"])
    menu_no = parsed.path.rstrip("/").split("/")[-1]
    base = f"{parsed.scheme}://{parsed.netloc}"
    r = requests.post(
        f"{base}/bbs/list",
        json={"menuNo": menu_no, "pagingSearchDto": {"page": 1, "pageSize": 10,
                                                     "searchType": "", "searchContents": ""}},
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("resultCode") != "00":
        raise ValueError(f"API 오류: {body.get('resultMsg')}")
    return [
        {
            "title": row.get("title"),
            "link": f"{base}/bbs/detail?menuNo={menu_no}&bbsNo={row['bbsNo']}",
            "published": parse_naive_kst(row.get("regDate") or ""),
            "summary": row.get("contents"),
        }
        for row in body.get("resultData") or []
    ]


FETCHERS = {
    "rss": fetch_rss,
    "pipc_board": fetch_pipc_board,
    "msit_board": fetch_msit_board,
    "fsec_board": fetch_fsec_board,
}


# ---------------------------------------------------------------- 진입점

def fetch_source(src: dict) -> list[Item]:
    fetcher = FETCHERS[src.get("type", "rss")]
    prefix = src.get("link_prefix")
    items = []
    for raw in fetcher(src):
        title = clean_text(raw.get("title"))
        link = normalize_link(raw.get("link") or "")
        if not title:
            continue
        if prefix and not link.startswith(prefix):  # 사이트 내 지정 메뉴만
            continue
        items.append(Item(
            source=src["name"],
            track=src["track"],
            region=src.get("region", ""),
            title=title,
            link=link,
            published=raw.get("published"),
            summary=clean_text(raw.get("summary"))[:300],
        ))
    return items


def collect(
    sources: list[dict], start: datetime, end: datetime
) -> tuple[dict[str, list[Item]], list[str]]:
    """활성화된 모든 소스 수집 → 게시 시각이 [start, end) 인 글만.
    ({소스명: 항목}, [실패한 소스명]) 반환. 날짜를 알 수 없는 글은 제외."""
    result: dict[str, list[Item]] = {}
    failed: list[str] = []
    for src in sources:
        if not src.get("enabled", True):
            continue
        try:
            items = fetch_source(src)
        except Exception as exc:  # 한 소스 실패가 전체를 막지 않도록
            log.warning("[%s] 수집 실패: %s", src["name"], exc)
            failed.append(src["name"])
            continue
        in_range = [i for i in items if i.published and start <= i.published < end]
        undated = sum(1 for i in items if not i.published)
        log.info("[%s] %d건 수집, 대상일 %d건%s", src["name"], len(items), len(in_range),
                 f" (날짜 없음 {undated}건 제외)" if undated else "")
        if items and len(items) == undated:
            log.warning("[%s] 모든 글의 날짜를 읽지 못함 (페이지 구조 변경 가능성)", src["name"])
        result[src["name"]] = in_range
    return result, failed
