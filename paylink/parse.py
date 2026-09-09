from __future__ import annotations

import json
import re
from typing import Any

UPI_URI_RE = re.compile(r"upi://[^\s\"'<>]+", re.I)
HOSTED_INSTRUCTIONS_RE = re.compile(
    r"https://payments\.stripe\.com/upi/instructions/[^\s\"'<>]+",
    re.I,
)
STRIPE_HOSTED_RE = re.compile(r"https://pay\.openai\.com/c/pay/[^\s\"'<>]+", re.I)


def nested_get(data: Any, path: list[str]) -> Any:
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def walk_strings(value: Any, depth: int = 0) -> list[str]:
    found: list[str] = []
    if depth > 12:
        return found
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(walk_strings(item, depth + 1))
    elif isinstance(value, list):
        for item in value:
            found.extend(walk_strings(item, depth + 1))
    return found


def amount_minor(payload: Any) -> int:
    candidates = (
        nested_get(payload, ["total_summary", "due"]),
        nested_get(payload, ["invoice", "amount_due"]),
        nested_get(payload, ["elements_options", "amount"]),
    )
    for value in candidates:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.isdigit():
            return int(value)
        if isinstance(value, dict):
            nested = amount_minor(value)
            if nested:
                return nested
    return 0


def payment_method_types(payload: Any) -> list[str]:
    buckets = (
        nested_get(payload, ["elements_options", "payment_method_types"]),
        nested_get(payload, ["payment_method_preference", "payment_method_types"]),
        nested_get(payload, ["session", "payment_method_types"]),
    )
    types: list[str] = []
    for bucket in buckets:
        if isinstance(bucket, list):
            types.extend(str(item).lower() for item in bucket if item)
    return list(dict.fromkeys(types))


def coupon_name(payload: Any) -> str:
    for text in walk_strings(payload):
        if "plus-1-month-free" in text.lower() or "free trial" in text.lower():
            return text[:80]
    discounts = nested_get(payload, ["total_summary", "applied_discounts"]) or nested_get(payload, ["discounts"])
    if isinstance(discounts, list) and discounts:
        first = discounts[0]
        if isinstance(first, dict):
            return str(first.get("coupon") or first.get("name") or "")[:80]
        return str(first)[:80]
    return ""


def has_free_trial(payload: Any, due: int) -> bool:
    if due == 0:
        return True
    texts = " ".join(walk_strings(payload)).lower()
    return "trial" in texts or "percent_off" in texts or bool(coupon_name(payload))


def extract_upi_fields(payload: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(payload, dict):
        next_action = payload.get("next_action")
        if isinstance(next_action, dict):
            payload = {**payload, **next_action}
            display = next_action.get("display_bank_transfer_instructions") or next_action.get("upi_display_qr_code")
            if isinstance(display, dict):
                payload = {**payload, **display}
    for text in walk_strings(payload):
        if not result.get("upi_uri"):
            match = UPI_URI_RE.search(text)
            if match:
                result["upi_uri"] = match.group(0)
        if not result.get("hosted_instructions_url"):
            match = HOSTED_INSTRUCTIONS_RE.search(text)
            if match:
                result["hosted_instructions_url"] = match.group(0)
        if not result.get("hosted_url"):
            match = STRIPE_HOSTED_RE.search(text)
            if match:
                result["hosted_url"] = match.group(0)
        if text.startswith("https://payments.stripe.com/") and "qr" in text and not result.get("qr_image_url"):
            result["qr_image_url"] = text
        if isinstance(payload, dict) and payload.get("expires_at") and "expires_at" not in result:
            result["expires_at"] = payload.get("expires_at")
    return result


def extract_upi_from_html(html: str) -> dict[str, Any]:
    result = extract_upi_fields(html)
    for raw in re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.I | re.S):
        text = raw.strip()
        if not text.startswith("{") and not text.startswith("["):
            continue
        try:
            parsed = json.loads(text)
        except ValueError:
            continue
        for key, value in extract_upi_fields(parsed).items():
            result.setdefault(key, value)
    return result
