from __future__ import annotations

import argparse
import json
from pathlib import Path

from .service import run_jobs, settings_from_options
from .session import credentials_from_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="paylink",
        description="GPT UPI Checkout by LEVALZ — Fast 0₹ Stripe / UPI links from a ChatGPT session.",
    )
    parser.add_argument("--web", action="store_true", help="Open the localhost web console")
    parser.add_argument("--host", default="127.0.0.1", help="Web bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Web port (default 8765)")
    parser.add_argument("--token", help="ChatGPT access token")
    parser.add_argument("--session", help="Path to a session JSON that already contains an access_token")
    parser.add_argument("--sessions-dir", help="Directory of session_*.json files for batch extract")
    parser.add_argument("--proxy", default="", help="Proxy for every stage (http://host:port or host:port:user:pass)")
    parser.add_argument("--checkout-proxy", default="", help="ChatGPT checkout proxy")
    parser.add_argument("--provider-proxy", default="", help="Stripe init/confirm/poll proxy")
    parser.add_argument("--approve-proxy", default="", help="ChatGPT approve proxy")
    parser.add_argument("--checkout-country", default="JP", help="Checkout billing country. JP is the 0₹ trial default.")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--upi", action="store_true", help="Continue past Stripe init to extract a upi:// deep link")
    parser.add_argument("--allow-nonzero", action="store_true", help="Do not require a 0 due checkout")
    parser.add_argument("--no-hosted-fallback", action="store_true")
    args = parser.parse_args(argv)

    if args.web:
        from .web import serve

        serve(host=args.host, port=args.port)
        return 0

    jobs = _jobs(args)
    if not jobs:
        parser.error("provide --token, --session, --sessions-dir, or --web")

    settings = settings_from_options(
        proxy=args.proxy,
        checkout_proxy=args.checkout_proxy,
        provider_proxy=args.provider_proxy,
        approve_proxy=args.approve_proxy,
        checkout_country=args.checkout_country,
        mode="upi" if args.upi else "fast",
        require_zero_due=not args.allow_nonzero,
        allow_hosted_fallback=not args.no_hosted_fallback,
    )
    results = run_jobs(jobs, settings, workers=args.workers)
    for item in results:
        print(json.dumps(item, ensure_ascii=False))
    return 0 if results and all(item.get("ok") for item in results) else 1


def _jobs(args) -> list[dict[str, str]]:
    jobs: list[dict[str, str]] = []
    if args.token:
        jobs.append({"source": "token", "token": args.token, "cookie": "", "account_id": ""})
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


if __name__ == "__main__":
    raise SystemExit(main())
