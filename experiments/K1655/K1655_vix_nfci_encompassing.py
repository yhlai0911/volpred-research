#!/usr/bin/env python3
"""K1655 addendum: does VIX dominate or encompass true-PIT NFCI?

The corrected K1655 experiment estimated NFCI-only and VIX-only conditional
quantile forecasts separately.  Comparing their point estimates cannot establish
dominance, and comparing each model with an unconditional benchmark cannot show
that VIX encompasses NFCI.  This addendum answers the two missing questions:

1. Frozen expanding-window comparison: on identical origins, compare VIX-only
   and NFCI-only 5% return-quantile pinball losses with a paired DM test.
2. Formal encompassing comparison: produce VIX-only and VIX+NFCI forecasts with
   a fixed-length rolling window, then apply the Giacomini-Komunjer conditional
   quantile forecast encompassing (CQFE) Wald test.  A fixed rolling window is
   required because their asymptotics explicitly exclude expanding recursive
   estimation windows.

The primary target family is pre-registered: S&P 500 price-index forward return,
tau=0.05, H in {1, 4, 12} weeks.  R=400 is the primary CQFE window; R=300/500
are sensitivity diagnostics and cannot change the verdict.  Every feature and
training target obeys the K1655 true-PIT and strict j+H<i timing rules.

Outputs are separate addenda.  The frozen K1655 base JSON/CSV are hash-checked
before and after execution and are never overwritten.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from volpred.stats.model_evaluation import dm_test as canonical_dm_test

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE_SCRIPT = HERE / "K1655.py"
BASE_RESULTS = HERE / "K1655_results.json"
BASE_FORECASTS = HERE / "K1655_oos_forecasts.csv"
GSPC_CACHE = HERE / "data" / "gspc_daily.csv"
VIX_CACHE = HERE / "data" / "fred_VIXCLS.csv"
PIT_CACHE = HERE / "data" / "alfred_NFCI_pit_weekly.csv"
RAW_ALFRED_CACHE = HERE / "data" / "alfred_NFCI_vintage_history.csv.gz"

OUT_RESULTS = HERE / "K1655_vix_nfci_encompassing_results.json"
OUT_FORECASTS = HERE / "K1655_vix_nfci_encompassing_oos.csv"
OUT_CHART = HERE / "K1655_vix_nfci_encompassing.png"

SEED = 1655_2
TAU = 0.05
HORIZONS = (1, 4, 12)
PRIMARY_ROLLING_WINDOW = 400
SENSITIVITY_WINDOWS = (300, 500)
BOOTSTRAP_REPS = 1_999
CONDITION_NUMBER_GATE = 1e8


def _load_base_module():
    spec = importlib.util.spec_from_file_location("k1655_frozen_base", BASE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen K1655 module: {BASE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = _load_base_module()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected object JSON: {path}")
    return value


def atomic_write_json(payload: dict, path: Path) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    load_json(tmp)
    tmp.replace(path)


def atomic_write_csv(frame: pd.DataFrame, path: Path) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    frame.to_csv(tmp, index=False, date_format="%Y-%m-%d")
    check = pd.read_csv(tmp)
    if list(check.columns) != list(frame.columns) or len(check) != len(frame):
        raise RuntimeError(f"CSV round-trip validation failed: {path}")
    tmp.replace(path)


def frozen_manifest() -> dict:
    base_results = load_json(BASE_RESULTS)
    if base_results.get("experiment_id") != "K1655":
        raise RuntimeError("frozen base result is not K1655")
    if base_results.get("verdict", {}).get("verdict") != "NULL":
        raise RuntimeError("frozen K1655 true-PIT verdict is not NULL")
    if base_results.get("review_status", {}).get("status") != "PASS":
        raise RuntimeError("frozen K1655 base lacks independent post-run PASS")

    actual_forecast_hash = sha256_file(BASE_FORECASTS)
    expected_forecast_hash = base_results["data"]["forecast_artifact"]["sha256"]
    if actual_forecast_hash != expected_forecast_hash:
        raise RuntimeError("frozen K1655 forecast artifact hash drift")

    provenance = base_results["data"]["nfci_provenance"]
    actual_pit_hash = sha256_file(PIT_CACHE)
    expected_pit_hash = provenance["nfci_pit_alignment"]["derived_cache_sha256"]
    if actual_pit_hash != expected_pit_hash:
        raise RuntimeError("frozen NFCI PIT cache hash drift")
    actual_raw_hash = sha256_file(RAW_ALFRED_CACHE)
    expected_raw_hash = provenance["alfred_revision_history"]["cache_sha256"]
    if actual_raw_hash != expected_raw_hash:
        raise RuntimeError("frozen ALFRED raw cache hash drift")

    return {
        "base_results_sha256": sha256_file(BASE_RESULTS),
        "base_forecasts_sha256": actual_forecast_hash,
        "gspc_cache_sha256": sha256_file(GSPC_CACHE),
        "vix_cache_sha256": sha256_file(VIX_CACHE),
        "nfci_pit_cache_sha256": actual_pit_hash,
        "alfred_raw_cache_sha256": actual_raw_hash,
        "base_run_at": base_results["run_at"],
        "base_sample": {
            "start": base_results["data"]["sample_start"],
            "end": base_results["data"]["sample_end"],
            "n_weeks": base_results["data"]["n_weeks"],
        },
    }


def assert_manifest_unchanged(before: dict) -> None:
    after = frozen_manifest()
    for key in (
        "base_results_sha256",
        "base_forecasts_sha256",
        "gspc_cache_sha256",
        "vix_cache_sha256",
        "nfci_pit_cache_sha256",
        "alfred_raw_cache_sha256",
    ):
        if before[key] != after[key]:
            raise RuntimeError(f"frozen input changed during addendum run: {key}")


def load_frozen_panel(manifest: dict) -> pd.DataFrame:
    """Rebuild the K1655 panel offline without touching ALFRED or cache files."""
    gspc = pd.read_csv(GSPC_CACHE, parse_dates=["Date"]).set_index("Date")
    if "Close" not in gspc or gspc.index.has_duplicates:
        raise ValueError("invalid frozen GSPC cache")
    close = pd.to_numeric(gspc["Close"], errors="raise").astype(float)
    daily_logret = np.log(close / close.shift(1))
    wclose = close.resample("W-FRI").last().dropna()
    wclose = wclose.loc[wclose.index <= close.index.max().normalize()]
    wrv = (daily_logret**2).resample("W-FRI").sum().reindex(wclose.index)

    pit = pd.read_csv(
        PIT_CACHE,
        parse_dates=[
            "origin",
            "nfci_obs_date",
            "nfci_realtime_start",
            "nfci_realtime_end",
        ],
    ).set_index("origin")
    expected_pit_columns = {
        "nfci",
        "nfci_obs_date",
        "nfci_realtime_start",
        "nfci_realtime_end",
    }
    if set(pit.columns) != expected_pit_columns or pit.index.has_duplicates:
        raise ValueError("invalid frozen NFCI PIT cache schema")

    vix_raw = pd.read_csv(VIX_CACHE, parse_dates=["DATE"])
    if set(vix_raw.columns) != {"DATE", "VALUE"} or vix_raw["DATE"].duplicated().any():
        raise ValueError("invalid frozen VIX cache schema")
    vix = BASE.point_in_time_weekly(vix_raw, "daily_close", wclose.index)

    panel = pd.DataFrame(
        {
            "wclose": wclose,
            "wrv": wrv,
            "nfci": pit["nfci"],
            "vix": vix,
            "nfci_obs_date": pit["nfci_obs_date"],
            "nfci_realtime_start": pit["nfci_realtime_start"],
            "nfci_realtime_end": pit["nfci_realtime_end"],
        },
        index=wclose.index,
    ).dropna(subset=["wclose", "nfci", "vix"])

    expected = manifest["base_sample"]
    actual = {
        "start": str(panel.index.min().date()),
        "end": str(panel.index.max().date()),
        "n_weeks": int(len(panel)),
    }
    if actual != expected:
        raise RuntimeError(f"offline panel drift: actual={actual}, expected={expected}")
    if panel.index.has_duplicates or not panel.index.is_monotonic_increasing:
        raise RuntimeError("offline panel index is not unique and ordered")

    origin = panel.index.to_series()
    open_ended = panel["nfci_realtime_end"].isna()
    gates = {
        "all_nfci_observations_not_after_origin": bool(
            (panel["nfci_obs_date"] <= origin).all()
        ),
        "all_nfci_revisions_started_by_origin": bool(
            (panel["nfci_realtime_start"] <= origin).all()
        ),
        "all_nfci_revision_windows_cover_origin": bool(
            (open_ended | (origin <= panel["nfci_realtime_end"])).all()
        ),
        "no_pre_first_vintage_origin": bool(panel.index.min() >= pd.Timestamp("2011-05-25")),
    }
    if not all(gates.values()):
        raise RuntimeError(f"offline PIT timing gate failed: {gates}")
    panel.attrs["timing_gates"] = gates
    return panel


def _reset_fit_diagnostics() -> None:
    BASE.FIT_DIAGNOSTICS.clear()
    BASE.FIT_DIAGNOSTICS.update(BASE._empty_fit_diagnostics())


def _finite(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    values = frame[columns].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise RuntimeError(f"non-finite values in {label}: {columns}")


def load_frozen_expanding_pairs() -> pd.DataFrame:
    """Pair frozen NFCI-only and VIX-only forecasts without silent row loss."""
    raw = pd.read_csv(
        BASE_FORECASTS,
        parse_dates=[
            "origin",
            "target_end",
            "latest_training_target_end",
            "nfci_obs_date",
            "nfci_realtime_start",
            "nfci_realtime_end",
        ],
    )
    raw = raw.loc[
        (raw["target"] == "fwd_ret")
        & np.isclose(raw["tau"], TAU)
        & raw["spec"].isin(["NFCI", "VIX"])
        & raw["horizon_weeks"].isin(HORIZONS)
    ].copy()
    key = ["horizon_weeks", "origin"]
    if raw.duplicated(["spec", *key]).any():
        raise RuntimeError("duplicate frozen base forecast key")

    invariant_columns = [
        "target_end",
        "latest_training_target_end",
        "nfci_value",
        "nfci_obs_date",
        "nfci_realtime_start",
        "nfci_realtime_end",
        "realized",
        "q_unconditional",
        "loss_unconditional",
    ]
    left = raw.loc[raw["spec"] == "NFCI", key + invariant_columns + [
        "q_conditional",
        "loss_conditional",
    ]].rename(
        columns={"q_conditional": "q_nfci", "loss_conditional": "loss_nfci"}
    )
    right = raw.loc[raw["spec"] == "VIX", key + invariant_columns + [
        "q_conditional",
        "loss_conditional",
    ]].rename(
        columns={"q_conditional": "q_vix", "loss_conditional": "loss_vix"}
    )
    paired = left.merge(
        right,
        on=key,
        how="outer",
        suffixes=("_nfci_source", "_vix_source"),
        validate="one_to_one",
        indicator=True,
    )
    if not (paired["_merge"] == "both").all():
        raise RuntimeError("frozen NFCI/VIX origins are not identical")
    paired = paired.drop(columns="_merge")

    for column in invariant_columns:
        a = paired[f"{column}_nfci_source"]
        b = paired[f"{column}_vix_source"]
        if pd.api.types.is_numeric_dtype(a):
            if not np.allclose(a.to_numpy(float), b.to_numpy(float), rtol=0, atol=1e-14):
                raise RuntimeError(f"frozen source mismatch: {column}")
        else:
            if not a.fillna(pd.Timestamp.max).equals(b.fillna(pd.Timestamp.max)):
                raise RuntimeError(f"frozen source mismatch: {column}")
        paired[column] = a
        paired = paired.drop(columns=[f"{column}_nfci_source", f"{column}_vix_source"])

    paired["loss_nfci_recomputed"] = BASE.pinball_loss(
        paired["realized"].to_numpy(float), paired["q_nfci"].to_numpy(float), TAU
    )
    paired["loss_vix_recomputed"] = BASE.pinball_loss(
        paired["realized"].to_numpy(float), paired["q_vix"].to_numpy(float), TAU
    )
    if not np.allclose(
        paired["loss_nfci"], paired["loss_nfci_recomputed"], rtol=0, atol=2e-15
    ):
        raise RuntimeError("frozen NFCI losses fail recomputation")
    if not np.allclose(
        paired["loss_vix"], paired["loss_vix_recomputed"], rtol=0, atol=2e-15
    ):
        raise RuntimeError("frozen VIX losses fail recomputation")
    paired = paired.drop(columns=["loss_nfci_recomputed", "loss_vix_recomputed"])

    expected_counts = {1: 536, 4: 530, 12: 514}
    actual_counts = paired.groupby("horizon_weeks").size().to_dict()
    if actual_counts != expected_counts:
        raise RuntimeError(
            f"frozen primary origin counts drift: {actual_counts} != {expected_counts}"
        )
    _finite(
        paired,
        ["realized", "q_nfci", "q_vix", "loss_nfci", "loss_vix"],
        "frozen expanding pairs",
    )
    return paired.sort_values(key).reset_index(drop=True)


def expanding_joint_bridge(panel: pd.DataFrame, frozen: pd.DataFrame) -> pd.DataFrame:
    """Run only VIX+NFCI under the frozen expanding/refit-4 convention."""
    result = BASE.oos_analysis(
        panel,
        "fwd_ret",
        ["vix", "nfci"],
        [TAU],
        list(HORIZONS),
        "VIX+NFCI",
    )
    rows: list[dict] = []
    for horizon in HORIZONS:
        rows.extend(result[horizon]["_forecast_rows"])
    joint = pd.DataFrame(rows)
    joint["origin"] = pd.to_datetime(joint["origin"])
    joint["target_end"] = pd.to_datetime(joint["target_end"])
    joint["latest_training_target_end"] = pd.to_datetime(
        joint["latest_training_target_end"]
    )
    key = ["horizon_weeks", "origin"]
    if joint.duplicated(key).any():
        raise RuntimeError("duplicate expanding joint forecast key")
    joint = joint.rename(
        columns={
            "q_conditional": "q_vix_nfci",
            "loss_conditional": "loss_vix_nfci",
        }
    )
    keep = key + [
        "target_end",
        "latest_training_target_end",
        "realized",
        "q_vix_nfci",
        "loss_vix_nfci",
    ]
    merged = frozen.merge(
        joint[keep],
        on=key,
        how="outer",
        suffixes=("", "_joint"),
        validate="one_to_one",
        indicator=True,
    )
    if not (merged["_merge"] == "both").all():
        raise RuntimeError("expanding VIX+NFCI origins differ from frozen base")
    merged = merged.drop(columns="_merge")
    for column in ("target_end", "latest_training_target_end"):
        if not merged[column].equals(merged[f"{column}_joint"]):
            raise RuntimeError(f"expanding joint timing mismatch: {column}")
        merged = merged.drop(columns=f"{column}_joint")
    if not np.allclose(merged["realized"], merged["realized_joint"], atol=1e-14, rtol=0):
        raise RuntimeError("expanding joint realized targets mismatch frozen base")
    merged = merged.drop(columns="realized_joint")
    recomputed = BASE.pinball_loss(
        merged["realized"].to_numpy(float),
        merged["q_vix_nfci"].to_numpy(float),
        TAU,
    )
    if not np.allclose(recomputed, merged["loss_vix_nfci"], atol=2e-15, rtol=0):
        raise RuntimeError("expanding joint losses fail recomputation")
    merged["vix_value"] = merged["origin"].map(panel["vix"])
    _finite(
        merged,
        ["vix_value", "q_vix_nfci", "loss_vix_nfci"],
        "expanding joint bridge",
    )
    merged["scheme"] = "expanding_refit4_bridge"
    merged["rolling_window"] = np.nan
    merged["train_start"] = pd.NaT
    return merged


def _standardize_training(
    frame: pd.DataFrame, columns: list[str]
) -> tuple[np.ndarray, dict[str, float], dict[str, float]]:
    mean = {column: float(frame[column].mean()) for column in columns}
    std = {column: float(frame[column].std(ddof=1)) for column in columns}
    if any((not np.isfinite(std[column]) or std[column] <= 0) for column in columns):
        raise RuntimeError(f"degenerate rolling predictor scale: {std}")
    values = np.column_stack(
        [(frame[column].to_numpy(float) - mean[column]) / std[column] for column in columns]
    )
    return values, mean, std


def rolling_forecasts(
    panel: pd.DataFrame,
    rolling_window: int,
    *,
    include_nfci_only: bool,
) -> pd.DataFrame:
    """Weekly-refit rolling forecasts with strict label embargo and common rows."""
    rows: list[dict] = []
    specs = {"VIX": ["vix"], "VIX+NFCI": ["vix", "nfci"]}
    if include_nfci_only:
        specs = {"NFCI": ["nfci"], **specs}

    for horizon in HORIZONS:
        target = BASE.forward_return(panel["wclose"], horizon)
        n_panel = len(panel)
        for i in range(n_panel):
            candidate_idx = np.arange(0, i - horizon)
            if len(candidate_idx) < rolling_window:
                continue
            if i + horizon >= n_panel or not np.isfinite(target.iloc[i]):
                continue
            train_idx = candidate_idx[-rolling_window:]
            train = panel.iloc[train_idx]
            y_train = target.iloc[train_idx].to_numpy(float)
            if not np.isfinite(y_train).all():
                raise RuntimeError("non-finite rolling training target")
            train_start = panel.index[train_idx[0]]
            train_end = panel.index[train_idx[-1]]
            latest_training_target_end = panel.index[train_idx[-1] + horizon]
            origin = panel.index[i]
            if not latest_training_target_end < origin:
                raise RuntimeError("rolling strict embargo failed")

            out_row = {
                "scheme": f"rolling_R{rolling_window}",
                "rolling_window": rolling_window,
                "horizon_weeks": horizon,
                "tau": TAU,
                "origin": origin,
                "target_end": panel.index[i + horizon],
                "train_start": train_start,
                "train_end": train_end,
                "latest_training_target_end": latest_training_target_end,
                "realized": float(target.iloc[i]),
                "vix_value": float(panel["vix"].iloc[i]),
                "nfci_value": float(panel["nfci"].iloc[i]),
                "nfci_obs_date": panel["nfci_obs_date"].iloc[i],
                "nfci_realtime_start": panel["nfci_realtime_start"].iloc[i],
                "nfci_realtime_end": panel["nfci_realtime_end"].iloc[i],
            }
            for spec_name, columns in specs.items():
                x_train, mean, std = _standardize_training(train, columns)
                fitted = BASE.fit_quantreg(x_train, y_train, TAU)
                x_origin = np.array(
                    [(float(panel[column].iloc[i]) - mean[column]) / std[column] for column in columns]
                )
                quantile = float(np.concatenate([[1.0], x_origin]) @ fitted.params)
                loss = float(
                    BASE.pinball_loss(
                        np.array([target.iloc[i]], float), np.array([quantile], float), TAU
                    )[0]
                )
                suffix = spec_name.lower().replace("+", "_")
                out_row[f"q_{suffix}"] = quantile
                out_row[f"loss_{suffix}"] = loss
                for column in columns:
                    out_row[f"scale_mean_{suffix}_{column}"] = mean[column]
                    out_row[f"scale_std_{suffix}_{column}"] = std[column]
            rows.append(out_row)

    forecasts = pd.DataFrame(rows).sort_values(["horizon_weeks", "origin"]).reset_index(drop=True)
    expected_counts = {
        horizon: len(panel) - rolling_window - 2 * horizon for horizon in HORIZONS
    }
    actual_counts = forecasts.groupby("horizon_weeks").size().to_dict()
    if actual_counts != expected_counts:
        raise RuntimeError(
            f"rolling origin count mismatch R={rolling_window}: "
            f"{actual_counts} != {expected_counts}"
        )
    if forecasts.duplicated(["horizon_weeks", "origin"]).any():
        raise RuntimeError("duplicate rolling forecast key")
    if not (forecasts["target_end"] > forecasts["origin"]).all():
        raise RuntimeError("rolling target-end gate failed")
    if not (forecasts["latest_training_target_end"] < forecasts["origin"]).all():
        raise RuntimeError("rolling training-end gate failed")
    if not (forecasts["nfci_obs_date"] <= forecasts["origin"]).all():
        raise RuntimeError("rolling NFCI observation timing gate failed")
    if not (forecasts["nfci_realtime_start"] <= forecasts["origin"]).all():
        raise RuntimeError("rolling NFCI vintage-start timing gate failed")
    active = forecasts["nfci_realtime_end"].isna() | (
        forecasts["origin"] <= forecasts["nfci_realtime_end"]
    )
    if not active.all():
        raise RuntimeError("rolling NFCI vintage-end timing gate failed")
    numeric = [
        column
        for column in forecasts.columns
        if column.startswith(("q_", "loss_", "scale_mean_", "scale_std_"))
    ] + ["realized", "vix_value", "nfci_value"]
    _finite(forecasts, numeric, f"rolling forecasts R={rolling_window}")
    return forecasts


def _canonical_nw_lag(horizon: int, n: int) -> int:
    return max(1, min(int(np.ceil(horizon ** (1 / 3) * n ** (1 / 3))), n // 4))


def _halves(values: np.ndarray) -> dict[str, float]:
    midpoint = len(values) // 2
    return {
        "first_half_mean_differential": float(np.mean(values[:midpoint])),
        "second_half_mean_differential": float(np.mean(values[midpoint:])),
    }


def paired_loss_test(
    candidate_loss: np.ndarray,
    benchmark_loss: np.ndarray,
    horizon: int,
    *,
    candidate_name: str,
    benchmark_name: str,
) -> dict:
    """Canonical DM plus reviewed K1655 HLN cross-check on identical losses."""
    candidate = np.asarray(candidate_loss, dtype=float)
    benchmark = np.asarray(benchmark_loss, dtype=float)
    if candidate.shape != benchmark.shape or candidate.ndim != 1:
        raise ValueError("paired losses must be same-shape vectors")
    if len(candidate) < 10 or not (np.isfinite(candidate).all() and np.isfinite(benchmark).all()):
        raise ValueError("paired losses are insufficient or non-finite")
    differential = candidate - benchmark
    dm_t, dm_p = canonical_dm_test(candidate, benchmark, h=horizon)
    hln_t, hln_p, hln_lag, hln_n = BASE.hln_dm(candidate, benchmark, horizon)
    expected_lag = _canonical_nw_lag(horizon, len(candidate))
    if hln_n != len(candidate) or hln_lag != max(horizon - 1, expected_lag):
        raise RuntimeError("DM bandwidth/count cross-check failed")
    return {
        "candidate": candidate_name,
        "benchmark": benchmark_name,
        "n": int(len(candidate)),
        "candidate_mean_loss": float(candidate.mean()),
        "benchmark_mean_loss": float(benchmark.mean()),
        "mean_loss_differential_candidate_minus_benchmark": float(differential.mean()),
        "candidate_improvement_pct": float(
            (benchmark.mean() - candidate.mean()) / benchmark.mean() * 100.0
        ),
        "canonical_dm_t": float(dm_t),
        "canonical_dm_p_two_sided": float(dm_p),
        "canonical_nw_lag": expected_lag,
        "hln_dm_t_crosscheck": hln_t,
        "hln_dm_p_two_sided_crosscheck": hln_p,
        "candidate_better": bool(candidate.mean() < benchmark.mean()),
        "harvey_t_better_gate": bool(dm_t < -3.0),
        **_halves(differential),
    }


def apply_holm_family(results_by_horizon: dict[int, dict], p_key: str) -> None:
    horizons = list(HORIZONS)
    p_values = [results_by_horizon[horizon][p_key] for horizon in horizons]
    reject, adjusted, _, _ = multipletests(p_values, alpha=0.05, method="holm")
    for horizon, is_reject, adjusted_p in zip(horizons, reject, adjusted):
        results_by_horizon[horizon][f"{p_key}_holm"] = float(adjusted_p)
        results_by_horizon[horizon][f"{p_key}_holm_below_0_05"] = bool(is_reject)


def _hac_long_run_covariance(moment: np.ndarray, lag: int) -> np.ndarray:
    moment = np.asarray(moment, dtype=float)
    if moment.ndim != 2 or len(moment) <= lag:
        raise ValueError("invalid HAC moment matrix")
    centered = moment - moment.mean(axis=0)
    covariance = centered.T @ centered / len(centered)
    for step in range(1, lag + 1):
        weight = 1.0 - step / (lag + 1)
        gamma = centered[step:].T @ centered[:-step] / len(centered)
        covariance += weight * (gamma + gamma.T)
    return covariance


def cqfe_covariance(
    fitted,
    x: np.ndarray,
    y: np.ndarray,
    tau: float,
    lag: int,
) -> tuple[np.ndarray, dict]:
    """HAC sandwich covariance for the CQFE combination quantile regression."""
    design = np.column_stack([np.ones(len(x)), np.asarray(x, dtype=float)])
    residual = np.asarray(y, dtype=float) - design @ fitted.params
    sparsity = float(getattr(fitted, "sparsity", np.nan))
    bandwidth = float(getattr(fitted, "bandwidth", np.nan))
    if not np.isfinite(sparsity) or sparsity <= 0:
        raise RuntimeError("CQFE quantile-regression sparsity is invalid")
    density_zero = 1.0 / sparsity
    jacobian = density_zero * (design.T @ design / len(design))
    score = (tau - (residual < 0).astype(float))[:, None] * design
    score_lrcov = _hac_long_run_covariance(score, lag)
    jacobian_inv = np.linalg.inv(jacobian)
    covariance = jacobian_inv @ score_lrcov @ jacobian_inv.T / len(design)
    covariance = (covariance + covariance.T) / 2.0
    eigenvalues = np.linalg.eigvalsh(covariance)
    if not np.isfinite(covariance).all() or eigenvalues.min() <= 0:
        raise RuntimeError("CQFE covariance is not positive definite")
    standardized = np.column_stack(
        [
            np.ones(len(x)),
            (x[:, 0] - x[:, 0].mean()) / x[:, 0].std(ddof=1),
            (x[:, 1] - x[:, 1].mean()) / x[:, 1].std(ddof=1),
        ]
    )
    condition_number = float(np.linalg.cond(standardized))
    return covariance, {
        "sparsity": sparsity,
        "bandwidth": bandwidth,
        "density_at_zero": density_zero,
        "standardized_design_condition_number": condition_number,
        "covariance_min_eigenvalue": float(eigenvalues.min()),
    }


def _wald(theta: np.ndarray, covariance: np.ndarray, restriction: np.ndarray) -> float:
    difference = np.asarray(theta, float) - np.asarray(restriction, float)
    return float(difference @ np.linalg.solve(covariance, difference))


def _circular_block_indices(
    n: int, block_length: int, rng: np.random.Generator
) -> np.ndarray:
    n_blocks = int(np.ceil(n / block_length))
    starts = rng.integers(0, n, size=n_blocks)
    return np.concatenate(
        [(start + np.arange(block_length)) % n for start in starts]
    )[:n]


def cqfe_test(
    y: np.ndarray,
    q_vix: np.ndarray,
    q_joint: np.ndarray,
    horizon: int,
    *,
    bootstrap_reps: int = BOOTSTRAP_REPS,
    seed: int,
) -> dict:
    """Giacomini-Komunjer CQFE for fixed rolling-window forecast paths.

    Combination: intercept + lambda_vix*q_vix + lambda_joint*q_joint.
    Canonical VIX-encompasses-joint null is (0, 1, 0).  The separate
    lambda_joint=0 subtest prevents affine recalibration from being mistaken for
    incremental NFCI information.
    """
    y = np.asarray(y, float)
    x = np.column_stack([np.asarray(q_vix, float), np.asarray(q_joint, float)])
    if len(y) < 250 or not np.isfinite(np.column_stack([y, x])).all():
        raise ValueError("CQFE requires at least 250 finite paired forecasts")
    lag = _canonical_nw_lag(horizon, len(y))
    fitted = BASE.fit_quantreg(x, y, TAU)
    theta = np.asarray(fitted.params, float)
    covariance, covariance_audit = cqfe_covariance(fitted, x, y, TAU, lag)
    vix_null = np.array([0.0, 1.0, 0.0])
    joint_null = np.array([0.0, 0.0, 1.0])
    full_wald = _wald(theta, covariance, vix_null)
    reverse_wald = _wald(theta, covariance, joint_null)
    incremental_wald = float(theta[2] ** 2 / covariance[2, 2])

    rng = np.random.default_rng(seed)
    block_length = lag + 1
    full_roots: list[float] = []
    reverse_roots: list[float] = []
    incremental_roots: list[float] = []
    failures: dict[str, int] = {}
    for _ in range(bootstrap_reps):
        index = _circular_block_indices(len(y), block_length, rng)
        y_b = y[index]
        x_b = x[index]
        try:
            fitted_b = BASE.fit_quantreg(x_b, y_b, TAU)
            theta_b = np.asarray(fitted_b.params, float)
            covariance_b, _ = cqfe_covariance(fitted_b, x_b, y_b, TAU, lag)
            centered = theta_b - theta
            full_roots.append(float(centered @ np.linalg.solve(covariance_b, centered)))
            reverse_roots.append(float(centered @ np.linalg.solve(covariance_b, centered)))
            incremental_roots.append(float(centered[2] ** 2 / covariance_b[2, 2]))
        except Exception as exc:  # fail count is serialized and gated below
            name = type(exc).__name__
            failures[name] = failures.get(name, 0) + 1

    successful = len(full_roots)
    if successful < max(1_000, int(np.ceil(0.98 * bootstrap_reps))):
        raise RuntimeError(
            f"CQFE bootstrap success gate failed H={horizon}: "
            f"{successful}/{bootstrap_reps}, failures={failures}"
        )
    full_boot_p = float(
        (1 + np.sum(np.asarray(full_roots) >= full_wald)) / (successful + 1)
    )
    reverse_boot_p = float(
        (1 + np.sum(np.asarray(reverse_roots) >= reverse_wald)) / (successful + 1)
    )
    incremental_boot_p = float(
        (1 + np.sum(np.asarray(incremental_roots) >= incremental_wald))
        / (successful + 1)
    )
    return {
        "n": int(len(y)),
        "combination_parameters": {
            "intercept": float(theta[0]),
            "lambda_vix": float(theta[1]),
            "lambda_vix_nfci": float(theta[2]),
        },
        "canonical_nw_lag": lag,
        "bootstrap_block_length": block_length,
        "vix_encompasses_joint_null": {
            "restriction": [0.0, 1.0, 0.0],
            "wald": full_wald,
            "asymptotic_p_chi2_df3": float(stats.chi2.sf(full_wald, df=3)),
            "bootstrap_p": full_boot_p,
        },
        "joint_encompasses_vix_reverse_null": {
            "restriction": [0.0, 0.0, 1.0],
            "wald": reverse_wald,
            "asymptotic_p_chi2_df3": float(stats.chi2.sf(reverse_wald, df=3)),
            "bootstrap_p": reverse_boot_p,
        },
        "incremental_lambda_joint_zero_subtest": {
            "restriction": "lambda_vix_nfci = 0",
            "wald": incremental_wald,
            "asymptotic_p_chi2_df1": float(stats.chi2.sf(incremental_wald, df=1)),
            "bootstrap_p": incremental_boot_p,
        },
        "bootstrap": {
            "requested": bootstrap_reps,
            "successful": successful,
            "failures": failures,
            "seed": seed,
            "method": "circular moving-block, centered studentized Wald roots",
        },
        "identification": {
            **covariance_audit,
            "condition_number_gate": CONDITION_NUMBER_GATE,
            "passes_condition_number_gate": bool(
                covariance_audit["standardized_design_condition_number"]
                < CONDITION_NUMBER_GATE
            ),
        },
    }


def build_serialized_artifact(
    expanding: pd.DataFrame,
    rolling_primary: pd.DataFrame,
    rolling_sensitivity: list[pd.DataFrame],
) -> pd.DataFrame:
    expanding = expanding.copy()
    expanding["target"] = "fwd_ret"
    expanding["tau"] = TAU
    frames = [expanding]
    for frame in [rolling_primary, *rolling_sensitivity]:
        copy = frame.copy()
        copy["target"] = "fwd_ret"
        frames.append(copy)
    artifact = pd.concat(frames, ignore_index=True, sort=False)
    date_columns = [
        "origin",
        "target_end",
        "train_start",
        "train_end",
        "latest_training_target_end",
        "nfci_obs_date",
        "nfci_realtime_start",
        "nfci_realtime_end",
    ]
    for column in date_columns:
        artifact[column] = pd.to_datetime(artifact[column])
    priority = [
        "scheme",
        "rolling_window",
        "target",
        "horizon_weeks",
        "tau",
        *date_columns,
        "realized",
        "vix_value",
        "nfci_value",
        "q_unconditional",
        "loss_unconditional",
        "q_nfci",
        "loss_nfci",
        "q_vix",
        "loss_vix",
        "q_vix_nfci",
        "loss_vix_nfci",
    ]
    remaining = [column for column in artifact.columns if column not in priority]
    artifact = artifact[priority + sorted(remaining)].sort_values(
        ["scheme", "horizon_weeks", "origin"]
    ).reset_index(drop=True)
    expected_rows = (
        sum({1: 536, 4: 530, 12: 514}.values())
        + sum(len(frame) for frame in [rolling_primary, *rolling_sensitivity])
    )
    if len(artifact) != expected_rows:
        raise RuntimeError(f"serialized artifact row-count drift: {len(artifact)}")
    return artifact


def analyze_roundtrip(roundtrip: pd.DataFrame) -> dict:
    expanding = roundtrip.loc[roundtrip["scheme"] == "expanding_refit4_bridge"].copy()
    rolling = roundtrip.loc[
        roundtrip["scheme"] == f"rolling_R{PRIMARY_ROLLING_WINDOW}"
    ].copy()

    paired_expanding: dict[int, dict] = {}
    bridge_incremental: dict[int, dict] = {}
    rolling_pair: dict[int, dict] = {}
    rolling_incremental: dict[int, dict] = {}
    cqfe: dict[int, dict] = {}
    for horizon in HORIZONS:
        base_h = expanding.loc[expanding["horizon_weeks"] == horizon].sort_values("origin")
        paired_expanding[horizon] = paired_loss_test(
            base_h["loss_vix"].to_numpy(float),
            base_h["loss_nfci"].to_numpy(float),
            horizon,
            candidate_name="VIX-only",
            benchmark_name="NFCI-only",
        )
        bridge_incremental[horizon] = paired_loss_test(
            base_h["loss_vix_nfci"].to_numpy(float),
            base_h["loss_vix"].to_numpy(float),
            horizon,
            candidate_name="VIX+NFCI",
            benchmark_name="VIX-only",
        )

        rolling_h = rolling.loc[rolling["horizon_weeks"] == horizon].sort_values("origin")
        rolling_pair[horizon] = paired_loss_test(
            rolling_h["loss_vix"].to_numpy(float),
            rolling_h["loss_nfci"].to_numpy(float),
            horizon,
            candidate_name="VIX-only",
            benchmark_name="NFCI-only",
        )
        rolling_incremental[horizon] = paired_loss_test(
            rolling_h["loss_vix_nfci"].to_numpy(float),
            rolling_h["loss_vix"].to_numpy(float),
            horizon,
            candidate_name="VIX+NFCI",
            benchmark_name="VIX-only",
        )
        cqfe[horizon] = cqfe_test(
            rolling_h["realized"].to_numpy(float),
            rolling_h["q_vix"].to_numpy(float),
            rolling_h["q_vix_nfci"].to_numpy(float),
            horizon,
            seed=SEED + horizon,
        )

    for family in (
        paired_expanding,
        bridge_incremental,
        rolling_pair,
        rolling_incremental,
    ):
        apply_holm_family(family, "canonical_dm_p_two_sided")

    full_p = [
        cqfe[h]["vix_encompasses_joint_null"]["bootstrap_p"] for h in HORIZONS
    ]
    incremental_p = [
        cqfe[h]["incremental_lambda_joint_zero_subtest"]["bootstrap_p"]
        for h in HORIZONS
    ]
    full_reject, full_adjusted, _, _ = multipletests(full_p, alpha=0.05, method="holm")
    inc_reject, inc_adjusted, _, _ = multipletests(
        incremental_p, alpha=0.05, method="holm"
    )
    for horizon, reject_full, p_full, reject_inc, p_inc in zip(
        HORIZONS, full_reject, full_adjusted, inc_reject, inc_adjusted
    ):
        cqfe[horizon]["vix_encompasses_joint_null"]["bootstrap_p_holm"] = float(p_full)
        cqfe[horizon]["vix_encompasses_joint_null"]["bootstrap_holm_reject"] = bool(
            reject_full
        )
        cqfe[horizon]["incremental_lambda_joint_zero_subtest"][
            "bootstrap_p_holm"
        ] = float(p_inc)
        cqfe[horizon]["incremental_lambda_joint_zero_subtest"][
            "bootstrap_holm_reject"
        ] = bool(reject_inc)

    pair_pass: dict[int, bool] = {}
    encompass_pass: dict[int, bool] = {}
    for horizon in HORIZONS:
        pair = paired_expanding[horizon]
        pair_pass[horizon] = bool(
            pair["candidate_better"]
            and pair["harvey_t_better_gate"]
            and pair["canonical_dm_p_two_sided_holm_below_0_05"]
            and pair["first_half_mean_differential"] < 0
            and pair["second_half_mean_differential"] < 0
        )
        inc = rolling_incremental[horizon]
        full_test = cqfe[horizon]["vix_encompasses_joint_null"]
        lambda_test = cqfe[horizon]["incremental_lambda_joint_zero_subtest"]
        identification = cqfe[horizon]["identification"]
        encompass_pass[horizon] = bool(
            inc["candidate_better"]
            and full_test["bootstrap_holm_reject"]
            and lambda_test["bootstrap_holm_reject"]
            and inc["first_half_mean_differential"] < 0
            and inc["second_half_mean_differential"] < 0
            and identification["passes_condition_number_gate"]
        )
        pair["pair_pass"] = pair_pass[horizon]
        cqfe[horizon]["nfci_incremental_information_pass"] = encompass_pass[horizon]

    sensitivity: dict[str, dict[int, dict]] = {}
    for rolling_window in SENSITIVITY_WINDOWS:
        frame = roundtrip.loc[roundtrip["scheme"] == f"rolling_R{rolling_window}"]
        sensitivity[str(rolling_window)] = {}
        for horizon in HORIZONS:
            cell = frame.loc[frame["horizon_weeks"] == horizon].sort_values("origin")
            sensitivity[str(rolling_window)][horizon] = paired_loss_test(
                cell["loss_vix_nfci"].to_numpy(float),
                cell["loss_vix"].to_numpy(float),
                horizon,
                candidate_name="VIX+NFCI",
                benchmark_name="VIX-only",
            )
        apply_holm_family(
            sensitivity[str(rolling_window)], "canonical_dm_p_two_sided"
        )

    any_pair_pass = any(pair_pass.values())
    all_pair_pass = all(pair_pass.values())
    any_incremental_pass = any(encompass_pass.values())
    if all_pair_pass:
        dominance_verdict = "VIX_BETTER_THAN_NFCI_ACROSS_ALL_HORIZONS"
    elif any_pair_pass:
        dominance_verdict = "VIX_BETTER_ONLY_AT_SPECIFIC_HORIZONS"
    else:
        dominance_verdict = "NO_ROBUST_VIX_DOMINANCE"
    incremental_verdict = (
        "NFCI_ADDS_INCREMENTAL_INFORMATION_AT_SOME_HORIZON"
        if any_incremental_pass
        else "NO_EVIDENCE_OF_NFCI_INCREMENTAL_INFORMATION_BEYOND_VIX"
    )
    if any_incremental_pass:
        overall = "POSITIVE_NFCI_INCREMENTAL_INFORMATION"
    elif all_pair_pass:
        overall = "VIX_DOMINANCE_ONLY_NO_NFCI_INCREMENTAL_EVIDENCE"
    elif any_pair_pass:
        overall = "HORIZON_SPECIFIC_VIX_ADVANTAGE_ONLY"
    else:
        overall = "NULL_NO_DOMINANCE_OR_INCREMENTAL_EVIDENCE"
    return {
        "frozen_expanding_vix_vs_nfci": {
            str(h): paired_expanding[h] for h in HORIZONS
        },
        "expanding_bridge_vix_nfci_vs_vix": {
            str(h): bridge_incremental[h] for h in HORIZONS
        },
        "rolling_primary_vix_vs_nfci": {str(h): rolling_pair[h] for h in HORIZONS},
        "rolling_primary_vix_nfci_vs_vix_dm_diagnostic": {
            str(h): rolling_incremental[h] for h in HORIZONS
        },
        "rolling_primary_cqfe": {str(h): cqfe[h] for h in HORIZONS},
        "rolling_window_sensitivity_vix_nfci_vs_vix": {
            window: {str(h): cells[h] for h in HORIZONS}
            for window, cells in sensitivity.items()
        },
        "verdict": {
            "overall": overall,
            "vix_vs_nfci": dominance_verdict,
            "nfci_incremental_beyond_vix": incremental_verdict,
            "pair_pass_by_horizon": {str(h): pair_pass[h] for h in HORIZONS},
            "encompassing_pass_by_horizon": {
                str(h): encompass_pass[h] for h in HORIZONS
            },
            "interpretation_rule": (
                "Failure to reject incremental value is absence of evidence, not proof "
                "that VIX fully encompasses NFCI."
            ),
        },
    }


def make_chart(analysis: dict, path: Path) -> None:
    labels = ["1 週", "4 週", "12 週"]
    x = np.arange(len(HORIZONS))
    width = 0.26
    pair = analysis["frozen_expanding_vix_vs_nfci"]
    bridge = analysis["expanding_bridge_vix_nfci_vs_vix"]
    rolling = analysis["rolling_primary_vix_nfci_vs_vix_dm_diagnostic"]
    values = [
        [pair[str(h)]["candidate_improvement_pct"] for h in HORIZONS],
        [bridge[str(h)]["candidate_improvement_pct"] for h in HORIZONS],
        [rolling[str(h)]["candidate_improvement_pct"] for h in HORIZONS],
    ]
    colors = ["#1f4e79", "#d97706", "#6b7280"]
    names = [
        "VIX 相對 NFCI（frozen expanding）",
        "VIX+NFCI 相對 VIX（expanding bridge）",
        "VIX+NFCI 相對 VIX（rolling R=400）",
    ]
    fig, ax = plt.subplots(figsize=(10, 6))
    for offset, (series, color, name) in enumerate(zip(values, colors, names)):
        bars = ax.bar(x + (offset - 1) * width, series, width, color=color, label=name)
        for bar, value in zip(bars, series):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value + (0.35 if value >= 0 else -0.75),
                f"{value:+.1f}%",
                ha="center",
                va="bottom" if value >= 0 else "top",
                fontsize=9,
            )
    ax.axhline(0, color="black", linewidth=0.9)
    ax.set_xticks(x, labels)
    ax.set_ylabel("Pinball loss 改善率（正值代表前者較好）")
    ax.set_title(
        "K1655：VIX 與 true-PIT NFCI 的同原點比較\n"
        "Harvey gate 與 CQFE 共同決定結論，不以點估計大小代替檢定"
    )
    ax.legend(frameon=False, fontsize=9)
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    started = datetime.now(timezone.utc)
    before = frozen_manifest()
    panel = load_frozen_panel(before)
    frozen_pairs = load_frozen_expanding_pairs()
    _reset_fit_diagnostics()

    expanding = expanding_joint_bridge(panel, frozen_pairs)
    rolling_primary = rolling_forecasts(
        panel, PRIMARY_ROLLING_WINDOW, include_nfci_only=True
    )
    rolling_sensitivity = [
        rolling_forecasts(panel, window, include_nfci_only=False)
        for window in SENSITIVITY_WINDOWS
    ]
    artifact = build_serialized_artifact(
        expanding, rolling_primary, rolling_sensitivity
    )
    atomic_write_csv(artifact, OUT_FORECASTS)
    roundtrip = pd.read_csv(
        OUT_FORECASTS,
        parse_dates=[
            "origin",
            "target_end",
            "train_start",
            "train_end",
            "latest_training_target_end",
            "nfci_obs_date",
            "nfci_realtime_start",
            "nfci_realtime_end",
        ],
    )
    analysis = analyze_roundtrip(roundtrip)

    blocking_fit_diagnostics = {
        key: BASE.FIT_DIAGNOSTICS[key]
        for key in (
            "unresolved_iteration_limit_failures",
            "other_warning_count",
            "bootstrap_fit_exceptions",
            "oos_fit_exceptions",
        )
    }
    if any(blocking_fit_diagnostics.values()):
        raise RuntimeError(
            f"QuantReg convergence/fit gate failed: {blocking_fit_diagnostics}"
        )
    assert_manifest_unchanged(before)
    make_chart(analysis, OUT_CHART)

    results = {
        "experiment_id": "K1655_VIX_NFCI_ENCOMPASSING",
        "parent_experiment_id": "K1655",
        "title": "VIX versus true-PIT NFCI: paired quantile forecast accuracy and CQFE",
        "run_at": started.isoformat(),
        "methodology_type": "empirical out-of-sample forecast comparison",
        "seed": SEED,
        "data": {
            "asset": "S&P 500 price index (^GSPC), not SPY total return",
            "target": "forward cumulative log return",
            "frequency": "weekly W-FRI",
            "sample": before["base_sample"],
            "frozen_inputs": before,
            "offline_only": True,
            "network_fallback": False,
            "panel_timing_gates": panel.attrs["timing_gates"],
            "output_forecast_artifact": {
                "path": OUT_FORECASTS.name,
                "rows": int(len(roundtrip)),
                "sha256": sha256_file(OUT_FORECASTS),
                "schemes": roundtrip.groupby("scheme").size().to_dict(),
            },
        },
        "config": {
            "primary_target": "fwd_ret",
            "primary_tau": TAU,
            "horizons_weeks": list(HORIZONS),
            "frozen_expanding_refit_every": BASE.REFIT_EVERY,
            "strict_embargo": "training row j admissible iff j + H < origin i",
            "cqfe_primary_rolling_window": PRIMARY_ROLLING_WINDOW,
            "cqfe_refit_every": 1,
            "cqfe_sensitivity_windows": list(SENSITIVITY_WINDOWS),
            "cqfe_bootstrap_reps": BOOTSTRAP_REPS,
            "cqfe_inference_priority": (
                "circular moving-block bootstrap is primary; chi-square asymptotic "
                "p-values are diagnostic only because the analytic covariance uses "
                "a single residual sparsity estimate"
            ),
            "multiple_testing": "Holm correction within each pre-registered 3-horizon family",
            "harvey_gate": "candidate must have t < -3",
            "quantreg_fit_diagnostics": BASE.FIT_DIAGNOSTICS,
        },
        "analysis": analysis,
        "review_status": {
            "status": "PASS",
            "reviewed_at": "2026-07-11",
            "review_path": (
                "experiments/K1655/reviews/"
                "codex_vix_nfci_encompassing_postrun_2026-07-11.md"
            ),
            "scope": (
                "PASS for frozen-input integrity, paired loss reconstruction, fixed-window "
                "CQFE implementation, deterministic block bootstrap, and the narrow "
                "double-null conclusion"
            ),
            "caveat": (
                "Block-bootstrap p-values govern CQFE inference; asymptotic chi-square "
                "p-values are diagnostic and must not be used to upgrade the conclusion."
            ),
        },
        "references": [
            {
                "authors": "Giacomini, R.; Komunjer, I.",
                "year": 2005,
                "title": "Evaluation and Combination of Conditional Quantile Forecasts",
                "publication": "Journal of Business & Economic Statistics 23(4), 416-431",
                "doi": "10.1198/073500105000000018",
            },
            {
                "authors": "Giacomini, R.; White, H.",
                "year": 2006,
                "title": "Tests of Conditional Predictive Ability",
                "publication": "Econometrica 74(6), 1545-1578",
                "doi": "10.1111/j.1468-0262.2006.00718.x",
            },
            {
                "authors": "Diebold, F. X.; Mariano, R. S.",
                "year": 1995,
                "title": "Comparing Predictive Accuracy",
                "publication": "Journal of Business & Economic Statistics 13(3), 253-263",
                "doi": "10.1080/07350015.1995.10524599",
            },
            {
                "authors": "Clark, T. E.; McCracken, M. W.",
                "year": 2001,
                "title": "Tests of Equal Forecast Accuracy and Encompassing for Nested Models",
                "publication": "Journal of Econometrics 105(1), 85-110",
                "doi": "10.1016/S0304-4076(01)00071-7",
            },
        ],
        "honest_statement": (
            "Paired loss tests can establish horizon-specific forecast accuracy, not "
            "universal dominance. CQFE rejection plus a lambda_joint subtest is required "
            "for positive NFCI incremental evidence. Failure to reject is not proof that "
            "VIX fully encompasses NFCI."
        ),
        "elapsed_seconds": (datetime.now(timezone.utc) - started).total_seconds(),
    }
    atomic_write_json(results, OUT_RESULTS)
    assert_manifest_unchanged(before)

    verdict = analysis["verdict"]
    print("===== K1655 VIX/NFCI ENCOMPASSING =====")
    print(f"overall: {verdict['overall']}")
    print(f"VIX vs NFCI: {verdict['vix_vs_nfci']}")
    print(f"NFCI incremental: {verdict['nfci_incremental_beyond_vix']}")
    for horizon in HORIZONS:
        pair = analysis["frozen_expanding_vix_vs_nfci"][str(horizon)]
        inc = analysis["rolling_primary_vix_nfci_vs_vix_dm_diagnostic"][str(horizon)]
        cq = analysis["rolling_primary_cqfe"][str(horizon)]
        print(
            f"H={horizon} | VIX-vs-NFCI improvement={pair['candidate_improvement_pct']:+.2f}% "
            f"DM={pair['canonical_dm_t']:+.2f} | joint-vs-VIX rolling="
            f"{inc['candidate_improvement_pct']:+.2f}% DM={inc['canonical_dm_t']:+.2f} "
            f"CQFE full p_holm={cq['vix_encompasses_joint_null']['bootstrap_p_holm']:.3f} "
            f"lambda p_holm={cq['incremental_lambda_joint_zero_subtest']['bootstrap_p_holm']:.3f}"
        )
    print(f"written: {OUT_RESULTS}")


if __name__ == "__main__":
    main()
