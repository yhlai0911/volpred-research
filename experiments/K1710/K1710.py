#!/usr/bin/env python3
"""K1710: open-convention + mixed-timing anchor panels on the K1699 pinned vintage.

The prg-periodic-garch rewrite headline is a single "three forecast-timing
convention" main table: same model, same data, the PRG-vs-baseline DM moves
from a strong PRG advantage under mixed timing (K880 SPY: legacy GJR-vs-PRG
t ~ +5 to +6, i.e. PRG_Extended better) to ~0 under strict close timing (K1699)
purely because of *when* the full-day forecast is issued relative to the
overnight session. NB orientation: K1710 standardises every panel to PRG-first
(dm_cell(PRG, baseline), NEGATIVE t = PRG better), so that legacy +5/+6 becomes
a large NEGATIVE mixed-anchor t here; the anchor cross-check maps the sign
explicitly. The close-time panel already exists
as a pinned, deterministic, Codex-PASS experiment (K1699). The open-time and
mixed-timing panels only existed in K1544, whose data was never pinned
(2026-06-24 live yfinance fetch) and whose Codex caveat flags the point
estimates as vintage-fragile -- unusable in a submission table.

K1710 reproduces the two missing panels on *the K1699 pinned snapshot* so that
all three panels of the main table share one data vintage and pass the paper's
reproduce gate:

  1. Open-convention panel (issued at day-d open, current overnight realized):
        PRG_open_known : full-day = r2_ov[t] (realized) + h_in_hat(r2_ov[t])
        FairGJRX       : K1544 fair-information GJR-X,
                         h_t = omega + alpha r2_c2c[t-1] + gamma 1(r<0) r2
                               + beta h[t-1] + delta r2_ov[t]  (current overnight)
     Main DM cell: PRG_open_known vs FairGJRX.

  2. Mixed-timing anchor (the OLD paper headline object):
        PRG_canonical_mixed : h_ov_hat (issued d-1 close) + h_in_hat(r2_ov[t])
                              (intraday fed the day-d realized overnight)
        GJR                 : close-to-close GJR(1,1), the K1699 baseline
     Main DM cell: PRG_canonical_mixed vs GJR.

Reuse / provenance:
- Data: the seven K1699 pinned CSVs are copied into experiments/K1710/data/ and
  their SHA256 is asserted equal to the values K1699 recorded (self-contained).
  All reads use float_precision="round_trip" (K1699 section 6: a 1-ulp parser
  drift flips the non-convex PRG MLE basin).
- PRG forecasts: the canonical / open-known loop is K1699's *fixed*
  prg_close_convention_forecasts propagation (inherits the k881/k886 refit-
  failure stale-state fix from K1699's Codex review), so PRG_canonical_mixed is
  bit-identical to K1699's PRG_canonical_diag on this vintage.
- FairGJRX: reused verbatim from K1544 (gjrx_current_oos_forecast), including
  its internal RandomState(1544) multistart; deterministic on the pinned data.
- GJR baseline: base-module gjr_oos_forecast, identical call to K1699's GJR.
- QLIKE: canonical volpred.stats.model_evaluation.qlike_pointwise
  (actual/predicted orientation).
- DM: canonical volpred.stats.model_evaluation.dm_test (Newey-West HAC,
  bandwidth ceil(n^(1/3)), h=1). Every cell records an explicit orientation
  string; per cell we also report loss-diff acf(1) and a 2x-bandwidth
  sensitivity t (supplementary, not the primary inference).
- Determinism: global seed 1710; the whole pipeline is run twice and the numeric
  core (QLIKE + DM t/p + overnight share) is asserted bit-identical.

Sign convention (all DM cells): dm_cell(A, B) reports pair "A_vs_B" with a
negative t meaning model A has the lower loss (A better). This matches K1699's
dm_cell so the three panels of the paper table share one orientation. Note the
K1544 anchor was oriented the opposite way (fair minus PRG, positive = PRG
better); the anchor cross-check below maps the sign explicitly.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

EXPERIMENT_ID = "K1710"
ROOT = Path(__file__).resolve().parents[2]
EXP_DIR = Path(__file__).resolve().parent
DATA_DIR = EXP_DIR / "data"
K1699_DATA_DIR = ROOT / "experiments" / "k1699" / "data"

if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from volpred.stats.model_evaluation import dm_test, qlike_pointwise  # noqa: E402

RNG_SEED = 1710
GJR_REFIT_FREQ_DAYS = 63  # identical to K1699 GJR baseline cadence

# K1699-recorded SHA256 of the pinned vintage (data_snapshots in
# experiments/k1699/k1699_results.json). K1710 asserts its copies match.
K1699_SNAPSHOT_SHA256 = {
    "SPY_snapshot.csv": "501af099f9e8205d4629b607ee2e30a147e7beef6ed5ce1282abc00ad2ae183b",
    "QQQ_snapshot.csv": "b42eb032309215841faa55a7476366df9541b991dcb8b046ac4135c31fb4835d",
    "GLD_snapshot.csv": "0741addcf29a2769bd550ea80558a1f6579f6a0441d49039b5437e48b9395f35",
    "EEM_snapshot.csv": "924a7447754546c05852aee899951995f567cae5b23e37e2eccf7c8bef87d7c3",
    "0050_TW_snapshot.csv": "91ec88b94cc7692c5f3feaded96c28218f9b8408cd52105367bd296a388e8b0f",
    "TAIFEX_sessions_snapshot.csv": "59c21377aea941e9c18094a47d07a1d2caa3d0b73a66c7f97e8bd6b44f950acf",
    "TAIFEX_daily_snapshot.csv": "b573f0e2736532c7671bab7120c1872ef23b5682e50013c607a635790cf42588",
}


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


def read_k880_spy_anchor() -> dict[str, Any]:
    """Read the authoritative K880 SPY canonical(PRG_Extended)-vs-GJR DM t from
    the checked-in artifact rather than hardcoding, and expose its orientation
    explicitly (Codex K1710 review, item 4c provenance fix).

    K880 stores 'GJR_vs_PRG_Extended' under the same dm_cell convention as K1710
    (negative t = first-named model better). Positive t there means GJR is worse,
    i.e. PRG_Extended is better. In K1710's PRG-first convention that equals a
    NEGATIVE mixed-anchor t.
    """
    p = ROOT / "paper/prg-periodic-garch/experiments/k880_results.json"
    out: dict[str, Any] = {
        "orientation_note": (
            "K880 key 'GJR_vs_PRG_Extended': positive t => GJR worse => PRG_Extended "
            "better; equivalent K1710 PRG-first t = -(that value)."
        ),
        "directional_prior_note": (
            "K880 2026-06-13 rerun and K1699 README cite SPY mixed-timing DM ~ +5.06 "
            "in GJR-vs-PRG orientation (PRG better); the checked-in original artifact "
            "value below may differ at the vintage level. Both agree PRG_Extended beats "
            "GJR; K1710's own pinned mixed-anchor t is the reproduction of record."
        ),
    }
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        t = float(d["layer5_dm_tests"]["GJR_vs_PRG_Extended"]["t_stat"])
        out.update({
            "source_file": str(p.relative_to(ROOT)),
            "source_key": "layer5_dm_tests.GJR_vs_PRG_Extended.t_stat",
            "k880_gjr_vs_prg_extended_t_positive_prg_better": t,
            "k880_prg_first_equivalent_t_negative_prg_better": -t,
        })
    except Exception as exc:  # pragma: no cover - provenance best-effort
        out["read_error"] = f"{type(exc).__name__}: {exc}"
    return out


def sync_snapshots() -> dict[str, Any]:
    """Copy the K1699 pinned CSVs into experiments/K1710/data/ (self-contained)
    and assert each copy's SHA256 equals K1699's recorded value."""
    DATA_DIR.mkdir(exist_ok=True)
    provenance: dict[str, Any] = {}
    for fname, expected in K1699_SNAPSHOT_SHA256.items():
        dst = DATA_DIR / fname
        if not dst.exists():
            src = K1699_DATA_DIR / fname
            if not src.exists():
                raise FileNotFoundError(f"K1699 source snapshot missing: {src}")
            shutil.copy2(src, dst)
        actual = _sha256(dst)
        if actual != expected:
            raise AssertionError(
                f"SHA256 mismatch for {fname}: got {actual}, K1699 recorded {expected}"
            )
        provenance[fname] = {
            "file": str(dst.relative_to(ROOT)),
            "sha256": actual,
            "matches_k1699": True,
        }
    return provenance


def load_ohlc(fname: str) -> pd.DataFrame:
    return pd.read_csv(
        DATA_DIR / fname, index_col=0, parse_dates=True, float_precision="round_trip"
    )


def load_taifex() -> tuple[pd.DataFrame, pd.DataFrame]:
    sess_df = pd.read_csv(
        DATA_DIR / "TAIFEX_sessions_snapshot.csv", index_col=0, float_precision="round_trip"
    )
    daily_df = pd.read_csv(
        DATA_DIR / "TAIFEX_daily_snapshot.csv", index_col=0, parse_dates=True,
        float_precision="round_trip",
    )
    return sess_df, daily_df


# ------------------------------------------- PRG canonical + open-known loop

def prg_canonical_and_open(
    module: Any,
    r_overnight: np.ndarray,
    r_intra: np.ndarray,
    r2_overnight: np.ndarray,
    r2_intra: np.ndarray,
    is_end: int,
    *,
    refit_freq: int,
) -> dict[str, np.ndarray]:
    """Expanding-window PRG Extended: canonical mixed-timing and open-known.

    Propagation is K1699's fixed prg_close_convention_forecasts loop (so
    canonical is bit-identical to K1699's PRG_canonical_diag on this vintage).
    Both objects share the same intraday equation fed the day-d *realized*
    overnight (h_in_c); they differ only in the first full-day term:
        canonical  = h_ov_hat + h_in_c           (h_ov forecast at d-1 close)
        open_known = r2_overnight[t] + h_in_c     (overnight realized at d open)
    Parameter ordering across k880/k881/k886 is [o0,a0,b0,o1,a1,b1,g0,g1].
    """
    n_days = len(r_overnight)
    canonical = np.full(n_days, np.nan)
    open_known = np.full(n_days, np.nan)

    estimator = getattr(module, "estimate_prg_spy", None) or getattr(module, "estimate_prg")
    n_starts = int(getattr(module, "PRG_N_STARTS", 3))
    has_forecast_day = hasattr(module, "_prg_forecast_day")  # k881/k886 family

    current_params: np.ndarray | None = None
    h_state: float | None = None

    def _forecast_pair(p: np.ndarray, h_after_intra_prev: float, t: int) -> tuple[float, float]:
        o0, a0, b0, o1, a1, b1, g0, g1 = (float(v) for v in p[:8])
        lev0 = g0 * r2_intra[t - 1] * (1.0 if r_intra[t - 1] < 0.0 else 0.0)
        h_ov = o0 + a0 * r2_intra[t - 1] + lev0 + b0 * h_after_intra_prev
        if h_ov < 1e-12:
            h_ov = 1e-12
        # intraday equation with day-d realized overnight (mixed timing)
        lev1 = g1 * r2_overnight[t] * (1.0 if r_overnight[t] < 0.0 else 0.0)
        h_in_c = o1 + a1 * r2_overnight[t] + lev1 + b1 * h_ov
        if h_in_c < 1e-12:
            h_in_c = 1e-12
        return h_ov + h_in_c, r2_overnight[t] + h_in_c

    if has_forecast_day:
        for t in range(is_end, n_days):
            rebuilt = False
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
                    rebuilt = True
            if current_params is None or h_state is None:
                continue
            if not rebuilt and t != is_end:
                d = t - 1
                x_prev = r2_intra[d - 1] if d > 0 else r2_overnight[0]
                r_prev = r_intra[d - 1] if d > 0 else r_overnight[0]
                h_state = module._prg_propagate_one_day(
                    *(float(v) for v in current_params[:8]),
                    h_state, x_prev, r_prev, r2_overnight[d], r_overnight[d],
                )
            canonical[t], open_known[t] = _forecast_pair(current_params, h_state, t)
        return {"canonical": canonical, "open_known": open_known}

    # k880 family: state via _prg_propagate_days_numba
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
        canonical[t], open_known[t] = _forecast_pair(current_params, h_state, t)
        o0, a0, b0, o1, a1, b1, g0, g1 = (float(v) for v in current_params[:8])
        h_state = module._prg_propagate_days_numba(
            o0, a0, b0, g0, o1, a1, b1, g1,
            r_overnight, r_intra, r2_overnight, r2_intra, t, t + 1, h_state,
        )
    return {"canonical": canonical, "open_known": open_known}


def taifex_canonical_and_open(
    k883: Any, sess_df: pd.DataFrame, daily_df: pd.DataFrame,
) -> tuple[dict[str, np.ndarray], int]:
    """TAIFEX session-level PRG Extended: canonical + open-known.

    Follows K1699's taifex_close_convention_forecasts session recursion
    (h_all[t] is F_{t-1} measurable; day-d overnight session index 2d, intraday
    2d+1). open_known[d] = x_overnight_daily[d] (realized) + h_in_c, where
    h_in_c is the intraday session variance fed the day-d realized overnight.
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

    # Defensive alignment asserts (Codex K1710 review suggestion): the pinned
    # session series must be exactly two sessions per day, strictly alternating
    # overnight(0)/intraday(1), with overnight x equal to the daily x_overnight
    # column. Guards against silent 2d/2d+1 misalignment on any future data swap.
    assert n_sessions == 2 * n_days, (
        f"TAIFEX session/day misalignment: {n_sessions} sessions != 2 x {n_days} days"
    )
    assert np.array_equal(s_arr[::2], np.zeros(n_days)) and np.array_equal(
        s_arr[1::2], np.ones(n_days)
    ), "TAIFEX session_type is not a strict 0(overnight)/1(intraday) alternation"
    assert np.allclose(
        x_arr[::2], daily_df["x_overnight"].values.astype(np.float64),
        rtol=0.0, atol=1e-12, equal_nan=True,
    ), "TAIFEX overnight-session x does not match daily x_overnight (index misaligned)"

    params, _ll = k883.estimate_prg(
        r_arr[:is_end_sess], x_arr[:is_end_sess], s_arr[:is_end_sess],
        extended=True, n_starts=5,
    )
    nan_out = {
        "canonical": np.full(n_days, np.nan),
        "open_known": np.full(n_days, np.nan),
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
        lev1 = g1 * x_arr[i_ov] * (1.0 if r_arr[i_ov] < 0.0 else 0.0)
        h_in_c = o1 + a1 * x_arr[i_ov] + lev1 + b1 * h_ov
        h_in_c = max(h_in_c, 1e-12)
        out["canonical"][d] = h_ov + h_in_c
        out["open_known"][d] = x_overnight_daily[d] + h_in_c
    return out, is_end_days


# ---------------------------------------------------------------- DM helpers

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
    """Bartlett-kernel HAC t at an explicit bandwidth; sensitivity companion to
    the canonical dm_test (which fixes bandwidth at ceil(n^(1/3)))."""
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


# ---------------------------------------------------------------- evaluation

def _oos_overnight_share(r2_ov_oos: np.ndarray, r2_in_oos: np.ndarray) -> float:
    """sum(r2_ov) / sum(r2_ov + r2_in) over OOS, from the pinned snapshot."""
    m = np.isfinite(r2_ov_oos) & np.isfinite(r2_in_oos)
    tot = float(np.sum(r2_ov_oos[m]) + np.sum(r2_in_oos[m]))
    if tot <= 0:
        return math.nan
    return float(np.sum(r2_ov_oos[m]) / tot)


def evaluate_market(
    market: str,
    target: np.ndarray,
    forecasts: dict[str, np.ndarray],
    is_end: int,
    dates: pd.Index,
    r2_overnight: np.ndarray,
    r2_intra: np.ndarray,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    models = ["PRG_open_known", "FairGJRX", "PRG_canonical_mixed", "GJR"]

    target_oos = np.asarray(target[is_end:], dtype=np.float64)
    oos = {m: np.asarray(forecasts[m][is_end:], dtype=np.float64) for m in models}
    dates_oos = dates[is_end:]

    common = np.isfinite(target_oos) & (target_oos > 0)
    for m in models:
        common &= np.isfinite(oos[m]) & (oos[m] > 0)

    losses = {m: qlike_pointwise(target_oos[common], oos[m][common]) for m in models}
    qlike = {m: float(np.mean(losses[m])) for m in models}

    ov_share = _oos_overnight_share(
        np.asarray(r2_overnight[is_end:], dtype=np.float64),
        np.asarray(r2_intra[is_end:], dtype=np.float64),
    )

    dm_cells = {
        # --- PANEL A: open convention (issued at day-d open) ---
        "open_panel_main": dm_cell(losses["PRG_open_known"], losses["FairGJRX"],
                                   "PRG_open_known", "FairGJRX"),
        # --- PANEL B: mixed-timing anchor (old paper headline object) ---
        "mixed_anchor_main": dm_cell(losses["PRG_canonical_mixed"], losses["GJR"],
                                     "PRG_canonical_mixed", "GJR"),
        # --- secondary cells ---
        "secondary_fairgjrx_vs_gjr": dm_cell(losses["FairGJRX"], losses["GJR"],
                                             "FairGJRX", "GJR"),
        "secondary_open_known_vs_gjr": dm_cell(losses["PRG_open_known"], losses["GJR"],
                                               "PRG_open_known", "GJR"),
    }

    return {
        "market": market,
        "metadata": metadata,
        "oos_period": {
            "start": str(pd.Timestamp(dates_oos[0]).date()) if len(dates_oos) else None,
            "end": str(pd.Timestamp(dates_oos[-1]).date()) if len(dates_oos) else None,
            "n_oos": int(len(dates_oos)),
            "n_common_valid": int(common.sum()),
        },
        "oos_overnight_variance_share": ov_share,
        "qlike": qlike,
        "dm_tests": dm_cells,
        "forecast_diagnostics": {
            m: {"valid_oos": int(np.isfinite(oos[m]).sum())} for m in models
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


def _numeric_core(results: dict[str, Any]) -> str:
    """Deterministic serialization of the numeric outputs for bit-identical
    rerun verification (QLIKE + DM t/p + overnight share)."""
    core: dict[str, Any] = {}
    for market, r in results["markets"].items():
        core[market] = {
            "qlike": r["qlike"],
            "oos_overnight_variance_share": r["oos_overnight_variance_share"],
            "n_common_valid": r["oos_period"]["n_common_valid"],
            "dm": {
                k: {"t": c["t_stat"], "p": c["p_value"], "n": c["n"]}
                for k, c in r["dm_tests"].items()
            },
        }
    return json.dumps(_json_clean(core), sort_keys=True)


def write_tables(results: dict[str, Any]) -> None:
    rows = []
    for market, r in results["markets"].items():
        dm = r["dm_tests"]
        rows.append({
            "market": market,
            "n_common_valid": r["oos_period"]["n_common_valid"],
            "oos_start": r["oos_period"]["start"],
            "oos_end": r["oos_period"]["end"],
            "oos_overnight_variance_share": r["oos_overnight_variance_share"],
            "qlike_prg_open_known": r["qlike"]["PRG_open_known"],
            "qlike_fair_gjrx": r["qlike"]["FairGJRX"],
            "qlike_prg_canonical_mixed": r["qlike"]["PRG_canonical_mixed"],
            "qlike_gjr": r["qlike"]["GJR"],
            "dm_t_open_panel_prg_vs_fairgjrx": dm["open_panel_main"]["t_stat"],
            "dm_p_open_panel_prg_vs_fairgjrx": dm["open_panel_main"]["p_value"],
            "dm_t_mixed_anchor_prg_vs_gjr": dm["mixed_anchor_main"]["t_stat"],
            "dm_p_mixed_anchor_prg_vs_gjr": dm["mixed_anchor_main"]["p_value"],
            "dm_t_fairgjrx_vs_gjr": dm["secondary_fairgjrx_vs_gjr"]["t_stat"],
            "dm_t_open_known_vs_gjr": dm["secondary_open_known_vs_gjr"]["t_stat"],
        })

    with (EXP_DIR / "per_market_table.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    with (EXP_DIR / "per_market_table.md").open("w", encoding="utf-8") as f:
        f.write("| Market | N | ON share | PRG open-known | Fair GJR-X | PRG canonical | GJR "
                "| DM t open (PRG vs FairGJRX) | DM t mixed (PRG vs GJR) |\n")
        f.write("|---|---:|---:|---:|---:|---:|---:|---:|---:|\n")
        for row in rows:
            f.write(
                f"| {row['market']} | {row['n_common_valid']} | "
                f"{row['oos_overnight_variance_share']:.4f} | "
                f"{row['qlike_prg_open_known']:.6f} | {row['qlike_fair_gjrx']:.6f} | "
                f"{row['qlike_prg_canonical_mixed']:.6f} | {row['qlike_gjr']:.6f} | "
                f"{row['dm_t_open_panel_prg_vs_fairgjrx']:.3f} | "
                f"{row['dm_t_mixed_anchor_prg_vs_gjr']:.3f} |\n"
            )


def make_chart(results: dict[str, Any]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    markets = list(results["markets"].keys())
    x = np.arange(len(markets))

    open_q = [results["markets"][m]["qlike"]["PRG_open_known"] for m in markets]
    fair_q = [results["markets"][m]["qlike"]["FairGJRX"] for m in markets]
    canon_q = [results["markets"][m]["qlike"]["PRG_canonical_mixed"] for m in markets]
    gjr_q = [results["markets"][m]["qlike"]["GJR"] for m in markets]
    t_open = [results["markets"][m]["dm_tests"]["open_panel_main"]["t_stat"] for m in markets]
    t_mixed = [results["markets"][m]["dm_tests"]["mixed_anchor_main"]["t_stat"] for m in markets]

    fig, axes = plt.subplots(2, 1, figsize=(11, 9), constrained_layout=True)
    w = 0.2
    axes[0].bar(x - 1.5 * w, open_q, w, label="PRG open-known", color="#2ca02c")
    axes[0].bar(x - 0.5 * w, fair_q, w, label="Fair GJR-X", color="#ff7f0e")
    axes[0].bar(x + 0.5 * w, canon_q, w, label="PRG canonical (mixed)", color="#1f77b4")
    axes[0].bar(x + 1.5 * w, gjr_q, w, label="GJR (close-to-close)", color="#7f7f7f")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(markets)
    axes[0].set_ylabel("OOS QLIKE")
    axes[0].set_title("K1710 QLIKE on the K1699 pinned vintage: open-convention + mixed anchor")
    axes[0].legend()

    w2 = 0.38
    axes[1].bar(x - w2 / 2, t_open, w2, label="Open panel: PRG_open_known vs FairGJRX",
                color="#2ca02c")
    axes[1].bar(x + w2 / 2, t_mixed, w2, label="Mixed anchor: PRG_canonical vs GJR",
                color="#1f77b4")
    for yline in (3.0, -3.0):
        axes[1].axhline(yline, color="black", linestyle="--", linewidth=1)
    axes[1].axhline(0.0, color="black", linewidth=0.8)
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(markets)
    axes[1].set_ylabel("DM t (negative favors PRG)")
    axes[1].set_title("Canonical DM t-stats; dashed lines |t| = 3 (Harvey). "
                      "Negative = PRG better.")
    axes[1].legend()

    fig.savefig(EXP_DIR / "fig_K1710_open_and_mixed.png", dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------- build

def build_results(modules: dict[str, Any], k1544: Any) -> dict[str, Any]:
    k880 = modules["k880"]
    k881 = modules["k881"]
    k886 = modules["k886"]
    k883 = modules["k883"]

    markets: dict[str, Any] = {}

    def run_ohlc(market: str, fname: str, module: Any, is_end: int,
                 prg_refit: int, meta: dict[str, Any]) -> dict[str, Any]:
        df = load_ohlc(fname)
        r_overnight = df["r_overnight"].values.astype(np.float64)
        r_intra = df["r_intra"].values.astype(np.float64)
        r_c2c = df["r_c2c"].values.astype(np.float64)
        r2_overnight = df["r2_overnight"].values.astype(np.float64)
        r2_intra = df["r2_intra"].values.astype(np.float64)
        target = df["sigma2_fullday"].values.astype(np.float64)

        print(f"\n[{market}] n={len(df)}, IS={is_end}, OOS={len(df) - is_end}")
        print(f"[{market}] PRG canonical + open-known...")
        prg = prg_canonical_and_open(
            module, r_overnight, r_intra, r2_overnight, r2_intra, is_end, refit_freq=prg_refit,
        )
        print(f"[{market}] Fair GJR-X (current overnight)...")
        fair_gjr, _fair_diag = k1544.gjrx_current_oos_forecast(
            r_c2c, r2_overnight, is_end,
            refit_freq=k1544.FAIR_GJR_REFIT_FREQ_DAYS, dates=df.index,
        )
        print(f"[{market}] GJR close-to-close baseline...")
        gjr_fc = module.gjr_oos_forecast(r_c2c, is_end, refit_freq=GJR_REFIT_FREQ_DAYS)

        meta = {
            **meta,
            "n_total": int(len(df)),
            "n_is": int(is_end),
            "n_oos": int(len(df) - is_end),
            "period": f"{pd.Timestamp(df.index[0]).date()} to {pd.Timestamp(df.index[-1]).date()}",
            "prg_refit_freq_days": int(prg_refit),
            "fair_gjr_refit_freq_days": int(k1544.FAIR_GJR_REFIT_FREQ_DAYS),
            "gjr_refit_freq_days": GJR_REFIT_FREQ_DAYS,
        }
        return evaluate_market(
            market, target,
            {
                "PRG_open_known": prg["open_known"],
                "PRG_canonical_mixed": prg["canonical"],
                "FairGJRX": fair_gjr,
                "GJR": gjr_fc,
            },
            is_end, df.index, r2_overnight, r2_intra, meta,
        )

    # SPY via canonical K880 module
    spy_df = load_ohlc("SPY_snapshot.csv")
    spy_is_end = int((spy_df.index <= k880.IS_END_DATE).sum())
    markets["SPY"] = run_ohlc(
        "SPY", "SPY_snapshot.csv", k880, spy_is_end, k880.PRG_REFIT_FREQ,
        {"data_source": "K1699 pinned SPY snapshot (yfinance via k880 load_spy_data, 2026-07-12 vintage)",
         "target": "sigma2_fullday = r2_overnight + r2_intra",
         "split": f"IS through {k880.IS_END_DATE}"},
    )

    fname_map = {"QQQ": "QQQ_snapshot.csv", "GLD": "GLD_snapshot.csv", "EEM": "EEM_snapshot.csv"}
    for ticker, cfg in k881.ASSETS.items():
        df = load_ohlc(fname_map[ticker])
        is_end = int(len(df) * k881.IS_FRACTION)
        markets[ticker] = run_ohlc(
            ticker, fname_map[ticker], k881, is_end, k881.REFIT_FREQ_PRG,
            {"data_source": f"K1699 pinned {ticker} snapshot (yfinance via k881, 2026-07-12 vintage)",
             "description": cfg["description"],
             "target": "sigma2_fullday = r2_overnight + r2_intra",
             "split": f"{k881.IS_FRACTION:.0%} in-sample"},
        )

    tw_df = load_ohlc("0050_TW_snapshot.csv")
    tw_is_end = int(len(tw_df) * k886.IS_FRACTION)
    markets["0050.TW"] = run_ohlc(
        "0050.TW", "0050_TW_snapshot.csv", k886, tw_is_end, k886.REFIT_FREQ_PRG,
        {"data_source": "K1699 pinned 0050.TW snapshot (yfinance via k886, 2026-07-12 vintage)",
         "target": "sigma2_fullday = r2_overnight + r2_intra",
         "split": f"{k886.IS_FRACTION:.0%} in-sample"},
    )

    # TAIFEX from pinned session/daily snapshots
    print("\n[TAIFEX] loading pinned session/daily snapshots...")
    sess_df, daily_df = load_taifex()
    prg_tx, tx_is_end = taifex_canonical_and_open(k883, sess_df, daily_df)
    tx_target = daily_df["rv_fullday"].values.astype(np.float64)
    tx_returns = (daily_df["overnight_gap"].values + daily_df["day_return"].values).astype(np.float64)
    tx_x_overnight = daily_df["x_overnight"].values.astype(np.float64)
    tx_x_intraday = daily_df["x_intraday"].values.astype(np.float64)
    print("[TAIFEX] Fair GJR-X (current overnight)...")
    tx_fair, _tx_fair_diag = k1544.gjrx_current_oos_forecast(
        tx_returns, tx_x_overnight, tx_is_end,
        refit_freq=max(1, int(k883.REFIT_FREQ // 2)), dates=daily_df.index,
    )
    print("[TAIFEX] GJR close-to-close baseline...")
    tx_gjr = k883.gjr_oos_forecast(tx_returns, tx_is_end, refit_freq=GJR_REFIT_FREQ_DAYS)
    markets["TAIFEX"] = evaluate_market(
        "TAIFEX", tx_target,
        {
            "PRG_open_known": prg_tx["open_known"],
            "PRG_canonical_mixed": prg_tx["canonical"],
            "FairGJRX": tx_fair,
            "GJR": tx_gjr,
        },
        tx_is_end, pd.Index(daily_df.index), tx_x_overnight, tx_x_intraday,
        {
            "data_source": "K1699 pinned TAIFEX session/daily snapshots (TX tick via k883)",
            "target": "rv_fullday = x_overnight + x_intraday",
            "n_total": int(len(daily_df)),
            "n_is": int(tx_is_end),
            "n_oos": int(len(daily_df) - tx_is_end),
            "period": f"{pd.Timestamp(daily_df.index[0]).date()} to {pd.Timestamp(daily_df.index[-1]).date()}",
            "prg_refit_freq_sessions": int(k883.REFIT_FREQ),
            "fair_gjr_refit_freq_days": int(max(1, k883.REFIT_FREQ // 2)),
            "gjr_refit_freq_days": GJR_REFIT_FREQ_DAYS,
        },
    )

    return {"markets": markets}


# ---------------------------------------------------------------------- main

def main() -> None:
    start = time.time()
    np.random.seed(RNG_SEED)

    print("=" * 72)
    print("K1710: open-convention + mixed-timing anchor on the K1699 pinned vintage")
    print("=" * 72)

    snapshots = sync_snapshots()
    print(f"Snapshots synced + SHA256-verified against K1699 ({len(snapshots)} files)")

    modules = {
        "k880": _load_module(ROOT / "paper/prg-periodic-garch/experiments/k880_prg_spy_validation.py", "k880_prg_ref"),
        "k881": _load_module(ROOT / "paper/prg-periodic-garch/experiments/k881_prg_multi_asset.py", "k881_prg_ref"),
        "k886": _load_module(ROOT / "paper/prg-periodic-garch/experiments/k886_prg_0050tw.py", "k886_prg_ref"),
        "k883": _load_module(ROOT / "paper/prg-periodic-garch/experiments/k883_taifex_tick_prg.py", "k883_prg_ref"),
    }
    k1544 = _load_module(
        ROOT / "experiments/k1544_prg_fair_info_gjr/k1544_prg_fair_info_gjr.py", "k1544_fair_ref"
    )

    print("\n### PASS 1 ###")
    results = build_results(modules, k1544)
    print("\n### PASS 2 (determinism check) ###")
    np.random.seed(RNG_SEED)
    results2 = build_results(modules, k1544)

    core1, core2 = _numeric_core(results), _numeric_core(results2)
    bit_identical = core1 == core2
    if not bit_identical:
        raise AssertionError(
            "Determinism check FAILED: pass 1 and pass 2 numeric cores differ."
        )
    print("\nDeterminism check PASSED: two passes produce bit-identical numeric core.")

    # anchor cross-check vs K1544 (open panel) and K880 (mixed anchor)
    k1544_open_anchor = {  # fair minus open-PRG t (positive = PRG better) from K1544
        "SPY": 2.1149, "QQQ": 2.9668, "GLD": 3.6253,
        "EEM": 10.1305, "0050.TW": 3.8697, "TAIFEX": 5.6075,
    }
    anchor_report = {}
    for m, r in results["markets"].items():
        open_t = r["dm_tests"]["open_panel_main"]["t_stat"]  # PRG-fair, neg = PRG better
        mixed_t = r["dm_tests"]["mixed_anchor_main"]["t_stat"]  # PRG-GJR, neg = PRG better
        k1544_t = k1544_open_anchor.get(m)
        anchor_report[m] = {
            "open_panel_prg_vs_fairgjrx_t": open_t,
            "open_panel_prg_better": bool(open_t < 0),
            "k1544_open_anchor_fair_minus_prg_t": k1544_t,
            "k1544_orientation_equivalent_t": (-open_t),  # flip to K1544 orientation
            "open_direction_matches_k1544": bool(k1544_t is not None and open_t < 0),
            "mixed_anchor_prg_vs_gjr_t": mixed_t,
            "mixed_anchor_prg_better": bool(mixed_t < 0),
        }

    core_json = _json_clean({
        "experiment_id": EXPERIMENT_ID,
        "title": "Open-convention + mixed-timing anchor panels for the PRG three-convention main table",
        "created_at": pd.Timestamp.utcnow().isoformat(),
        "random_seed": RNG_SEED,
        "research_question": (
            "On the K1699 pinned snapshot vintage, reproduce the two panels missing "
            "from the PRG three-forecast-timing-convention main table: (A) the "
            "open-convention panel (PRG open-known vs fair-information GJR-X, both "
            "issued at the day-d open with the current overnight realized) and (B) "
            "the mixed-timing anchor (PRG canonical vs close-to-close GJR, the old "
            "paper headline object). Do the directions reproduce K1544 / K880 so all "
            "three main-table panels share one vintage and pass the reproduce gate?"
        ),
        "sign_convention": (
            "Every DM cell is dm_cell(A, B) -> pair 'A_vs_B', NEGATIVE t means model A "
            "has lower loss (A better). Same orientation as K1699's close panel so the "
            "three-panel table is internally consistent. K1544 used the opposite "
            "orientation (fair minus PRG, positive = PRG better); the anchor cross-check "
            "flips the sign explicitly."
        ),
        "method_summary": {
            "open_convention": (
                "PRG_open_known full-day = r2_overnight[t] (realized at day-d open) + "
                "h_in_hat(r2_overnight[t]); FairGJRX = omega + alpha r2_c2c[t-1] + "
                "gamma I(r<0) r2 + beta h[t-1] + delta r2_overnight[t] (current overnight, "
                "K1544 spec), estimated on data strictly before the forecast origin, "
                "expanding window, refit every 63 days."
            ),
            "mixed_timing_anchor": (
                "PRG_canonical_mixed = h_ov_hat (issued d-1 close) + h_in_hat(r2_overnight[t]) "
                "(intraday fed day-d realized overnight); GJR = close-to-close GJR(1,1), "
                "identical to the K1699 baseline. This is the old paper headline object."
            ),
            "loss": "canonical volpred qlike_pointwise (actual/predicted orientation)",
            "dm": (
                "canonical volpred.stats.model_evaluation.dm_test, h=1, Newey-West HAC "
                "bandwidth ceil(n^(1/3)); per-cell loss-diff acf(1) and 2x-bandwidth "
                "sensitivity t reported"
            ),
            "no_lookahead_guard": (
                "All PRG/GJR-X/GJR fits use observations strictly before the forecast "
                "origin. Open-convention forecasts use only day-d information realized at "
                "the market open (r2_overnight[t]); they never use r_c2c[t], the intraday "
                "return, or the full-day target[t]."
            ),
            "overnight_variance_share": (
                "oos_overnight_variance_share = sum(r2_overnight) / sum(r2_overnight + "
                "r2_intra) over the OOS window, from the pinned snapshot (paper Data table)."
            ),
            "harvey_threshold": "|t| > 3.0",
        },
        "data_snapshots": snapshots,
        "data_vintage_note": (
            "Data is the K1699 2026-07-12 pinned vintage (SHA256-verified). K1544 open "
            "panel (2026-06-24 unpinned) and K880 mixed anchor are DIRECTIONAL anchors, "
            "not bit-identical targets: yfinance auto_adjust retro-adjusts history so "
            "point values differ at the vintage/ulp level; the robust claim is the DM "
            "direction, which must reproduce."
        ),
        "determinism": {
            "two_pass_bit_identical": bit_identical,
            "global_seed": RNG_SEED,
            "note": (
                "PRG estimators use their base-module internal multistart seeds; FairGJRX "
                "reuses K1544's internal RandomState(1544). All fits deterministic; two "
                "full pipeline passes assert bit-identical numeric core."
            ),
        },
        "anchor_validation": {
            "open_panel_vs_k1544": anchor_report,
            "mixed_anchor_vs_k880_spy": {
                "k880_reference": read_k880_spy_anchor(),
                "k1710_spy_mixed_anchor_prg_first_t_negative_prg_better":
                    results["markets"]["SPY"]["dm_tests"]["mixed_anchor_main"]["t_stat"],
                "k1710_spy_mixed_anchor_prg_better": bool(
                    results["markets"]["SPY"]["dm_tests"]["mixed_anchor_main"]["t_stat"] < 0
                ),
                "direction_matches_k880": bool(
                    results["markets"]["SPY"]["dm_tests"]["mixed_anchor_main"]["t_stat"] < 0
                ),
                "note": (
                    "Direction check only: K880 has PRG_Extended beating GJR (GJR-vs-PRG "
                    "t positive ~ +5 to +6.45 across vintages); K1710's PRG-first "
                    "mixed-anchor t must be large NEGATIVE (PRG better). Point value is "
                    "not a bit-identical target across vintages."
                ),
            },
        },
        "markets": results["markets"],
        "relation_to_prior": {
            "K1699": "close-convention panel (strict t-1), same pinned vintage, 0/6 Harvey vs GJR",
            "K1544": "open-convention panel, UNPINNED 2026-06-24 data (vintage-fragile caveat)",
            "K880": (
                "mixed-timing canonical headline (ill-posed timing artifact): PRG_Extended "
                "beats GJR on SPY with GJR-vs-PRG t ~ +5.06 (2026-06-13 rerun, directional) "
                "to +6.4537 (checked-in original artifact); both = PRG better. See "
                "anchor_validation.mixed_anchor_vs_k880_spy for the pinned provenance."
            ),
            "role": (
                "K1710 supplies panels A (open) and B (mixed) on the K1699 vintage so the "
                "paper's three-convention main table is single-vintage and reproduce-gated."
            ),
        },
        "references": [
            "Bollerslev and Ghysels (1996), Periodic autoregressive conditional heteroskedasticity.",
            "Patton (2011), Volatility forecast comparison using imperfect volatility proxies.",
            "Diebold and Mariano (1995), Comparing predictive accuracy.",
            "Harvey, Leybourne, and Newbold (1997), Testing equality of prediction MSEs.",
            "Harvey, Liu, and Zhu (2016), ...and the cross-section of expected returns.",
            "Linton and Wu (2020), A coupled component DCS-EGARCH model for intraday and overnight volatility.",
        ],
        "runtime_seconds": float(time.time() - start),
    })

    write_tables({"markets": results["markets"]})
    make_chart({"markets": results["markets"]})

    for name in ["K1710_results.json", "results.json"]:
        with (EXP_DIR / name).open("w", encoding="utf-8") as f:
            json.dump(core_json, f, indent=2, ensure_ascii=False)

    print("\nSummary table:")
    print((EXP_DIR / "per_market_table.md").read_text(encoding="utf-8"))
    print("\nAnchor validation (open panel, K1544 orientation flip):")
    for m, a in anchor_report.items():
        print(f"  {m}: K1710 open t={a['open_panel_prg_vs_fairgjrx_t']:+.3f} "
              f"(=> K1544-orient {a['k1544_orientation_equivalent_t']:+.3f}, "
              f"K1544 anchor {a['k1544_open_anchor_fair_minus_prg_t']:+.3f}); "
              f"mixed t={a['mixed_anchor_prg_vs_gjr_t']:+.3f}")
    print(f"\nSaved results to {EXP_DIR}")


if __name__ == "__main__":
    main()
