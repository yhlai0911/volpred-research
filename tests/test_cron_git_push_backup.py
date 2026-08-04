from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_git_push_backup_uses_cron_safe_auth_helpers() -> None:
    script = (ROOT / "scripts" / "cron_git_push_backup.sh").read_text(encoding="utf-8")

    assert 'export HOME="${HOME:-/Users/yhlai0911}"' in script
    assert 'export GH_CONFIG_DIR="${GH_CONFIG_DIR:-$HOME/.config/gh}"' in script
    assert 'UV_BIN="${UV_BIN:-/opt/homebrew/bin/uv}"' in script
    assert 'GH_BIN="${GH_BIN:-/opt/homebrew/bin/gh}"' in script
    assert "$GH_BIN auth git-credential" in script
    assert "git_auth fetch origin main" in script
    assert 'git_auth push origin "${PUSH_SHA}:refs/heads/main"' in script
    assert "\n  uv run volpred ops send-alert" not in script
    assert "--body-md \"git push origin main 失敗" not in script
    assert "--body-md \"origin/main 領先本地" not in script


def test_ci_owned_push_suppresses_child_notifications() -> None:
    script = (ROOT / "scripts" / "cron_git_push_backup.sh").read_text(encoding="utf-8")

    # Only the two externally owned branches retain the whole-alert guard.  The
    # internal hold must always create its P1 and suppress transport separately.
    guard = 'if [ "${VOLPRED_SUPPRESS_PUSH_ALERTS:-0}" != "1" ]; then'
    assert script.count(guard) == 2
    assert script.count("CI incident watcher owns terminal notification") == 3
    assert "INTERNAL_ROUTE_ARGS+=(--suppress-owner-transport)" in script
    assert "ci-remediation start" in script
    assert "ci-remediation exit" in script
    assert "On-demand CI remediation is not a scheduled git_push_backup fire" in script


def test_silent_fallback_hold_routes_to_stable_p1_before_any_notification() -> None:
    script = (ROOT / "scripts" / "cron_git_push_backup.sh").read_text(encoding="utf-8")

    assert script.count("--internal-remediable-key git_push_backup_hold") == 1
    assert "resolve-internal-alert" in script
    assert "--alert-key git_push_backup_hold" in script
    hold_block = script[
        script.index("# 2.5) silent-fallback gate"):script.index("# 3) fast-forward push")
    ]
    assert 'send-alert "${INTERNAL_ROUTE_ARGS[@]}"' in hold_block
    assert '--observed-at "$AUDIT_STARTED_AT"' in hold_block
    assert "--suppress-owner-transport" in hold_block
    assert '--observed-at "$AUDIT_FINISHED_AT"' in hold_block
    # Divergence and a real transport failure remain owner-facing alerts; only
    # the guard-held, mechanically repairable branch is suppressed.
    assert 'title "git-push-backup: 偵測到 origin 分岔"' in script
    # The push-failure title became classifier-derived on 2026-08-04 (a fixed
    # body blamed auth for what was a file-size rejection), so pin the routing
    # invariant instead of the literal title: still a warn-level owner alert,
    # never the internal remediable route, and the owner-facing string remains
    # the default the classifier overrides.
    push_block = script[script.index("# 3) fast-forward push"):]
    assert 'PUSH_CLASS_TITLE="git-push-backup: push 失敗"' in push_block
    assert "send-alert --level warn" in push_block
    assert '--title "$PUSH_CLASS_TITLE"' in push_block
    assert "--suppress-owner-transport" not in push_block
    assert "INTERNAL_ROUTE_ARGS" not in push_block


def test_audit_and_push_are_bound_to_one_immutable_sha() -> None:
    script = (ROOT / "scripts" / "cron_git_push_backup.sh").read_text(encoding="utf-8")

    assert "PUSH_SHA=$(git rev-parse refs/heads/main" in script
    assert '--rev "$PUSH_SHA"' in script
    assert 'origin/main..$PUSH_SHA' in script
    assert '$PUSH_SHA..origin/main' in script
    assert 'git_auth push origin "${PUSH_SHA}:refs/heads/main"' in script
    assert "git_auth push origin main" not in script
