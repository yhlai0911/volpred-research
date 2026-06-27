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
