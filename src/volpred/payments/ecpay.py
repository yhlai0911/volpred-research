"""ECPay 綠界 adapter — checkout-param building + CheckMacValue signing/verify.

Implements ECPay's documented CheckMacValue algorithm (AIO), verified against
ECPay's published STAGE test vector in tests/test_payments_ecpay.py. NO network
calls and NO real credentials live here: the buyer's browser POSTs the returned
form to ECPay directly, and credentials come from env at call time.

Credentials (env):
  ECPAY_MERCHANT_ID, ECPAY_HASH_KEY, ECPAY_HASH_IV, ECPAY_ENV ('stage'|'prod')
Defaults are ECPay's PUBLIC stage/test values (documented everywhere, safe for
sandbox), so the adapter is testable with zero secrets. Production requires the
platform's real merchant credentials — see the go-live checklist.

Signing algorithm (ECPay AIO, EncryptType=1 / SHA256):
  1. drop any existing CheckMacValue
  2. sort params by key, case-insensitive
  3. raw = "HashKey=<key>&" + "k1=v1&k2=v2&..." + "&HashIV=<iv>"
  4. urlencode(raw) via quote_plus(safe="-_.!*()") then lowercase
     (matches .NET HttpUtility.UrlEncode as ECPay's SDK does)
  5. SHA256 hex, uppercased
"""
from __future__ import annotations

import hashlib
import os
from urllib.parse import quote_plus

from .base import (
    CheckoutRequest,
    CheckoutResponse,
    PaymentProvider,
    PaymentsConfigError,
    require_payments_enabled,
)

# ECPay's PUBLIC stage/test credentials (documented in every ECPay tutorial and
# their own SDK samples). Safe to ship as defaults — they only work against the
# stage endpoint and cannot move real money.
STAGE_MERCHANT_ID = "2000132"
STAGE_HASH_KEY = "5294y06JbISpM5x9"
STAGE_HASH_IV = "v77hoKGq4kWxNNIS"

STAGE_AIO_URL = "https://payment-stage.ecpay.com.tw/Cashier/AioCheckOut/V5"
PROD_AIO_URL = "https://payment.ecpay.com.tw/Cashier/AioCheckOut/V5"


def _ecpay_urlencode(raw: str) -> str:
    """quote_plus with ECPay's safe set, then lowercase (mirrors ECPay SDK /
    .NET HttpUtility.UrlEncode casing)."""
    return quote_plus(raw, safe="-_.!*()").lower()


def make_check_mac_value(params: dict[str, str], hash_key: str, hash_iv: str) -> str:
    """Compute ECPay CheckMacValue (SHA256/EncryptType=1) for `params`."""
    filtered = {k: v for k, v in params.items() if k != "CheckMacValue"}
    ordered = sorted(filtered.items(), key=lambda kv: kv[0].lower())
    raw = "HashKey=%s&" % hash_key
    raw += "&".join(f"{k}={v}" for k, v in ordered)
    raw += "&HashIV=%s" % hash_iv
    encoded = _ecpay_urlencode(raw)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest().upper()


class ECPayProvider(PaymentProvider):
    name = "ecpay"

    def __init__(
        self,
        *,
        merchant_id: str | None = None,
        hash_key: str | None = None,
        hash_iv: str | None = None,
        env: str | None = None,
    ) -> None:
        self.env = (env or os.environ.get("ECPAY_ENV") or "stage").strip().lower()
        # Default to public stage creds so the adapter is usable/testable with
        # no secrets. Production MUST supply real creds via env.
        self.merchant_id = merchant_id or os.environ.get("ECPAY_MERCHANT_ID") or STAGE_MERCHANT_ID
        self.hash_key = hash_key or os.environ.get("ECPAY_HASH_KEY") or STAGE_HASH_KEY
        self.hash_iv = hash_iv or os.environ.get("ECPAY_HASH_IV") or STAGE_HASH_IV
        if self.env == "prod" and self.merchant_id == STAGE_MERCHANT_ID:
            raise PaymentsConfigError(
                "ECPAY_ENV=prod but merchant_id is still the public stage id — "
                "refusing to build a production checkout with test credentials."
            )

    @property
    def aio_url(self) -> str:
        return PROD_AIO_URL if self.env == "prod" else STAGE_AIO_URL

    def _base_params(self, req: CheckoutRequest, trade_date: str) -> dict[str, str]:
        """Build the AioCheckOut field set (recurring via 定期定額 when the plan
        is recurring). `trade_date` is injected (not clock-read) so callers keep
        control of time and tests are deterministic. Format: 'YYYY/MM/DD HH:MM:SS'."""
        params = {
            "MerchantID": self.merchant_id,
            "MerchantTradeNo": req.order_no,
            "MerchantTradeDate": trade_date,
            "PaymentType": "aio",
            "TotalAmount": str(int(req.amount_twd)),
            "TradeDesc": "VolPred membership",
            "ItemName": req.item_name,
            "ReturnURL": req.return_url,
            "ClientBackURL": req.client_back_url,
            "ChoosePayment": "Credit",
            "EncryptType": "1",
        }
        # Recurring plans use ECPay 定期定額 (credit-card periodic auth). Monthly,
        # bill every 1 month, cap the auth count high; ECPay handles the cadence.
        if req.extra.get("recurring"):
            params.update({
                "PeriodAmount": str(int(req.amount_twd)),
                "PeriodType": "M",       # Month
                "Frequency": "1",         # every 1 month
                "ExecTimes": "99",        # up to 99 charges (~8 yrs); user can cancel
            })
        if req.user_id:
            params["CustomField1"] = req.user_id
        return params

    def create_subscription_checkout(
        self, req: CheckoutRequest, *, trade_date: str | None = None
    ) -> CheckoutResponse:
        require_payments_enabled()  # HARD gate — nothing chargeable while off
        if trade_date is None:
            # Only import/clock-read on the live path; tests inject trade_date.
            from datetime import datetime
            trade_date = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        params = self._base_params(req, trade_date)
        params["CheckMacValue"] = make_check_mac_value(params, self.hash_key, self.hash_iv)
        return CheckoutResponse(
            provider=self.name,
            action_url=self.aio_url,
            fields=params,
            order_no=req.order_no,
        )

    def build_checkout_fields_unchecked(
        self, req: CheckoutRequest, *, trade_date: str
    ) -> dict[str, str]:
        """Build + sign fields WITHOUT the payments-enabled gate — for tests and
        signature reconciliation only. Never call from a request path."""
        params = self._base_params(req, trade_date)
        params["CheckMacValue"] = make_check_mac_value(params, self.hash_key, self.hash_iv)
        return params

    def verify_callback(self, params: dict[str, str]) -> bool:
        """Verify ECPay's async ReturnURL POST signature. Read-only — safe while
        payments disabled (reconciliation/testing). Constant-time compare."""
        import hmac

        received = str(params.get("CheckMacValue", ""))
        expected = make_check_mac_value(params, self.hash_key, self.hash_iv)
        return hmac.compare_digest(received.upper(), expected.upper())
