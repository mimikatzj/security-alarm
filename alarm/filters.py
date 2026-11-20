"""키워드 기반 우선순위 / 중복 제거 / 섹션별 선별 (LLM 미사용)."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .collector import Item

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass
class Section:
    track: str
    region: str
    label: str
    limit: int = 0              # 섹션 전체 상한 (0 = 제한 없음)
    limit_per_source: int = 0   # 소스별 상한 (0 = 제한 없음)
    dedupe: bool = False        # 같은 사건 다른 기사 중복 제거
    strict_limit: bool = False  # True 면 우선순위 글도 상한을 넘지 않음
    items: list[Item] = field(default_factory=list)

    def matches(self, it: Item) -> bool:
        return it.track == self.track and (not self.region or it.region == self.region)

    @property
    def priority_count(self) -> int:
        return sum(1 for i in self.items if i.priority)


def load_sections(cfg: dict) -> list[Section]:
    out = []
    for s in cfg["sections"]:
        label = s.get("label") or (f"[{s['track']}] {s['region']}" if s.get("region") else f"[{s['track']}]")
        out.append(Section(s["track"], s.get("region", ""), label,
                           s.get("limit", 0) or 0, s.get("limit_per_source", 0) or 0,
                           bool(s.get("dedupe", False)), bool(s.get("strict_limit", False))))
    return out


# ---------------------------------------------------------------- 키워드 매칭

def _contains(text: str, keywords: list[str]) -> bool:
    low = text.lower()
    return any(str(k).lower() in low for k in keywords)


_ORG_PREFIX_RE = re.compile(r"^\s*[^\s,]{2,12},\s*")  # "개인정보위, " "과기정통부, " 같은 기관명 머리말


def priority_level(item: Item, rules: list[dict]) -> int:
    """맞는 규칙 중 가장 높은 level 반환 (0 = 일반). 제목만 본다 (요약은 오탐이 잦음).
    - any:   [..]          하나라도 포함
    - all:   [[..], [..]]  각 묶음에서 하나씩 모두 포함
    - none:  [..]          (선택) 이 중 하나라도 있으면 해당 규칙 불충족
    - level: 숫자          (선택, 기본 1) 클수록 먼저 배치"""
    # 기관명 머리말은 빼고 판단 (예: '개인정보위'의 '개인정보'가 항상 걸리는 것 방지)
    text = _ORG_PREFIX_RE.sub("", item.title)
    best = 0
    for rule in rules or []:
        if rule.get("none") and _contains(text, rule["none"]):
            continue
        hit = ("any" in rule and _contains(text, rule["any"])) or (
            "all" in rule and all(_contains(text, group) for group in rule["all"]))
        if hit:
            best = max(best, int(rule.get("level", 1)))
    return best


def score(item: Item, weights: dict[str, int]) -> int:
    text = f"{item.title} {item.summary}".lower()
    return sum(w for k, w in weights.items() if str(k).lower() in text)


# ---------------------------------------------------------------- 중복 제거

_STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "with", "by", "as", "at",
         "from", "is", "are", "via", "after", "its", "new", "over", "into", "says",
         # 보안 기사에 흔한 단어 — 같은 사건 판단에 도움이 안 됨
         "hackers", "hacker", "attack", "attacks", "data", "breach", "critical", "flaw",
         "rce", "security", "vulnerability", "exploited", "exploit", "ransomware", "cyberattack"}
# 한글 흔한 단어는 토큰화 전에 제거
_KO_COMMON_RE = re.compile(
    r"개인정보|유출|해킹|보안|취약점|공격|랜섬웨어|확인|규모|사고|피해|의심|가능성|정보|기업|서비스|시스템|최대|공식"
)
# 풀 크기가 작을 때 IDF 가 흔들리지 않도록 더하는 가상 문서 수
_IDF_SMOOTH = 20


def _tokens(title: str) -> set[str]:
    """한글은 2글자 단위, 영어는 단어 단위 토큰."""
    t = re.sub(r"\[[^\]]*\]", " ", title).lower()
    t = _KO_COMMON_RE.sub(" ", t)
    t = re.sub(r"[^\w가-힣]+", " ", t)
    out: set[str] = set()
    for w in t.split():
        if re.search("[가-힣]", w):
            out |= {w[i: i + 2] for i in range(len(w) - 1)} or {w}
        elif w not in _STOP and len(w) > 1:
            out.add(w)
    return out


_JOSA_RE = re.compile(r"(에서|으로|에게|까지|부터|이|가|은|는|을|를|의|에|로|와|과|도|만)$")
_KO_GENERIC = {"업데이트", "대학교", "정부", "당국", "기관", "공공", "금융", "고객", "회원", "사용자",
               "이용자", "학생", "직원", "서버", "계정", "홈페이지", "악성코드", "긴급", "주민등록번호",
               "데일리시큐", "보안뉴스"}  # 매체명


def _entities(title: str) -> set[str]:
    """고유명사 후보: 3글자 이상 한글 단어(조사 제거) / 숫자가 섞인 영어 단어(Java4Shell, CVE 번호 등).
    영어 일반 단어(stolen, active 등)는 오탐이 많아 제외 — 영어는 유사도만으로 판단."""
    t = re.sub(r"\[[^\]]*\]", " ", title).lower()
    t = _KO_COMMON_RE.sub(" ", t)
    out = set()
    for w in re.sub(r"[^\w가-힣]+", " ", t).split():
        if re.fullmatch(r"[가-힣]+", w):
            w = _JOSA_RE.sub("", w)
            if len(w) >= 3 and w not in _KO_GENERIC:
                out.add(w)
        elif re.fullmatch(r"[a-z0-9]+", w) and len(w) >= 4 and re.search(r"\d", w) and re.search(r"[a-z]", w):
            out.add(w)
    return out


def dedupe(items: list[Item], threshold: float) -> list[Item]:
    """같은 사건을 다룬 기사 제거. 앞쪽(우선순위 높은) 기사를 남긴다.
    중복 판단 = IDF 유사도 ≥ threshold
            또는 (고유명사를 공유하고 유사도 ≥ threshold × 0.55)
    흔한 단어(해킹·유출·RCE 등)보다 드문 단어(회사명·제품명)에 가중치를 준다."""
    ents = [_entities(i.title) for i in items]
    toks = [_tokens(i.title) for i in items]
    n = len(items)
    df: dict[str, int] = {}
    for t in toks:
        for x in t:
            df[x] = df.get(x, 0) + 1
    idf = {x: math.log((n + _IDF_SMOOTH) / c) for x, c in df.items()}

    def weight(s: set[str]) -> float:
        return sum(idf[x] for x in s)

    kept: list[int] = []
    for i in range(n):
        dup = False
        for j in kept:
            denom = min(weight(toks[i]), weight(toks[j]))
            sim = weight(toks[i] & toks[j]) / denom if denom > 0 else 0.0
            if sim >= threshold or (ents[i] & ents[j] and sim >= threshold * 0.55):
                dup = True
                break
        if not dup:
            kept.append(i)
    return [items[i] for i in kept]


# ---------------------------------------------------------------- 선별

def _rank_key(i: Item):
    return (i.priority, i.score, i.published or _EPOCH)


def select(
    per_source: dict[str, list[Item]],
    sources: list[dict],
    sections: list[Section],
    cfg: dict,
    seen: set[str],
) -> tuple[list[Section], set[str]]:
    """섹션별로 선별된 항목을 채워 반환. 두 번째 값은 이번에 '처리'한 모든 uid
    (상한·중복으로 안 보낸 글도 포함 — 다시 실행해도 같은 글이 나오지 않게 기록)."""
    global_excl = cfg.get("filters", {}).get("exclude_keywords", []) or []
    weights = cfg.get("scoring", {}).get("keywords", {}) or {}
    rules = cfg.get("priority_rules", {}) or {}
    threshold = cfg.get("dedupe_threshold", 0.35)
    src_cfg = {s["name"]: s for s in sources}

    handled: set[str] = set()
    candidates: list[Item] = []
    for name, items in per_source.items():
        sc = src_cfg[name]
        include = sc.get("include_keywords") or []
        exclude = global_excl + (sc.get("exclude_keywords") or [])
        for it in items:
            if it.uid in seen:
                continue
            handled.add(it.uid)
            text = f"{it.title} {it.summary}"
            if include and not _contains(text, include):
                continue
            if exclude and _contains(text, exclude):
                continue
            it.score = score(it, weights)
            it.priority = priority_level(it, rules.get(it.track, []))
            candidates.append(it)

    for sec in sections:
        pool = sorted((i for i in candidates if sec.matches(i)), key=_rank_key, reverse=True)
        if sec.dedupe:
            pool = dedupe(pool, threshold)
        sec.items = _pick(pool, sec.limit, sec.limit_per_source, sec.strict_limit)
    return sections, handled


def _pick(pool: list[Item], limit: int, per_source: int, strict: bool = False) -> list[Item]:
    """우선순위 글은 상한과 관계없이 전부, 남는 자리만 일반 글로 채운다.
    strict 이면 우선순위 글 먼저 채우되 상한(limit)에서 자른다."""
    # 높은 등급(침해사고 > 긴급 취약점)부터, 같은 등급 안에서만 매체별로 번갈아
    pri = [it for lv in sorted({i.priority for i in pool if i.priority}, reverse=True)
           for it in _round_robin([i for i in pool if i.priority == lv])]
    rest = _round_robin([i for i in pool if not i.priority])
    if strict and limit:
        return (pri + rest)[:limit]
    if per_source:
        out = list(pri)
        for src in dict.fromkeys(i.source for i in pool):
            room = per_source - sum(1 for i in pri if i.source == src)
            out += [i for i in rest if i.source == src][: max(0, room)]
        return sorted(out, key=_rank_key, reverse=True)
    if limit:
        return pri + rest[: max(0, limit - len(pri))]
    return pri + rest


def _round_robin(items: list[Item]) -> list[Item]:
    """한 소스가 상위권을 독점하지 않도록 소스별로 번갈아 배치 (라운드마다 점수순)."""
    by_src: dict[str, list[Item]] = {}
    for it in sorted(items, key=_rank_key, reverse=True):
        by_src.setdefault(it.source, []).append(it)
    out: list[Item] = []
    while by_src:
        rnd = [lst.pop(0) for lst in by_src.values()]
        out.extend(sorted(rnd, key=_rank_key, reverse=True))
        by_src = {s: lst for s, lst in by_src.items() if lst}
    return out
