from __future__ import annotations

import json
from typing import Any

import requests

from app.config import settings


class QwenClient:
    def __init__(self) -> None:
        self.enabled = bool(settings.qwen_enabled and settings.dashscope_api_key)

    def chat_json(self, *, model: str, system: str, user: str, max_tokens: int = 1024) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        headers = {
            "Authorization": f"Bearer {settings.dashscope_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            resp = requests.post(settings.qwen_base_url, headers=headers, json=payload, timeout=30)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception:
            return None


qwen_client = QwenClient()
