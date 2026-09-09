from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .extract import ExtractSettings, extract_upi_link
from .session import credentials_from_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="paylink",
        description="Fast 0₹ ChatGPT Stripe checkout links from an access token. Optional --upi for the UPI deep link.",
    )
    parser.add_argument("--token", help="ChatGPT access token")
    parser.add_argument("--session", help="Path to a session JSON that already contains an access_token")
    parser.add_argument("--sessions-dir", help="Directory of session_*.json files for batch extract")
    parser.add_argument("--proxy", default="", help="Proxy for every stage (http://host:port or socks5h://...)")
    parser.add_argument("--checkout-proxy", default="", help="ChatGPT checkout proxy")
    parser.add_argument("--provider-proxy", default="", help="Stripe init/confirm/poll proxy")
    parser.add_argument("--approve-proxy", default="", help="ChatGPT approve proxy")
    parser.add_argument("--checkout-country", default="JP", help="Checkout billing country. JP is the 0₹ trial default.")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--upi", action="store_true", help="Continue past Stripe init to extract a upi:// deep link")
    parser.add_argument("--allow-nonzero", action="store_true", help="Do not require a 0 due checkout")
    parser.add_argument("--no-hosted-fallback", action="store_true")
    args = parser.parse_args(argv)

    jobs = _jobs(args)
    if not jobs:
        parser.error("provide --token, --session, or --sessions-dir")

    settings = ExtractSettings(
        checkout_proxy=args.checkout_proxy or args.proxy,
        provider_proxy=args.provider_proxy or args.proxy,
        approve_proxy=args.approve_proxy or args.proxy,
        checkout_country=args.checkout_country,
        require_zero_due=not args.allow_nonzero,
        allow_hosted_fallback=not args.no_hosted_fallback,
        mode="upi" if args.upi else "fast",
    )
    workers = max(1, min(int(args.workers or 1), 8, len(jobs)))
    results = []
    if len(jobs) == 1:
        results.append(_run_job(jobs[0], settings))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_run_job, job, settings): job for job in jobs}
            for future in as_completed(futures):
                results.append(future.result())

    for item in results:
        print(json.dumps(item, ensure_ascii=False))
    return 0 if all(item.get("ok") for item in results) else 1


def _jobs(args) -> list[dict[str, str]]:
    jobs: list[dict[str, str]] = []
    if args.token:
        jobs.append({"source": "token", "token": args.token})
    if args.session:
        creds = credentials_from_path(args.session)
        jobs.append({
            "source": str(args.session),
            "token": creds["access_token"],
            "cookie": creds.get("cookie_header") or creds["session_token"],
            "account_id": creds["account_id"],
        })
    if args.sessions_dir:
        folder = Path(args.sessions_dir)
        for path in sorted(folder.glob("*.json")):
            try:
                creds = credentials_from_path(path)
                jobs.append({
                    "source": str(path),
                    "token": creds["access_token"],
                    "cookie": creds.get("cookie_header") or creds["session_token"],
                    "account_id": creds["account_id"],
                })
            except (OSError, ValueError, json.JSONDecodeError):
                jobs.append({"source": str(path), "token": "", "error": "invalid_session"})
    return jobs


def _run_job(job: dict[str, str], settings: ExtractSettings) -> dict:
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


if __name__ == "__main__":
    raise SystemExit(main())
