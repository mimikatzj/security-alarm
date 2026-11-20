"""카카오톡 '나에게 보내기' (talk/memo/default/send) 클라이언트."""
from __future__ import annotations

import json
import logging

import requests

log = logging.getLogger(__name__)

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
TEXT_LIMIT = 200  # 텍스트 템플릿 본문 최대 길이


class KakaoError(RuntimeError):
    pass


def _link(url: str) -> dict:
    return {"web_url": url, "mobile_web_url": url}


def truncate(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


class KakaoClient:
    def __init__(self, rest_api_key: str, refresh_token: str, client_secret: str | None = None):
        self.rest_api_key = rest_api_key
        self.refresh_token = refresh_token
        self.client_secret = client_secret
        self.access_token: str | None = None
        self.new_refresh_token: str | None = None

    def refresh(self) -> None:
        """refresh token 으로 access token 발급. 만료 1개월 이내면 새 refresh token 도 함께 발급됨."""
        data = {
            "grant_type": "refresh_token",
            "client_id": self.rest_api_key,
            "refresh_token": self.refresh_token,
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret
        r = requests.post(TOKEN_URL, data=data, timeout=15)
        if r.status_code != 200:
            raise KakaoError(f"토큰 갱신 실패 {r.status_code}: {r.text}")
        body = r.json()
        self.access_token = body["access_token"]
        if body.get("refresh_token"):
            self.new_refresh_token = body["refresh_token"]
            log.info("새 refresh token 발급됨 (GitHub Secret 갱신 필요)")

    def _send(self, template: dict) -> None:
        if not self.access_token:
            self.refresh()
        r = requests.post(
            MEMO_URL,
            headers={"Authorization": f"Bearer {self.access_token}"},
            data={"template_object": json.dumps(template, ensure_ascii=False)},
            timeout=15,
        )
        if r.status_code != 200 or r.json().get("result_code") != 0:
            raise KakaoError(f"메시지 전송 실패 {r.status_code}: {r.text}")

    def send_text(self, text: str, url: str, button_title: str = "자세히 보기") -> None:
        self._send(
            {
                "object_type": "text",
                "text": truncate(text, TEXT_LIMIT),
                "link": _link(url),
                "button_title": button_title,
            }
        )

    def send_list(
        self,
        header: str,
        header_url: str,
        rows: list[tuple[str, str, str]],
        button: tuple[str, str] | None = None,
    ) -> None:
        """rows: [(제목, 설명, URL)] 2~3개."""
        tpl = {
            "object_type": "list",
            "header_title": truncate(header, 200),
            "header_link": _link(header_url),
            "contents": [
                {"title": truncate(t, 80), "description": truncate(d, 80), "link": _link(u)}
                for t, d, u in rows
            ],
        }
        if button:
            tpl["buttons"] = [{"title": button[0], "link": _link(button[1])}]
        self._send(tpl)
