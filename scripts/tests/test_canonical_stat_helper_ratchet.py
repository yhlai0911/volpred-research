from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.audit_canonical_stat_helpers import (
    DEFAULT_BASELINE,
    ROOT,
    collect_local_helper_sites,
    compare_to_baseline,
)


def _write_baseline(path: Path, sites: list[str]) -> None:
    path.write_text(json.dumps({"local_helper_sites": sites}), encoding="utf-8")


def test_new_local_holm_copy_fails_ratchet(tmp_path: Path) -> None:
    experiment = tmp_path / "experiments" / "k_new"
    experiment.mkdir(parents=True)
    (experiment / "run.py").write_text(
        "def holm_adjust(p_values):\n    return p_values\n",
        encoding="utf-8",
    )
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, [])

    added, stale_active, resurrected = compare_to_baseline(tmp_path, baseline)

    assert [site.identity for site in added] == [
        "experiments/k_new/run.py::holm_adjust"
    ]
    assert stale_active == []
    assert resurrected == []


def test_importing_canonical_helper_does_not_create_site(tmp_path: Path) -> None:
    experiment = tmp_path / "experiments" / "k_new"
    experiment.mkdir(parents=True)
    (experiment / "run.py").write_text(
        "from volpred.stats.inference import holm_step_down\n",
        encoding="utf-8",
    )
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, [])

    assert compare_to_baseline(tmp_path, baseline) == ([], [], [])


def test_second_same_named_helper_in_one_file_still_fails(tmp_path: Path) -> None:
    experiment = tmp_path / "experiments" / "k_new"
    experiment.mkdir(parents=True)
    (experiment / "run.py").write_text(
        "def holm_adjust(p_values):\n    return p_values\n\n"
        "def holm_adjust(p_values):\n    return p_values\n",
        encoding="utf-8",
    )
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, ["experiments/k_new/run.py::holm_adjust"])

    added, stale_active, resurrected = compare_to_baseline(tmp_path, baseline)

    assert len(added) == 1
    assert added[0].identity == "experiments/k_new/run.py::holm_adjust"
    assert stale_active == []
    assert resurrected == []


def test_candidate_parse_failure_fails_closed(tmp_path: Path) -> None:
    experiment = tmp_path / "experiments" / "k_new"
    experiment.mkdir(parents=True)
    (experiment / "run.py").write_text(
        "def holm_adjust(:\n",
        encoding="utf-8",
    )
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, [])

    with pytest.raises(ValueError, match="cannot parse candidate"):
        compare_to_baseline(tmp_path, baseline)


def test_git_checkout_ignores_untracked_experiment_wip(tmp_path: Path) -> None:
    subprocess.run(
        ["git", "init", "--quiet", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    tracked = tmp_path / "experiments" / "tracked" / "run.py"
    tracked.parent.mkdir(parents=True)
    tracked.write_text(
        "def holm_adjust(p_values):\n    return p_values\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "experiments/tracked/run.py"],
        check=True,
        capture_output=True,
        text=True,
    )
    untracked = tmp_path / "experiments" / "other_session" / "run.py"
    untracked.parent.mkdir(parents=True)
    untracked.write_text(
        "def holm_adjust(p_values):\n    return p_values\n",
        encoding="utf-8",
    )
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, ["experiments/tracked/run.py::holm_adjust"])

    assert compare_to_baseline(tmp_path, baseline) == ([], [], [])


def test_removed_active_site_requires_baseline_retirement(tmp_path: Path) -> None:
    (tmp_path / "experiments").mkdir()
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, ["experiments/old/run.py::holm_adjust"])

    added, stale_active, resurrected = compare_to_baseline(tmp_path, baseline)

    assert added == []
    assert stale_active == ["experiments/old/run.py::holm_adjust"]
    assert resurrected == []


def test_retired_site_cannot_resurrect(tmp_path: Path) -> None:
    experiment = tmp_path / "experiments" / "old"
    experiment.mkdir(parents=True)
    (experiment / "run.py").write_text(
        "def holm_adjust(p_values):\n    return p_values\n",
        encoding="utf-8",
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "local_helper_sites": [],
                "retired_sites": [
                    {"site": "experiments/old/run.py::holm_adjust"}
                ],
            }
        ),
        encoding="utf-8",
    )

    added, stale_active, resurrected = compare_to_baseline(tmp_path, baseline)

    assert added == []
    assert stale_active == []
    assert [site.identity for site in resurrected] == [
        "experiments/old/run.py::holm_adjust"
    ]


def test_active_and_retired_baseline_must_be_disjoint(tmp_path: Path) -> None:
    (tmp_path / "experiments").mkdir()
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "local_helper_sites": ["experiments/old/run.py::holm_adjust"],
                "retired_sites": [
                    {"site": "experiments/old/run.py::holm_adjust"}
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="active and retired"):
        compare_to_baseline(tmp_path, baseline)


def test_repository_matches_frozen_baseline_and_k1380_is_retired() -> None:
    added, stale_active, resurrected = compare_to_baseline(ROOT, DEFAULT_BASELINE)
    current = {site.identity for site in collect_local_helper_sites(ROOT)}

    assert added == []
    assert stale_active == []
    assert resurrected == []
    assert (
        "experiments/K1380_v4/k1380_v4_rc_correction.py::holm_step_down"
        not in current
    )
