"""카카오 설정 확인용: 테스트 메시지 1건(텍스트 + 리스트) 발송.

사용법 (PowerShell):
  $env:KAKAO_REST_API_KEY="..."; $env:KAKAO_REFRESH_TOKEN="..."; [$env:KAKAO_CLIENT_SECRET="..."]
  .venv\\Scripts\\python scripts\\kakao_test.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from alarm.kakao import KakaoClient, KakaoError  # noqa: E402


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        client = KakaoClient(
            os.environ["KAKAO_REST_API_KEY"],
            os.environ["KAKAO_REFRESH_TOKEN"],
            os.getenv("KAKAO_CLIENT_SECRET") or None,
        )
    except KeyError as e:
        print(f"환경변수 {e} 가 없습니다.")
        return 1
    try:
        client.refresh()
        print("1) 토큰 갱신 성공")
        client.send_text("🛡️ 보안 브리핑 테스트 메시지입니다.", "https://www.boho.or.kr", "보호나라 열기")
        print("2) 텍스트 메시지 발송 성공")
        client.send_list(
            "[사고] 국내 (테스트)",
            "https://www.boannews.com",
            [
                ("❗테스트 기사 1", "보안뉴스 · 링크 확인용", "https://www.boannews.com"),
                ("테스트 기사 2", "데일리시큐 · 링크 확인용", "https://www.dailysecu.com"),
            ],
        )
        print("3) 리스트 메시지 발송 성공 — 카톡 '나와의 채팅'을 확인하고 링크가 열리는지 눌러보세요.")
    except KakaoError as e:
        print("실패:", e)
        return 1
    if client.new_refresh_token:
        print("\n[!] 새 refresh token 이 발급됐습니다. KAKAO_REFRESH_TOKEN 을 이 값으로 바꾸세요:\n"
              + client.new_refresh_token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
