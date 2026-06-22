from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "cron_handoff_regen.sh"


def test_handoff_regen_prefers_project_venv_python() -> None:
    text = SCRIPT.read_text()

    assert 'PYTHON_BIN="/Users/yhlai0911/Desktop/volpred-research/.venv/bin/python"' in text
    assert 'PYTHON_RUN=("$PYTHON_BIN")' in text
    assert "PYTHON_RUN=(/Users/yhlai0911/.local/bin/uv run python)" in text
    assert "python_runner=${PYTHON_RUN[*]}" in text


def test_handoff_regen_uses_shared_python_runner_for_both_subcommands() -> None:
    text = SCRIPT.read_text()

    assert (
        '"${PYTHON_RUN[@]}" '
        "/Users/yhlai0911/Desktop/volpred-research/scripts/generate_handoff.py"
    ) in text
    assert (
        '"${PYTHON_RUN[@]}" '
        "/Users/yhlai0911/Desktop/volpred-research/scripts/task_pool_claim.py cleanup --stale-hours 2"
    ) in text
    assert text.count('"${PYTHON_RUN[@]}"') == 2
