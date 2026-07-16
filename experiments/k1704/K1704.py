#!/usr/bin/env python3
"""K1704: point-in-time consensus weighting for biased volatility proxies.

The experiment uses the canonical TAIFEX all-contract TX archive.  For every
trading-day file it selects the completed-day highest-volume monthly contract,
then computes homogeneous day-session RV at 1/5/10-minute sampling, the
Parkinson range proxy, and squared open-to-close log return.  Forecast models
are evaluated against every proxy and a heuristic consensus whose log-biases
and inverse residual-dispersion weights are estimated only from observations
before each forecast origin.

Methodology type: empirical forecast-comparison diagnostic.  No causal or
trading claim is made.  Random seed: 42.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import os
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from arch import arch_model
from scipy import stats


SEED = 42
EPS = 1e-12
PROXY_COLUMNS = ["rv_1min", "rv_5min", "rv_10min", "parkinson", "r2_day"]
MODEL_NAMES = ["HAR_RV5", "GJR_GARCH", "EWMA_R2"]

ROOT = Path(__file__).resolve().parents[2]
for candidate in (ROOT / "src", ROOT / "scripts"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import collect_taifex_tick as collector  # noqa: E402
import volpred.stats.mcs as mcs_module  # noqa: E402
import volpred.stats.model_evaluation as evaluation_module  # noqa: E402
from volpred.stats.mcs import model_confidence_set  # noqa: E402
from volpred.stats.model_evaluation import (  # noqa: E402
    dm_test,
    qlike,
    qlike_pointwise,
    spearman_corr,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json_dump(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        with open(tmp_name, encoding="utf-8") as handle:
            json.load(handle)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def atomic_csv_dump(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    try:
        frame.to_csv(tmp_name, index=False, float_format="%.16g")
        check = pd.read_csv(tmp_name, float_precision="round_trip")
        if len(check) != len(frame):
            raise RuntimeError("proxy-cache row-count verification failed")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _rv_from_ticks(
    ticks: pd.DataFrame, minutes: int, *, include_session_open: bool = True
) -> float:
    hour = ticks["trade_time"] // 10000
    minute = (ticks["trade_time"] % 10000) // 100
    minute_of_day = hour * 60 + minute
    session_start = collector.DAY_START // 10000 * 60 + (collector.DAY_START % 10000) // 100
    offset = minute_of_day - session_start
    endpoint = ticks["trade_time"].eq(collector.DAY_END)
    # Anchor every grid at the 08:45 session open.  The exact 13:45 endpoint is
    # the close of the last interval, not the start of an empty next interval.
    offset = offset.where(~endpoint, offset - 1)
    bar = session_start + (offset // minutes) * minutes
    closes = ticks.assign(_bar=bar).groupby("_bar", sort=True)["price"].last()
    sampled = closes.to_numpy(dtype=float)
    if include_session_open:
        # A close-to-close grid needs the first observed session price as its
        # left endpoint; otherwise the opening interval is silently omitted.
        sampled = np.concatenate(([float(ticks["price"].iloc[0])], sampled))
    if len(sampled) < 2:
        return math.nan
    log_returns = np.diff(np.log(sampled))
    return float(np.square(log_returns).sum())


def extract_proxy_row(path_value: str) -> dict[str, Any]:
    """Build one daily row using the collector's canonical normalization."""
    path = Path(path_value)
    frame = collector.read_taifex_ticks(path)
    active_contract = collector.pick_active_contract(frame)
    ticks = frame[
        frame["contract"].eq(active_contract)
        & frame["trade_time"].between(collector.DAY_START, collector.DAY_END)
    ].copy()
    ticks = ticks.sort_values(["trade_date", "trade_time", "_row_order"], kind="stable")
    if len(ticks) < 20:
        raise collector.SourceFormatError("fewer than twenty active-contract day ticks")

    prices = ticks["price"].to_numpy(dtype=float)
    high = float(np.max(prices))
    low = float(np.min(prices))
    session_return = float(np.log(prices[-1] / prices[0]))
    return {
        "date": collector._date_from_filename(path).date().isoformat(),
        "active_contract": active_contract,
        "rv_1min": _rv_from_ticks(ticks, 1),
        "rv_5min": _rv_from_ticks(ticks, 5),
        # Preserve the repo collector's close-only convention solely to audit
        # source selection and canonical compatibility. It is not a target.
        "rv_5min_canonical_convention": _rv_from_ticks(
            ticks, 5, include_session_open=False
        ),
        "rv_10min": _rv_from_ticks(ticks, 10),
        "parkinson": float(np.log(high / low) ** 2 / (4.0 * np.log(2.0))),
        "r2_day": session_return**2,
        "day_return": session_return,
        "n_ticks": int(len(ticks)),
        "source_file": path.name,
        "source_size": path.stat().st_size,
        "source_mtime_ns": path.stat().st_mtime_ns,
        "source_sha256": sha256_file(path),
    }


def inventory_hash(files: list[Path]) -> str:
    lines = []
    for path in files:
        stat = path.stat()
        lines.append(f"{path.name}\t{stat.st_size}\t{stat.st_mtime_ns}\n")
    return hashlib.sha256("".join(lines).encode()).hexdigest()


def byte_inventory_hash(frame: pd.DataFrame) -> str:
    ordered = frame.sort_values("source_file")
    payload = "".join(
        f"{row.source_file}\t{row.source_sha256}\n"
        for row in ordered[["source_file", "source_sha256"]].itertuples(index=False)
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def cached_inventory_hash(frame: pd.DataFrame) -> str:
    ordered = frame.sort_values("source_file")
    payload = "".join(
        f"{row.source_file}\t{int(row.source_size)}\t{int(row.source_mtime_ns)}\n"
        for row in ordered[
            ["source_file", "source_size", "source_mtime_ns"]
        ].itertuples(index=False)
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def verify_cached_source_bytes(frame: pd.DataFrame, source_dir: Path) -> dict[str, Any]:
    """Re-read every cached source file and fail closed on any byte drift."""
    if frame["source_file"].duplicated().any():
        duplicates = sorted(frame.loc[frame["source_file"].duplicated(), "source_file"].unique())
        raise RuntimeError(f"proxy cache has duplicate source files: {duplicates[:5]}")

    expected_names = set(frame["source_file"].astype(str))
    listed = collector.list_source_files(source_dir)
    listed_names = {path.name for path in listed}
    missing = sorted(expected_names - listed_names)
    if missing:
        raise RuntimeError(f"cached raw source files are missing: {missing[:5]}")

    current_lines: list[str] = []
    for row in frame[["source_file", "source_size", "source_sha256"]].itertuples(index=False):
        path = source_dir / str(row.source_file)
        observed_size = path.stat().st_size
        if observed_size != int(row.source_size):
            raise RuntimeError(
                f"cached raw source size mismatch for {path.name}: "
                f"expected={int(row.source_size)} observed={observed_size}"
            )
        observed_hash = sha256_file(path)
        if observed_hash != str(row.source_sha256):
            raise RuntimeError(
                f"cached raw source SHA256 mismatch for {path.name}: "
                f"expected={row.source_sha256} observed={observed_hash}"
            )
        current_lines.append(f"{path.name}\t{observed_hash}\n")

    return {
        "raw_bytes_reverified": True,
        "listed_source_file_count": len(listed),
        "expected_source_file_count": len(expected_names),
        "extra_source_files_not_in_cache": sorted(listed_names - expected_names),
        "current_source_byte_inventory_sha256": hashlib.sha256(
            "".join(sorted(current_lines)).encode()
        ).hexdigest(),
    }


def proxy_builder_code_sha256() -> str:
    functions = (
        _rv_from_ticks,
        extract_proxy_row,
        inventory_hash,
        byte_inventory_hash,
        cached_inventory_hash,
    )
    payload = "\n".join(inspect.getsource(function) for function in functions)
    return hashlib.sha256(payload.encode()).hexdigest()


def build_proxy_cache(
    source_dir: Path,
    canonical_rv_path: Path,
    cache_path: Path,
    workers: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    canonical = pd.read_csv(canonical_rv_path, float_precision="round_trip")
    canonical["date"] = pd.to_datetime(canonical["date"])
    canonical_dates = set(canonical["date"].dt.date)
    all_files = collector.list_source_files(source_dir)
    files = [path for path in all_files if collector._date_from_filename(path).date() in canonical_dates]
    excluded_files = [path.name for path in all_files if path not in files]
    if len(files) < 252:
        raise RuntimeError(f"need >=252 TX files, found {len(files)}")
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(extract_proxy_row, str(path)): path for path in files}
        for future in as_completed(future_map):
            path = future_map[future]
            try:
                rows.append(future.result())
            except Exception as exc:  # noqa: BLE001 - retain full extraction audit
                errors.append(f"{path.name}: {exc}")
    if errors:
        raise RuntimeError(f"proxy extraction failed for {len(errors)} files: {errors[:5]}")

    derived = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    derived["date"] = pd.to_datetime(derived["date"])
    merged = derived.merge(
        canonical[["date", "active_contract", "rv_5min", "day_return"]],
        on="date",
        how="inner",
        suffixes=("_derived", "_canonical"),
        validate="one_to_one",
    )
    if len(merged) != len(files):
        raise RuntimeError(f"canonical/derived join lost rows: {len(merged)} != {len(files)}")
    contract_mismatch = int(
        (merged["active_contract_derived"] != merged["active_contract_canonical"]).sum()
    )
    canonical_rv_gap = np.abs(
        merged["rv_5min_canonical_convention"] - merged["rv_5min_canonical"]
    )
    if contract_mismatch or float(canonical_rv_gap.max()) > 1e-14:
        raise RuntimeError(
            f"collector parity failed: contract_mismatch={contract_mismatch}, "
            f"max_abs_canonical_rv5_gap={float(canonical_rv_gap.max())}"
        )
    return_gap = np.abs(merged["day_return_derived"] - merged["day_return_canonical"])
    if float(return_gap.max()) > 1e-14:
        raise RuntimeError(f"day-return parity failed: max_abs_gap={float(return_gap.max())}")

    out = merged[
        [
            "date",
            "active_contract_canonical",
            "rv_1min",
            "rv_5min_derived",
            "rv_5min_canonical_convention",
            "rv_10min",
            "parkinson",
            "r2_day",
            "day_return_canonical",
            "n_ticks",
            "source_file",
            "source_size",
            "source_mtime_ns",
            "source_sha256",
        ]
    ].rename(
        columns={
            "active_contract_canonical": "active_contract",
            "rv_5min_derived": "rv_5min",
            "day_return_canonical": "day_return",
        }
    )
    out["builder_collector_sha256"] = sha256_file(Path(collector.__file__))
    out["builder_proxy_code_sha256"] = proxy_builder_code_sha256()
    out["builder_mcs_sha256"] = sha256_file(Path(mcs_module.__file__))
    out["builder_evaluation_sha256"] = sha256_file(Path(evaluation_module.__file__))
    atomic_csv_dump(out, cache_path)
    audit = {
        "source_file_count": len(files),
        "excluded_not_in_canonical": excluded_files,
        "source_inventory_sha256": inventory_hash(files),
        "source_byte_inventory_sha256": byte_inventory_hash(out),
        "canonical_rv_sha256": sha256_file(canonical_rv_path),
        "cache_sha256": sha256_file(cache_path),
        "collector_code_sha256": sha256_file(Path(collector.__file__)),
        "experiment_code_sha256": sha256_file(Path(__file__)),
        "mcs_code_sha256": sha256_file(Path(mcs_module.__file__)),
        "evaluation_code_sha256": sha256_file(Path(evaluation_module.__file__)),
        "contract_mismatches": contract_mismatch,
        "max_abs_canonical_rv5_parity_gap": float(canonical_rv_gap.max()),
        "max_abs_day_return_parity_gap": float(return_gap.max()),
    }
    return out, audit


def load_proxy_cache(
    cache_path: Path,
    canonical_rv_path: Path,
    source_dir: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = pd.read_csv(cache_path, float_precision="round_trip")
    required = {
        "date", "active_contract", "day_return", "source_file", "source_size",
        "source_mtime_ns", "source_sha256", "rv_5min_canonical_convention",
        "builder_collector_sha256", "builder_proxy_code_sha256", "builder_mcs_sha256",
        "builder_evaluation_sha256",
        *PROXY_COLUMNS,
    }
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"proxy cache missing columns: {sorted(missing)}")
    expected_builder = {
        "builder_collector_sha256": sha256_file(Path(collector.__file__)),
        "builder_proxy_code_sha256": proxy_builder_code_sha256(),
        "builder_mcs_sha256": sha256_file(Path(mcs_module.__file__)),
        "builder_evaluation_sha256": sha256_file(Path(evaluation_module.__file__)),
    }
    for column, expected in expected_builder.items():
        observed = set(frame[column].dropna().astype(str))
        if observed != {expected}:
            raise RuntimeError(
                f"proxy cache builder mismatch for {column}: observed={sorted(observed)}, "
                f"expected={expected}; rebuild proxies"
            )
    canonical = pd.read_csv(canonical_rv_path, float_precision="round_trip")
    canonical["date"] = pd.to_datetime(canonical["date"])
    frame["date"] = pd.to_datetime(frame["date"])
    merged = frame.merge(
        canonical[["date", "active_contract", "rv_5min", "day_return"]],
        on="date",
        how="inner",
        suffixes=("_cache", "_canonical"),
        validate="one_to_one",
    )
    if len(merged) != len(frame) or len(frame) != len(canonical):
        raise RuntimeError(
            f"canonical/cache join mismatch: merged={len(merged)}, "
            f"cache={len(frame)}, canonical={len(canonical)}"
        )
    contract_mismatch = int(
        (merged["active_contract_cache"] != merged["active_contract_canonical"]).sum()
    )
    canonical_rv_gap = np.abs(
        merged["rv_5min_canonical_convention"] - merged["rv_5min_canonical"]
    )
    return_gap = np.abs(merged["day_return_cache"] - merged["day_return_canonical"])
    if contract_mismatch or float(canonical_rv_gap.max()) > 1e-14:
        raise RuntimeError(
            f"cached collector parity failed: contract_mismatch={contract_mismatch}, "
            f"max_abs_canonical_rv5_gap={float(canonical_rv_gap.max())}"
        )
    if float(return_gap.max()) > 1e-14:
        raise RuntimeError(
            f"cached day-return parity failed: max_abs_gap={float(return_gap.max())}"
        )
    raw_byte_audit = verify_cached_source_bytes(frame, source_dir)
    audit = {
        "source_file_count": int(len(frame)),
        "source_inventory_sha256": cached_inventory_hash(frame),
        "source_byte_inventory_sha256": byte_inventory_hash(frame),
        "canonical_rv_sha256": sha256_file(canonical_rv_path),
        "cache_sha256": sha256_file(cache_path),
        "collector_code_sha256": sha256_file(Path(collector.__file__)),
        "experiment_code_sha256": sha256_file(Path(__file__)),
        "mcs_code_sha256": sha256_file(Path(mcs_module.__file__)),
        "evaluation_code_sha256": sha256_file(Path(evaluation_module.__file__)),
        "contract_mismatches": contract_mismatch,
        "max_abs_canonical_rv5_parity_gap": float(canonical_rv_gap.max()),
        "max_abs_day_return_parity_gap": float(return_gap.max()),
        **raw_byte_audit,
    }
    return frame, audit


def har_forecasts(frame: pd.DataFrame, oos_start: int, train_window: int) -> np.ndarray:
    positive_rv = frame["rv_5min"].where(frame["rv_5min"] > 0)
    log_rv = np.log(positive_rv)
    # Explicit lag surface: every feature at t is built only from RV through t-1.
    lagged_rv5 = log_rv.shift(1)
    features = pd.DataFrame(
        {
            "const": 1.0,
            "daily_lag": lagged_rv5,
            "weekly_lag": lagged_rv5.rolling(5).mean(),
            "monthly_lag": lagged_rv5.rolling(22).mean(),
        }
    )
    forecasts = np.full(len(frame), np.nan)
    for origin in range(oos_start, len(frame)):
        start = max(22, origin - train_window)
        x_train = features.iloc[start:origin].to_numpy(dtype=float)
        y_train = log_rv.iloc[start:origin].to_numpy(dtype=float)
        valid = np.isfinite(x_train).all(axis=1) & np.isfinite(y_train)
        beta, *_ = np.linalg.lstsq(x_train[valid], y_train[valid], rcond=None)
        residual = y_train[valid] - x_train[valid] @ beta
        smear = float(np.mean(np.exp(residual)))
        forecasts[origin] = float(np.exp(features.iloc[origin].to_numpy() @ beta) * smear)
    return forecasts


def ewma_forecasts(frame: pd.DataFrame) -> np.ndarray:
    squared = frame["day_return"].pow(2)
    # Forecast at t uses returns only through t-1; this is the required lag.
    return squared.shift(1).ewm(alpha=0.06, adjust=False, min_periods=22).mean().to_numpy()


def gjr_forecasts(
    frame: pd.DataFrame,
    oos_start: int,
    train_window: int,
    refit_every: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    returns_pct = frame["day_return"].to_numpy(dtype=float) * 100.0
    forecasts = np.full(len(frame), np.nan)
    params: dict[str, float] | None = None
    previous_h: float | None = None
    refit_count = 0
    fit_failures: list[str] = []

    for origin in range(oos_start, len(frame)):
        must_refit = params is None or (origin - oos_start) % refit_every == 0
        if must_refit:
            start = max(0, origin - train_window)
            train = returns_pct[start:origin]
            model = arch_model(
                train,
                mean="Zero",
                vol="GARCH",
                p=1,
                o=1,
                q=1,
                dist="normal",
                rescale=False,
            )
            fit = model.fit(disp="off", show_warning=False, options={"maxiter": 1000})
            if int(fit.convergence_flag) != 0:
                fit_failures.append(f"origin={origin}:flag={fit.convergence_flag}")
            p = fit.params
            params = {
                "omega": float(p["omega"]),
                "alpha": float(p["alpha[1]"]),
                "gamma": float(p["gamma[1]"]),
                "beta": float(p["beta[1]"]),
            }
            previous_h = float(fit.forecast(horizon=1, reindex=False).variance.iloc[-1, 0])
            refit_count += 1
        else:
            assert params is not None and previous_h is not None
            shock = returns_pct[origin - 1]
            previous_h = (
                params["omega"]
                + params["alpha"] * shock**2
                + params["gamma"] * (shock < 0) * shock**2
                + params["beta"] * previous_h
            )
        forecasts[origin] = max(float(previous_h) / 10000.0, EPS)

    if fit_failures:
        raise RuntimeError(f"GJR optimizer failed closed: {fit_failures[:5]}")
    return forecasts, {"refit_count": refit_count, "refit_every": refit_every, "fit_failures": 0}


def point_in_time_composite(
    frame: pd.DataFrame,
    oos_start: int,
    calibration_window: int,
) -> tuple[np.ndarray, pd.DataFrame, pd.DataFrame]:
    proxies = frame[PROXY_COLUMNS].where(frame[PROXY_COLUMNS] > 0)
    log_proxies = np.log(proxies)
    composite = np.full(len(frame), np.nan)
    weights = pd.DataFrame(np.nan, index=frame.index, columns=PROXY_COLUMNS)
    biases = pd.DataFrame(np.nan, index=frame.index, columns=PROXY_COLUMNS)

    for origin in range(oos_start, len(frame)):
        start = max(0, origin - calibration_window)
        history = log_proxies.iloc[start:origin].dropna()
        if len(history) < 252:
            continue
        # Estimate each proxy's residual against a leave-one-proxy-out centre.
        # This prevents a proxy from mechanically improving its own reliability
        # score through inclusion in the same-day median. Correlated errors among
        # the three RV grids remain a documented limitation.
        leave_one_out = pd.DataFrame(
            {
                column: history.drop(columns=column).median(axis=1)
                for column in PROXY_COLUMNS
            },
            index=history.index,
        )
        bias = (history - leave_one_out).mean(axis=0)
        residual = history.sub(bias, axis=1) - leave_one_out
        mse = residual.pow(2).mean(axis=0).clip(lower=1e-8)
        weight = (1.0 / mse) / (1.0 / mse).sum()
        current = log_proxies.iloc[origin] - bias
        composite[origin] = float(np.exp(np.dot(weight.to_numpy(), current.to_numpy())))
        weights.iloc[origin] = weight
        biases.iloc[origin] = bias
    return composite, weights, biases


def calibrate_forecasts_to_target(
    actual: np.ndarray,
    forecasts: dict[str, np.ndarray],
    oos_start: int,
    calibration_window: int,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Apply a past-only multiplicative scale calibration for a given target."""
    calibrated = {name: np.full(len(actual), np.nan) for name in MODEL_NAMES}
    scale_history = {name: [] for name in MODEL_NAMES}
    for origin in range(oos_start, len(actual)):
        start = max(0, origin - calibration_window)
        for name in MODEL_NAMES:
            past_actual = actual[start:origin]
            past_forecast = forecasts[name][start:origin]
            valid = (
                np.isfinite(past_actual)
                & np.isfinite(past_forecast)
                & (past_actual > 0)
                & (past_forecast > 0)
            )
            if int(valid.sum()) < 252:
                continue
            log_scale = float(np.mean(np.log(past_actual[valid]) - np.log(past_forecast[valid])))
            scale = float(np.exp(log_scale))
            calibrated[name][origin] = forecasts[name][origin] * scale
            scale_history[name].append(scale)
    audit = {
        name: {
            "n_origins": len(values),
            "mean_scale": float(np.mean(values)),
            "min_scale": float(np.min(values)),
            "max_scale": float(np.max(values)),
        }
        for name, values in scale_history.items()
    }
    return calibrated, audit


def build_common_evaluation_mask(
    actuals: dict[str, np.ndarray],
    forecasts_by_target: dict[str, dict[str, np.ndarray]],
    oos_start: int,
    origin_eligibility: np.ndarray | None = None,
) -> np.ndarray:
    """Freeze one cross-target OOS ledger and fail on post-eligibility gaps."""
    lengths = {len(values) for values in actuals.values()}
    if len(lengths) != 1:
        raise RuntimeError(f"target length mismatch: {sorted(lengths)}")
    n_obs = lengths.pop()
    if origin_eligibility is None:
        eligible = np.arange(n_obs) >= oos_start
    else:
        eligible = np.asarray(origin_eligibility, dtype=bool).copy()
        if len(eligible) != n_obs:
            raise RuntimeError("origin eligibility length mismatch")
        if eligible[:oos_start].any():
            raise RuntimeError("origin eligibility includes pre-OOS observations")
    for values in actuals.values():
        invalid = eligible & (~np.isfinite(values) | (values <= 0))
        if invalid.any():
            raise RuntimeError("origin eligibility contains invalid target values")
    if int(eligible.sum()) < 252:
        raise RuntimeError(f"common positive-target OOS ledger too short: {int(eligible.sum())}")

    for target_name, forecasts in forecasts_by_target.items():
        if set(forecasts) != set(MODEL_NAMES):
            raise RuntimeError(f"unexpected model set for {target_name}: {sorted(forecasts)}")
        for model_name, values in forecasts.items():
            if len(values) != n_obs:
                raise RuntimeError(
                    f"forecast length mismatch for {target_name}/{model_name}: {len(values)} != {n_obs}"
                )
            invalid = eligible & (~np.isfinite(values) | (values <= 0))
            if invalid.any():
                positions = np.flatnonzero(invalid)
                raise RuntimeError(
                    f"forecast coverage failure for {target_name}/{model_name}: "
                    f"{len(positions)} eligible origins, first={positions[:5].tolist()}"
                )
    return eligible


def build_origin_eligibility_mask(
    actuals: dict[str, np.ndarray],
    raw_forecasts: dict[str, np.ndarray],
    oos_start: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Predeclare origins evaluable from targets and lagged model information."""
    lengths = {len(values) for values in [*actuals.values(), *raw_forecasts.values()]}
    if len(lengths) != 1:
        raise RuntimeError(f"origin eligibility length mismatch: {sorted(lengths)}")
    n_obs = lengths.pop()
    oos = np.arange(n_obs) >= oos_start
    target_valid = np.ones(n_obs, dtype=bool)
    for values in actuals.values():
        target_valid &= np.isfinite(values) & (values > 0)
    forecast_valid_by_model = {
        name: np.isfinite(values) & (values > 0)
        for name, values in raw_forecasts.items()
    }
    forecast_valid = np.ones(n_obs, dtype=bool)
    for values in forecast_valid_by_model.values():
        forecast_valid &= values
    eligible = oos & target_valid & forecast_valid
    if int(eligible.sum()) < 252:
        raise RuntimeError(f"common origin eligibility too short: {int(eligible.sum())}")
    audit = {
        "oos_candidates": int(oos.sum()),
        "eligible": int(eligible.sum()),
        "excluded_invalid_target": int((oos & ~target_valid).sum()),
        "excluded_unavailable_raw_forecast_by_model": {
            name: int((oos & ~values).sum())
            for name, values in forecast_valid_by_model.items()
        },
        "policy": (
            "predeclare the intersection of positive observed targets and raw one-step "
            "forecasts available from lagged information; any calibrated forecast gap "
            "inside this frozen set fails closed"
        ),
    }
    return eligible, audit


def evaluate_target(
    actual: np.ndarray,
    forecasts: dict[str, np.ndarray],
    evaluation_mask: np.ndarray,
) -> dict[str, Any]:
    if len(evaluation_mask) != len(actual):
        raise RuntimeError("evaluation mask length mismatch")
    mask = np.asarray(evaluation_mask, dtype=bool)
    if not mask.any():
        raise RuntimeError("evaluation mask is empty")
    if (~np.isfinite(actual[mask]) | (actual[mask] <= 0)).any():
        raise RuntimeError("evaluation ledger contains invalid target values")
    for name, values in forecasts.items():
        if len(values) != len(actual):
            raise RuntimeError(f"forecast length mismatch for {name}")
        if (~np.isfinite(values[mask]) | (values[mask] <= 0)).any():
            raise RuntimeError(f"evaluation ledger contains invalid forecasts for {name}")

    y = actual[mask]
    model_fc = {name: values[mask] for name, values in forecasts.items()}
    losses = {name: qlike_pointwise(y, values) for name, values in model_fc.items()}
    metrics = {}
    for name, values in model_fc.items():
        rho, rho_p = spearman_corr(y, values)
        metrics[name] = {
            "qlike": qlike(y, values),
            "mse": float(np.mean(np.square(y - values))),
            "spearman_rho": rho,
            "spearman_p": rho_p,
        }
    ranking = sorted(MODEL_NAMES, key=lambda name: metrics[name]["qlike"])
    dm = {}
    for left_pos, left in enumerate(MODEL_NAMES):
        for right in MODEL_NAMES[left_pos + 1 :]:
            t_stat, p_value = dm_test(losses[left], losses[right], h=1)
            dm[f"{left}_vs_{right}"] = {
                "t_stat": t_stat,
                "p_value": p_value,
                "sign_convention": "negative favors first model",
                "harvey_abs_t_gt_3": abs(t_stat) > 3.0,
            }
    mcs = model_confidence_set(losses, alpha=0.10, n_boot=1000, seed=SEED)
    mcs["eliminated"] = [list(item) for item in mcs["eliminated"]]
    return {
        "n_oos": int(mask.sum()),
        "metrics": metrics,
        "ranking_qlike": ranking,
        "dm_newey_west_hac": dm,
        "mcs_alpha_0_10_1000_stationary_bootstrap": mcs,
    }


def data_diagnostics(frame: pd.DataFrame) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "n_days": int(len(frame)),
        "date_start": frame["date"].min().date().isoformat(),
        "date_end": frame["date"].max().date().isoformat(),
        "roll_days": int(frame["active_contract"].ne(frame["active_contract"].shift()).sum() - 1),
        "proxy_summary": {},
        "log_proxy_correlation": {},
    }
    for column in PROXY_COLUMNS:
        series = frame[column]
        diagnostics["proxy_summary"][column] = {
            "mean": float(series.mean()),
            "median": float(series.median()),
            "std": float(series.std()),
            "skew": float(stats.skew(series, nan_policy="omit")),
            "kurtosis_excess": float(stats.kurtosis(series, nan_policy="omit")),
            "nonpositive": int((series <= 0).sum()),
        }
    positive_proxies = frame[PROXY_COLUMNS].where(frame[PROXY_COLUMNS] > 0)
    corr = np.log(positive_proxies).corr(method="spearman")
    diagnostics["log_proxy_correlation"] = {
        row: {column: float(value) for column, value in values.items()}
        for row, values in corr.to_dict(orient="index").items()
    }
    return diagnostics


def infer_verdict(targets: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    raw_winners = {name: targets[name]["ranking_qlike"][0] for name in PROXY_COLUMNS}
    composite_winner = targets["consensus_weighted"]["ranking_qlike"][0]
    unique_raw = sorted(set(raw_winners.values()))
    rank_vectors = {
        name: [targets[name]["ranking_qlike"].index(model) + 1 for model in MODEL_NAMES]
        for name in [*PROXY_COLUMNS, "consensus_weighted"]
    }
    composite_vector = rank_vectors["consensus_weighted"]
    rank_rho = {}
    for name in PROXY_COLUMNS:
        rho, _ = stats.spearmanr(rank_vectors[name], composite_vector)
        rank_rho[name] = float(rho)

    singleton_mcs_winners = {}
    for name in [*PROXY_COLUMNS, "consensus_weighted"]:
        members = targets[name]["mcs_alpha_0_10_1000_stationary_bootstrap"]["mcs_models"]
        singleton_mcs_winners[name] = members[0] if len(members) == 1 else None
    identified = {winner for winner in singleton_mcs_winners.values() if winner is not None}

    if (
        len(unique_raw) == 1
        and unique_raw[0] == composite_winner
        and len(identified) == 1
        and all(winner == unique_raw[0] for winner in singleton_mcs_winners.values())
    ):
        verdict = "PROXY_ROBUST_STATISTICAL_RANKING"
    elif len(identified) > 1:
        verdict = "PROXY_DEPENDENT_STATISTICAL_RANKING"
    else:
        verdict = "INCONCLUSIVE_RANKING_SENSITIVITY"
    return verdict, {
        "raw_proxy_winners": raw_winners,
        "unique_raw_winners": unique_raw,
        "composite_winner": composite_winner,
        "spearman_rank_vs_composite": rank_rho,
        "singleton_mcs_winners": singleton_mcs_winners,
        "rule": (
            "robust iff every raw/consensus point winner and singleton MCS winner agrees; "
            "proxy-dependent iff at least two targets have distinct singleton MCS winners; "
            "otherwise inconclusive"
        ),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    np.random.seed(SEED)
    experiment_dir = Path(__file__).resolve().parent
    cache_path = args.proxy_cache or experiment_dir / "K1704_daily_proxies.csv"
    results_path = args.results or experiment_dir / "K1704_results.json"

    if args.rebuild_proxies or not cache_path.exists():
        frame, source_audit = build_proxy_cache(
            args.source_dir, args.canonical_rv, cache_path, args.workers
        )
    else:
        frame, source_audit = load_proxy_cache(cache_path, args.canonical_rv, args.source_dir)
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date").reset_index(drop=True)
    for column in [*PROXY_COLUMNS, "day_return"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if len(frame) < args.oos_start + 252:
        raise RuntimeError("insufficient observations for >=252-day OOS evaluation")

    forecast_start = args.oos_start - args.calibration_window
    if forecast_start < 500:
        raise RuntimeError("oos-start must leave >=500 observations before forecast calibration")
    raw_forecasts = {
        "HAR_RV5": har_forecasts(frame, forecast_start, args.train_window),
        "EWMA_R2": ewma_forecasts(frame),
    }
    raw_forecasts["GJR_GARCH"], gjr_audit = gjr_forecasts(
        frame, forecast_start, args.train_window, args.refit_every
    )
    composite, weights, biases = point_in_time_composite(
        frame, forecast_start, args.calibration_window
    )

    actuals: dict[str, np.ndarray] = {
        name: frame[name].to_numpy(dtype=float) for name in PROXY_COLUMNS
    }
    actuals["consensus_weighted"] = composite
    forecasts_by_target: dict[str, dict[str, np.ndarray]] = {}
    scale_calibration: dict[str, Any] = {}
    for name in PROXY_COLUMNS:
        forecasts, scale_audit = calibrate_forecasts_to_target(
            actuals[name], raw_forecasts, args.oos_start, args.calibration_window
        )
        forecasts_by_target[name] = forecasts
        scale_calibration[name] = scale_audit
    consensus_forecasts, consensus_scale_audit = calibrate_forecasts_to_target(
        composite, raw_forecasts, args.oos_start, args.calibration_window
    )
    forecasts_by_target["consensus_weighted"] = consensus_forecasts
    scale_calibration["consensus_weighted"] = consensus_scale_audit

    origin_eligibility, origin_eligibility_audit = build_origin_eligibility_mask(
        actuals, raw_forecasts, args.oos_start
    )
    common_mask = build_common_evaluation_mask(
        actuals,
        forecasts_by_target,
        args.oos_start,
        origin_eligibility=origin_eligibility,
    )
    common_dates = frame.loc[common_mask, "date"].dt.date.astype(str).tolist()
    common_ledger_hash = hashlib.sha256(
        "\n".join(common_dates).encode()
    ).hexdigest()
    targets: dict[str, dict[str, Any]] = {
        name: evaluate_target(actuals[name], forecasts_by_target[name], common_mask)
        for name in [*PROXY_COLUMNS, "consensus_weighted"]
    }

    verdict, sensitivity = infer_verdict(targets)
    weight_valid = weights.dropna()
    bias_valid = biases.dropna()
    midpoint = args.oos_start + (len(frame) - args.oos_start) // 2
    split_results = {}
    for label, slc in {
        "early_oos": slice(args.oos_start, midpoint),
        "late_oos": slice(midpoint, len(frame)),
    }.items():
        split_results[label] = {
            "date_start": frame["date"].iloc[slc.start].date().isoformat(),
            "date_end": frame["date"].iloc[slc.stop - 1].date().isoformat(),
            "consensus_target": evaluate_target(
                composite[slc],
                {k: v[slc] for k, v in consensus_forecasts.items()},
                common_mask[slc],
            ),
        }

    results: dict[str, Any] = {
        "experiment_id": "K1704",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "methodology_type": "empirical forecast-comparison diagnostic",
        "verdict": verdict,
        "data": {
            "source": "local TAIFEX all-contract TX daily tick archive",
            "contract_rule": "completed-day highest-total-volume monthly TX contract",
            "session": "homogeneous day session 08:45-13:45; no cross-session/roll returns",
            "canonical_rv_path": str(args.canonical_rv),
            "source_dir": str(args.source_dir),
            "proxy_cache": str(cache_path),
            "source_audit": source_audit,
            "diagnostics": data_diagnostics(frame),
        },
        "design": {
            "oos_start_index": args.oos_start,
            "oos_start_date": frame["date"].iloc[args.oos_start].date().isoformat(),
            "oos_end_date": frame["date"].iloc[-1].date().isoformat(),
            "common_evaluation_n": int(common_mask.sum()),
            "common_evaluation_date_start": common_dates[0],
            "common_evaluation_date_end": common_dates[-1],
            "common_evaluation_date_sha256": common_ledger_hash,
            "common_evaluation_dates": common_dates,
            "origin_eligibility": origin_eligibility_audit,
            "train_window": args.train_window,
            "calibration_window": args.calibration_window,
            "forecast_horizon_days": 1,
            "lookahead_policy": (
                "HAR features and EWMA use explicit shift(1); GJR at origin t is fit/filtered "
                "only through return t-1; composite bias and weights use [t-window,t) only"
            ),
            "proxy_bias_method": (
                "past-window mean log deviation from a leave-one-proxy-out same-day median"
            ),
            "proxy_weight_method": (
                "consensus heuristic: inverse past-window residual log-MSE around cross-proxy median"
            ),
            "model_scale_calibration": (
                "for each target and origin, multiply each raw model forecast by the past-window "
                "geometric mean actual/forecast ratio; >=252 prior valid pairs required"
            ),
            "qlike": "actual/predicted - log(actual/predicted) - 1",
            "dm": "repo canonical Newey-West HAC DM, h=1, automatic bandwidth; Harvey |t|>3 screen",
            "mcs": "HLN stationary-bootstrap MCS alpha=0.10, 1000 reps, seed=42",
            "gjr": gjr_audit,
        },
        "point_in_time_consensus_calibration": {
            "n_origins": int(len(weight_valid)),
            "mean_weights": {k: float(v) for k, v in weight_valid.mean().items()},
            "min_weights": {k: float(v) for k, v in weight_valid.min().items()},
            "max_weights": {k: float(v) for k, v in weight_valid.max().items()},
            "mean_log_biases": {k: float(v) for k, v in bias_valid.mean().items()},
        },
        "point_in_time_model_scale_calibration": scale_calibration,
        "targets": targets,
        "ranking_sensitivity": sensitivity,
        "split_oos_robustness": split_results,
        "references": [
            "Corsi (2009), Journal of Financial Econometrics 7, 174-196, doi:10.1093/jjfinec/nbp001",
            "Hansen and Lunde (2006), JBES 24, 127-161, doi:10.1198/073500106000000071",
            "Patton (2011), Journal of Econometrics 160, 246-256, doi:10.1016/j.jeconom.2010.03.034",
            "Hansen, Lunde and Nason (2011), Econometrica 79, 453-497, doi:10.3982/ECTA5771",
            "Liu, Patton and Sheppard (2015), Journal of Econometrics 187, 293-311, doi:10.1016/j.jeconom.2015.02.008",
        ],
        "prior_knowledge": [
            "K1057: rankings flip across RV and r-squared native targets, motivating a common multi-target ledger",
            "K1072: 5-minute RV was practically close to noise-robust alternatives in a short SPY sample",
            "Patton2011-proxy-robust: robust loss still requires a conditionally unbiased proxy",
        ],
        "limitations": [
            "The consensus weights are a heuristic, not identified optimal measurement-error weights; latent integrated variance remains unobserved.",
            "Leave-one-proxy-out residual centres remove direct self-inclusion, but 1/5/10-minute RV share ticks and correlated measurement errors remain unidentified.",
            "Same-day maximum-volume contract selection is valid for end-of-day measurement, not intraday trading.",
            "Only the homogeneous TX day session is studied; night-session conclusions do not follow.",
            "Parkinson and squared-return proxies retain jump, drift, and microstructure assumptions.",
            "MCS uses 1000 bootstrap draws; sufficient for the preregistered diagnostic but not ultra-tail p-values.",
        ],
    }
    atomic_json_dump(results, results_path)
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path.home() / "Dropbox" / "TAIFEXDATA" / "TAIFEXDATA" / "python",
    )
    parser.add_argument(
        "--canonical-rv",
        type=Path,
        default=ROOT / "data" / "intraday" / "taifex_5min_rv.csv",
    )
    parser.add_argument("--proxy-cache", type=Path)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--rebuild-proxies", action="store_true")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--oos-start", type=int, default=1500)
    parser.add_argument("--train-window", type=int, default=1500)
    parser.add_argument("--calibration-window", type=int, default=500)
    parser.add_argument("--refit-every", type=int, default=21)
    return parser.parse_args()


if __name__ == "__main__":
    output = run(parse_args())
    print(json.dumps({
        "experiment_id": output["experiment_id"],
        "verdict": output["verdict"],
        "n_days": output["data"]["diagnostics"]["n_days"],
        "oos": [output["design"]["oos_start_date"], output["design"]["oos_end_date"]],
        "ranking_sensitivity": output["ranking_sensitivity"],
    }, ensure_ascii=False, indent=2))
