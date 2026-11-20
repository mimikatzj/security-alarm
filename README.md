# security-alarm

국내외 보안 사고·정책 보도자료·보안 가이드를 지정 메뉴에서 모아서 **매일 아침 8시(KST) 카카오톡 "나에게 보내기"로 보내는** 배치입니다.
LLM 없이 Python으로만 동작하고, GitHub Actions에서 실행됩니다.

## 구조

```
alarm/
  collector.py   수집기 (RSS / 개인정보위·과기정통부 목록 파싱 / 금융보안원 API), 날짜는 KST 기준
  filters.py     제외 키워드, 이미 보낸 글/중복 제목 제거, 키워드 점수, 섹션별 상한 적용
  kakao.py       토큰 갱신 + 나에게 보내기 (리스트/텍스트 템플릿)
  digest.py      전체 목록 마크다운 (digests/YYYY-MM-DD.md)
  state.py       이미 보낸 글 기록 (state/seen.json)
  main.py        진입점
config/sources.yaml   수집 소스, 키워드, 메시지 수 설정
scripts/kakao_auth.py 최초 1회 refresh token 발급 도우미
.github/workflows/daily-brief.yml
```

## 출력 구성 · 수집 소스

| 섹션 | 상한 | 소스 (사이트 내 지정 메뉴) | 수집 방식 |
|---|---|---|---|
| [사고] 국내 | 최대 5건 | 보안뉴스 사건·사고, 데일리시큐 이슈 | RSS |
| [사고] 해외 | 최대 3건 | The Hacker News Cyber Attack, BleepingComputer Security | RSS (Bleeping은 `/news/security/` 링크만) |
| [정책] | 소스별 최대 3건 | 개인정보보호위원회 보도자료 | 목록 페이지 파싱 |
| | | 과학기술정보통신부 보도자료 | 목록 페이지 파싱 (등록일은 페이지 스크립트에서 추출) |
| [가이드] | 전부 | KISA 보호나라 보고서/가이드 | RSS |
| | | 개인정보보호위원회 안내서 | 목록 페이지 파싱 |
| | | 금융보안원 가이드 | 게시판 JSON API |

소스·상한·키워드는 `config/sources.yaml`만 고치면 됩니다.
RSS가 없는 사이트는 화면 구조가 바뀌면 수집이 깨질 수 있습니다. 실패하면 카톡 요약에 "⚠️ 수집 실패: 소스명"이 표시됩니다.

## 로컬 테스트

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt       # Windows (macOS/Linux: .venv/bin/pip)
.venv/Scripts/python -m alarm.main --dry-run         # 카톡 대신 콘솔 출력, 상태 저장 안 함
```

## 설정 순서

### 1. 카카오 개발자 앱 만들기
1. https://developers.kakao.com 에서 **애플리케이션 추가**
2. **앱 키 → REST API 키** 복사
3. **카카오 로그인 → 활성화 ON**, **Redirect URI**에 `https://localhost:3000` 추가
4. **카카오 로그인 → 동의항목 → "카카오톡 메시지 전송(talk_message)"** 을 선택 동의로 설정
5. **플랫폼 → Web → 사이트 도메인**에 아래 도메인 등록 (등록 안 한 도메인 링크는 카톡에서 열리지 않음)
   ```
   https://www.boannews.com
   https://www.dailysecu.com
   https://thehackernews.com
   https://www.bleepingcomputer.com
   https://pipc.go.kr
   https://www.msit.go.kr
   https://www.boho.or.kr
   https://www.fsec.or.kr
   https://github.com
   ```
6. (선택) **보안 → Client Secret**을 쓰고 있으면 그 값도 복사

### 2. refresh token 발급 (로컬, 1회)
```bash
.venv/Scripts/python scripts/kakao_auth.py --rest-api-key <REST_API_KEY> [--client-secret <SECRET>]
```
출력된 URL을 열어 로그인·동의하고, 연결 오류 화면이 나오면 **주소창 URL 전체**를 붙여넣으면 refresh token이 출력됩니다.

### 3. GitHub 저장소 Secrets 등록
`Settings → Secrets and variables → Actions → New repository secret`

| 이름 | 값 | 필수 |
|---|---|---|
| `KAKAO_REST_API_KEY` | REST API 키 | ✅ |
| `KAKAO_REFRESH_TOKEN` | 2단계 결과 | ✅ |
| `KAKAO_CLIENT_SECRET` | Client Secret을 쓰는 경우 | |
| `GH_PAT` | refresh token 자동 갱신용 PAT (아래 참고) | 권장 |

**GH_PAT**: 카카오 refresh token은 약 2개월간 유효하고, 만료 1개월 전부터 토큰을 갱신할 때 새 토큰이 함께 발급됩니다.
워크플로가 새 토큰을 `KAKAO_REFRESH_TOKEN` Secret에 자동으로 저장하려면 **Fine-grained PAT**(해당 저장소, *Secrets: Read and write* 권한)를 `GH_PAT`로 등록하세요.
등록하지 않으면 경고만 남기며, 약 2개월마다 2단계를 다시 해야 합니다.

### 4. 실행 확인
`Actions → daily-security-brief → Run workflow` (먼저 `dry_run` 체크해서 로그 확인 → 체크 해제 후 실제 발송)

## 동작 방식

- **일정**: 매일 UTC 22:00 = **KST 07:00** 실행, **전날 00:00~24:00(KST)에 올라온 글**만 대상 (GitHub 스케줄은 수십 분 늦어질 수 있지만 대상 날짜는 고정이라 영향 없음)
- **누락 복구**: 실행을 놓친 날은 `Run workflow`에서 `date`에 그 날짜(YYYY-MM-DD)를 넣어 다시 보낼 수 있습니다. 로컬은 `python -m alarm.main --date 2026-11-18`.
- **우선순위 (❗)**: `priority_rules` 규칙에 맞는 글. 제목만 보고 판단합니다.
  - 사고 ① 최우선: 실제 침해사고 (해킹·유출·랜섬웨어·탈취·breach·hacked 등, 단 "위험/점검/권고/패치" 같은 취약점·권고 기사는 제외)
  - 사고 ② 우선: 긴급·고위험 취약점 (제로데이, 실제 악용, 원격 코드 실행, "긴급/critical + 취약점/패치" 등)
  - 같은 ❗ 안에서는 ①이 ②보다 먼저 배치됩니다 (해외처럼 3건 고정일 때 침해사고부터 채움).
  - 정책: 과징금·과태료·제재·처분·조사, 또는 보안 관련 + 정책 변경(개정·시행·의무·강화·지침 등)
- **상한 규칙**: 우선순위 글은 **상한을 넘어도 전부** 보여주고, 남는 자리만 일반 글(키워드 점수 → 최신순, 매체별로 번갈아)로 채웁니다.
  예) 국내 사고 상한 5건인데 침해사고가 8건이면 8건 모두 발송.
  단, **`[사고] 해외`는 예외로 상한 3건을 지킵니다** (`strict_limit: true`, 우선순위 글부터 채움).
- **같은 사건 중복 제거**: `[사고] 국내`, `[사고] 해외` 섹션 안에서만 합니다 (`dedupe: true`). 제목의 드문 단어(회사명·제품명) 겹침으로 판단하고 우선순위가 높은 기사를 남깁니다. 기준은 `dedupe_threshold`로 조절합니다.
- **재발송 방지**: 보낸 글 링크를 `state/seen.json`에 기록하고 워크플로가 커밋합니다 (45일 보관). 같은 날짜로 다시 실행해도 같은 글은 다시 오지 않고, 발송에 실패하면 기록하지 않습니다.
- **카톡 메시지**: 요약 1건 + 섹션별 리스트(3건씩 묶음), 하루 최대 `max_messages`(기본 20)건. 같은 내용이 `digests/날짜.md`에도 남고 "전체 목록" 버튼으로 연결됩니다.
- **장애 대응**: 소스 하나가 실패해도 나머지는 발송하고 요약 메시지에 "수집 실패"를 표시합니다. 전부 실패하거나 카톡 발송이 실패하면 워크플로가 실패하고 GitHub이 메일로 알려줍니다.
- 커밋이 매일 생기므로 "60일 동안 활동 없는 저장소의 스케줄 비활성화"에도 걸리지 않습니다.

## 주의
- 저장소가 **private**이면 "전체 목록" 링크(github.com)는 GitHub에 로그인해야 볼 수 있습니다.
