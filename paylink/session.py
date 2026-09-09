from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def access_token_from_payload(data: Any) -> str:
    creds = credentials_from_payload(data)
    return creds["access_token"]


def session_token_from_payload(data: Any) -> str:
    return credentials_from_payload(data)["session_token"]


def credentials_from_payload(data: Any) -> dict[str, str]:
    """Read ChatGPT web session JSON (accessToken + sessionToken) or tool session files."""
    empty = {"access_token": "", "session_token": "", "account_id": "", "cookie_header": ""}
    if isinstance(data, str):
        text = data.strip()
        if text.startswith("{") or text.startswith("["):
            data = json.loads(text)
        else:
            token = text if _looks_token(text) else ""
            return {**empty, "access_token": token}
    if not isinstance(data, dict):
        return empty

    access = str(
        data.get("access_token")
        or data.get("accessToken")
        or ""
    ).strip()
    session = str(
        data.get("session_token")
        or data.get("sessionToken")
        or ""
    ).strip()
    cookie_header = str(
        data.get("cookie_header")
        or data.get("cookie")
        or ""
    ).strip()
    account = data.get("account") if isinstance(data.get("account"), dict) else {}
    account_id = str(account.get("id") or data.get("chatgpt_account_id") or data.get("account_id") or "").strip()
    auth_session = data.get("auth_session") if isinstance(data.get("auth_session"), dict) else {}
    if not access:
        for key in ("accessToken", "access_token"):
            value = auth_session.get(key)
            if isinstance(value, str) and value.strip():
                access = value.strip()
                break
        nested = auth_session.get("session") if isinstance(auth_session.get("session"), dict) else {}
        if not access:
            for key in ("accessToken", "access_token"):
                value = nested.get(key)
                if isinstance(value, str) and value.strip():
                    access = value.strip()
                    break
    if not session:
        session = str(auth_session.get("sessionToken") or auth_session.get("session_token") or "").strip()
    if not cookie_header:
        cookie_header = str(auth_session.get("cookie_header") or auth_session.get("cookie") or "").strip()
    if not session and "session-token=" in cookie_header.lower():
        for item in cookie_header.split(";"):
            if "__secure-next-auth.session-token=" in item.lower():
                session = item.split("=", 1)[1].strip()
                break
    if not cookie_header and session:
        cookie_header = session
    return {
        "access_token": access,
        "session_token": session,
        "account_id": account_id,
        "cookie_header": cookie_header,
    }


def credentials_from_path(path: str | Path) -> dict[str, str]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    creds = credentials_from_payload(payload)
    if not creds["access_token"] and not creds["session_token"] and not creds["cookie_header"]:
        raise ValueError(f"no access_token/sessionToken in {source}")
    return creds


def access_token_from_path(path: str | Path) -> str:
    creds = credentials_from_path(path)
    token = creds["access_token"]
    if not token:
        raise ValueError(f"no access_token in {path}")
    return token


def _looks_token(text: str) -> bool:
    return text.startswith(("eyJ", "sk-", "ya29.")) or len(text) > 40
