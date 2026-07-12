"""Regression tests for K1701's nested general-loss inference."""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import k1701


def _synthetic_panel(n: int = 260) -> pd.DataFrame:
    generator = np.random.default_rng(1701)
    index = pd.date_range("2010-01-01", periods=n, freq="B")
    base = generator.normal(size=n)
    extra = generator.normal(size=n)
    target = np.exp(0.2 + 0.15 * base + 0.05 * extra + generator.normal(scale=0.1, size=n))
    return pd.DataFrame({"base": base, "extra": extra, "target": target}, index=index)


def test_paired_fixed_window_uses_same_exact_training_size_and_embargo() -> None:
    audit: dict = {}
    out = k1701.paired_fixed_window_oos(
        _synthetic_panel(),
        ["base"],
        ["base", "extra"],
        "target",
        h=5,
        log_target=True,
        train_window=80,
        audit=audit,
    )
    assert not out.empty
    assert list(out.columns) == ["pred_base", "pred_aug", "actual"]
    record = audit["gw_fixed_window"][0]
    assert record["same_training_dates_for_both_models"] is True
    assert record["min_train_size"] == record["max_train_size"] == 80
    assert record["min_origin_minus_last_train_pos"] > 5
    assert record["ok"] is True


def test_paired_fixed_window_is_bit_reproducible() -> None:
    panel = _synthetic_panel()
    kwargs = dict(
        df=panel,
        base_feats=["base"],
        aug_feats=["base", "extra"],
        target="target",
        h=1,
        log_target=True,
        train_window=80,
    )
    first = k1701.paired_fixed_window_oos(**kwargs)
    second = k1701.paired_fixed_window_oos(**kwargs)
    pd.testing.assert_frame_equal(first, second, check_exact=True)


def test_gw_general_loss_detects_helpful_augmented_forecast() -> None:
    generator = np.random.default_rng(42)
    base = 0.55 + generator.normal(scale=0.04, size=1200)
    aug = base - 0.03 + generator.normal(scale=0.01, size=1200)
    result = k1701.giacomini_white_unconditional(aug, base, h=5)
    assert result["z_stat"] < -3.0
    assert result["p_value_two_sided"] < 0.01
    assert result["loss"] == "Patton QLIKE"


def test_material_gain_exclusion_reverses_burden_of_proof() -> None:
    generator = np.random.default_rng(43)
    base = 0.55 + generator.normal(scale=0.04, size=1200)
    aug = base + generator.normal(scale=0.005, size=1200)
    result = k1701.gw_material_gain_exclusion(aug, base, h=5, margin=0.01)
    assert result["z_stat"] > 3.0
    assert result["p_value_one_sided"] < 0.01
    assert "does not prove exact equality" in result["scope"]


def test_block_bootstrap_is_seeded_and_diagnostic_only() -> None:
    generator = np.random.default_rng(44)
    base = 0.55 + generator.normal(scale=0.04, size=300)
    aug = base + generator.normal(scale=0.01, size=300)
    first = k1701.moving_block_skill_ci(aug, base, h=5, seed=42, reps=1000)
    second = k1701.moving_block_skill_ci(aug, base, h=5, seed=42, reps=1000)
    assert first == second
    assert "not re-estimated" in first["scope"]


def test_primary_claim_sink_uses_gw_not_raw_dm() -> None:
    source = inspect.getsource(k1701.main)
    tree = ast.parse(source)
    call_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "dm_test" not in call_names
    assert "gw_p_two_sided" in source
    assert "material_gain_exclusion_p" in source
    assert "qlike_dm_diagnostic" not in source


def test_primary_family_fails_closed_when_empty_or_incomplete() -> None:
    with pytest.raises(ValueError, match="Incomplete pre-registered"):
        k1701.require_complete_primary_family([])
    partial = [
        {"asset": asset, "h": h}
        for asset in k1701.ASSETS
        for h in k1701.HORIZONS
    ][:-1]
    with pytest.raises(ValueError, match="Incomplete pre-registered"):
        k1701.require_complete_primary_family(partial)


def test_primary_family_accepts_each_registered_cell_exactly_once() -> None:
    complete = [
        {"asset": asset, "h": h}
        for asset in k1701.ASSETS
        for h in k1701.HORIZONS
    ]
    k1701.require_complete_primary_family(complete)


def test_source_declares_raw_dm_diagnostic_only_without_primary_dm_phrase() -> None:
    source = Path(k1701.__file__).read_text(encoding="utf-8")
    assert "nested-dm: diagnostic-only" in source
    assert "DM machinery (canonical primary" not in source
    assert '"raw_dm_role": "diagnostic-only; never feeds a nested-model verdict"' in source


def test_readme_primary_table_and_reference_metadata_match_results_json() -> None:
    root = Path(k1701.__file__).parent
    results = json.loads((root / "k1701_results.json").read_text(encoding="utf-8"))
    readme = (root / "README.md").read_text(encoding="utf-8").replace("−", "-")
    for cell in results["primary_family"]:
        expected = (
            f"| {cell['asset']} | {cell['h']} | {cell['n']:,} | "
            f"{cell['qlike_improve_pct']:+.3f}% | {cell['gw_z']:+.3f} | "
            f"{cell['bh_q']:.3f} | fail |"
        )
        assert expected in readme
    assert results["primary_verdict"]["verdict"] in readme
    assert len(results["references"]) >= 5
    assert all(ref.get("doi") for ref in results["references"])
