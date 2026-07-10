"""Mechanical activation gate for the strategy registry.

`docs/strategy-registry.md` defines five checks that a strategy MUST pass before
it may go live (same-period comparison, cross-OOS, Codex review, sensitivity,
MDD acceptable). Historically those five were pure prose with zero enforcement:
any code path that flipped a `strategy_signals` row to `is_active=True` listed a
strategy on the paid platform with nobody verifying the checks ran. This module
is the single enforcement owner for that concern.

A strategy may only transition **inactive -> active** when a valid activation
receipt exists at ``storage/ops/strategy_gate_receipts/<strategy_key>.json``. The
receipt records, per gate, either ``true`` (the check genuinely passed) or the
string ``"grandfathered"`` (the strategy predates the gate — see the backfill
script). There is deliberately **no environment escape hatch**: a gate that can
be switched off via env is a fail-open gate that lies. The only legitimate way
through is to produce a real receipt.

Callers wire in at every activation write path (both `scripts/supabase_sync.py`
choke points plus `scripts/list_new_strategy.py`'s independent write). The gate
is scoped to the *transition*: a no-op `is_active=True` re-sync of an
already-active strategy (the daily_update.py full-sync path) does NOT require a
receipt, so daily sync never blocks and the live cards never disappear.
"""

from __future__ import annotations

import json
from pathlib import Path

from volpred.ops.diagnostics import warn

# Ordered so error messages list the gates the way strategy-registry.md does.
GATE_KEYS: tuple[str, ...] = (
    "same_period_comparison",
    "cross_oos",
    "codex_review",
    "sensitivity",
    "mdd_acceptable",
)

# A gate value is valid iff it is boolean True (check actually passed) or the
# literal "grandfathered" sentinel (strategy predates the gate). `is True`
# (not `== True`) keeps 1 / 1.0 from masquerading as a pass.
_GRANDFATHERED = "grandfathered"

# Repo root: src/volpred/ops/strategy_gate.py -> parents[3]. Kept as a function
# so tests can monkeypatch `receipts_dir` without an env escape hatch on the gate
# itself (this relocates receipts; it never disables the gate).
_REPO_ROOT = Path(__file__).resolve().parents[3]


class StrategyGateError(RuntimeError):
    """Raised when a strategy activation is attempted without a valid receipt.

    Also raised by activation write paths when the current active state cannot
    be determined (e.g. the strategy_signals lookup failed), because "new
    strategy first activation" and "backend transiently unavailable" are
    externally indistinguishable and fail-open there would be a backdoor.
    """


def receipts_dir() -> Path:
    return _REPO_ROOT / "storage" / "ops" / "strategy_gate_receipts"


def receipt_path(strategy_key: str) -> Path:
    return receipts_dir() / f"{strategy_key}.json"


def load_receipt(strategy_key: str) -> dict | None:
    """Return the parsed receipt for a strategy, or None if none exists.

    A present-but-corrupt receipt raises `StrategyGateError` rather than
    returning None: silently degrading a corrupt receipt into "no receipt" would
    hide the corruption and emit a misleading "no receipt" activation error.
    """
    path = receipt_path(strategy_key)
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        return json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        warn(
            "strategy_gate",
            "receipt exists but could not be read/parsed",
            strategy_key=strategy_key,
            path=str(path),
            err=str(exc),
        )
        raise StrategyGateError(
            f"Activation receipt for '{strategy_key}' exists at {path} but is "
            f"unreadable/invalid JSON ({exc}). Fix or regenerate the receipt; "
            f"refusing to activate on a corrupt receipt."
        ) from exc


def validate_receipt(receipt: object) -> tuple[bool, list[str]]:
    """Validate a receipt's shape. Returns (ok, reasons_if_not_ok)."""
    reasons: list[str] = []
    if not isinstance(receipt, dict):
        return False, ["receipt is not a JSON object"]
    gates = receipt.get("gates")
    if not isinstance(gates, dict):
        return False, ["missing or non-object 'gates' field"]
    for key in GATE_KEYS:
        if key not in gates:
            reasons.append(f"missing gate '{key}'")
            continue
        value = gates[key]
        if value is True or value == _GRANDFATHERED:
            continue
        reasons.append(
            f"gate '{key}' is {value!r}; must be true or \"{_GRANDFATHERED}\""
        )
    return (not reasons), reasons


def _activation_help(strategy_key: str) -> str:
    path = receipt_path(strategy_key)
    gate_list = "\n".join(f"    - {k}" for k in GATE_KEYS)
    return (
        f"Strategy '{strategy_key}' cannot be activated: no valid activation "
        f"receipt.\n"
        f"To list a strategy you must pass all five checks in "
        f"docs/strategy-registry.md:\n{gate_list}\n"
        f"Run `uv run python scripts/evaluate_new_strategy.py` for the "
        f"same-period comparison + MDD outputs, secure Codex review + "
        f"cross-OOS + sensitivity evidence, then write the receipt to:\n"
        f"    {path}\n"
        f"with a 'gates' object mapping each of the five keys to true "
        f"(or \"{_GRANDFATHERED}\" for pre-gate strategies)."
    )


def assert_activation_allowed(strategy_key: str, strategy_name: str) -> None:
    """Raise `StrategyGateError` unless a valid activation receipt exists.

    Call this ONLY on an inactive->active transition (new listing or reactivating
    a disabled strategy). No-op re-syncs of an already-active strategy must not
    call it, or daily full-sync would block.
    """
    receipt = load_receipt(strategy_key)
    if receipt is None:
        raise StrategyGateError(_activation_help(strategy_key))
    ok, reasons = validate_receipt(receipt)
    if not ok:
        raise StrategyGateError(
            f"Activation receipt for '{strategy_key}' ({strategy_name}) at "
            f"{receipt_path(strategy_key)} is incomplete/invalid: "
            f"{'; '.join(reasons)}. All five gates must be true or "
            f"\"{_GRANDFATHERED}\"."
        )
