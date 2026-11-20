"""최초 1회: 카카오 refresh token 발급 도우미 (로컬에서 실행).

사용법:
  python scripts/kakao_auth.py --rest-api-key <REST_API_KEY> [--client-secret <SECRET>] \
      [--redirect-uri https://localhost:3000]

1) 출력된 URL 을 브라우저에서 열고 로그인/동의
2) 리다이렉트된 주소창 URL 전체(또는 code 값)를 붙여넣기
3) 출력된 refresh_token 을 GitHub Secret KAKAO_REFRESH_TOKEN 에 저장
"""
import argparse
import sys
from urllib.parse import parse_qs, urlencode, urlparse

import requests


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--rest-api-key", required=True)
    p.add_argument("--client-secret")
    p.add_argument("--redirect-uri", default="https://localhost:3000")
    a = p.parse_args()

    auth_url = "https://kauth.kakao.com/oauth/authorize?" + urlencode(
        {
            "client_id": a.rest_api_key,
            "redirect_uri": a.redirect_uri,
            "response_type": "code",
            "scope": "talk_message",
        }
    )
    print("1) 아래 URL 을 브라우저에서 여세요:\n\n" + auth_url + "\n")
    raw = input("2) 리다이렉트된 URL 전체 또는 code 값을 붙여넣으세요: ").strip()
    code = parse_qs(urlparse(raw).query).get("code", [raw])[0]

    data = {
        "grant_type": "authorization_code",
        "client_id": a.rest_api_key,
        "redirect_uri": a.redirect_uri,
        "code": code,
    }
    if a.client_secret:
        data["client_secret"] = a.client_secret
    r = requests.post("https://kauth.kakao.com/oauth/token", data=data, timeout=15)
    if r.status_code != 200:
        print("토큰 발급 실패:", r.status_code, r.text)
        return 1
    body = r.json()
    print("\n발급 성공. 아래 값을 GitHub Secret KAKAO_REFRESH_TOKEN 에 저장하세요.\n")
    print(body["refresh_token"])
    print(f"\n(refresh token 유효기간: {body.get('refresh_token_expires_in', 0) // 86400}일, "
          f"scope: {body.get('scope')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
