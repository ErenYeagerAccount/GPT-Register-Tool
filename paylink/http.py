from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import urljoin

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)
CHATGPT_ORIGIN = "https://chatgpt.com"
IMPERSONATE = "chrome146"


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
    def chatgpt_post(self, path: str, body: dict[str, Any], token: str, proxy: str, timeout: int) -> HttpResponse: ...
    def stripe_post(self, url: str, data: dict[str, str], proxy: str, timeout: int) -> HttpResponse: ...
    def stripe_get(self, url: str, params: dict[str, str], proxy: str, timeout: int) -> HttpResponse: ...
    def fetch_text(self, url: str, proxy: str, timeout: int) -> HttpResponse: ...


def normalize_proxy(proxy: str) -> str:
    value = str(proxy or "").strip()
    if not value:
        return ""
    if "://" not in value:
        return f"http://{value}"
    return value


def _proxy_map(proxy: str) -> dict[str, str] | None:
    value = normalize_proxy(proxy)
    if not value:
        return None
    return {"http": value, "https": value}


class CurlTransport:
    """Keep-alive ChatGPT + Stripe sessions so a token finishes in a few round trips."""

    def __init__(self) -> None:
        try:
            from curl_cffi import requests as curl_requests
        except ImportError:  # pragma: no cover
            curl_requests = None
        import requests

        self._curl = curl_requests
        self._requests = requests
        self._stripe = requests.Session()
        self._stripe.headers["User-Agent"] = USER_AGENT
        self._stripe_proxy = ""

    def chatgpt_post(self, path: str, body: dict[str, Any], token: str, proxy: str, timeout: int) -> HttpResponse:
        url = urljoin(CHATGPT_ORIGIN + "/", path.lstrip("/"))
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": CHATGPT_ORIGIN,
            "Referer": "https://chatgpt.com/",
            "User-Agent": USER_AGENT,
        }
        kwargs: dict[str, Any] = {"headers": headers, "json": body, "timeout": timeout}
        proxies = _proxy_map(proxy)
        try:
            if self._curl is not None:
                if proxies:
                    kwargs["proxies"] = proxies
                try:
                    response = self._curl.post(url, impersonate=IMPERSONATE, **kwargs)
                except Exception:
                    response = self._curl.post(url, impersonate="chrome", **kwargs)
            else:
                if proxies:
                    kwargs["proxies"] = proxies
                response = self._requests.post(url, **kwargs)
        except Exception as exc:
            return HttpResponse(599, str(exc))
        return HttpResponse(response.status_code, response.text)

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
