from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


RESULT_SCHEMA = "paylink.upi.v1"


@dataclass
class PaylinkResult:
    ok: bool
    payment_method: str = "upi"
    schema: str = RESULT_SCHEMA
    status: str = ""
    url: str = ""
    upi_uri: str = ""
    hosted_url: str = ""
    link_type: str = ""
    cs_id: str = ""
    amount: int = 0
    currency: str = "INR"
    error: str = ""
    error_code: str = ""
    error_stage: str = ""
    retryable: bool = False
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        extras = payload.pop("extras") or {}
        payload.update(extras)
        return {key: value for key, value in payload.items() if value not in ("", None, {}, [])}

    @classmethod
    def success(
        cls,
        *,
        url: str,
        link_type: str,
        cs_id: str,
        amount: int,
        currency: str,
        upi_uri: str = "",
        hosted_url: str = "",
        **extras: Any,
    ) -> "PaylinkResult":
        return cls(
            ok=True,
            status="extracted",
            url=url,
            upi_uri=upi_uri,
            hosted_url=hosted_url,
            link_type=link_type,
            cs_id=cs_id,
            amount=amount,
            currency=currency,
            extras=extras,
        )

    @classmethod
    def failure(
        cls,
        *,
        error: str,
        error_code: str,
        error_stage: str,
        retryable: bool = False,
        cs_id: str = "",
        amount: int = 0,
        currency: str = "INR",
        **extras: Any,
    ) -> "PaylinkResult":
        return cls(
            ok=False,
            status="failed",
            error=error,
            error_code=error_code,
            error_stage=error_stage,
            retryable=retryable,
            cs_id=cs_id,
            amount=amount,
            currency=currency,
            extras=extras,
        )
