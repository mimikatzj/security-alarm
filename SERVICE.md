# 서비스 개요

## 목적
매일 아침 국내외 보안 사고·정책·가이드를 자동으로 모아 카카오톡으로 받는다.

## 원칙
- LLM 미사용: 키워드 규칙 기반 필터링·점수화만 사용
- 서버 없음: GitHub Actions 스케줄(매일 08:00 KST)로 실행, 상태는 저장소에 커밋
- 지정 메뉴만 수집: 사이트 전체가 아니라 지정한 게시판/카테고리만 읽는다
- 설정 중심: 소스·상한·키워드는 `config/sources.yaml`에서 조정

## 최종 출력

```
[사고]
- 국내 [최대 5건]   보안뉴스(사건·사고), 데일리시큐(이슈)
- 해외 [최대 3건]   The Hacker News(Cyber Attack), BleepingComputer(Security)

[정책] [각각 최대 3건]
  개인정보보호위원회(보도자료), 과학기술정보통신부(보도자료)

[가이드] [올라오는 건 전부]
  KISA 보호나라(보고서/가이드), 개인정보보호위원회(안내서), 금융보안원(가이드)
```

## 소스별 수집 방식

| 소스 | URL | 방식 |
|---|---|---|
| 보안뉴스 사건·사고 | https://www.boannews.com/rss/S1N2.xml | RSS |
| 데일리시큐 이슈 | https://www.dailysecu.com/rss/S1N2.xml | RSS |
| The Hacker News Cyber Attack | https://thehackernews.com/feeds/posts/default/-/Cyber%20Attack?alt=rss | RSS |
| BleepingComputer Security | https://www.bleepingcomputer.com/feed/ | RSS, 링크가 `/news/security/`인 글만 |
| 개인정보위 보도자료 | https://pipc.go.kr/np/cop/bbs/selectBoardList.do?bbsId=BS074&mCode=C020010000 | 목록 HTML 파싱 |
| 과기정통부 보도자료 | https://www.msit.go.kr/bbs/list.do?sCode=user&mPid=208&mId=307 | 목록 HTML 파싱, 등록일은 페이지 스크립트(`td_REG_DT_n`)에서 추출 |
| KISA 보호나라 보고서/가이드 | https://www.boho.or.kr/kr/rss.do?bbsId=B0000127 | RSS (목록 menuNo=205021과 같은 게시판) |
| 개인정보위 안내서 | https://pipc.go.kr/np/cop/bbs/selectBoardList.do?bbsId=BS217&mCode=D010030000 | 목록 HTML 파싱 |
| 금융보안원 가이드 | https://www.fsec.or.kr/bbs/222 | 게시판 목록 JSON API (`POST /bbs/list`) |

## 실행 시점
매일 07:00 KST, **전날(00:00~24:00 KST) 게시글**을 대상으로 한다.

## 우선순위
| 섹션 | 최우선 (❗) |
|---|---|
| 사고 | ① 실제 침해사고가 난 건 (최우선) ② 긴급·고위험 취약점 (제로데이, 실제 악용, 긴급 패치 등) |
| 정책 | 보안 관련 정책 변경, 과징금, 조사 |

우선순위 글이 상한(국내 5, 정책 소스별 3)을 넘으면 **전부** 보여준다.
남는 자리는 일반 글로 채운다.
단, **해외는 상한 3건을 지킨다** (우선순위 글부터 채우고 3건에서 자름).

## 중복 체크
`[사고] 국내` 안에서, `[사고] 해외` 안에서만 같은 사건을 다룬 기사를 하나로 줄인다.
정책·가이드는 중복 체크를 하지 않는다.

## 처리 흐름
1. **수집**: 소스별 수집기 실행 → 전날 게시글만 남김. 한 소스가 실패해도 나머지는 계속 진행
2. **정제**: 이미 보낸 글 제외 → 제외 키워드
3. **판정**: 트랙별 우선순위 규칙(제목 기준)으로 ❗ 판정, 키워드 점수 계산
4. **중복 제거**: 사고 섹션만, 같은 사건 기사 중 우선순위 높은 1건 유지
5. **선별**: 우선순위 글 전부 + 남는 자리에 일반 글 (점수 → 최신순, 매체별로 번갈아)
6. **발송**: 카카오톡 나에게 보내기 (요약 1건 + 섹션별 리스트)
7. **기록**: `digests/YYYY-MM-DD.md` 전체 목록, `state/seen.json` 발송 이력 커밋
