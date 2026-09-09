from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .service import (
    inspect_job,
    job_from_session,
    preview_proxy,
    run_jobs,
    settings_from_options,
)

UI_DIR = Path(__file__).resolve().parent / "webui"
TITLE = "GPT UPI CHECKOUT BY LEVALZ"
MAX_BODY = 2_000_000


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    httpd = ThreadingHTTPServer((host, int(port)), PaylinkHandler)
    print(f"{TITLE}")
    print(f"Local console: http://{host}:{port}/")
    print("Bound to localhost only. Sessions are not written to disk.")
    httpd.serve_forever()


class PaylinkHandler(BaseHTTPRequestHandler):
    server_version = "LevalzPaylink/1.0"

    def log_message(self, format: str, *args) -> None:
        message = format % args
        if "/api/" in message:
            message = message.split(" ")[0] + " [redacted]"
        super().log_message("%s", message)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            self._send_file(UI_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path == "/health":
            self._send_json({"ok": True, "title": TITLE, "bind": "localhost"})
            return
        self._send_json({"ok": False, "error": "not_found"}, status=404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            body = self._read_json()
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        if path == "/api/inspect":
            self._send_json(self._inspect(body))
            return
        if path == "/api/preview-proxy":
            self._send_json(preview_proxy(str(body.get("proxy") or ""), str(body.get("checkout_country") or "JP")))
            return
        if path == "/api/extract":
            self._send_json(self._extract(body))
            return
        self._send_json({"ok": False, "error": "not_found"}, status=404)

    def _inspect(self, body: dict) -> dict:
        jobs = _jobs_from_body(body)
        if not jobs:
            return {"ok": False, "error": "missing_session", "results": []}
        results = [inspect_job(job) for job in jobs]
        return {"ok": all(item.get("ok") for item in results), "results": results}

    def _extract(self, body: dict) -> dict:
        jobs = _jobs_from_body(body)
        if not jobs:
            return {"ok": False, "error": "missing_session", "results": []}
        settings = settings_from_options(
            proxy=str(body.get("proxy") or ""),
            checkout_proxy=str(body.get("checkout_proxy") or ""),
            provider_proxy=str(body.get("provider_proxy") or ""),
            approve_proxy=str(body.get("approve_proxy") or ""),
            checkout_country=str(body.get("checkout_country") or "JP"),
            mode="upi" if body.get("upi") or str(body.get("mode") or "").lower() == "upi" else "fast",
            require_zero_due=not bool(body.get("allow_nonzero")),
            allow_hosted_fallback=not bool(body.get("no_hosted_fallback")),
        )
        workers = int(body.get("workers") or 1)
        results = run_jobs(jobs, settings, workers=workers)
        return {
            "ok": bool(results) and all(item.get("ok") for item in results),
            "proxy": preview_proxy(str(body.get("checkout_proxy") or body.get("proxy") or ""), settings.checkout_country),
            "results": results,
        }

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("payload too large")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON object required")
        return payload

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self._send_json({"ok": False, "error": "ui_missing"}, status=500)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def _jobs_from_body(body: dict) -> list[dict[str, str]]:
    jobs: list[dict[str, str]] = []
    token = str(body.get("token") or "").strip()
    if token:
        jobs.append({"source": "token", "token": token, "cookie": "", "account_id": ""})
    sessions = body.get("sessions")
    if isinstance(sessions, str) and sessions.strip():
        sessions = _split_sessions(sessions)
    if isinstance(sessions, list):
        for index, item in enumerate(sessions, start=1):
            jobs.append(job_from_session(item, f"session-{index}"))
    session = body.get("session")
    if session not in (None, ""):
        jobs.append(job_from_session(session, "session"))
    return jobs


def _split_sessions(text: str) -> list:
    raw = text.strip()
    if not raw:
        return []
    if raw.startswith("["):
        payload = json.loads(raw)
        return payload if isinstance(payload, list) else [payload]
    chunks: list[str] = []
    buf = []
    depth = 0
    for char in raw:
        buf.append(char)
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
            if depth == 0:
                chunk = "".join(buf).strip()
                if chunk:
                    chunks.append(chunk)
                buf = []
    if not chunks:
        return [raw]
    parsed = []
    for chunk in chunks:
        try:
            parsed.append(json.loads(chunk))
        except json.JSONDecodeError:
            parsed.append(chunk)
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="paylink.web", description=TITLE)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    serve(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
