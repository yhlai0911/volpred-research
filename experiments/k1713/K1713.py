#!/usr/bin/env python3
"""K1713 duplicate-closure and byte-level replay audit for K1661.

K1713's queued brief is already covered by K1661.  This script verifies that
the earlier experiment contains the requested markets, daily-OHLC HAR/HARQ
design, explicit lag policy, QLIKE direction, and DM-HLN inference.  It then
replays every stored K1661 forecast comparison from the immutable OHLC
snapshots and refuses closure if any reported metric differs.

No new empirical claim is created.  The output is a reproducible audit receipt
that closes a duplicate queue item without pretending it is independent
evidence.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd


SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from volpred.stats.model_evaluation import dm_test as canonical_dm_test
from volpred.stats.model_evaluation import qlike_pointwise as canonical_qlike_pointwise

SOURCE_DIR = ROOT / "experiments" / "k1661"
SOURCE_SCRIPT = SOURCE_DIR / "k1661_harq_ohlc.py"
SOURCE_RESULTS = SOURCE_DIR / "k1661_results.json"
SOURCE_REVIEW = SOURCE_DIR / "reviews" / "codex_review.md"
OUTPUT = HERE / "K1713_results.json"

ASSET_FILES = {
    "SPY": "SPY_ohlc.csv",
    "0050.TW": "0050.TW_ohlc.csv",
    "TWII": "TWII_ohlc.csv",
}
MODELS = ("HAR", "HARQ", "HARQ-F", "HARQ-smooth")
ATOL = 1e-12
RTOL = 1e-10
PINNED_SOURCE_COMMIT = "cdb8759466e082aa5565f5df9796a2f85dc08221"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob_sha256(commit: str, relative_path: str) -> str:
    payload = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{commit}:{relative_path}"],
        check=True,
        capture_output=True,
    ).stdout
    return hashlib.sha256(payload).hexdigest()


def load_source_module():
    spec = importlib.util.spec_from_file_location("k1661_replay_target", SOURCE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {SOURCE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lag_signal(signal: pd.Series) -> pd.Series:
    """Canonical one-day information lag used by the independent audit."""
    return signal.shift(1)


def independent_design(rv: pd.Series, rq: pd.Series) -> pd.DataFrame:
    """Rebuild K1661's target-date ledger without calling its implementation."""
    design = pd.DataFrame(index=rv.index)
    design["RV_d"] = lag_signal(rv)
    design["RV_w"] = lag_signal(rv.rolling(5).mean())
    design["RV_m"] = lag_signal(rv.rolling(22).mean())
    design["sqrtRQ"] = lag_signal(np.sqrt(rq))
    design["sqrtRQ_sm"] = lag_signal(np.sqrt(rq.rolling(5).mean()))
    design["y"] = rv
    return design.dropna()


def close_enough(actual: float, expected: float, label: str) -> dict:
    passed = bool(np.isclose(actual, expected, atol=ATOL, rtol=RTOL))
    return {
        "label": label,
        "actual": float(actual),
        "expected": float(expected),
        "abs_diff": float(abs(actual - expected)),
        "passed": passed,
    }


def source_contract_checks(source: str, review: str, stored: dict) -> dict[str, bool]:
    return {
        "queued_markets_present": stored.get("assets") == ["SPY", "0050.TW", "TWII"],
        "garman_klass_present": "def garman_klass" in source,
        "range_quarticity_present": "def range_quarticity" in source,
        "explicit_feature_shift_present": ".shift(1)" in source,
        "rolling_window_1000_present": bool(re.search(r"WINDOW\s*=\s*1000", source)),
        "qlike_actual_over_predicted": "r = a / f" in source,
        "legacy_dm_hln_horizon_one_identified": "dm_hln" in source and "h=1" in source,
        "har_and_harq_present": all(model in source for model in ("HAR", "HARQ")),
        "source_review_pass_but_fallback_disclosed": (
            "VERDICT**: **PASS" in review and "code-reviewer" in review and "Codex fallback" in review
        ),
        "canonical_null_not_overclaimed": stored.get("verdict") == "NULL",
    }


def loss_diff_acf(diff: np.ndarray, lag: int) -> float:
    if lag <= 0 or lag >= len(diff):
        return float("nan")
    left = diff[lag:] - np.mean(diff[lag:])
    right = diff[:-lag] - np.mean(diff[:-lag])
    denom = float(np.sqrt(np.sum(left**2) * np.sum(right**2)))
    return float(np.sum(left * right) / denom) if denom > 0 else float("nan")


def dm_with_fixed_lag(candidate_loss: np.ndarray, baseline_loss: np.ndarray, lag: int) -> dict:
    """Bartlett-HAC lag sensitivity; canonical dm_test remains the primary test."""
    diff = np.asarray(candidate_loss, dtype=float) - np.asarray(baseline_loss, dtype=float)
    diff = diff[np.isfinite(diff)]
    n = len(diff)
    mean = float(np.mean(diff))
    centered = diff - mean
    long_run_var = float(np.mean(centered**2))
    for step in range(1, min(lag, n - 1) + 1):
        weight = 1.0 - step / (lag + 1.0)
        long_run_var += 2.0 * weight * float(np.mean(centered[step:] * centered[:-step]))
    if not np.isfinite(long_run_var) or long_run_var <= 0:
        return {"lag": int(lag), "t_stat": None, "long_run_var": long_run_var}
    return {
        "lag": int(lag),
        "t_stat": float(mean / np.sqrt(long_run_var / n)),
        "long_run_var": long_run_var,
    }


def replay_asset(module, name: str, stored_asset: dict) -> tuple[dict, list[dict]]:
    path = SOURCE_DIR / "data" / ASSET_FILES[name]
    ohlc = pd.read_csv(path, index_col=0, parse_dates=True)
    ohlc.columns = [str(column).title() for column in ohlc.columns]
    ohlc = ohlc[["Open", "High", "Low", "Close"]].apply(pd.to_numeric, errors="coerce").dropna()

    rv = module.garman_klass(ohlc)
    rq = module.range_quarticity(ohlc)
    source_design = module.build_design(rv, rq)
    audit_design = independent_design(rv, rq)
    design_equal = bool(
        source_design.index.equals(audit_design.index)
        and np.allclose(source_design.to_numpy(), audit_design.to_numpy(), atol=0.0, rtol=0.0)
    )

    replayed_models: dict[str, dict] = {}
    losses: dict[str, np.ndarray] = {}
    comparisons: list[dict] = []
    for model in MODELS:
        dates, actual, predicted, n_insanity = module.rolling_oos(source_design, model)
        qlike_pw = canonical_qlike_pointwise(actual, predicted)
        qlike = float(np.mean(qlike_pw))
        mse = float(np.mean((actual - predicted) ** 2))
        expected = stored_asset["models"][model]
        comparisons.extend(
            [
                close_enough(qlike, expected["qlike"], f"{name}.{model}.qlike"),
                close_enough(mse, expected["mse"], f"{name}.{model}.mse"),
            ]
        )
        if len(actual) != expected["n_oos"]:
            comparisons.append(
                {
                    "label": f"{name}.{model}.n_oos",
                    "actual": int(len(actual)),
                    "expected": int(expected["n_oos"]),
                    "abs_diff": int(abs(len(actual) - expected["n_oos"])),
                    "passed": False,
                }
            )
        if n_insanity != expected["n_insanity_filter"]:
            comparisons.append(
                {
                    "label": f"{name}.{model}.n_insanity_filter",
                    "actual": int(n_insanity),
                    "expected": int(expected["n_insanity_filter"]),
                    "abs_diff": int(abs(n_insanity - expected["n_insanity_filter"])),
                    "passed": False,
                }
            )
        losses[model] = qlike_pw
        replayed_models[model] = {
            "qlike": qlike,
            "mse": mse,
            "n_oos": int(len(actual)),
            "n_insanity_filter": int(n_insanity),
            "first_forecast_date": str(pd.Timestamp(dates[0]).date()),
            "last_forecast_date": str(pd.Timestamp(dates[-1]).date()),
        }

    dm = module.dm_hln(losses["HARQ"], losses["HAR"], h=1)
    stored_dm = stored_asset["dm_hln_HARQ_vs_HAR"]
    comparisons.extend(
        [
            close_enough(dm["dm_hln"], stored_dm["dm_hln"], f"{name}.HARQ_vs_HAR.dm_hln"),
            close_enough(dm["p_two"], stored_dm["p_two"], f"{name}.HARQ_vs_HAR.p_two"),
        ]
    )

    # Current-rule primary inference. K1661's historical local DM-HLN uses
    # range(1, h), which degenerates to iid at h=1. The canonical repository
    # implementation applies Bartlett HAC with ceil(n^(1/3)) bandwidth.
    canonical_t, canonical_p = canonical_dm_test(losses["HARQ"], losses["HAR"], h=1)
    n_loss = len(losses["HARQ"])
    canonical_lag = max(1, min(int(np.ceil(n_loss ** (1.0 / 3.0))), n_loss // 4))
    diff = losses["HARQ"] - losses["HAR"]
    sensitivity_lags = sorted({0, 1, 5, 10, canonical_lag, 20})
    sensitivity = [dm_with_fixed_lag(losses["HARQ"], losses["HAR"], lag) for lag in sensitivity_lags]

    return (
        {
            "asset": name,
            "input_sha256": sha256(path),
            "n_ohlc_rows": int(len(ohlc)),
            "n_design_rows": int(len(source_design)),
            "independent_design_byte_equal": design_equal,
            "models": replayed_models,
            "legacy_dm_hln_HARQ_vs_HAR_diagnostic": dm,
            "loss_diff_acf_1": loss_diff_acf(diff, 1),
            "canonical_dm_hac_HARQ_vs_HAR": {
                "t_stat": float(canonical_t),
                "p_value_two_sided": float(canonical_p),
                "hac_lag": int(canonical_lag),
                "candidate_better_direction": "negative",
                "harvey_abs_t_gt_3": bool(abs(canonical_t) > 3.0),
            },
            "dm_hac_lag_sensitivity": sensitivity,
        },
        comparisons,
    )


def main() -> dict:
    source = SOURCE_SCRIPT.read_text(encoding="utf-8")
    review = SOURCE_REVIEW.read_text(encoding="utf-8")
    stored = json.loads(SOURCE_RESULTS.read_text(encoding="utf-8"))
    module = load_source_module()

    contract = source_contract_checks(source, review, stored)
    stored_by_asset = {row["asset"]: row for row in stored["results"]}
    replayed: list[dict] = []
    comparisons: list[dict] = []
    for name in ASSET_FILES:
        asset_result, asset_comparisons = replay_asset(module, name, stored_by_asset[name])
        replayed.append(asset_result)
        comparisons.extend(asset_comparisons)

    source_paths = {
        "k1661_harq_ohlc.py": SOURCE_SCRIPT,
        "k1661_results.json": SOURCE_RESULTS,
        "reviews/codex_review.md": SOURCE_REVIEW,
    }
    source_hashes = {name: sha256(path) for name, path in source_paths.items()}
    pinned_hashes = {
        name: git_blob_sha256(PINNED_SOURCE_COMMIT, f"experiments/k1661/{name}")
        for name in source_paths
    }
    pinned_source_unchanged = source_hashes == pinned_hashes
    canonical_inference_valid = all(
        np.isfinite(row["canonical_dm_hac_HARQ_vs_HAR"]["t_stat"])
        and row["canonical_dm_hac_HARQ_vs_HAR"]["hac_lag"] >= 1
        for row in replayed
    )

    all_pass = bool(
        all(contract.values())
        and all(row["independent_design_byte_equal"] for row in replayed)
        and all(row["passed"] for row in comparisons)
        and pinned_source_unchanged
        and canonical_inference_valid
    )
    payload = {
        "experiment_id": "K1713",
        "seed": SEED,
        "task_disposition": "duplicate_closure",
        "duplicate_of": "K1661",
        "source_experiment_commit": PINNED_SOURCE_COMMIT,
        "verdict": "DUPLICATE_CLOSURE_PASS" if all_pass else "AUDIT_FAIL",
        "creates_new_empirical_claim": False,
        "reason": (
            "K1661 already implements the full queued design: daily-OHLC Garman-Klass RV, "
            "range-quarticity proxy, HAR/HARQ, rolling W=1000 one-step forecasts, QLIKE, "
            "DM-HLN, and SPY/0050.TW/TWII (documented TX proxy)."
        ),
        "source_hashes": source_hashes,
        "pinned_commit_hashes": pinned_hashes,
        "pinned_source_unchanged": pinned_source_unchanged,
        "contract_checks": contract,
        "replay": replayed,
        "metric_comparisons": comparisons,
        "tolerance": {"absolute": ATOL, "relative": RTOL},
        "lookahead_policy": (
            "Independent ledger uses signal.shift(1) for daily, weekly, monthly RV and "
            "sqrt(RQ); rolling training targets end strictly before each forecast origin."
        ),
        "inference_retrofit": (
            "K1661's legacy h=1 DM-HLN has HAC lag 0 and is retained only for byte-replay. "
            "K1713's primary inference uses volpred.stats.model_evaluation.dm_test with the "
            "canonical ceil(n^(1/3)) Bartlett-HAC bandwidth and reports lag sensitivity."
        ),
        "conclusion": (
            "Close K1713 as a verified duplicate and current-HAC-rule retrofit of K1661. "
            "Do not count it as an independent replication or add a second knowledge finding."
        ),
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": payload["verdict"], "checks": len(comparisons)}, indent=2))
    if not all_pass:
        raise SystemExit("K1713 audit failed; inspect K1713_results.json")
    return payload


if __name__ == "__main__":
    main()
