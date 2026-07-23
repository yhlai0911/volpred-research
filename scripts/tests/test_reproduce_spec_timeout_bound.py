"""`timeout_seconds` must admit honest long runtimes and still reject unit errors.

2026-07-22 — the bound was [1, 3600]. K1730 arm A's production run genuinely takes
13448s, so its `reproduce_spec.json` declared 18000 and the validator rejected it.
The only values that *would* have validated were lies: 3600 declares a timeout the
run is guaranteed to blow through, which turns the reproduce gate into theatre.

The bound exists to catch magnitude errors (milliseconds pasted into a seconds
field), not to cap how long an experiment may run — the executed ceiling is
``min(CLI --timeout, spec.timeout_seconds)``, which the caller can always lower.
So the bound moved to 24h: honest multi-hour declarations pass, 13448000 still does not.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reproduce_check as rc  # noqa: E402

VALID_SHA = "a" * 64


def _write_spec(tmp_path: Path, timeout: object) -> Path:
    spec = {
        "schema_version": rc.SPEC_SCHEMA,
        "entrypoint": {"path": "run.py", "args": []},
        "canonical_result": "results.json",
        "inputs": [{"path": "data/in.csv", "sha256": VALID_SHA}],
        "timeout_seconds": timeout,
        "network": "deny",
        "randomness": {
            "status": "declared",
            "seeds": [{"library": "numpy", "value": 42}],
        },
        # explicit empty ignore list keeps this fixture about the timeout bound only
        "comparison": {"ignore_pointers": [], "ignore_reasons": {}},
    }
    (tmp_path / rc.SPEC_NAME).write_text(json.dumps(spec), encoding="utf-8")
    # the loader also checks the declared paths exist — make them real so a
    # failure here can only be about the timeout bound
    (tmp_path / "run.py").write_text("", encoding="utf-8")
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "in.csv").write_text("", encoding="utf-8")
    (tmp_path / "results.json").write_text("{}", encoding="utf-8")
    return tmp_path


def test_k1730_real_runtime_declaration_is_accepted(tmp_path):
    """18000s — the value K1730 arm A actually needs — must load."""
    spec, err = rc.load_spec(_write_spec(tmp_path, 18_000))
    assert err is None, f"honest long-runtime declaration rejected: {err}"
    assert spec is not None
    assert spec["timeout_seconds"] == 18_000


@pytest.mark.parametrize("timeout", [1, 3600, rc.MAX_TIMEOUT_SECONDS])
def test_in_bounds_values_accepted(tmp_path, timeout):
    spec, err = rc.load_spec(_write_spec(tmp_path, timeout))
    assert err is None, f"{timeout} should be in bounds, got: {err}"
    assert spec is not None


@pytest.mark.parametrize(
    "timeout",
    [
        0,
        -1,
        rc.MAX_TIMEOUT_SECONDS + 1,
        13_448_000,  # the K1730 runtime pasted in as milliseconds
        3.5,
        "1800",
        True,  # bool is an int subclass; it is not a duration
    ],
)
def test_out_of_bounds_and_wrong_type_rejected(tmp_path, timeout):
    spec, err = rc.load_spec(_write_spec(tmp_path, timeout))
    assert spec is None
    assert err is not None and "timeout_seconds" in err


def test_bound_is_twenty_four_hours():
    """Pin the constant: widening it further is a decision, not a typo."""
    assert rc.MAX_TIMEOUT_SECONDS == 86_400
