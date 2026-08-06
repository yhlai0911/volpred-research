"""Required CI gates must expose stable, unambiguous check contexts."""
from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
EXPECTED = {
    "pytest.yml": {"pytest"},
    "source-encoding.yml": {"source-encoding"},
    "silent-fallbacks.yml": {"silent-fallback"},
    "knowledge-provenance.yml": {"data-baseline"},
    "queue-invariants.yml": {"real-queue"},
    "experiment-artifacts.yml": {"artifacts"},
}


def test_required_gate_check_contexts_are_stable_and_unique() -> None:
    contexts: list[str] = []
    for filename, expected in EXPECTED.items():
        workflow = yaml.safe_load((WORKFLOWS / filename).read_text(encoding="utf-8")) or {}
        jobs = set((workflow.get("jobs") or {}).keys())
        assert jobs == expected, f"{filename}: expected {expected}, found {jobs}"
        contexts.extend(jobs)

    assert len(contexts) == len(set(contexts)), (
        "required status checks cannot safely select duplicate job contexts: "
        f"{contexts}"
    )
