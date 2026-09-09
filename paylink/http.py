from __future__ import annotations

import re
import uuid
from typing import Any, Protocol
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

CHATGPT_ORIGIN = "https://chatgpt.com"
# Match gen_pp_link checkout: functional curl_cffi + this UA, impersonate chrome124.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)
IMPERSONATE_CANDIDATES = ("chrome124", "chrome131", "chrome", "chrome146")
KEEP_COOKIES = (
    "__Host-next-auth.csrf-token",
    "__Secure-next-auth.callback-url",
    "__Secure-next-auth.session-token",
)
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


def chatgpt_impersonate() -> str:
    try:
        from curl_cffi.requests.impersonate import BrowserType

        supported = {item.value for item in BrowserType}
    except Exception:
        return "chrome124"
    for name in IMPERSONATE_CANDIDATES:
        if name in supported:
            return name
    return next(iter(supported), "chrome")


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


def account_cookie_header(raw: str, device_id: str = "") -> str:
    """Minimal per-link Cookie header: NextAuth essentials + this link's oai-did.

    Drops Cloudflare ``__cf_bm`` and any other leftover jar cookies, matching
    gen_pp_link's request-based checkout (Cookie header only, no Session).
    """
    kept: dict[str, str] = {}
    text = str(raw or "").strip()
    if text.startswith("eyJ") and "session-token" not in text.lower():
        kept["__Secure-next-auth.session-token"] = text
    else:
        for item in text.split(";"):
            item = item.strip()
            if "=" not in item:
                continue
            name, value = item.split("=", 1)
            name = name.strip()
            value = value.strip()
            if not value:
                continue
            if name in KEEP_COOKIES:
                kept[name] = value
    if device_id:
        kept["oai-did"] = device_id
    return "; ".join(f"{name}={kept[name]}" for name in (*KEEP_COOKIES, "oai-did") if name in kept)


def _proxy_map(proxy: str) -> dict[str, str] | None:
    value = normalize_proxy(proxy)
    if not value:
        return None
    return {"http": value, "https": value}


class CurlTransport:
    """Request-based ChatGPT client like gen_pp_link._checkout_post.

    Each link gets a new device id and a reset Stripe session. ChatGPT calls
    use curl_cffi's functional API so Cloudflare cookies cannot accumulate.
    """

    def __init__(self) -> None:
        try:
            from curl_cffi import requests as curl_requests
        except ImportError:  # pragma: no cover
            curl_requests = None
        import requests

        self._curl = curl_requests
        self._requests = requests
        self._impersonate = chatgpt_impersonate()
        self._country = "JP"
        self._device_id = ""
        self._session_id = ""
        self._stripe = None
        self._stripe_proxy = ""
        self.reset()

    def reset(self, country: str = "JP") -> None:
        self._country = (country or "JP").upper()
        self._device_id = str(uuid.uuid4())
        self._session_id = str(uuid.uuid4())
        self._stripe = self._requests.Session()
        self._stripe.headers["User-Agent"] = USER_AGENT
        self._stripe.cookies.clear()
        self._stripe_proxy = ""

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
        headers = self._headers(account_id=account_id, token=token, cookie=cookie)
        kwargs: dict[str, Any] = {"headers": headers, "timeout": timeout}
        proxies = _proxy_map(proxy)
        if proxies:
            kwargs["proxies"] = proxies
        try:
            if self._curl is not None:
                kwargs["impersonate"] = self._impersonate
                if method == "POST":
                    response = self._curl.post(url, json=body, **kwargs)
                else:
                    response = self._curl.get(url, **kwargs)
            elif method == "POST":
                response = self._requests.post(url, json=body, **kwargs)
            else:
                response = self._requests.get(url, **kwargs)
        except TypeError:
            kwargs.pop("impersonate", None)
            if self._curl is None:
                return HttpResponse(599, "curl_cffi missing")
            if method == "POST":
                response = self._curl.post(url, json=body, impersonate="chrome", **kwargs)
            else:
                response = self._curl.get(url, impersonate="chrome", **kwargs)
        except Exception as exc:
            return HttpResponse(599, str(exc))
        return HttpResponse(response.status_code, response.text)

    def _headers(self, *, account_id: str = "", token: str = "", cookie: str = "") -> dict[str, str]:
        geo = GEO.get(self._country) or GEO["US"]
        headers = {
            "Accept": "application/json",
            "Accept-Language": geo["lang_full"],
            "Content-Type": "application/json",
            "Origin": CHATGPT_ORIGIN,
            "Referer": "https://chatgpt.com/",
            "User-Agent": USER_AGENT,
            "oai-device-id": self._device_id,
            "oai-language": geo["lang"],
            "oai-session-id": self._session_id,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if account_id:
            headers["Chatgpt-Account-Id"] = account_id
        cookie_header = account_cookie_header(cookie, self._device_id)
        if cookie_header:
            headers["Cookie"] = cookie_header
        return headers

    def _stripe_session(self, proxy: str):
        if self._stripe is None:
            self.reset(self._country)
        mapped = _proxy_map(proxy)
        key = normalize_proxy(proxy)
        if key != self._stripe_proxy:
            self._stripe.proxies.clear()
            if mapped:
                self._stripe.proxies.update(mapped)
            self._stripe.cookies.clear()
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
