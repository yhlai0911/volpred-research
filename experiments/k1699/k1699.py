#!/usr/bin/env python3
"""K1699: six-market close-convention horserace for the PRG dual-timing narrative.

PRG deep review 2026-07-11 (paper/prg-periodic-garch/review_history/
fable_deep_review_20260711/README.md, P0-2 / K-new-A) requires the last piece
of evidence for the dual forecast-timing-convention framework:

    Close convention (strict t-1 day-ahead, all information in F^c_{d-1}):
        PRG_tminus1 full-day forecast = h_ov_hat + h_in_hat(h_ov_hat)
        vs daily GJR(1,1) one-step-ahead
        vs HAR on log(sigma2_fullday) one-step-ahead

Existing evidence is SPY-only (K880v2 DM -0.57; K880 rerun PRG_Extended_tminus1
DM -1.48). This experiment generalises to the six K1544 markets:
SPY, QQQ, GLD, EEM, 0050.TW, TAIFEX.

Two close-convention PRG variants are reported:

- PRG_tminus1_exp (PRIMARY, review-spec h_in(h_ov)): the intraday equation's
  unobserved overnight shock r2_ov[t] is replaced by its model-consistent
  conditional expectation h_ov_hat_t, and the leverage indicator by its
  symmetric-innovation expectation 1/2:
      h_in = omega1 + (alpha1 + 0.5*gamma1) * h_ov_hat + beta1 * h_ov_hat
- PRG_tminus1_lag (robustness, replicates the K880-rerun variant): the
  intraday equation is fed the lagged realized overnight (r2_ov[t-1]):
      h_in = omega1 + alpha1*r2_ov[t-1] + gamma1*r2_ov[t-1]*I(r_ov[t-1]<0)
             + beta1 * h_ov_hat

Both variants use only information available at the day d-1 close. Estimation
(expanding window, refit cadence identical to K1544) also only uses data
strictly before the forecast origin.

Canonical mixed-timing PRG (h_ov_hat + h_in(realized r2_ov[t])) is computed as
a DIAGNOSTIC anchor only, to cross-check against K1544/K880 levels; it is not
part of the close-convention headline.

Methodology hard rules honoured (.claude/rules/experiments.md):
- QLIKE: canonical volpred.stats.model_evaluation.qlike_pointwise
  (actual/predicted orientation).
- DM: canonical volpred.stats.model_evaluation.dm_test (Newey-West HAC,
  bandwidth ceil(h^(1/3) n^(1/3)), h=1). No local h-1 lag reimplementation.
- Loss-differential acf(1) is reported per DM cell, plus a 2x-bandwidth
  Newey-West sensitivity t-stat (labelled sensitivity-only; canonical dm_test
  remains the primary inference).
- Data snapshots are pinned to experiments/k1699/data/*.csv with SHA256
  recorded in the results JSON; reruns read the snapshot, not live yfinance.
- Fixed seed (1699); module estimators additionally use internal
  RandomState(42) multistarts, so fits are deterministic.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import multiprocessing as mp
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

EXPERIMENT_ID = "k1699"
ROOT = Path(__file__).resolve().parents[2]
EXP_DIR = Path(__file__).resolve().parent
DATA_DIR = EXP_DIR / "data"

if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from volpred.stats.model_evaluation import dm_test, qlike_pointwise  # noqa: E402

RNG_SEED = 1699
GJR_HAR_REFIT_FREQ_DAYS = 63


# ---------------------------------------------------------------- module load

def _load_module(abs_path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, abs_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {abs_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- snapshots

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_or_snapshot_ohlc(market: str, loader) -> tuple[pd.DataFrame, dict[str, str]]:
    """Pin the loaded OHLC/session dataframe to a CSV snapshot.

    First run fetches via the module loader and writes the snapshot; reruns
    read the snapshot so results are reproducible without live yfinance.
    """
    path = DATA_DIR / f"{market.replace('.', '_')}_snapshot.csv"
    if path.exists():
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        origin = "snapshot"
    else:
        df = loader()
        df.to_csv(path)
        origin = "fetched_then_pinned"
    return df, {"file": str(path.relative_to(ROOT)), "sha256": _sha256(path), "origin": origin}


def load_or_snapshot_taifex(k883) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    sess_path = DATA_DIR / "TAIFEX_sessions_snapshot.csv"
    daily_path = DATA_DIR / "TAIFEX_daily_snapshot.csv"
    if sess_path.exists() and daily_path.exists():
        sess_df = pd.read_csv(sess_path, index_col=0)
        daily_df = pd.read_csv(daily_path, index_col=0, parse_dates=True)
        origin = "snapshot"
    else:
        rv_df = k883.load_all_rv_data()
        sess_df, daily_df = k883.build_session_series(rv_df)
        sess_df.to_csv(sess_path)
        daily_df.to_csv(daily_path)
        origin = "built_from_ticks_then_pinned"
    meta = {
        "sessions": {"file": str(sess_path.relative_to(ROOT)), "sha256": _sha256(sess_path)},
        "daily": {"file": str(daily_path.relative_to(ROOT)), "sha256": _sha256(daily_path)},
        "origin": origin,
    }
    return sess_df, daily_df, meta


# ------------------------------------------------- PRG close-convention loop

def prg_close_convention_forecasts(
    module: Any,
    r_overnight: np.ndarray,
    r_intra: np.ndarray,
    r2_overnight: np.ndarray,
    r2_intra: np.ndarray,
    is_end: int,
    *,
    refit_freq: int,
) -> dict[str, np.ndarray]:
    """Expanding-window PRG Extended forecasts under three conventions.

    Returns canonical (mixed-timing diagnostic), tminus1_exp (primary
    close-convention), tminus1_lag (K880-rerun-style robustness). Parameter
    ordering across k880/k881/k886 modules is [o0,a0,b0,o1,a1,b1,g0,g1].
    """
    n_days = len(r_overnight)
    canonical = np.full(n_days, np.nan)
    tm1_exp = np.full(n_days, np.nan)
    tm1_lag = np.full(n_days, np.nan)

    estimator = getattr(module, "estimate_prg_spy", None) or getattr(module, "estimate_prg")
    n_starts = int(getattr(module, "PRG_N_STARTS", 3))
    has_forecast_day = hasattr(module, "_prg_forecast_day")  # k881/k886 family

    current_params: np.ndarray | None = None
    h_state: float | None = None

    def _forecast_variants(p: np.ndarray, h_after_intra_prev: float, t: int) -> tuple[float, float, float]:
        o0, a0, b0, o1, a1, b1, g0, g1 = (float(v) for v in p[:8])
        lev0 = g0 * r2_intra[t - 1] * (1.0 if r_intra[t - 1] < 0.0 else 0.0)
        h_ov = o0 + a0 * r2_intra[t - 1] + lev0 + b0 * h_after_intra_prev
        if h_ov < 1e-12:
            h_ov = 1e-12

        # canonical mixed-timing: realized current overnight feeds intraday eq
        lev1 = g1 * r2_overnight[t] * (1.0 if r_overnight[t] < 0.0 else 0.0)
        h_in_c = o1 + a1 * r2_overnight[t] + lev1 + b1 * h_ov
        if h_in_c < 1e-12:
            h_in_c = 1e-12

        # close-convention primary: expectation plug-in E[r2_ov]=h_ov,
        # E[r2_ov * I(r_ov<0)] = h_ov/2 under symmetric zero-mean innovation
        h_in_e = o1 + (a1 + 0.5 * g1) * h_ov + b1 * h_ov
        if h_in_e < 1e-12:
            h_in_e = 1e-12

        # close-convention robustness: lagged realized overnight plug-in
        lev1l = g1 * r2_overnight[t - 1] * (1.0 if r_overnight[t - 1] < 0.0 else 0.0)
        h_in_l = o1 + a1 * r2_overnight[t - 1] + lev1l + b1 * h_ov
        if h_in_l < 1e-12:
            h_in_l = 1e-12

        return h_ov + h_in_c, h_ov + h_in_e, h_ov + h_in_l

    if has_forecast_day:
        # k881/k886 family: state kept as h after intraday of day t-1
        for t in range(is_end, n_days):
            if (t - is_end) % refit_freq == 0 or t == is_end:
                params, _ll = estimator(
                    r_overnight[:t], r_intra[:t], r2_overnight[:t], r2_intra[:t],
                    extended=True, n_starts=n_starts,
                )
                if params is not None:
                    current_params = params
                    h_state = module._prg_propagate_full(
                        *(float(v) for v in current_params[:8]),
                        r_overnight[:t], r_intra[:t], r2_overnight[:t], r2_intra[:t], t,
                    )

            if current_params is None or h_state is None:
                continue

            if (t - is_end) % refit_freq != 0 and t != is_end:
                d = t - 1
                x_prev = r2_intra[d - 1] if d > 0 else r2_overnight[0]
                r_prev = r_intra[d - 1] if d > 0 else r_overnight[0]
                h_state = module._prg_propagate_one_day(
                    *(float(v) for v in current_params[:8]),
                    h_state, x_prev, r_prev, r2_overnight[d], r_overnight[d],
                )

            canonical[t], tm1_exp[t], tm1_lag[t] = _forecast_variants(current_params, h_state, t)
        return {"canonical": canonical, "tminus1_exp": tm1_exp, "tminus1_lag": tm1_lag}

    # k880 family: state rebuilt/propagated via _prg_propagate_days_numba
    for t in range(is_end, n_days):
        if (t - is_end) % refit_freq == 0 or t == is_end:
            params, _ll = estimator(
                r_overnight[:t], r_intra[:t], r2_overnight[:t], r2_intra[:t],
                extended=True, n_starts=n_starts,
            )
            if params is not None:
                current_params = params
                o0, a0, b0, o1, a1, b1, g0, g1 = (float(v) for v in current_params[:8])
                h_init = np.mean(r2_overnight[: min(50, t)] + r2_intra[: min(50, t)]) / 2.0
                if h_init < 1e-12:
                    h_init = 1e-8
                h_state = module._prg_propagate_days_numba(
                    o0, a0, b0, g0, o1, a1, b1, g1,
                    r_overnight, r_intra, r2_overnight, r2_intra, 0, t, h_init,
                )

        if current_params is None or h_state is None:
            continue

        canonical[t], tm1_exp[t], tm1_lag[t] = _forecast_variants(current_params, h_state, t)

        o0, a0, b0, o1, a1, b1, g0, g1 = (float(v) for v in current_params[:8])
        h_state = module._prg_propagate_days_numba(
            o0, a0, b0, g0, o1, a1, b1, g1,
            r_overnight, r_intra, r2_overnight, r2_intra, t, t + 1, h_state,
        )

    return {"canonical": canonical, "tminus1_exp": tm1_exp, "tminus1_lag": tm1_lag}


def taifex_close_convention_forecasts(
    k883: Any,
    sess_df: pd.DataFrame,
    daily_df: pd.DataFrame,
) -> tuple[dict[str, np.ndarray], int]:
    """TAIFEX session-level PRG Extended under the three conventions.

    Session recursion follows K1544's taifex path (h_all[t] is F_{t-1}
    measurable); the day-d overnight session index is 2d, intraday 2d+1.
    """
    r_arr = sess_df["r"].values.astype(np.float64)
    x_arr = sess_df["x"].values.astype(np.float64)
    s_arr = sess_df["session_type"].values.astype(np.float64)
    n_sessions = len(sess_df)
    n_days = len(daily_df)
    is_end_sess = int(n_sessions * k883.IS_FRACTION)
    if is_end_sess % 2 != 0:
        is_end_sess += 1
    is_end_days = is_end_sess // 2

    params, _ll = k883.estimate_prg(
        r_arr[:is_end_sess], x_arr[:is_end_sess], s_arr[:is_end_sess],
        extended=True, n_starts=5,
    )
    nan_out = {
        "canonical": np.full(n_days, np.nan),
        "tminus1_exp": np.full(n_days, np.nan),
        "tminus1_lag": np.full(n_days, np.nan),
    }
    if params is None:
        return nan_out, is_end_days

    h_all = np.full(n_sessions, np.nan)
    params_at_session: list[np.ndarray | None] = [None] * n_sessions
    current_params = params.copy()
    h_full = k883.prg_recursive_oos(current_params, r_arr, x_arr, s_arr, extended=True)
    h_all[:is_end_sess] = h_full[:is_end_sess]

    for t in range(is_end_sess, n_sessions):
        if (t - is_end_sess) % k883.REFIT_FREQ == 0:
            p_new, _ll_new = k883.estimate_prg(
                r_arr[:t], x_arr[:t], s_arr[:t], extended=True, n_starts=3,
            )
            if p_new is not None:
                current_params = p_new
            h_full = k883.prg_recursive_oos(
                current_params, r_arr[: t + 1], x_arr[: t + 1], s_arr[: t + 1], extended=True,
            )
            h_all[t] = h_full[t]
        else:
            st = int(s_arr[t])
            omega = (float(current_params[0]), float(current_params[3]))
            alpha = (float(current_params[1]), float(current_params[4]))
            beta = (float(current_params[2]), float(current_params[5]))
            gamma = (float(current_params[6]), float(current_params[7]))
            h_prev = h_all[t - 1] if np.isfinite(h_all[t - 1]) else 1e-8
            lev = gamma[st] * x_arr[t - 1] * (1.0 if r_arr[t - 1] < 0.0 else 0.0)
            h_all[t] = omega[st] + alpha[st] * x_arr[t - 1] + lev + beta[st] * h_prev
            if h_all[t] < 1e-12:
                h_all[t] = 1e-12
        params_at_session[t] = np.asarray(current_params, dtype=np.float64).copy()

    out = nan_out
    x_overnight_daily = daily_df["x_overnight"].values.astype(np.float64)
    for d in range(is_end_days, n_days):
        i_ov = 2 * d
        i_in = 2 * d + 1
        if i_in >= n_sessions:
            continue
        p = params_at_session[i_ov]
        if p is None or not np.isfinite(h_all[i_ov]):
            continue
        o1, a1, b1, g1 = float(p[3]), float(p[4]), float(p[5]), float(p[7])
        h_ov = float(h_all[i_ov])

        # canonical mixed-timing diagnostic: realized overnight session shock
        lev1 = g1 * x_arr[i_ov] * (1.0 if r_arr[i_ov] < 0.0 else 0.0)
        h_in_c = o1 + a1 * x_arr[i_ov] + lev1 + b1 * h_ov
        out["canonical"][d] = h_ov + max(h_in_c, 1e-12)

        # primary close-convention: expectation plug-in
        h_in_e = o1 + (a1 + 0.5 * g1) * h_ov + b1 * h_ov
        out["tminus1_exp"][d] = h_ov + max(h_in_e, 1e-12)

        # robustness: lagged realized overnight (previous day's ON session)
        i_ov_prev = i_ov - 2
        lev1l = g1 * x_arr[i_ov_prev] * (1.0 if r_arr[i_ov_prev] < 0.0 else 0.0)
        h_in_l = o1 + a1 * x_arr[i_ov_prev] + lev1l + b1 * h_ov
        out["tminus1_lag"][d] = h_ov + max(h_in_l, 1e-12)

    _ = x_overnight_daily  # kept for parity with K1544 taifex path; not used here
    return out, is_end_days


# ---------------------------------------------------------------- evaluation

def _acf1(d: np.ndarray) -> float:
    d = d[np.isfinite(d)]
    if len(d) < 3:
        return math.nan
    c = d - d.mean()
    denom = float(np.sum(c * c))
    if denom <= 0:
        return math.nan
    return float(np.sum(c[1:] * c[:-1]) / denom)


def _nw_tstat_sensitivity(d: np.ndarray, max_lag: int) -> float:
    """Bartlett-kernel HAC t-stat at an explicit bandwidth.

    Sensitivity-only companion to the canonical dm_test (which fixes bandwidth
    at ceil(h^(1/3) n^(1/3))); reported here at 2x canonical bandwidth.
    """
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return math.nan
    max_lag = int(min(max_lag, n // 4))
    d_mean = float(np.mean(d))
    c = d - d_mean
    var_d = float(np.mean(c * c))
    for lag in range(1, max_lag + 1):
        weight = 1.0 - lag / (max_lag + 1.0)
        var_d += 2.0 * weight * float(np.mean(c[lag:] * c[:-lag]))
    if var_d <= 0:
        return math.nan
    se = math.sqrt(var_d / n)
    if se < 1e-15:
        return math.nan
    return d_mean / se


def dm_cell(loss_a: np.ndarray, loss_b: np.ndarray, label_a: str, label_b: str) -> dict[str, Any]:
    """Canonical DM cell. Negative t means model A (first) has lower loss."""
    t_stat, p_val = dm_test(loss_a, loss_b, h=1)
    d = loss_a - loss_b
    n = int(np.isfinite(d).sum())
    bw_canonical = max(1, min(int(np.ceil(n ** (1.0 / 3.0))), n // 4)) if n else 0
    t_2x = _nw_tstat_sensitivity(d, 2 * bw_canonical) if n else math.nan
    return {
        "pair": f"{label_a}_vs_{label_b}",
        "t_stat": float(t_stat),
        "p_value": float(p_val),
        "n": n,
        "orientation": f"negative t means {label_a} loss < {label_b} loss ({label_a} better)",
        "harvey_pass_abs_t_gt_3": bool(np.isfinite(t_stat) and abs(t_stat) > 3.0),
        "loss_diff_acf1": _acf1(d),
        "hac_bandwidth_canonical": bw_canonical,
        "t_stat_2x_bandwidth_sensitivity": float(t_2x) if np.isfinite(t_2x) else None,
        "mean_loss_diff": float(np.nanmean(d)) if n else None,
    }


def evaluate_market(
    market: str,
    target: np.ndarray,
    forecasts: dict[str, np.ndarray],
    is_end: int,
    dates: pd.Index,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    headline_models = ["PRG_tminus1_exp", "PRG_tminus1_lag", "GJR", "HAR"]
    all_models = headline_models + ["PRG_canonical_diag"]

    target_oos = np.asarray(target[is_end:], dtype=np.float64)
    oos = {m: np.asarray(forecasts[m][is_end:], dtype=np.float64) for m in all_models}
    dates_oos = dates[is_end:]

    common = np.isfinite(target_oos) & (target_oos > 0)
    for m in all_models:
        common &= np.isfinite(oos[m]) & (oos[m] > 0)

    losses = {m: qlike_pointwise(target_oos[common], oos[m][common]) for m in all_models}
    qlike = {m: float(np.mean(losses[m])) for m in all_models}
    ranked = sorted(headline_models, key=lambda m: qlike[m])

    dm_cells = [
        dm_cell(losses["PRG_tminus1_exp"], losses["GJR"], "PRG_tminus1_exp", "GJR"),
        dm_cell(losses["PRG_tminus1_exp"], losses["HAR"], "PRG_tminus1_exp", "HAR"),
        dm_cell(losses["PRG_tminus1_lag"], losses["GJR"], "PRG_tminus1_lag", "GJR"),
        dm_cell(losses["PRG_tminus1_lag"], losses["HAR"], "PRG_tminus1_lag", "HAR"),
        dm_cell(losses["GJR"], losses["HAR"], "GJR", "HAR"),
    ]

    return {
        "market": market,
        "metadata": metadata,
        "oos_period": {
            "start": str(pd.Timestamp(dates_oos[0]).date()) if len(dates_oos) else None,
            "end": str(pd.Timestamp(dates_oos[-1]).date()) if len(dates_oos) else None,
            "n_oos": int(len(dates_oos)),
            "n_common_valid": int(common.sum()),
        },
        "qlike": qlike,
        "qlike_ranking_close_convention": ranked,
        "close_convention_winner": ranked[0],
        "dm_tests": {c["pair"]: c for c in dm_cells},
        "forecast_diagnostics": {
            m: {"valid_oos": int(np.isfinite(oos[m]).sum())} for m in all_models
        },
    }


# ---------------------------------------------------------------- reporting

def _json_clean(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_clean(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        val = float(obj)
        return val if math.isfinite(val) else None
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    return obj


def write_tables(results: dict[str, Any]) -> None:
    rows = []
    for market, r in results["markets"].items():
        dm = r["dm_tests"]
        rows.append({
            "market": market,
            "n_common_valid": r["oos_period"]["n_common_valid"],
            "oos_start": r["oos_period"]["start"],
            "oos_end": r["oos_period"]["end"],
            "qlike_prg_tminus1_exp": r["qlike"]["PRG_tminus1_exp"],
            "qlike_prg_tminus1_lag": r["qlike"]["PRG_tminus1_lag"],
            "qlike_gjr": r["qlike"]["GJR"],
            "qlike_har": r["qlike"]["HAR"],
            "qlike_prg_canonical_diag": r["qlike"]["PRG_canonical_diag"],
            "dm_t_exp_vs_gjr": dm["PRG_tminus1_exp_vs_GJR"]["t_stat"],
            "dm_p_exp_vs_gjr": dm["PRG_tminus1_exp_vs_GJR"]["p_value"],
            "dm_t_exp_vs_har": dm["PRG_tminus1_exp_vs_HAR"]["t_stat"],
            "dm_t_lag_vs_gjr": dm["PRG_tminus1_lag_vs_GJR"]["t_stat"],
            "dm_t_lag_vs_har": dm["PRG_tminus1_lag_vs_HAR"]["t_stat"],
            "dm_t_gjr_vs_har": dm["GJR_vs_HAR"]["t_stat"],
            "winner": r["close_convention_winner"],
        })

    with (EXP_DIR / "per_market_table.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    with (EXP_DIR / "per_market_table.md").open("w", encoding="utf-8") as f:
        f.write("| Market | N | PRG tm1 exp | PRG tm1 lag | GJR | HAR | DM t exp-GJR | DM t exp-HAR | DM t lag-GJR | Winner |\n")
        f.write("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|\n")
        for row in rows:
            f.write(
                f"| {row['market']} | {row['n_common_valid']} | "
                f"{row['qlike_prg_tminus1_exp']:.6f} | {row['qlike_prg_tminus1_lag']:.6f} | "
                f"{row['qlike_gjr']:.6f} | {row['qlike_har']:.6f} | "
                f"{row['dm_t_exp_vs_gjr']:.3f} | {row['dm_t_exp_vs_har']:.3f} | "
                f"{row['dm_t_lag_vs_gjr']:.3f} | {row['winner']} |\n"
            )


def make_chart(results: dict[str, Any]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    markets = list(results["markets"].keys())
    x = np.arange(len(markets))
    width = 0.28

    exp_q = [results["markets"][m]["qlike"]["PRG_tminus1_exp"] for m in markets]
    gjr_q = [results["markets"][m]["qlike"]["GJR"] for m in markets]
    har_q = [results["markets"][m]["qlike"]["HAR"] for m in markets]
    t_gjr = [results["markets"][m]["dm_tests"]["PRG_tminus1_exp_vs_GJR"]["t_stat"] for m in markets]
    t_har = [results["markets"][m]["dm_tests"]["PRG_tminus1_exp_vs_HAR"]["t_stat"] for m in markets]

    fig, axes = plt.subplots(2, 1, figsize=(10, 8), constrained_layout=True)
    axes[0].bar(x - width, exp_q, width, label="PRG t-1 (exp plug-in)", color="#1f77b4")
    axes[0].bar(x, gjr_q, width, label="GJR", color="#ff7f0e")
    axes[0].bar(x + width, har_q, width, label="HAR", color="#2ca02c")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(markets)
    axes[0].set_ylabel("OOS QLIKE")
    axes[0].set_title("K1699 close convention (strict t-1): PRG_tminus1 vs GJR vs HAR")
    axes[0].legend()

    w2 = 0.38
    axes[1].bar(x - w2 / 2, t_gjr, w2, label="PRG t-1 exp vs GJR", color="#1f77b4")
    axes[1].bar(x + w2 / 2, t_har, w2, label="PRG t-1 exp vs HAR", color="#9467bd")
    for yline in (3.0, -3.0):
        axes[1].axhline(yline, color="black", linestyle="--", linewidth=1)
    axes[1].axhline(0.0, color="black", linewidth=0.8)
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(markets)
    axes[1].set_ylabel("DM t (negative favors PRG t-1)")
    axes[1].set_title("Canonical DM t-stats; dashed lines show |t| = 3 (Harvey)")
    axes[1].legend()

    fig.savefig(EXP_DIR / "fig_k1699_close_convention.png", dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------- main

def main() -> None:
    start = time.time()
    np.random.seed(RNG_SEED)
    DATA_DIR.mkdir(exist_ok=True)
    try:
        # k883 tick loading uses a process pool; fork keeps the importlib-loaded
        # module visible to workers (spawn would re-import by name and fail)
        mp.set_start_method("fork", force=True)
    except RuntimeError:
        pass

    print("=" * 72)
    print("K1699: six-market close-convention PRG_tminus1 vs GJR vs HAR")
    print("=" * 72)

    k880 = _load_module(ROOT / "experiments/k880/k880_prg_spy_validation.py", "k880_prg_ref")
    k881 = _load_module(ROOT / "paper/prg-periodic-garch/experiments/k881_prg_multi_asset.py", "k881_prg_ref")
    k886 = _load_module(ROOT / "paper/prg-periodic-garch/experiments/k886_prg_0050tw.py", "k886_prg_ref")
    k883 = _load_module(ROOT / "paper/prg-periodic-garch/experiments/k883_taifex_tick_prg.py", "k883_prg_ref")

    markets: dict[str, Any] = {}
    snapshots: dict[str, Any] = {}

    def run_ohlc(market: str, df: pd.DataFrame, module: Any, is_end: int,
                 prg_refit: int, meta: dict[str, Any]) -> dict[str, Any]:
        arr = {
            "r_overnight": df["r_overnight"].values.astype(np.float64),
            "r_intra": df["r_intra"].values.astype(np.float64),
            "r_c2c": df["r_c2c"].values.astype(np.float64),
            "r2_overnight": df["r2_overnight"].values.astype(np.float64),
            "r2_intra": df["r2_intra"].values.astype(np.float64),
            "target": df["sigma2_fullday"].values.astype(np.float64),
        }
        print(f"\n[{market}] n={len(df)}, IS={is_end}, OOS={len(df) - is_end}")
        print(f"[{market}] PRG Extended close-convention variants...")
        prg = prg_close_convention_forecasts(
            module, arr["r_overnight"], arr["r_intra"],
            arr["r2_overnight"], arr["r2_intra"], is_end, refit_freq=prg_refit,
        )
        print(f"[{market}] GJR / HAR baselines...")
        gjr_fc = module.gjr_oos_forecast(arr["r_c2c"], is_end, refit_freq=GJR_HAR_REFIT_FREQ_DAYS)
        har_fc = module.har_oos_forecast(arr["target"], is_end, refit_freq=GJR_HAR_REFIT_FREQ_DAYS)
        meta = {
            **meta,
            "n_total": int(len(df)),
            "n_is": int(is_end),
            "n_oos": int(len(df) - is_end),
            "period": f"{pd.Timestamp(df.index[0]).date()} to {pd.Timestamp(df.index[-1]).date()}",
            "overnight_variance_share_pct": float(
                np.nanmean(arr["r2_overnight"]) / np.nanmean(arr["target"]) * 100.0
            ),
            "prg_refit_freq_days": int(prg_refit),
            "gjr_har_refit_freq_days": GJR_HAR_REFIT_FREQ_DAYS,
        }
        return evaluate_market(
            market, arr["target"],
            {
                "PRG_tminus1_exp": prg["tminus1_exp"],
                "PRG_tminus1_lag": prg["tminus1_lag"],
                "PRG_canonical_diag": prg["canonical"],
                "GJR": gjr_fc,
                "HAR": har_fc,
            },
            is_end, df.index, meta,
        )

    # SPY via canonical 2026-06-13 K880 rerun module
    print("\n[SPY] loading data...")
    spy_df, snapshots["SPY"] = load_or_snapshot_ohlc("SPY", k880.load_spy_data)
    spy_is_end = int((spy_df.index <= k880.IS_END_DATE).sum())
    markets["SPY"] = run_ohlc(
        "SPY", spy_df, k880, spy_is_end, k880.PRG_REFIT_FREQ,
        {"data_source": "yfinance via experiments/k880 (canonical 2026-06-13 rerun) load_spy_data",
         "target": "sigma2_fullday = r2_overnight + r2_intra",
         "split": f"IS through {k880.IS_END_DATE}"},
    )

    for ticker, cfg in k881.ASSETS.items():
        print(f"\n[{ticker}] loading data...")
        df, snapshots[ticker] = load_or_snapshot_ohlc(
            ticker, lambda t=ticker, c=cfg: k881.load_asset_data(t, c["start"])
        )
        is_end = int(len(df) * k881.IS_FRACTION)
        markets[ticker] = run_ohlc(
            ticker, df, k881, is_end, k881.REFIT_FREQ_PRG,
            {"data_source": f"yfinance via k881 load_asset_data({ticker})",
             "description": cfg["description"],
             "target": "sigma2_fullday = r2_overnight + r2_intra",
             "split": f"{k881.IS_FRACTION:.0%} in-sample"},
        )

    print("\n[0050.TW] loading data...")
    tw_df, snapshots["0050.TW"] = load_or_snapshot_ohlc(
        "0050.TW", lambda: k886.load_0050tw_data(k886.START_DATE, k886.END_DATE)
    )
    tw_is_end = int(len(tw_df) * k886.IS_FRACTION)
    markets["0050.TW"] = run_ohlc(
        "0050.TW", tw_df, k886, tw_is_end, k886.REFIT_FREQ_PRG,
        {"data_source": "yfinance via k886 load_0050tw_data",
         "target": "sigma2_fullday = r2_overnight + r2_intra",
         "split": f"{k886.IS_FRACTION:.0%} in-sample"},
    )

    print("\n[TAIFEX] loading tick-derived RV data...")
    sess_df, daily_df, snapshots["TAIFEX"] = load_or_snapshot_taifex(k883)
    prg_tx, tx_is_end = taifex_close_convention_forecasts(k883, sess_df, daily_df)
    tx_target = daily_df["rv_fullday"].values.astype(np.float64)
    tx_returns = (daily_df["overnight_gap"].values + daily_df["day_return"].values).astype(np.float64)
    print("[TAIFEX] GJR / HAR baselines...")
    tx_gjr = k883.gjr_oos_forecast(tx_returns, tx_is_end, refit_freq=GJR_HAR_REFIT_FREQ_DAYS)
    tx_har = k883.har_oos_forecast(tx_target, tx_is_end, refit_freq=GJR_HAR_REFIT_FREQ_DAYS)
    markets["TAIFEX"] = evaluate_market(
        "TAIFEX", tx_target,
        {
            "PRG_tminus1_exp": prg_tx["tminus1_exp"],
            "PRG_tminus1_lag": prg_tx["tminus1_lag"],
            "PRG_canonical_diag": prg_tx["canonical"],
            "GJR": tx_gjr,
            "HAR": tx_har,
        },
        tx_is_end, pd.Index(daily_df.index),
        {
            "data_source": "TAIFEX TX tick files via k883 (session series pinned to snapshot)",
            "target": "rv_fullday = x_overnight + x_intraday",
            "n_total": int(len(daily_df)),
            "n_is": int(tx_is_end),
            "n_oos": int(len(daily_df) - tx_is_end),
            "period": f"{pd.Timestamp(daily_df.index[0]).date()} to {pd.Timestamp(daily_df.index[-1]).date()}",
            "overnight_variance_share_pct": float(
                np.nanmean(daily_df["x_overnight"].values) / np.nanmean(tx_target) * 100.0
            ),
            "prg_refit_freq_sessions": int(k883.REFIT_FREQ),
            "gjr_har_refit_freq_days": GJR_HAR_REFIT_FREQ_DAYS,
        },
    )

    n_prg_wins = sum(
        1 for r in markets.values() if r["close_convention_winner"].startswith("PRG_tminus1")
    )
    harvey_cells = {
        m: {
            "exp_vs_gjr": r["dm_tests"]["PRG_tminus1_exp_vs_GJR"]["harvey_pass_abs_t_gt_3"],
            "exp_vs_har": r["dm_tests"]["PRG_tminus1_exp_vs_HAR"]["harvey_pass_abs_t_gt_3"],
        }
        for m, r in markets.items()
    }

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Six-market close-convention (strict t-1) horserace: PRG_tminus1 vs GJR vs HAR",
        "created_at": pd.Timestamp.utcnow().isoformat(),
        "random_seed": RNG_SEED,
        "research_question": (
            "Under the strict close-time convention (all forecast inputs in F^c_{d-1}), "
            "does PRG retain any advantage over daily GJR and HAR across the six K1544 "
            "markets, or is the canonical PRG headline advantage entirely a "
            "forecast-timing artifact?"
        ),
        "method_summary": {
            "close_convention": (
                "PRG_tminus1 full-day forecast = h_ov_hat + h_in_hat issued at day d-1 "
                "close. Primary variant (exp): unobserved overnight shock replaced by "
                "model-consistent expectation h_ov_hat, leverage indicator by 1/2 "
                "(symmetric innovation). Robustness variant (lag): lagged realized "
                "overnight plug-in, replicating the K880-rerun PRG_Extended_tminus1."
            ),
            "baselines": (
                "GJR(1,1) on close-to-close returns and HAR on log(sigma2_fullday), "
                "both strict one-step-ahead from d-1 close, expanding window, "
                "refit every 63 days."
            ),
            "loss": "canonical volpred qlike_pointwise (actual/predicted orientation)",
            "dm": (
                "canonical volpred.stats.model_evaluation.dm_test, h=1, Newey-West HAC "
                "bandwidth ceil(n^(1/3)); per-cell loss-diff acf(1) and 2x-bandwidth "
                "sensitivity t reported"
            ),
            "no_lookahead_guard": (
                "All PRG/GJR/HAR fits use observations strictly before the forecast "
                "origin; close-convention forecasts use no day-d information "
                "(no r2_overnight[d], no r_overnight[d], no target[d])."
            ),
            "harvey_threshold": "|t| > 3.0",
        },
        "data_snapshots": snapshots,
        "markets": markets,
        "headline": {
            "prg_tminus1_wins_qlike": n_prg_wins,
            "n_markets": len(markets),
            "harvey_significant_cells": harvey_cells,
        },
        "relation_to_prior": {
            "K880_rerun_spy_tminus1_vs_gjr_dm_t": -1.476,
            "K880v2_spy_close_convention_dm_t": -0.57,
            "K1544_open_convention": "PRG open-known beats fair GJR-X in all six markets",
            "note": (
                "K1699 pins its own data snapshot (2026-07-12 vintage for yfinance "
                "markets); K880/K1544 numbers are directional anchors, not "
                "bit-identical targets."
            ),
        },
        "references": [
            "Bollerslev and Ghysels (1996), Periodic autoregressive conditional heteroskedasticity.",
            "Patton (2011), Volatility forecast comparison using imperfect volatility proxies.",
            "Diebold and Mariano (1995), Comparing predictive accuracy.",
            "Harvey, Leybourne, and Newbold (1997), Testing equality of prediction MSEs.",
            "Harvey, Liu, and Zhu (2016), ...and the cross-section of expected returns.",
            "Corsi (2009), A simple approximate long-memory model of realized volatility.",
            "Linton and Wu (2020), A coupled component DCS-EGARCH model for intraday and overnight volatility.",
        ],
        "runtime_seconds": float(time.time() - start),
    }

    write_tables(results)
    make_chart(results)

    for name in ["k1699_results.json", "results.json"]:
        with (EXP_DIR / name).open("w", encoding="utf-8") as f:
            json.dump(_json_clean(results), f, indent=2, ensure_ascii=False)

    print("\nSummary table:")
    print((EXP_DIR / "per_market_table.md").read_text(encoding="utf-8"))
    print(f"PRG_tminus1 QLIKE wins: {n_prg_wins}/{len(markets)}")
    print(f"Saved results to {EXP_DIR}")


if __name__ == "__main__":
    main()
