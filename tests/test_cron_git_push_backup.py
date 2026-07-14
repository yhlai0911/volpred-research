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
    assert "git_auth push origin main" in script
    assert "\n  uv run volpred ops send-alert" not in script
    assert "--body-md \"git push origin main 失敗" not in script
    assert "--body-md \"origin/main 領先本地" not in script


def test_ci_owned_push_suppresses_child_notifications() -> None:
    script = (ROOT / "scripts" / "cron_git_push_backup.sh").read_text(encoding="utf-8")

    # Divergence, pre-push hold, and real push failure all retain their normal
    # standalone alert, but a CI incident invocation has one terminal notifier.
    guard = 'if [ "${VOLPRED_SUPPRESS_PUSH_ALERTS:-0}" != "1" ]; then'
    assert script.count(guard) == 3
    assert script.count("CI incident watcher owns terminal notification") == 3
    assert "ci-remediation start" in script
    assert "ci-remediation exit" in script
    assert "On-demand CI remediation is not a scheduled git_push_backup fire" in script
