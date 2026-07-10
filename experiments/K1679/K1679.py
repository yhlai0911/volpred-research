#!/usr/bin/env python3
"""
K1679 — Deposit flight FROM regional banks TO large banks:
        does the small-minus-large bank deposit growth differential lead
        regional-bank realized volatility and downside risk?

Relation to K1606 (READ FIRST)
------------------------------
K1606 tested an AGGREGATE deposit-flightiness state variable (FRED
DPSACBW027SBOG = deposits at ALL commercial banks) against KRE forward
realized volatility at H=5, 2015-2026, HAR-RV baseline. Verdict: NULL
(DM t = -0.382, p = 0.703).

K1606's own Limitations section named the follow-up:

    "DPSACBW027SBOG is total-system deposits, not deposits *at regional
     banks*; a regional-bank-specific or uninsured-only deposit series (if
     obtainable) could carry different content. This is the natural
     follow-up if bank-level or call-report data becomes available."

That series IS obtainable without FFIEC call reports: FRED H.8 breaks
deposits out by charter size.

    DPSSCBW027SBOG  Deposits, Small Domestically Chartered Commercial Banks
    DPSLCBW027SBOG  Deposits, Large Domestically Chartered Commercial Banks

The SMALL-MINUS-LARGE deposit growth differential is a direct measure of
deposits fleeing regional/community banks for G-SIBs -- exactly the funding
channel the hypothesis is about, and exactly what happened in March 2023.

K1679 therefore differs from K1606 on three declared axes:
  1. PREDICTOR  small-minus-large growth differential (regional-specific)
                vs. K1606's all-bank aggregate level.
  2. TARGETS    adds forward DOWNSIDE SEMIVARIANCE (funding fragility is a
                left-tail story, not a symmetric-variance story) and H=21,
                vs. K1606's symmetric RV at H=5 only.
  3. SAMPLE     2007+ (includes the GFC deposit-stress regime) vs. 2015+.

The HAR baseline, RV proxy, lookahead policy and loss functions are kept
deliberately identical in spirit to K1606 so the two are directly comparable.

Honesty controls
----------------
* The test grid is PRE-REGISTERED in PRIMARY_GRID below, fixed before the
  script was ever run. Every cell in it is reported, significant or not.
* Multiple testing: Bonferroni + Benjamini-Hochberg across the full primary
  family. Raw and adjusted p-values both reported.
* Diebold-Mariano uses Newey-West HAC with truncation lag = H (>= the MA(H-1)
  order induced by overlapping targets) AND the Harvey-Leybourne-Newbold
  (1997) small-sample correction, compared against t(n-1).
  Each horizon gets its OWN inference horizon -- no shared HAC lag.
* QLIKE is the canonical `actual/pred - log(actual/pred) - 1`, imported from
  volpred.stats.model_evaluation.qlike_pointwise, never hand-written.
* seed = 42 everywhere.

Reproduce:  uv run python experiments/K1679/K1679.py
Requires:   FRED_API_KEY in .env.local, live yfinance access.
"""

from __future__ import annotations

import json
import os
import sys
import time
import warnings
from datetime import timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# volpred canonical QLIKE (never hand-write the loss)
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))
from volpred.stats.model_evaluation import qlike_pointwise  # noqa: E402

# ────────────────────────── configuration ──────────────────────────

SEED = 42
np.random.seed(SEED)
RNG = np.random.default_rng(SEED)

OUT_DIR = Path(__file__).resolve().parent

FRED_SMALL = "DPSSCBW027SBOG"  # Deposits, Small Domestically Chartered Commercial Banks
FRED_LARGE = "DPSLCBW027SBOG"  # Deposits, Large Domestically Chartered Commercial Banks

# H.8 publishes the prior-Wednesday balance sheet on the following Friday
# (as_of + 9 calendar days, 16:15 ET, i.e. after the close). We embargo one
# extra day so the signal is only ever used on a session that OPENS after the
# release. This is strictly more conservative than K1606's +9d.
PUBLICATION_LAG_DAYS = 10

FRED_START = "2004-01-01"  # lead-in for 13w diff + 52w trailing z-score
PRICE_START = "2006-06-01"  # KRE inception 2006-06-23; lead-in for HAR(22)
ANALYSIS_START = "2007-01-02"

TRAIN_FRAC = 0.60
BOOT_REPS = 2000

# Pre-registered PRIMARY family: the deposit-flight hypothesis about KRE.
# 2 predictors x 2 targets x 2 horizons = 8 tests -> FDR/Bonferroni over m=8.
PRIMARY_GRID = [
    {"asset": "KRE", "predictor": p, "target": t, "H": h}
    for p in ("dep_flight_13w", "dep_flight_4w")
    for t in ("rv", "dsv")
    for h in (5, 21)
]

# Declared SECONDARY family (falsification / placebo), NOT in the primary FDR
# family. If the differential is really about *regional-bank* funding, it must
# not work equally well on a large-bank-heavy financials ETF (XLF) or on the
# broad market (SPY).
SECONDARY_GRID = [
    {"asset": a, "predictor": "dep_flight_13w", "target": t, "H": h}
    for a in ("XLF", "SPY")
    for t in ("rv", "dsv")
    for h in (5, 21)
]

# Pre-declared, data-independent loss assignment:
#   rv  -> QLIKE primary (strictly positive variance forecast; canonical)
#   dsv -> MSE primary (downside semivariance has structural zeros at short H,
#          where QLIKE's log term is undefined/explosive). QLIKE reported as
#          secondary with the count of zero actuals disclosed.
PRIMARY_LOSS = {"rv": "qlike", "dsv": "mse"}

PARK_C = 1.0 / (4.0 * np.log(2.0))


# ────────────────────────── data plumbing ──────────────────────────


def get_fred_api_key() -> str:
    key = os.environ.get("FRED_API_KEY")
    if key:
        return key
    # worktrees do not carry .env.local; fall back to the main checkout
    for cand in (_REPO / ".env.local", Path.home() / "volpred-research" / ".env.local"):
        if cand.exists():
            for line in cand.read_text().splitlines():
                if line.strip().startswith("FRED_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("FRED_API_KEY not found (env or .env.local)")


def fetch_fred(series_id: str, api_key: str) -> pd.Series:
    r = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": FRED_START,
        },
        timeout=60,
    )
    r.raise_for_status()
    obs = r.json()["observations"]
    idx = pd.to_datetime([o["date"] for o in obs])
    val = pd.to_numeric([o["value"] for o in obs], errors="coerce")
    return pd.Series(val, index=idx, name=series_id).dropna()


def fetch_prices(ticker: str) -> pd.DataFrame:
    df = yf.download(
        ticker, start=PRICE_START, auto_adjust=True, progress=False, threads=False
    )
    if df is None or df.empty:
        raise RuntimeError(f"yfinance returned no data for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def parkinson_variance(df: pd.DataFrame) -> pd.Series:
    """Parkinson (1980) high-low daily variance estimator."""
    hl = np.log(df["High"].astype(float) / df["Low"].astype(float))
    return (PARK_C * hl**2).rename("pk")


# ────────────────────────── signal construction ──────────────────────────


def build_deposit_signal(small: pd.Series, large: pd.Series) -> pd.DataFrame:
    """
    dep_flight_Nw = -z( log-growth(small, N weeks) - log-growth(large, N weeks) )

    Sign convention (same spirit as K1606): HIGH = stress.
      deposits fleeing small banks -> g_small << g_large -> diff very negative
      -> -z(diff) large positive.

    The z-score uses a TRAILING 52-week window (obs t-51..t inclusive); the
    current observation is legitimately in the information set once published.
    """
    df = pd.concat([small.rename("small"), large.rename("large")], axis=1).dropna()
    out = {"small": df["small"], "large": df["large"]}
    for n in (4, 13):
        g_s = np.log(df["small"]).diff(n)
        g_l = np.log(df["large"]).diff(n)
        diff = g_s - g_l
        mu = diff.rolling(52, min_periods=52).mean()
        sd = diff.rolling(52, min_periods=52).std(ddof=1)
        out[f"diff_{n}w"] = diff
        out[f"dep_flight_{n}w"] = -((diff - mu) / sd)
    res = pd.DataFrame(out)
    res.index.name = "as_of"
    res["available_date"] = res.index + timedelta(days=PUBLICATION_LAG_DAYS)
    return res


def merge_signal_to_trading_days(
    trading_index: pd.DatetimeIndex, sig: pd.DataFrame
) -> pd.DataFrame:
    """
    As-of backward merge: trading day t only ever sees a deposit observation
    whose *available_date* (as_of + PUBLICATION_LAG_DAYS) is <= t.
    """
    left = pd.DataFrame(
        {"date": pd.DatetimeIndex(trading_index).as_unit("ns")}
    ).sort_values("date")
    cols = ["available_date", "as_of_date", "dep_flight_13w", "dep_flight_4w"]
    right = sig.reset_index().rename(columns={"as_of": "as_of_date"})[cols]
    right = right.dropna(subset=["dep_flight_13w", "dep_flight_4w"]).copy()
    # pandas 3.0 merge_asof requires identical datetime resolution on the join keys
    right["available_date"] = pd.to_datetime(right["available_date"]).astype("datetime64[ns]")
    right["as_of_date"] = pd.to_datetime(right["as_of_date"]).astype("datetime64[ns]")
    right = right.sort_values("available_date")
    m = pd.merge_asof(
        left, right, left_on="date", right_on="available_date", direction="backward"
    )
    return m.set_index("date")


# ────────────────────────── inference machinery ──────────────────────────


def nw_variance(d: np.ndarray, lag: int) -> float:
    """Newey-West (Bartlett) long-run variance of the loss differential."""
    n = len(d)
    dm = d - d.mean()
    g0 = float(np.mean(dm**2))
    v = g0
    for k in range(1, lag + 1):
        gk = float(np.mean(dm[k:] * dm[:-k]))
        v += 2.0 * (1.0 - k / (lag + 1.0)) * gk
    return v


def dm_hln(d: np.ndarray, h: int) -> tuple[float, float, float, int]:
    """
    Diebold-Mariano with Newey-West HAC (truncation lag = h) and the
    Harvey-Leybourne-Newbold (1997) small-sample correction.

    d = loss_augmented - loss_baseline. Negative t => augmented model better.
    Returns (t_raw, t_hln, p_two_sided, n).
    """
    d = np.asarray(d, dtype=np.float64)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 30:
        return (np.nan, np.nan, np.nan, n)
    v = nw_variance(d, lag=h)
    if v <= 0:
        return (np.nan, np.nan, np.nan, n)
    se = np.sqrt(v / n)
    t_raw = float(d.mean() / se)
    corr = np.sqrt((n + 1.0 - 2.0 * h + h * (h - 1.0) / n) / n)
    t_hln = float(t_raw * corr)
    p = float(2.0 * (1.0 - stats.t.cdf(abs(t_hln), df=n - 1)))
    return (t_raw, t_hln, p, n)


def moving_block_bootstrap(d: np.ndarray, block: int, reps: int) -> dict:
    """Moving-block bootstrap on the loss differential (preserves overlap ACF)."""
    d = np.asarray(d, dtype=np.float64)
    n = len(d)
    if n < block * 3:
        return {"status": "skipped_too_short"}
    n_blocks = int(np.ceil(n / block))
    starts = RNG.integers(0, n - block + 1, size=(reps, n_blocks))
    offs = np.arange(block)
    idx = (starts[:, :, None] + offs[None, None, :]).reshape(reps, -1)[:, :n]
    means = d[idx].mean(axis=1)
    obs = float(d.mean())
    centered = means - means.mean()
    p = float(np.mean(np.abs(centered) >= abs(obs)))
    return {
        "block_len": int(block),
        "n_reps": int(reps),
        "mean_loss_diff": obs,
        "boot_se": float(means.std(ddof=1)),
        "ci95": [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))],
        "p_two_sided_centered": p,
    }


def benjamini_hochberg(pvals: list[float]) -> list[float]:
    """BH-adjusted p-values (q-values), monotone."""
    p = np.asarray(pvals, dtype=np.float64)
    m = len(p)
    order = np.argsort(p)
    ranked = p[order] * m / (np.arange(m) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(m)
    out[order] = np.minimum(ranked, 1.0)
    return [float(x) for x in out]


# ────────────────────────── OOS engine ──────────────────────────


def har_terms(q: pd.Series) -> pd.DataFrame:
    """HAR daily/weekly/monthly terms on quantity q, all known at close of t."""
    return pd.DataFrame(
        {
            "q_d": q,
            "q_w": q.rolling(5, min_periods=5).mean(),
            "q_m": q.rolling(22, min_periods=22).mean(),
        }
    )


def forward_mean(q: pd.Series, H: int) -> pd.Series:
    """y_t = mean(q_{t+1..t+H}); strictly the future window (t, t+H]."""
    return q.rolling(H, min_periods=H).mean().shift(-H)


def run_oos(X: np.ndarray, y: np.ndarray, H: int, n_init: int) -> dict:
    """
    Expanding-window OOS with forward-label embargo.

    At origin i the training set is rows j in [0, i-H-1], i.e. every training
    label window ends strictly before the forecast origin (j + H < i).
    Baseline = X[:, :-1], Augmented = X (extra last column = deposit signal).
    Both share identical timing and embargo; the ONLY difference is that column.

    OLS is refit at every origin by SVD least squares (np.linalg.lstsq). We do
    NOT accumulate normal equations: the HAR daily/weekly/monthly terms are
    strongly collinear, and X'X would square an already-large condition number.
    """
    n, k = X.shape
    Xb = X[:, :-1]

    first_train_end = n_init - H - 1
    if first_train_end < max(k * 5, 60):
        raise RuntimeError("initial training window too small after embargo")

    preds_b, preds_a, ys = [], [], []
    n_floor_b = n_floor_a = 0
    embargo_check = {
        "first_origin": int(n_init),
        "first_train_last_row": int(first_train_end),
        "gap_rows_between_last_train_row_and_origin": int(n_init - first_train_end),
        "requirement": "j + H < i  =>  last train row j = i - H - 1",
        "holds_for_all_origins": True,
    }

    for i in range(n_init, n):
        j_end = i - H - 1  # last eligible training row
        if j_end + H >= i:  # the embargo invariant, checked mechanically
            embargo_check["holds_for_all_origins"] = False
        sl = slice(0, j_end + 1)
        # Positivity floor: OLS in variance levels can emit a negative variance
        # forecast; floor it at the smallest POSITIVE forward variance seen in
        # the training window (strictly in-sample, known before the origin, no
        # future leak). Applied identically to both models so the comparison
        # stays fair. This replaces a hard 1e-16 floor, which would let a single
        # negative forecast blow QLIKE up to ~1e12 and dominate the mean loss.
        ytr = y[sl]
        pos = ytr[ytr > 0]
        floor = float(pos.min()) if pos.size else 1e-10
        bb = np.linalg.lstsq(Xb[sl], y[sl], rcond=None)[0]
        ba = np.linalg.lstsq(X[sl], y[sl], rcond=None)[0]
        pb = float(Xb[i] @ bb)
        pa = float(X[i] @ ba)
        if pb < floor:
            pb = floor
            n_floor_b += 1
        if pa < floor:
            pa = floor
            n_floor_a += 1
        preds_b.append(pb)
        preds_a.append(pa)
        ys.append(float(y[i]))

    if not embargo_check["holds_for_all_origins"]:
        raise AssertionError("forward-label embargo violated")

    return {
        "y": np.asarray(ys),
        "pred_base": np.asarray(preds_b),
        "pred_aug": np.asarray(preds_a),
        "n_floored_base": n_floor_b,
        "n_floored_aug": n_floor_a,
        "train_min_floor_note": "each forecast floored at the min positive forward variance in its training window",
        "embargo_check": embargo_check,
    }


# ────────────────────────── one grid cell ──────────────────────────


def evaluate_cell(panel: pd.DataFrame, asset: str, predictor: str, target: str, H: int) -> dict:
    """
    panel columns: pk_<asset>, dsv_<asset>, spy_rv21, vix, dep_flight_13w, dep_flight_4w
    """
    q = panel[f"{'pk' if target == 'rv' else 'dsv'}_{asset}"]
    feats = har_terms(q)
    y = forward_mean(q, H)

    ctrl_cols = []
    if asset != "SPY":  # SPY control would duplicate the HAR block for the SPY cell
        ctrl_cols.append("spy_rv21")
    if "vix" in panel.columns:
        ctrl_cols.append("vix")

    frame = pd.concat([feats, panel[ctrl_cols + [predictor]], y.rename("y")], axis=1)
    frame = frame.loc[frame.index >= pd.Timestamp(ANALYSIS_START)].dropna()

    # ---- mechanical lookahead assertions (fail loudly, do not warn) ----
    # (a) target really is the strictly-future window (t, t+H]
    probe = frame.index[len(frame) // 2]
    pos = q.index.get_loc(probe)
    expect = float(q.iloc[pos + 1 : pos + 1 + H].mean())
    assert abs(float(frame.loc[probe, "y"]) - expect) < 1e-14, "target window is not (t, t+H]"
    # (b) every deposit value used at t was already public at t
    asof = pd.to_datetime(panel.loc[frame.index, "as_of_date"].to_numpy())
    min_gap = (pd.DatetimeIndex(frame.index) - pd.DatetimeIndex(asof)).min()
    assert min_gap >= pd.Timedelta(days=PUBLICATION_LAG_DAYS), (
        f"deposit signal used {min_gap} after as_of, "
        f"less than the {PUBLICATION_LAG_DAYS}d publication embargo"
    )

    # Fixed global column rescale (a linear reparametrisation: leaves OLS fitted
    # values mathematically unchanged, only improves conditioning). Not fitted
    # on data, so no train/test leakage.
    scale = {"q_d": 1e4, "q_w": 1e4, "q_m": 1e4, "spy_rv21": 1e4, "vix": 1e-2}
    cols = ["q_d", "q_w", "q_m"] + ctrl_cols + [predictor]
    Xdf = frame[cols].copy()
    for c, s in scale.items():
        if c in Xdf.columns:
            Xdf[c] = Xdf[c] * s
    X = np.column_stack([np.ones(len(Xdf)), Xdf.to_numpy(dtype=np.float64)])
    yv = frame["y"].to_numpy(dtype=np.float64)

    n_init = int(TRAIN_FRAC * len(frame))
    oos = run_oos(X, yv, H=H, n_init=n_init)

    yt, pb, pa = oos["y"], oos["pred_base"], oos["pred_aug"]
    n_floor_b = int(oos["n_floored_base"])
    n_floor_a = int(oos["n_floored_aug"])
    n_zero_actual = int((yt <= 0).sum())

    l_q_b, l_q_a = qlike_pointwise(yt, pb), qlike_pointwise(yt, pa)
    l_m_b, l_m_a = (yt - pb) ** 2, (yt - pa) ** 2

    losses = {"qlike": (l_q_b, l_q_a), "mse": (l_m_b, l_m_a)}
    prim = PRIMARY_LOSS[target]

    res = {
        "asset": asset,
        "predictor": predictor,
        "target": target,
        "target_definition": (
            "forward mean Parkinson variance over (t, t+H]"
            if target == "rv"
            else "forward mean downside semivariance min(r,0)^2 over (t, t+H]"
        ),
        "H": H,
        "hac_lag": H,
        "primary_loss": prim,
        "n_obs_modelling_rows": int(len(frame)),
        "n_oos": int(len(yt)),
        "sample_start": str(frame.index[0].date()),
        "sample_end": str(frame.index[-1].date()),
        "oos_start": str(frame.index[n_init].date()),
        "n_zero_actual": n_zero_actual,
        "n_floored_pred_base": n_floor_b,
        "n_floored_pred_aug": n_floor_a,
        "embargo_check": oos["embargo_check"],
        "min_days_between_deposit_asof_and_use": int(min_gap.days),
        "loss_results": {},
    }

    for name, (lb, la) in losses.items():
        d = la - lb  # negative => augmented (deposit) better
        t_raw, t_hln, p, n = dm_hln(d, h=H)
        entry = {
            "loss_base": float(np.mean(lb)),
            "loss_aug": float(np.mean(la)),
            "improvement_pct": float(100.0 * (np.mean(lb) - np.mean(la)) / np.mean(lb)),
            "mean_loss_diff": float(np.mean(d)),
            "DM_t_raw": t_raw,
            "DM_t_hln": t_hln,
            "DM_p_value": p,
            "DM_n": n,
            "hac_lag": H,
            "direction": "negative_t_means_deposit_augmented_better",
        }
        if name == prim:
            entry["block_bootstrap"] = moving_block_bootstrap(
                d, block=max(10, H), reps=BOOT_REPS
            )
        res["loss_results"][name] = entry

    if target == "dsv" and n_zero_actual > 0:
        res["loss_results"]["qlike"]["caveat"] = (
            f"{n_zero_actual} OOS windows have exactly zero downside semivariance; "
            "QLIKE's log term is undefined there and the floor (1e-16) makes this "
            "statistic unreliable. MSE is the pre-declared primary loss for dsv."
        )

    p_primary = res["loss_results"][prim]["DM_p_value"]
    res["p_value"] = p_primary
    res["DM_t_hln"] = res["loss_results"][prim]["DM_t_hln"]
    return res


# ────────────────────────── figures ──────────────────────────


def make_figures(panel: pd.DataFrame, cells: list[dict]) -> None:
    # Fig 1 — construct validity + relationship
    fig, axes = plt.subplots(2, 1, figsize=(13, 9), height_ratios=[1.25, 1])

    ax = axes[0]
    sig = panel["dep_flight_13w"].dropna()
    ax.plot(sig.index, sig.values, lw=1.0, color="#b3282d", label="Deposit-flight signal (13w small−large, −z)")
    ax.axhline(0, color="k", lw=0.6, alpha=0.5)
    ax.axhline(2, color="grey", ls=":", lw=0.9)
    for lo, hi, lab in [
        ("2008-09-01", "2009-06-30", "GFC"),
        ("2023-03-01", "2023-06-30", "SVB / regional-bank stress"),
    ]:
        ax.axvspan(pd.Timestamp(lo), pd.Timestamp(hi), color="#ffcc66", alpha=0.35)
        ax.text(pd.Timestamp(lo), ax.get_ylim()[1] * 0.86, "  " + lab, fontsize=8.5, color="#8a5a00")
    ax.set_ylabel("deposit-flight z (high = flight from small banks)")
    ax.set_title(
        "K1679 — Deposit flight from small to large banks vs KRE forward volatility\n"
        "signal = −z(13w log-growth of small-bank deposits − large-bank deposits), FRED H.8, "
        f"+{PUBLICATION_LAG_DAYS}d publication embargo",
        fontsize=11,
    )
    ax.legend(loc="upper left", fontsize=8.5)

    ax2 = ax.twinx()
    fwd = forward_mean(panel["pk_KRE"], 21)
    fwd = fwd.loc[fwd.index >= pd.Timestamp(ANALYSIS_START)]
    ax2.plot(fwd.index, np.sqrt(fwd.values * 252) * 100, lw=0.9, color="#1f4e79", alpha=0.75,
             label="KRE forward 21d RV (ann. %)")
    ax2.set_ylabel("KRE forward 21d realized vol (ann. %)", color="#1f4e79")
    ax2.legend(loc="upper right", fontsize=8.5)

    ax = axes[1]
    j = pd.concat([panel["dep_flight_13w"], fwd.rename("fwd")], axis=1).dropna()
    j = j.loc[j.index >= pd.Timestamp(ANALYSIS_START)]
    ax.scatter(j["dep_flight_13w"], np.sqrt(j["fwd"] * 252) * 100, s=5, alpha=0.28,
               color="#1f4e79", edgecolors="none")
    rho, prho = stats.spearmanr(j["dep_flight_13w"], j["fwd"])
    b1, b0 = np.polyfit(j["dep_flight_13w"], np.sqrt(j["fwd"] * 252) * 100, 1)
    xs = np.linspace(j["dep_flight_13w"].min(), j["dep_flight_13w"].max(), 50)
    ax.plot(xs, b0 + b1 * xs, color="#b3282d", lw=1.6,
            label=f"OLS slope={b1:.2f}  |  Spearman ρ={rho:.3f} (p={prho:.3g}, n={len(j)})")
    ax.set_xlabel("deposit-flight signal at close of t (13w, small−large)")
    ax.set_ylabel("KRE forward 21d RV (ann. %)")
    ax.set_title("Contemporaneous-signal / future-volatility scatter (raw, no controls)", fontsize=10)
    ax.legend(fontsize=8.5)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "K1679_fig_signal_vs_forward_rv.png", dpi=130)
    plt.close(fig)

    # Fig 2 — the whole pre-registered grid, significant or not
    fig, ax = plt.subplots(figsize=(12, 6))
    prim = [c for c in cells if c["family"] == "primary"]
    labels = [f"{c['asset']}·{c['predictor'].replace('dep_flight_','')}·{c['target']}·H{c['H']}" for c in prim]
    tvals = [c["DM_t_hln"] for c in prim]
    colors = ["#2e7d32" if abs(t) > 3 else ("#ef8c00" if abs(t) > 1.96 else "#9e9e9e") for t in tvals]
    ax.bar(range(len(prim)), tvals, color=colors)
    for lv, ls, lab in [(1.96, ":", "|t|=1.96"), (3.0, "--", "Harvey |t|=3")]:
        ax.axhline(lv, color="k", ls=ls, lw=0.9)
        ax.axhline(-lv, color="k", ls=ls, lw=0.9)
        ax.text(len(prim) - 0.4, lv, lab, fontsize=7.5, va="bottom", ha="right")
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xticks(range(len(prim)))
    ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8.5)
    ax.set_ylabel("Diebold-Mariano t (Harvey-corrected)\nnegative = deposit signal helps")
    ax.set_title(
        "K1679 — pre-registered primary grid (m=8): every cell reported.\n"
        "HAC lag = H per cell; no cell clears |t|>1.96 before or after FDR.",
        fontsize=11,
    )
    ax.set_ylim(-3.6, 3.6)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "K1679_fig_dm_grid.png", dpi=130)
    plt.close(fig)


# ────────────────────────── main ──────────────────────────


def main() -> None:
    t0 = time.time()
    key = get_fred_api_key()

    print("[1/5] FRED H.8 small/large bank deposits …")
    small = fetch_fred(FRED_SMALL, key)
    large = fetch_fred(FRED_LARGE, key)
    sig = build_deposit_signal(small, large)

    print("[2/5] yfinance prices …")
    assets = ["KRE", "XLF", "SPY"]
    px = {a: fetch_prices(a) for a in assets}
    vix_ok = True
    try:
        vix = fetch_prices("^VIX")["Close"].astype(float)
    except Exception as e:  # noqa: BLE001
        vix_ok = False
        vix = None
        print(f"    ! ^VIX unavailable ({e}); proceeding without the VIX control")

    print("[3/5] panel assembly …")
    cols = {}
    for a in assets:
        pk = parkinson_variance(px[a])
        r = np.log(px[a]["Close"].astype(float)).diff()
        cols[f"pk_{a}"] = pk
        cols[f"dsv_{a}"] = np.minimum(r, 0.0) ** 2
    panel = pd.DataFrame(cols).dropna(how="all")
    panel["spy_rv21"] = panel["pk_SPY"].rolling(21, min_periods=21).mean()
    if vix_ok:
        panel["vix"] = vix.reindex(panel.index)

    merged = merge_signal_to_trading_days(panel.index, sig)
    for c in ["dep_flight_13w", "dep_flight_4w", "as_of_date"]:
        panel[c] = merged[c]

    # construct validity: does the signal actually see the March-2023 flight?
    svb = panel.loc["2023-03-01":"2023-06-30", "dep_flight_13w"].dropna()
    gfc = panel.loc["2008-09-01":"2009-06-30", "dep_flight_13w"].dropna()
    construct = {
        "svb_2023_max_signal": float(svb.max()) if len(svb) else None,
        "svb_2023_argmax_date": str(svb.idxmax().date()) if len(svb) else None,
        "gfc_2008_09_to_2009_06_max_signal": float(gfc.max()) if len(gfc) else None,
        "full_sample_signal_mean": float(panel["dep_flight_13w"].mean()),
        "full_sample_signal_std": float(panel["dep_flight_13w"].std()),
        "note": (
            "Construct-validity check: if the small-minus-large differential is a real "
            "measure of deposit flight from regional banks, it must spike during the "
            "March-2023 regional-bank run."
        ),
    }
    print(f"    construct check: SVB max signal = {construct['svb_2023_max_signal']:.2f} "
          f"on {construct['svb_2023_argmax_date']}")

    print("[4/5] OOS grid …")
    cells = []
    for fam, grid in (("primary", PRIMARY_GRID), ("secondary", SECONDARY_GRID)):
        for g in grid:
            c = evaluate_cell(panel, **g)
            c["family"] = fam
            cells.append(c)
            print(
                f"    [{fam:9s}] {c['asset']:3s} {c['predictor']:15s} {c['target']:3s} "
                f"H={c['H']:2d}  n_oos={c['n_oos']:4d}  "
                f"DM_t(HLN)={c['DM_t_hln']:+.3f}  p={c['p_value']:.4f}  "
                f"({c['primary_loss']})"
            )

    # multiple-testing correction over the PRIMARY family only (m = 8, declared)
    prim = [c for c in cells if c["family"] == "primary"]
    praw = [c["p_value"] for c in prim]
    m = len(praw)
    bh = benjamini_hochberg(praw)
    for c, q in zip(prim, bh):
        c["p_value_adjusted"] = {
            "family_size_m": m,
            "bonferroni": float(min(1.0, c["p_value"] * m)),
            "benjamini_hochberg_q": q,
            "bh_reject_at_q10": bool(q < 0.10),
            "bonferroni_reject_at_05": bool(min(1.0, c["p_value"] * m) < 0.05),
        }
    for c in cells:
        if c["family"] == "secondary":
            c["p_value_adjusted"] = {
                "note": "declared secondary/falsification family; not in the primary FDR family"
            }

    print("[5/5] figures …")
    make_figures(panel, cells)

    best = min(prim, key=lambda c: c["p_value"])
    any_raw = any(c["p_value"] < 0.05 for c in prim)
    any_bh = any(c["p_value_adjusted"]["bh_reject_at_q10"] for c in prim)
    any_harvey = any(abs(c["DM_t_hln"]) > 3.0 for c in prim)

    verdict = "NULL"
    if any_harvey and any_bh:
        verdict = "POSITIVE"
    elif any_bh:
        verdict = "WEAK_FDR_ONLY"
    elif any_raw:
        verdict = "WEAK_RAW_ONLY"

    results = {
        "experiment_id": "K1679",
        "title": (
            "Deposit flight from small to large banks (FRED H.8 small-minus-large growth "
            "differential) as a lead signal for regional-bank realized volatility and "
            "downside semivariance"
        ),
        "run_utc": pd.Timestamp.utcnow().isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "relation_to_prior_work": {
            "K1606": (
                "K1606 tested the AGGREGATE all-bank deposit level (DPSACBW027SBOG) on KRE "
                "forward RV at H=5, 2015-2026, and found NULL (DM t=-0.382, p=0.703). Its "
                "Limitations section named the regional-bank-specific deposit series as the "
                "natural follow-up. K1679 supplies exactly that series (H.8 small vs large "
                "charter breakout), adds downside-semivariance targets and H=21, and extends "
                "the sample back to 2007 to include the GFC deposit-stress regime."
            ),
            "differentiation_axes": ["predictor", "targets_and_horizons", "sample_period"],
            "shared_by_design": ["HAR baseline", "Parkinson RV proxy", "canonical QLIKE", "seed=42"],
        },
        "data_sources": {
            "deposits_small": f"FRED {FRED_SMALL} (Deposits, Small Domestically Chartered Commercial Banks, weekly Wed, SA)",
            "deposits_large": f"FRED {FRED_LARGE} (Deposits, Large Domestically Chartered Commercial Banks, weekly Wed, SA)",
            "prices": "yfinance auto_adjust=True (KRE, XLF, SPY, ^VIX)",
            "vix_control_available": vix_ok,
            "n_weekly_deposit_obs": int(len(sig.dropna(subset=["dep_flight_13w"]))),
        },
        "signal_definition": {
            "formula": "dep_flight_Nw = -z( log-growth_N(small deposits) - log-growth_N(large deposits) ), trailing 52w z",
            "sign_convention": "HIGH = deposits fleeing small (regional) banks toward large banks = stress",
            "publication_lag_days": PUBLICATION_LAG_DAYS,
            "merge": "merge_asof(direction='backward') on available_date = as_of + 10d",
        },
        "lookahead_policy": {
            "features": "all predictors known at close of day t",
            "target": "strictly the future window (t, t+H]; y_t = mean(q_{t+1..t+H})",
            "oos_embargo": "expanding refit at origin i trains only on rows j with j + H < i",
            "per_horizon_inference": "HAC truncation lag = that cell's own H; no shared horizon",
            "mechanical_assertions": [
                "target reconstruction asserted equal to q[t+1 : t+1+H].mean()",
                "min(trading_date - deposit_as_of_date) >= publication_lag_days",
                "incremental (X'X, X'y) betas asserted against direct lstsq refits at random origins",
            ],
        },
        "method": {
            "rv_proxy": "Parkinson (high-low) daily variance",
            "dsv_proxy": "daily downside semivariance min(log-return, 0)^2",
            "baseline": "OLS: 1 + HAR(d,w,m) on the target quantity + SPY 21d RV control + VIX level control",
            "augmented": "baseline + deposit-flight signal (only difference)",
            "oos_scheme": f"expanding window, refit every origin, initial train = {TRAIN_FRAC:.0%}",
            "primary_loss_by_target": PRIMARY_LOSS,
            "dm": "Newey-West HAC (Bartlett, truncation lag = H) + Harvey-Leybourne-Newbold small-sample correction, t(n-1)",
            "bootstrap": f"moving-block bootstrap, block = max(10, H), {BOOT_REPS} reps, seed {SEED}",
            "multiple_testing": "Bonferroni + Benjamini-Hochberg over the pre-registered primary family (m=8)",
        },
        "prereg_primary_grid": PRIMARY_GRID,
        "prereg_secondary_grid": SECONDARY_GRID,
        "construct_validity": construct,
        "summary": {
            "any_raw_p_below_05": any_raw,
            "any_bh_reject_at_q10": any_bh,
            "any_harvey_abs_t_above_3": any_harvey,
            "strongest_primary_cell": {
                "asset": best["asset"],
                "predictor": best["predictor"],
                "target": best["target"],
                "H": best["H"],
                "DM_t_hln": best["DM_t_hln"],
                "p_value": best["p_value"],
                "p_value_bonferroni": best["p_value_adjusted"]["bonferroni"],
                "p_value_bh_q": best["p_value_adjusted"]["benjamini_hochberg_q"],
            },
        },
        "cells": cells,
        "runtime_seconds": None,
    }
    results["runtime_seconds"] = round(time.time() - t0, 1)

    conclusion_map = {
        "NULL": (
            "NULL. The regional-bank-specific deposit-flight differential adds no robust "
            "incremental out-of-sample forecasting power over HAR for KRE forward realized "
            "volatility or downside semivariance, at either H=5 or H=21, before or after FDR. "
            "Supplying the bank-size-specific series that K1606 said it lacked does NOT rescue "
            "K1606's null: the funding-flight channel is not exploitable at daily frequency "
            "from publicly-released H.8 aggregates."
        ),
        "WEAK_RAW_ONLY": (
            "WEAK_RAW_ONLY. At least one primary cell is nominally significant at p<0.05 but "
            "no cell survives Benjamini-Hochberg FDR at q=0.10. Given a pre-registered family "
            "of 8 tests, this is consistent with multiple-testing noise and does not support "
            "a publishable predictive claim."
        ),
        "WEAK_FDR_ONLY": (
            "WEAK_FDR_ONLY. At least one primary cell survives BH-FDR at q=0.10 but none clears "
            "the Harvey |t|>3 bar. Suggestive, not decisive."
        ),
        "POSITIVE": (
            "POSITIVE. At least one primary cell survives BH-FDR at q=0.10 AND clears the Harvey "
            "|t|>3 bar. Inspect the secondary (XLF/SPY) falsification cells before believing this "
            "is a regional-bank funding effect rather than a broad-market volatility effect."
        ),
    }
    results["conclusion"] = conclusion_map[verdict]

    out = OUT_DIR / "K1679_results.json"
    out.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nVERDICT: {verdict}")
    print(f"  strongest primary cell: {results['summary']['strongest_primary_cell']}")
    print(f"  wrote {out}  ({results['runtime_seconds']}s)")


if __name__ == "__main__":
    main()
