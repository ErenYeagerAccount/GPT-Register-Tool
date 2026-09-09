from __future__ import annotations

import time
import uuid
from typing import Any

from .http import CurlTransport, Transport
from .models import PaylinkResult
from .parse import (
    amount_minor,
    coupon_name,
    extract_upi_fields,
    extract_upi_from_html,
    has_free_trial,
    payment_method_types,
)

CHECKOUT_PATH = "/backend-api/payments/checkout"
CONFIRM_PATH = "/backend-api/payments/checkout/confirm"
APPROVE_PATH = "/backend-api/payments/checkout/approve"
STRIPE_INIT = "https://api.stripe.com/v1/payment_pages/{cs_id}/init"
STRIPE_CONFIRM = "https://api.stripe.com/v1/payment_pages/{cs_id}/confirm"
STRIPE_GET = "https://api.stripe.com/v1/payment_pages/{cs_id}"
STRIPE_VERSION = (
    "2025-03-31.basil; checkout_server_update_beta=v1; "
    "checkout_manual_approval_preview=v1"
)

BILLING = {
    "name": "Rahul Sharma",
    "email": "upi-scanner@example.com",
    "line1": "Flat 302, Sai Residency",
    "line2": "MG Road, Andheri East",
    "city": "Mumbai",
    "state": "Maharashtra",
    "postal": "400069",
    "country": "IN",
}


class ExtractSettings:
    def __init__(
        self,
        *,
        checkout_proxy: str = "",
        provider_proxy: str = "",
        approve_proxy: str = "",
        checkout_country: str = "IN",
        payment_country: str = "IN",
        require_zero_due: bool = True,
        checkout_ui_mode: str = "hosted",
        chatgpt_timeout: int = 20,
        stripe_timeout: int = 20,
        approve_attempts: int = 8,
        poll_attempts: int = 8,
        poll_interval_seconds: float = 0.4,
        allow_hosted_fallback: bool = True,
    ) -> None:
        self.checkout_proxy = checkout_proxy
        self.provider_proxy = provider_proxy or checkout_proxy
        self.approve_proxy = approve_proxy or self.provider_proxy
        self.checkout_country = (checkout_country or "IN").upper()
        self.payment_country = (payment_country or "IN").upper()
        self.require_zero_due = bool(require_zero_due)
        self.checkout_ui_mode = checkout_ui_mode if checkout_ui_mode in {"custom", "hosted"} else "hosted"
        self.chatgpt_timeout = max(5, int(chatgpt_timeout))
        self.stripe_timeout = max(5, int(stripe_timeout))
        self.approve_attempts = max(1, min(int(approve_attempts), 20))
        self.poll_attempts = max(1, min(int(poll_attempts), 20))
        self.poll_interval_seconds = max(0.0, min(float(poll_interval_seconds), 5.0))
        self.allow_hosted_fallback = bool(allow_hosted_fallback)


def extract_upi_link(
    access_token: str,
    *,
    settings: ExtractSettings | None = None,
    transport: Transport | None = None,
    sleep: Any = time.sleep,
) -> PaylinkResult:
    token = str(access_token or "").strip()
    if not token:
        return PaylinkResult.failure(
            error="missing access token",
            error_code="missing_access_token",
            error_stage="auth",
        )
    cfg = settings or ExtractSettings()
    client = transport or CurlTransport()
    return _run(token, cfg, client, sleep)


def _run(token: str, cfg: ExtractSettings, client: Transport, sleep) -> PaylinkResult:
    checkout_country = cfg.checkout_country
    currency = "INR"
    stripe_js_id = str(uuid.uuid4())

    checkout = client.chatgpt_post(
        CHECKOUT_PATH,
        {
            "entry_point": "all_plans_pricing_modal",
            "plan_name": "chatgptplusplan",
            "billing_details": {"country": checkout_country, "currency": currency},
            "promo_campaign": {"promo_campaign_id": "plus-1-month-free", "is_coupon_from_query_param": False},
            "checkout_ui_mode": cfg.checkout_ui_mode,
        },
        token,
        cfg.checkout_proxy,
        cfg.chatgpt_timeout,
    )
    if checkout.status_code == 401:
        return PaylinkResult.failure(
            error="access token invalid or expired",
            error_code="checkout_unauthorized",
            error_stage="checkout",
            retryable=True,
        )
    if checkout.status_code >= 400:
        return PaylinkResult.failure(
            error=f"checkout failed: {checkout.status_code}",
            error_code="checkout_failed",
            error_stage="checkout",
            retryable=checkout.status_code >= 500,
        )
    checkout_data = _json(checkout)
    cs_id = str(checkout_data.get("checkout_session_id") or checkout_data.get("id") or "")
    if not cs_id.startswith("cs_"):
        return PaylinkResult.failure(
            error="checkout response missing cs_id",
            error_code="checkout_bad_response",
            error_stage="checkout",
        )
    stripe_pk = str(checkout_data.get("publishable_key") or "").strip()
    if not stripe_pk.startswith("pk_"):
        return PaylinkResult.failure(
            error="checkout response missing publishable key",
            error_code="checkout_publishable_key_missing",
            error_stage="checkout",
            cs_id=cs_id,
        )
    processor_entity = str(checkout_data.get("processor_entity") or ("openai_llc" if checkout_country == "US" else "openai_ie"))

    init_body = {
        "browser_locale": "en-IN",
        "browser_timezone": "Asia/Kolkata",
        "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
        "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[stripe_js_id]": stripe_js_id,
        "elements_session_client[locale]": "en",
        "elements_session_client[is_aggregation_expected]": "false",
        "elements_options_client[saved_payment_method][enable_save]": "never",
        "elements_options_client[saved_payment_method][enable_redisplay]": "never",
        "key": stripe_pk,
        "_stripe_version": STRIPE_VERSION,
    }
    init_resp = client.stripe_post(
        STRIPE_INIT.format(cs_id=cs_id),
        init_body,
        cfg.provider_proxy,
        cfg.stripe_timeout,
    )
    if init_resp.status_code >= 400:
        return PaylinkResult.failure(
            error=f"stripe init failed: {init_resp.status_code}",
            error_code="stripe_init_failed",
            error_stage="stripe_init",
            retryable=True,
            cs_id=cs_id,
        )
    init = _json(init_resp)
    due = amount_minor(init)
    pm_types = payment_method_types(init)
    coupon = coupon_name(init)
    if cfg.require_zero_due and not has_free_trial(init, due):
        return PaylinkResult.failure(
            error=f"no_free_trial: due={due} coupon={coupon}",
            error_code="no_free_trial",
            error_stage="capability",
            cs_id=cs_id,
            amount=due,
            currency=currency,
            coupon_name=coupon,
        )
    if pm_types and "upi" not in pm_types:
        return PaylinkResult.failure(
            error=f"UPI not available: {pm_types}",
            error_code="upi_not_available",
            error_stage="capability",
            cs_id=cs_id,
            amount=due,
            currency=currency,
            payment_method_types=pm_types,
        )

    tax_body = {
        "tax_region[country]": BILLING["country"],
        "tax_region[postal_code]": BILLING["postal"],
        "tax_region[state]": BILLING["state"],
        "tax_region[city]": BILLING["city"],
        "tax_region[line1]": BILLING["line1"],
        "tax_region[line2]": BILLING["line2"],
        "key": stripe_pk,
        "_stripe_version": STRIPE_VERSION,
    }
    tax_resp = client.stripe_post(STRIPE_GET.format(cs_id=cs_id), tax_body, cfg.provider_proxy, cfg.stripe_timeout)
    if tax_resp.status_code < 400:
        init = _json(tax_resp) or init
        due = amount_minor(init) or due

    confirm_body = {
        "payment_method_data[type]": "upi",
        "payment_method_data[billing_details][name]": BILLING["name"],
        "payment_method_data[billing_details][email]": BILLING["email"],
        "payment_method_data[billing_details][address][line1]": BILLING["line1"],
        "payment_method_data[billing_details][address][line2]": BILLING["line2"],
        "payment_method_data[billing_details][address][city]": BILLING["city"],
        "payment_method_data[billing_details][address][state]": BILLING["state"],
        "payment_method_data[billing_details][address][postal_code]": BILLING["postal"],
        "payment_method_data[billing_details][address][country]": BILLING["country"],
        "expected_amount": str(due),
        "expected_payment_method_type": "upi",
        "return_url": f"https://chatgpt.com/checkout/{processor_entity}/{cs_id}",
        "client_attribution_metadata[client_session_id]": stripe_js_id,
        "client_attribution_metadata[checkout_session_id]": cs_id,
        "client_attribution_metadata[merchant_integration_source]": "checkout",
        "client_attribution_metadata[merchant_integration_version]": "custom",
        "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
        "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
        "client_attribution_metadata[payment_method_selection_flow]": "automatic",
        "key": stripe_pk,
        "_stripe_version": STRIPE_VERSION,
    }
    init_checksum = init.get("init_checksum") if isinstance(init, dict) else None
    if init_checksum:
        confirm_body["init_checksum"] = str(init_checksum)
    confirm_resp = client.stripe_post(
        STRIPE_CONFIRM.format(cs_id=cs_id),
        confirm_body,
        cfg.provider_proxy,
        cfg.stripe_timeout,
    )
    confirm_data: dict[str, Any] = {}
    if confirm_resp.status_code < 400:
        confirm_data = _json(confirm_resp)

    approval_data: dict[str, Any] = {}
    approval_ok = False
    chatgpt_confirm = client.chatgpt_post(
        CONFIRM_PATH,
        {"checkout_session_id": cs_id, "selected_payment_method_type": "upi"},
        token,
        cfg.approve_proxy,
        cfg.chatgpt_timeout,
    )
    if chatgpt_confirm.status_code < 400:
        approval_data = _json(chatgpt_confirm)
        approval_ok = str(approval_data.get("result") or "").lower() == "approved"
    if not approval_ok:
        for _ in range(cfg.approve_attempts):
            approve_resp = client.chatgpt_post(
                APPROVE_PATH,
                {"checkout_session_id": cs_id, "processor_entity": processor_entity},
                token,
                cfg.approve_proxy,
                cfg.chatgpt_timeout,
            )
            if approve_resp.status_code < 400:
                approval_data = _json(approve_resp)
                if str(approval_data.get("result") or "").lower() == "approved":
                    approval_ok = True
                    break
            sleep(cfg.poll_interval_seconds)

    qr_data: dict[str, Any] = {}
    for source in (confirm_data, approval_data):
        _merge(qr_data, extract_upi_fields(source))

    for attempt in range(cfg.poll_attempts):
        if qr_data.get("upi_uri") or qr_data.get("hosted_instructions_url"):
            break
        if attempt:
            sleep(cfg.poll_interval_seconds)
        page = client.stripe_get(
            STRIPE_GET.format(cs_id=cs_id),
            {"key": stripe_pk, "_stripe_version": STRIPE_VERSION},
            cfg.provider_proxy,
            cfg.stripe_timeout,
        )
        if page.status_code == 200:
            _merge(qr_data, extract_upi_fields(_json(page)))
        elif page.status_code >= 400:
            break

    if not qr_data.get("upi_uri") and qr_data.get("hosted_instructions_url"):
        html = client.fetch_text(str(qr_data["hosted_instructions_url"]), cfg.provider_proxy, cfg.stripe_timeout)
        if html.status_code == 200:
            _merge(qr_data, extract_upi_from_html(html.text))

    hosted_url = str(
        qr_data.get("hosted_url")
        or (init.get("stripe_hosted_url") if isinstance(init, dict) else "")
        or f"https://pay.openai.com/c/pay/{cs_id}"
    )
    upi_uri = str(qr_data.get("upi_uri") or qr_data.get("mobile_auth_url") or "")
    if upi_uri:
        return PaylinkResult.success(
            url=upi_uri,
            upi_uri=upi_uri,
            hosted_url=hosted_url,
            link_type="upi_deep_link",
            cs_id=cs_id,
            amount=due,
            currency=currency,
            approval_ok=approval_ok,
            processor_entity=processor_entity,
            coupon_name=coupon,
        )
    if cfg.allow_hosted_fallback and confirm_resp.status_code >= 400:
        return PaylinkResult.success(
            url=hosted_url,
            hosted_url=hosted_url,
            link_type="upi_hosted_fallback",
            cs_id=cs_id,
            amount=due,
            currency=currency,
            warning=f"stripe_confirm_failed: {confirm_resp.status_code}",
            processor_entity=processor_entity,
        )
    if cfg.allow_hosted_fallback:
        return PaylinkResult.success(
            url=hosted_url,
            hosted_url=hosted_url,
            link_type="upi_hosted_fallback",
            cs_id=cs_id,
            amount=due,
            currency=currency,
            approval_ok=approval_ok,
            processor_entity=processor_entity,
        )
    return PaylinkResult.failure(
        error="upi uri not returned",
        error_code="upi_uri_missing",
        error_stage="poll",
        retryable=True,
        cs_id=cs_id,
        amount=due,
        currency=currency,
    )


def _json(response) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _merge(target: dict[str, Any], extra: dict[str, Any]) -> None:
    for key, value in extra.items():
        if value and not target.get(key):
            target[key] = value
