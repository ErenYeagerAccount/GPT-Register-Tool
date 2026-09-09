from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .extract import ExtractSettings, extract_upi_link
from .http import normalize_proxy, pin_proxy_region
from .session import credentials_from_payload


MAX_JOBS = 20


def settings_from_options(
    *,
    proxy: str = "",
    checkout_proxy: str = "",
    provider_proxy: str = "",
    approve_proxy: str = "",
    checkout_country: str = "JP",
    mode: str = "fast",
    require_zero_due: bool = True,
    allow_hosted_fallback: bool = True,
) -> ExtractSettings:
    shared = (proxy or "").strip()
    return ExtractSettings(
        checkout_proxy=checkout_proxy or shared,
        provider_proxy=provider_proxy or shared,
        approve_proxy=approve_proxy or shared,
        checkout_country=checkout_country,
        require_zero_due=require_zero_due,
        allow_hosted_fallback=allow_hosted_fallback,
        mode=mode,
    )


def job_from_session(raw: Any, source: str) -> dict[str, str]:
    try:
        creds = credentials_from_payload(raw)
    except (TypeError, ValueError):
        return {"source": source, "token": "", "error": "invalid_session"}
    cookie = creds.get("cookie_header") or creds.get("session_token") or ""
    token = creds.get("access_token") or ""
    if not token and not cookie:
        return {"source": source, "token": "", "error": "missing_access_token"}
    return {
        "source": source,
        "token": token,
        "cookie": cookie,
        "account_id": creds.get("account_id") or "",
    }


def inspect_job(job: dict[str, str]) -> dict[str, Any]:
    if job.get("error"):
        return {"ok": False, "source": job.get("source") or "", "error_code": job["error"]}
    cookie = str(job.get("cookie") or "")
    token = str(job.get("token") or "")
    return {
        "ok": True,
        "source": job.get("source") or "",
        "has_access_token": bool(token),
        "has_session_cookie": bool(cookie),
        "account_id": job.get("account_id") or "",
        "session_ready": bool(cookie) or bool(token),
    }


def preview_proxy(proxy: str, checkout_country: str = "JP") -> dict[str, str]:
    raw = str(proxy or "").strip()
    normalized = normalize_proxy(raw)
    pinned = pin_proxy_region(normalized, checkout_country)
    return {
        "normalized": _redact_proxy(normalized),
        "checkout_pinned": _redact_proxy(pinned),
        "country": (checkout_country or "JP").upper(),
    }


def run_jobs(jobs: list[dict[str, str]], settings: ExtractSettings, workers: int = 1) -> list[dict[str, Any]]:
    if not jobs:
        return []
    capped = jobs[:MAX_JOBS]
    pool_size = max(1, min(int(workers or 1), 8, len(capped)))
    if len(capped) == 1:
        return [_run_job(capped[0], settings)]
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=pool_size) as pool:
        futures = {pool.submit(_run_job, job, settings): job for job in capped}
        for future in as_completed(futures):
            results.append(future.result())
    return results


def _run_job(job: dict[str, str], settings: ExtractSettings) -> dict[str, Any]:
    source = job.get("source") or ""
    if job.get("error") or not (job.get("token") or job.get("cookie")):
        return {"ok": False, "source": source, "error_code": job.get("error") or "missing_access_token"}
    job_settings = ExtractSettings(
        checkout_proxy=settings.checkout_proxy,
        provider_proxy=settings.provider_proxy,
        approve_proxy=settings.approve_proxy,
        checkout_country=settings.checkout_country,
        require_zero_due=settings.require_zero_due,
        allow_hosted_fallback=settings.allow_hosted_fallback,
        mode=settings.mode,
        cookie=job.get("cookie") or settings.cookie,
        account_id=job.get("account_id") or settings.account_id,
    )
    result = extract_upi_link(job.get("token") or "", settings=job_settings).to_dict()
    result["source"] = source
    return result


def _redact_proxy(proxy: str) -> str:
    value = str(proxy or "").strip()
    if not value:
        return ""
    if "://" not in value:
        return value
    scheme, rest = value.split("://", 1)
    if "@" not in rest:
        return value
    auth, host = rest.rsplit("@", 1)
    if ":" in auth:
        user = auth.split(":", 1)[0]
        return f"{scheme}://{user}:***@{host}"
    return f"{scheme}://***@{host}"
