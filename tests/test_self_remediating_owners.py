"""SELF_REMEDIATING claims must be mechanically true (assign_5195e5ae D4b/c).

2026-07-20 incident: `SELF_REMEDIATING['lazypack_render_stuck']` said "render
retry is wired into the alert path" while no such wiring existed.  Because the
registry suppresses both the auto-created task AND the honest email, a false
claim is worse than no claim: failures fell into a black hole for shifts.

Contract enforced here: every entry names an OWNER as `<file>:<function>`;
the file must exist, the function must be defined in it, and the alert path
must actually invoke it.  A claim that cannot pass this test belongs in the
default task-creating disposition (that is exactly how series_registry was
downgraded — its "reconciled automatically" prose was an audit plus advice to
run `--apply`, not a remediation).

Run: uv run --extra dev python -m pytest tests/test_self_remediating_owners.py -v
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from volpred.ops import alert_remediation as ar  # noqa: E402


@pytest.mark.parametrize("alert_id", sorted(ar.SELF_REMEDIATING))
def test_entry_carries_claim_and_owner(alert_id):
    entry = ar.SELF_REMEDIATING[alert_id]
    assert isinstance(entry, dict), "prose-only entries are banned — see D4b"
    assert entry.get("claim", "").strip()
    owner = entry.get("owner", "")
    assert re.fullmatch(r"[\w./-]+\.py:[A-Za-z_]\w*", owner), (
        f"{alert_id}: owner must be '<file>.py:<function>', got {owner!r}"
    )


@pytest.mark.parametrize("alert_id", sorted(ar.SELF_REMEDIATING))
def test_owner_exists_and_is_invoked(alert_id):
    owner = ar.SELF_REMEDIATING[alert_id]["owner"]
    rel_path, func = owner.split(":")
    path = ROOT / rel_path
    assert path.is_file(), f"{alert_id}: owner file missing: {rel_path}"
    source = path.read_text(encoding="utf-8")
    assert re.search(rf"^def {re.escape(func)}\(", source, re.MULTILINE), (
        f"{alert_id}: {func} is not defined in {rel_path}"
    )
    # Defined is not enough — the 2026-07-20 lie was precisely a mechanism
    # nobody called. Require at least one call site beyond the definition.
    calls = len(re.findall(rf"(?<!def ){re.escape(func)}\(", source))
    assert calls >= 1, (
        f"{alert_id}: {func} is defined but never invoked in {rel_path} — "
        "the claim is not wired"
    )


@pytest.mark.parametrize(
    "func",
    ["_auto_remediate_publish_drought", "_auto_remediate_lazypack_stuck"],
)
def test_check_alerts_actuators_run_before_the_alert_report(func):
    """SELF_REMEDIATING means 'fixed BEFORE emailing' — pin the ordering."""
    source = (ROOT / "scripts" / "check_alerts.py").read_text(encoding="utf-8")
    call = re.search(rf"^\s*\w+\s*=\s*{func}\(\)", source, re.MULTILINE)
    assert call, f"{func} has no assignment call site in check_alerts.py"
    report = source.find("report = check_alert_conditions(")
    assert report != -1
    assert call.start() < report, (
        f"{func} must run before check_alert_conditions builds the email"
    )


def test_series_registry_was_downgraded_to_task_disposition():
    """D4c audit: the alert audits drift and suggests --apply; it repairs nothing."""
    assert "series_registry" not in ar.SELF_REMEDIATING
    assert ar.ALERT_TASK_TYPE.get("series_registry") == "governance"


def test_disposition_reports_the_owner():
    condition = {"id": "lazypack_render_stuck", "breached": True, "body": ""}
    outcome = ar.remediate_condition(condition, storage_dir="storage")
    assert outcome["disposition"] == "self_remediating"
    assert outcome["owner"] == "scripts/check_alerts.py:_auto_remediate_lazypack_stuck"
    assert outcome["why"]
