from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from paylink.cli import main
from paylink.extract import ExtractSettings, extract_upi_link
from paylink.http import HttpResponse
from paylink.parse import extract_upi_fields, extract_upi_from_html, has_free_trial
from paylink.session import access_token_from_payload, access_token_from_path


class FakeTransport:
    def __init__(self, *, checkout=None, init=None, confirm=None, approve=None, page=None, html=""):
        self.checkout = checkout or {
            "checkout_session_id": "cs_test_123",
            "publishable_key": "pk_live_test",
            "processor_entity": "openai_ie",
        }
        self.init = init or {
            "total_summary": {"due": 0},
            "elements_options": {"payment_method_types": ["upi"]},
            "stripe_hosted_url": "https://pay.openai.com/c/pay/cs_test_123",
        }
        self.confirm = {} if confirm is None else confirm
        self.approve = {"result": "approved"} if approve is None else approve
        self.page = {"next_action": {"upi_display_qr_code": {"upi_uri": "upi://pay?pa=openai@upi&am=0"}}} if page is None else page
        self.html = html
        self.chatgpt_calls: list[str] = []
        self.stripe_posts: list[str] = []

    def chatgpt_post(self, path, body, token, proxy, timeout):
        self.chatgpt_calls.append(path)
        if path.endswith("/checkout"):
            return HttpResponse(200, payload=self.checkout)
        if path.endswith("/confirm"):
            return HttpResponse(400, payload={})
        return HttpResponse(200, payload=self.approve)

    def stripe_post(self, url, data, proxy, timeout):
        self.stripe_posts.append(url)
        if url.endswith("/init"):
            return HttpResponse(200, payload=self.init)
        if url.endswith("/confirm"):
            return HttpResponse(200, payload=self.confirm)
        return HttpResponse(200, payload=self.init)

    def stripe_get(self, url, params, proxy, timeout):
        return HttpResponse(200, payload=self.page)

    def fetch_text(self, url, proxy, timeout):
        return HttpResponse(200, self.html)


def test_access_token_from_nested_session():
    payload = {"auth_session": {"session": {"accessToken": "tok-nested"}}}
    assert access_token_from_payload(payload) == "tok-nested"


def test_access_token_from_path(tmp_path: Path):
    path = tmp_path / "session.json"
    path.write_text(json.dumps({"access_token": "tok-file"}), encoding="utf-8")
    assert access_token_from_path(path) == "tok-file"


def test_extracts_upi_deep_link_without_sleep():
    result = extract_upi_link(
        "tok",
        settings=ExtractSettings(poll_interval_seconds=0, approve_attempts=1, poll_attempts=1),
        transport=FakeTransport(),
        sleep=lambda _seconds: None,
    )
    assert result.ok
    assert result.link_type == "upi_deep_link"
    assert result.url.startswith("upi://")
    assert result.cs_id == "cs_test_123"


def test_rejects_expired_token():
    transport = FakeTransport()
    transport.chatgpt_post = lambda *args, **kwargs: HttpResponse(401, "unauthorized")
    result = extract_upi_link("tok", transport=transport, sleep=lambda _seconds: None)
    assert not result.ok
    assert result.error_code == "checkout_unauthorized"


def test_rejects_nonzero_without_trial():
    transport = FakeTransport(
        init={
            "total_summary": {"due": 19900},
            "elements_options": {"payment_method_types": ["upi"]},
        }
    )
    result = extract_upi_link(
        "tok",
        settings=ExtractSettings(require_zero_due=True, poll_interval_seconds=0),
        transport=transport,
        sleep=lambda _seconds: None,
    )
    assert not result.ok
    assert result.error_code == "no_free_trial"


def test_hosted_fallback_when_upi_missing():
    transport = FakeTransport(page={}, confirm={})
    result = extract_upi_link(
        "tok",
        settings=ExtractSettings(poll_interval_seconds=0, approve_attempts=1, poll_attempts=1),
        transport=transport,
        sleep=lambda _seconds: None,
    )
    assert result.ok
    assert result.link_type == "upi_hosted_fallback"
    assert "pay.openai.com" in result.url


def test_html_hydration_recovers_upi_uri():
    fields = extract_upi_from_html('<script>{"upi_uri":"upi://pay?pa=merchant@upi"}</script>')
    assert fields["upi_uri"].startswith("upi://")
    assert extract_upi_fields({"next_action": {"hosted_instructions_url": "https://payments.stripe.com/upi/instructions/abc"}})


def test_free_trial_when_due_is_zero():
    assert has_free_trial({"total_summary": {"due": 0}}, 0)


def test_cli_writes_json(tmp_path: Path, capsys):
    session = tmp_path / "session.json"
    session.write_text(json.dumps({"access_token": "tok"}), encoding="utf-8")
    transport = FakeTransport()
    with patch("paylink.cli.extract_upi_link", lambda token, settings: extract_upi_link(token, settings=settings, transport=transport, sleep=lambda _seconds: None)):
        code = main(["--session", str(session)])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == 0
    assert payload["ok"] is True
    assert payload["upi_uri"].startswith("upi://")
