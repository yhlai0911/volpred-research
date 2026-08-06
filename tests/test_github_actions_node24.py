"""Keep first-party CI actions on supported, cache-safe releases."""
from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
REQUIRED_ACTIONS = {
    "actions/checkout": "v7",
    "actions/setup-python": "v7",
    # setup-uv published v9.0.0 before creating a movable v9 tag. Pin the
    # resolvable release tag so CI cannot fail during action resolution.
    "astral-sh/setup-uv": "v9.0.0",
}


def _action_steps():
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        jobs = workflow.get("jobs") or {}
        for job_name, job in jobs.items():
            for index, step in enumerate((job or {}).get("steps") or []):
                uses = step.get("uses") if isinstance(step, dict) else None
                if uses:
                    yield path, str(job_name), index, step


def test_supported_node24_action_releases_are_used_everywhere() -> None:
    stale: list[str] = []
    for path, job_name, index, step in _action_steps():
        uses = str(step["uses"])
        action, separator, version = uses.partition("@")
        expected = REQUIRED_ACTIONS.get(action)
        if expected is not None and (not separator or version != expected):
            stale.append(
                f"{path.relative_to(ROOT)}:{job_name}:step[{index}] "
                f"uses {uses!r}; expected {action}@{expected}"
            )
    assert not stale, "Unsupported GitHub Action runtime(s):\n" + "\n".join(stale)


def test_setup_uv_cache_contract_is_explicit() -> None:
    missing: list[str] = []
    for path, job_name, index, step in _action_steps():
        if step.get("uses") != "astral-sh/setup-uv@v9.0.0":
            continue
        options = step.get("with") or {}
        if str(options.get("enable-cache", "")).casefold() != "true":
            continue
        python_cached = str(options.get("cache-python", "")).casefold() == "true"
        pruned = str(options.get("prune-cache", "")).casefold() == "true"
        if not python_cached or not pruned:
            missing.append(
                f"{path.relative_to(ROOT)}:{job_name}:step[{index}] "
                f"cache-python={options.get('cache-python')!r}, "
                f"prune-cache={options.get('prune-cache')!r}"
            )
    assert not missing, (
        "cache-enabled setup-uv steps must cache managed Python and explicitly "
        "prune the dependency cache:\n" + "\n".join(missing)
    )
