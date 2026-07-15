"""Keep CI history deep enough for commit-bound review receipts."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_pytest_checkout_fetches_reviewed_commits() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/pytest.yml").read_text())
    steps = workflow["jobs"]["pytest"]["steps"]
    checkout = next(step for step in steps if step.get("uses") == "actions/checkout@v4")

    assert checkout.get("with", {}).get("fetch-depth") == 0
