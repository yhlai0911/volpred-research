"""Gate: a guard holding daily writes must not be alerted as an infra failure.

2026-07-16: `daily_update` found feed.json dirty at the 08:03 fire and correctly
refused to overwrite an in-flight edit — then exited 1, which host_cron_fail
cannot tell apart from a genuine failure, so it raised CRITICAL and advised
"chmod +x / check Full Disk Access". Third instance of the class the alert rules
already name (§Severity taxonomy → Guard-held success): exit 1 must not be
overloaded for both a guard holding and hard failure.

The sentinel is shared with cron_git_push_backup.sh's held-push path rather than
minted fresh, so the two must not drift apart — the same pinning as
test_alerts_codex_default_matches_failover.
"""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _module_constant(path: Path, name: str) -> int:
    """Read a literal constant without importing (daily_update pulls in arch/numpy)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path}")


def test_daily_update_holds_with_the_guard_held_sentinel():
    assert _module_constant(ROOT / "scripts" / "daily_update.py", "GUARD_HELD_EXIT_CODE") == 120


def test_sentinel_matches_the_alert_exemption():
    """If alerts.py renumbers the sentinel, the hold silently becomes CRITICAL again."""
    alerts = ROOT / "src" / "volpred" / "ops" / "alerts.py"
    assert _module_constant(alerts, "_PUSH_HELD_EXIT_CODE") == _module_constant(
        ROOT / "scripts" / "daily_update.py", "GUARD_HELD_EXIT_CODE"
    )


def test_sentinel_is_exempt_from_host_cron_fail():
    """The exemption set is what actually spares the hold — assert it contains it."""
    from volpred.ops import alerts

    held = _module_constant(ROOT / "scripts" / "daily_update.py", "GUARD_HELD_EXIT_CODE")
    assert held in alerts._BENIGN_FINDINGS_EXIT_CODES


def test_dirty_guard_does_not_return_bare_one():
    """Pin the call site: returning 1 here is the bug this file exists to stop."""
    src = (ROOT / "scripts" / "daily_update.py").read_text(encoding="utf-8")
    marker = "tracked output already dirty"
    assert marker in src, "guard message changed — re-point this test at the new hold path"
    hold_block = src[src.index(marker) : src.index(marker) + 400]
    assert "return GUARD_HELD_EXIT_CODE" in hold_block
    assert "return 1" not in hold_block
