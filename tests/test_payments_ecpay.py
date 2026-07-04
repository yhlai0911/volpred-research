"""Tests for the payment scaffold (BUILT BUT NOT OPEN).

The load-bearing test is `test_check_mac_value_matches_ecpay_official_vector`:
it pins the CheckMacValue algorithm against ECPay's OWN published worked example
(developers.ecpay.com.tw/?p=2902). If the signing ever drifts, ECPay would
reject every checkout — so this vector must never break.
"""
from __future__ import annotations

import pytest

from volpred.payments import (
    PLANS,
    PaymentsDisabledError,
    payments_enabled,
    plan_by_id,
    role_for_plan,
)
from volpred.payments.base import CheckoutRequest
from volpred.payments.ecpay import ECPayProvider, make_check_mac_value


# ---------------------------------------------------------------------------
# CheckMacValue — pinned to ECPay's official published test vector
# ---------------------------------------------------------------------------

def test_check_mac_value_matches_ecpay_official_vector():
    params = {
        "ChoosePayment": "ALL",
        "EncryptType": "1",
        "ItemName": "Apple iphone 15",
        "MerchantID": "3002607",
        "MerchantTradeDate": "2023/03/12 15:30:23",
        "MerchantTradeNo": "ecpay20230312153023",
        "PaymentType": "aio",
        "ReturnURL": "https://www.ecpay.com.tw/receive.php",
        "TotalAmount": "30000",
        "TradeDesc": "促銷方案",
    }
    mac = make_check_mac_value(params, "pwFHCqoQZGmho4w6", "EkRm7iFT261dpevs")
    assert mac == "6C51C9E6888DE861FD62FB1DD17029FC742634498FD813DC43D4243B5685B840"


def test_check_mac_value_ignores_existing_field_and_is_order_independent():
    base = {"B": "2", "a": "1", "MerchantID": "2000132"}
    with_mac = {**base, "CheckMacValue": "STALE"}
    reordered = {"MerchantID": "2000132", "a": "1", "B": "2"}
    k, iv = "5294y06JbISpM5x9", "v77hoKGq4kWxNNIS"
    assert make_check_mac_value(base, k, iv) == make_check_mac_value(with_mac, k, iv)
    assert make_check_mac_value(base, k, iv) == make_check_mac_value(reordered, k, iv)


# ---------------------------------------------------------------------------
# The OFF switch — nothing chargeable while PAYMENTS_ENABLED is unset
# ---------------------------------------------------------------------------

def test_payments_disabled_by_default(monkeypatch):
    monkeypatch.delenv("PAYMENTS_ENABLED", raising=False)
    assert payments_enabled() is False


def test_create_checkout_raises_when_disabled(monkeypatch):
    monkeypatch.delenv("PAYMENTS_ENABLED", raising=False)
    provider = ECPayProvider()
    req = CheckoutRequest(
        plan_id="radar_plus", order_no="VP2026070400001", amount_twd=299,
        item_name="Radar Plus", return_url="https://volpred.zeabur.app/api/pay/ecpay/callback",
        client_back_url="https://volpred.zeabur.app/me", extra={"recurring": True},
    )
    with pytest.raises(PaymentsDisabledError):
        provider.create_subscription_checkout(req, trade_date="2026/07/04 15:00:00")


@pytest.mark.parametrize("flag", ["1", "true", "yes", "on", "TRUE"])
def test_payments_enabled_truthy_values(monkeypatch, flag):
    monkeypatch.setenv("PAYMENTS_ENABLED", flag)
    assert payments_enabled() is True


@pytest.mark.parametrize("flag", ["", "0", "false", "no", "off", "maybe"])
def test_payments_enabled_falsy_values(monkeypatch, flag):
    monkeypatch.setenv("PAYMENTS_ENABLED", flag)
    assert payments_enabled() is False


# ---------------------------------------------------------------------------
# Checkout field building (via the unchecked builder — no gate, deterministic)
# ---------------------------------------------------------------------------

def test_recurring_checkout_includes_period_fields_and_valid_signature():
    provider = ECPayProvider()  # public stage creds
    req = CheckoutRequest(
        plan_id="research_pro", order_no="VP2026070400002", amount_twd=599,
        item_name="Research Pro", return_url="https://volpred.zeabur.app/api/pay/ecpay/callback",
        client_back_url="https://volpred.zeabur.app/me", user_id="user-abc",
        extra={"recurring": True},
    )
    fields = provider.build_checkout_fields_unchecked(req, trade_date="2026/07/04 15:00:00")
    assert fields["PeriodType"] == "M"
    assert fields["PeriodAmount"] == "599"
    assert fields["Frequency"] == "1"
    assert fields["CustomField1"] == "user-abc"
    # The signature we generated must verify against our own verify_callback.
    assert provider.verify_callback(fields) is True


def test_verify_callback_rejects_tampered_amount():
    provider = ECPayProvider()
    req = CheckoutRequest(
        plan_id="radar_plus", order_no="VP2026070400003", amount_twd=299,
        item_name="Radar Plus", return_url="https://x/cb", client_back_url="https://x/me",
        extra={"recurring": True},
    )
    fields = provider.build_checkout_fields_unchecked(req, trade_date="2026/07/04 15:00:00")
    tampered = {**fields, "TotalAmount": "1"}  # attacker lowers the price
    assert provider.verify_callback(tampered) is False


def test_prod_env_refuses_stage_credentials(monkeypatch):
    from volpred.payments.base import PaymentsConfigError
    monkeypatch.delenv("ECPAY_MERCHANT_ID", raising=False)
    with pytest.raises(PaymentsConfigError):
        ECPayProvider(env="prod")


# ---------------------------------------------------------------------------
# Plan catalog — pinned to the frontend pricing page so a silent drift is caught
# ---------------------------------------------------------------------------

def test_plan_catalog_matches_frontend_pricing():
    ids = {p.plan_id for p in PLANS}
    assert ids == {"free", "radar_plus", "research_pro"}
    assert plan_by_id("radar_plus").price_twd_monthly == 299
    assert plan_by_id("research_pro").price_twd_monthly == 599
    assert plan_by_id("free").price_twd_monthly == 0
    assert role_for_plan("radar_plus") == "premium"
    assert role_for_plan("free") == "free"
    assert plan_by_id("nonexistent") is None
