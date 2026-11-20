"""이미 보낸 글 기록 (state/seen.json). GitHub Actions 가 실행 후 커밋합니다."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path


class SeenStore:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.data: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = {}

    def ids(self) -> set[str]:
        return set(self.data)

    def add(self, uids, today: date) -> None:
        for uid in uids:
            self.data.setdefault(uid, today.isoformat())

    def prune(self, today: date, retention_days: int) -> None:
        cutoff = (today - timedelta(days=retention_days)).isoformat()
        self.data = {k: v for k, v in self.data.items() if v >= cutoff}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=0, sort_keys=True) + "\n",
            encoding="utf-8",
        )
