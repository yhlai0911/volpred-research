"""Keep CI history deep enough for commit-bound review receipts.

A blobless partial clone retains every commit and tree object while fetching file
blobs only when the checked-out tip or a test actually needs them. This preserves
receipt verification without downloading the repository's full historical blob
corpus on every CI run.
"""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_pytest_checkout_fetches_reviewed_commits_bloblessly() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/pytest.yml").read_text())
    steps = workflow["jobs"]["pytest"]["steps"]
    checkout = next(
        step for step in steps if str(step.get("uses", "")).startswith("actions/checkout@")
    )

    options = checkout.get("with", {})
    assert checkout["uses"] == "actions/checkout@v7"
    assert options.get("fetch-depth") == 0
    assert options.get("filter") == "blob:none"


def test_every_full_history_checkout_is_blobless() -> None:
    offenders: list[str] = []
    for path in sorted((ROOT / ".github/workflows").glob("*.y*ml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job_name, job in (workflow.get("jobs") or {}).items():
            for index, step in enumerate((job or {}).get("steps") or []):
                if not isinstance(step, dict):
                    continue
                if not str(step.get("uses", "")).startswith("actions/checkout@"):
                    continue
                options = step.get("with") or {}
                if options.get("fetch-depth") == 0 and options.get("filter") != "blob:none":
                    offenders.append(
                        f"{path.relative_to(ROOT)}:{job_name}:step[{index}]"
                    )
    assert not offenders, (
        "full-history checkouts must retain commit objects without eagerly "
        "downloading all historical blobs:\n" + "\n".join(offenders)
    )
