from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def access_token_from_payload(data: Any) -> str:
    """Pull an access token from the session JSON shapes this repo already writes."""
    if isinstance(data, str):
        text = data.strip()
        return text if text.startswith(("eyJ", "sk-", "ya29.")) or len(text) > 40 else ""
    if not isinstance(data, dict):
        return ""
    token = str(data.get("access_token") or data.get("accessToken") or "").strip()
    if token:
        return token
    auth_session = data.get("auth_session") if isinstance(data.get("auth_session"), dict) else {}
    for key in ("accessToken", "access_token"):
        value = auth_session.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = auth_session.get("session") if isinstance(auth_session.get("session"), dict) else {}
    for key in ("accessToken", "access_token"):
        value = nested.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def access_token_from_path(path: str | Path) -> str:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    token = access_token_from_payload(payload)
    if not token:
        raise ValueError(f"no access_token in {source}")
    return token
