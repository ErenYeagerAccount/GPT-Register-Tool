from __future__ import annotations

import re
import uuid
from typing import Any, Protocol
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

CHATGPT_ORIGIN = "https://chatgpt.com"
GEO = {
    "JP": {"lang": "ja", "lang_full": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7"},
    "IN": {"lang": "en-IN", "lang_full": "en-IN,en-US;q=0.9,en;q=0.8"},
    "US": {"lang": "en-US", "lang_full": "en-US,en;q=0.9"},
}


class HttpResponse:
    def __init__(self, status_code: int, text: str = "", payload: Any = None) -> None:
        self.status_code = int(status_code)
        self.text = text or ""
        self._payload = payload

    def json(self) -> Any:
        if self._payload is not None:
            return self._payload
        import json

        return json.loads(self.text or "{}")


class Transport(Protocol):
    def chatgpt_post(
        self,
        path: str,
        body: dict[str, Any],
        token: str,
        proxy: str,
        timeout: int,
        cookie: str = "",
        account_id: str = "",
    ) -> HttpResponse: ...
    def chatgpt_get(
        self,
        path: str,
        token: str,
        proxy: str,
        timeout: int,
        cookie: str = "",
        account_id: str = "",
    ) -> HttpResponse: ...
    def stripe_post(self, url: str, data: dict[str, str], proxy: str, timeout: int) -> HttpResponse: ...
    def stripe_get(self, url: str, params: dict[str, str], proxy: str, timeout: int) -> HttpResponse: ...
    def fetch_text(self, url: str, proxy: str, timeout: int) -> HttpResponse: ...


def chrome_profile() -> dict[str, str]:
    impersonate = "chrome"
    try:
        from curl_cffi.requests.impersonate import BrowserType

        supported = {item.value for item in BrowserType}
        for name in ("chrome146", "chrome145", "chrome136", "chrome131", "chrome124", "chrome"):
            if name in supported:
                impersonate = name
                break
    except Exception:
        impersonate = "chrome124"
    version = "".join(ch for ch in impersonate if ch.isdigit()) or "131"
    return {
        "impersonate": impersonate,
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36"
        ),
        "sec_ch_ua": f'"Chromium";v="{version}", "Google Chrome";v="{version}", "Not.A/Brand";v="99"',
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": '"Windows"',
        "version": version,
    }


USER_AGENT = chrome_profile()["user_agent"]
IMPERSONATE = chrome_profile()["impersonate"]


def normalize_proxy(proxy: str) -> str:
    value = str(proxy or "").strip()
    if not value:
        return ""
    scheme = ""
    rest = value
    if "://" in value:
        scheme, rest = value.split("://", 1)
    parts = rest.split(":")
    if "@" not in rest and len(parts) == 4 and parts[1].isdigit():
        host, port, user, password = parts
        return (
            f"{scheme or 'http'}://{quote(user, safe='-._~')}:"
            f"{quote(password, safe='-._~')}@{host}:{port}"
        )
    if not scheme:
        return f"http://{rest}"
    return value


def pin_proxy_region(proxy: str, country: str) -> str:
    """Rewrite Cliproxy-style ``region-XX`` in the username to the checkout country."""
    iso = str(country or "").strip().upper()
    value = normalize_proxy(proxy)
    if not value or len(iso) != 2 or "region-" not in value.lower():
        return value
    parsed = urlsplit(value)
    user = unquote(parsed.username or "")
    if not user:
        return value
    new_user, count = re.subn(r"region-[A-Za-z]{2}", f"region-{iso}", user, count=1)
    if not count:
        return value
    password = unquote(parsed.password or "")
    host = parsed.hostname or ""
    if not host:
        return value
    port = f":{parsed.port}" if parsed.port else ""
    auth = f"{quote(new_user, safe='-._~')}:{quote(password, safe='-._~')}@"
    return urlunsplit((parsed.scheme or "http", f"{auth}{host}{port}", parsed.path, parsed.query, parsed.fragment))


def _proxy_map(proxy: str) -> dict[str, str] | None:
    value = normalize_proxy(proxy)
    if not value:
        return None
    return {"http": value, "https": value}


def _session_cookie_value(cookie: str) -> str:
    raw = str(cookie or "").strip()
    if not raw:
        return ""
    if "session-token" not in raw.lower() and raw.startswith("eyJ"):
        return raw
    match = re.search(r"__Secure-next-auth\.session-token=([^;]+)", raw, re.I)
    return match.group(1).strip() if match else ""


class CurlTransport:
    """One ChatGPT curl session per extract: warmup cookies, then checkout."""

    def __init__(self) -> None:
        try:
            from curl_cffi import requests as curl_requests
        except ImportError:  # pragma: no cover
            curl_requests = None
        import requests

        self._curl = curl_requests
        self._requests = requests
        self._profile = chrome_profile()
        self._device_id = str(uuid.uuid4())
        self._session_id = str(uuid.uuid4())
        self._country = "JP"
        self._chatgpt = None
        self._chatgpt_proxy = ""
        self._stripe = requests.Session()
        self._stripe.headers["User-Agent"] = self._profile["user_agent"]
        self._stripe_proxy = ""

    def prepare(
        self,
        proxy: str,
        timeout: int,
        *,
        cookie: str = "",
        country: str = "JP",
        account_id: str = "",
    ) -> HttpResponse:
        self._country = (country or "JP").upper()
        session = self._chatgpt_session(proxy)
        self._install_cookies(session, cookie)
        headers = self._headers(html=True, account_id=account_id)
        try:
            response = session.get(CHATGPT_ORIGIN + "/", headers=headers, timeout=max(timeout, 15))
        except Exception as exc:
            return HttpResponse(599, str(exc))
        return HttpResponse(response.status_code, response.text)

    def chatgpt_post(
        self,
        path: str,
        body: dict[str, Any],
        token: str,
        proxy: str,
        timeout: int,
        cookie: str = "",
        account_id: str = "",
    ) -> HttpResponse:
        return self._chatgpt_request("POST", path, token, proxy, timeout, cookie, account_id, body=body)

    def chatgpt_get(
        self,
        path: str,
        token: str,
        proxy: str,
        timeout: int,
        cookie: str = "",
        account_id: str = "",
    ) -> HttpResponse:
        return self._chatgpt_request("GET", path, token, proxy, timeout, cookie, account_id)

    def _chatgpt_request(
        self,
        method: str,
        path: str,
        token: str,
        proxy: str,
        timeout: int,
        cookie: str,
        account_id: str,
        body: dict[str, Any] | None = None,
    ) -> HttpResponse:
        url = urljoin(CHATGPT_ORIGIN + "/", path.lstrip("/"))
        session = self._chatgpt_session(proxy)
        self._install_cookies(session, cookie)
        headers = self._headers(html=False, account_id=account_id, token=token)
        try:
            if method == "POST":
                response = session.post(url, headers=headers, json=body, timeout=timeout)
            else:
                response = session.get(url, headers=headers, timeout=timeout)
        except Exception as exc:
            return HttpResponse(599, str(exc))
        return HttpResponse(response.status_code, response.text)

    def _chatgpt_session(self, proxy: str):
        key = normalize_proxy(proxy)
        if self._chatgpt is not None and key == self._chatgpt_proxy:
            return self._chatgpt
        impersonate = self._profile["impersonate"]
        proxies = _proxy_map(proxy) or {}
        if self._curl is not None:
            try:
                session = self._curl.Session(impersonate=impersonate)
            except Exception:
                session = self._curl.Session(impersonate="chrome")
        else:
            session = self._requests.Session()
        session.headers["User-Agent"] = self._profile["user_agent"]
        if hasattr(session, "proxies"):
            session.proxies.clear()
            session.proxies.update(proxies)
        self._chatgpt = session
        self._chatgpt_proxy = key
        return session

    def _install_cookies(self, session, cookie: str) -> None:
        token = _session_cookie_value(cookie)
        if token:
            self._set_cookie(session, "__Secure-next-auth.session-token", token)
        self._set_cookie(session, "oai-did", self._device_id)

    def _set_cookie(self, session, name: str, value: str) -> None:
        if not value:
            return
        try:
            session.cookies.set(name, value, domain="chatgpt.com", path="/")
        except Exception:
            session.cookies.set(name, value)

    def _headers(self, *, html: bool, account_id: str = "", token: str = "") -> dict[str, str]:
        geo = GEO.get(self._country) or GEO["US"]
        profile = self._profile
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" if html else "application/json",
            "Accept-Language": geo["lang_full"],
            "Origin": CHATGPT_ORIGIN,
            "Referer": "https://chatgpt.com/",
            "User-Agent": profile["user_agent"],
            "sec-ch-ua": profile["sec_ch_ua"],
            "sec-ch-ua-mobile": profile["sec_ch_ua_mobile"],
            "sec-ch-ua-platform": profile["sec_ch_ua_platform"],
            "sec-fetch-dest": "document" if html else "empty",
            "sec-fetch-mode": "navigate" if html else "cors",
            "sec-fetch-site": "same-origin",
            "oai-device-id": self._device_id,
            "oai-language": geo["lang"],
            "oai-session-id": self._session_id,
        }
        if not html:
            headers["Content-Type"] = "application/json"
            headers["oai-client-build-number"] = "8370486"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if account_id:
            headers["Chatgpt-Account-Id"] = account_id
        return headers

    def _stripe_session(self, proxy: str):
        mapped = _proxy_map(proxy)
        key = normalize_proxy(proxy)
        if key != self._stripe_proxy:
            self._stripe.proxies.clear()
            if mapped:
                self._stripe.proxies.update(mapped)
            self._stripe_proxy = key
        return self._stripe

    def stripe_post(self, url: str, data: dict[str, str], proxy: str, timeout: int) -> HttpResponse:
        try:
            response = self._stripe_session(proxy).post(url, data=data, timeout=timeout)
        except Exception as exc:
            return HttpResponse(599, str(exc))
        return HttpResponse(response.status_code, response.text)

    def stripe_get(self, url: str, params: dict[str, str], proxy: str, timeout: int) -> HttpResponse:
        try:
            response = self._stripe_session(proxy).get(url, params=params, timeout=timeout)
        except Exception as exc:
            return HttpResponse(599, str(exc))
        return HttpResponse(response.status_code, response.text)

    def fetch_text(self, url: str, proxy: str, timeout: int) -> HttpResponse:
        try:
            response = self._stripe_session(proxy).get(url, timeout=timeout)
        except Exception as exc:
            return HttpResponse(599, str(exc))
        return HttpResponse(response.status_code, response.text)
