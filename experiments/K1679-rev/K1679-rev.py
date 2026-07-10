#!/usr/bin/env python3
"""
K1679-rev — Knowledge-grade revision of K1679's regional-bank deposit-flight NULL.

K1679 (merged to main, Codex verdict = FAIL) found that the H.8 small-minus-large
bank deposit growth differential adds no robust incremental OOS forecasting power
over HAR for KRE forward realized volatility / downside semivariance (directional
NULL, all DM t positive = signal *hurts*). Three method problems blocked
knowledge-grade status. This revision fixes all three and re-tests.

The three fixes (see README §"Three fixes")
-------------------------------------------
1. ALFRED POINT-IN-TIME VINTAGES (lookahead).
   K1679 pulled the *current* FRED vintage of DPSSCBW027SBOG / DPSLCBW027SBOG,
   which embeds later revisions unavailable at the trading date. K1679-rev pulls
   the full ALFRED vintage history and reconstructs the signal AS IT WAS KNOWN at
   each weekly release: at every H.8 release date R_w, the series is snapshotted at
   the vintage current on R_w (older observations at whatever revision was public
   then, not the final revision), the rolling growth/z transform is recomputed on
   that snapshot, and the newest value is taken as the signal for that week. The
   embargo now uses the ACTUAL ALFRED first-print release date (realtime_start),
   +1 calendar day, instead of K1606/K1679's +10d heuristic. Both the current-
   vintage (K1679-style) and the point-in-time signals are run through the full
   grid so the README can show a clean before/after.

2. CLARK-WEST (2007) NESTED-FORECAST TEST.
   The baseline HAR is fully nested in the augmented model, so a standard DM/HLN
   test is biased toward NOT rejecting (biased toward the null). Clark-West adds
   the (pred_base - pred_aug)^2 adjustment term that corrects the estimation-noise
   bias under the null, and is the canonical test for nested-model MSPE comparison.
   It is applied to the two strongest K1679 cells
       dep_flight_4w · dsv · H5   and   dep_flight_4w · rv · H21
   (one-sided upper-tail: reject equal-MSPE in favour of the LARGER/augmented
   model; HAC truncation lag = that cell's own H; HLN small-sample correction).
   If CW flips these cells to significant, the null is not safe; if CW confirms,
   the K1606 -> K1679 funding-flight NULL narrative stands.

3. UN-FLOORED LOSS SENSITIVITY.
   K1679 applied a training-min positivity floor (leak-free, needed for QLIKE on
   RV) uniformly, INCLUDING the DSV/MSE cells that legitimately admit exact zeros;
   the strongest dsv cell had ~50/53 forecasts clipped to a common floor, which
   compresses the between-model difference. MSE needs no positivity floor, so this
   revision recomputes every MSE-based DM on the RAW (un-floored) forecasts as a
   sensitivity, alongside the floored numbers.

Hard constraints preserved from K1679
-------------------------------------
* seed = 42 everywhere.
* Forward-label embargo: at origin i, training rows j satisfy j + H < i.
* Per-horizon inference: every DM/HLN/CW uses its own H as the HAC truncation lag.
* Canonical QLIKE from volpred.stats.model_evaluation.qlike_pointwise (never
  hand-written); QLIKE direction actual/pred - log(actual/pred) - 1.
* Pre-registered primary grid identical to K1679 (2 predictors x 2 targets x 2 H).

Reproduce:  uv run python experiments/K1679-rev/K1679-rev.py
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

# Current-vintage embargo (K1679-style heuristic, kept for the before/after run):
# H.8 publishes the prior-Wednesday balance sheet on the following Friday
# (as_of + ~8 calendar days). +10d gives a 2-day buffer.
PUBLICATION_LAG_DAYS = 10
# Point-in-time embargo: we now KNOW the true ALFRED first-print release date
# (realtime_start), so we only need a 1-day buffer so the signal is used on a
# session that OPENS after the release.
PIT_BUFFER_DAYS = 1

FRED_START = "2004-01-01"  # lead-in for 13w diff + 52w trailing z-score
PRICE_START = "2006-06-01"  # KRE inception 2006-06-23; lead-in for HAR(22)
ANALYSIS_START = "2007-01-02"

TRAIN_FRAC = 0.60
BOOT_REPS = 2000

# Pre-registered PRIMARY family (identical to K1679): 2 predictors x 2 targets x 2 H.
PRIMARY_GRID = [
    {"asset": "KRE", "predictor": p, "target": t, "H": h}
    for p in ("dep_flight_13w", "dep_flight_4w")
    for t in ("rv", "dsv")
    for h in (5, 21)
]

# Declared SECONDARY family (falsification / placebo), NOT in the FDR family.
SECONDARY_GRID = [
    {"asset": a, "predictor": "dep_flight_13w", "target": t, "H": h}
    for a in ("XLF", "SPY")
    for t in ("rv", "dsv")
    for h in (5, 21)
]

# The two strongest K1679 cells that get the Clark-West nested test.
CW_CELLS = [
    {"asset": "KRE", "predictor": "dep_flight_4w", "target": "dsv", "H": 5},
    {"asset": "KRE", "predictor": "dep_flight_4w", "target": "rv", "H": 21},
]

PRIMARY_LOSS = {"rv": "qlike", "dsv": "mse"}
PARK_C = 1.0 / (4.0 * np.log(2.0))


# ────────────────────────── data plumbing ──────────────────────────


def get_fred_api_key() -> str:
    key = os.environ.get("FRED_API_KEY")
    if key:
        return key
    for cand in (_REPO / ".env.local", Path.home() / "volpred-research" / ".env.local"):
        if cand.exists():
            for line in cand.read_text().splitlines():
                if line.strip().startswith("FRED_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("FRED_API_KEY not found (env or .env.local)")


def fetch_fred_current(series_id: str, api_key: str) -> pd.Series:
    """Current (latest-revision) vintage — the K1679 behaviour, kept for the
    before/after comparison."""
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


def fetch_fred_first_release(series_id: str, api_key: str) -> pd.DataFrame:
    """
    ALFRED INITIAL-RELEASE-ONLY vintage (FRED observations output_type=4): for each
    observation date, the value AS FIRST PUBLISHED, plus the true release date
    (realtime_start). This is the point-in-time value actually available at the
    trading date — no later revision is ever used, which is strictly conservative
    and directly removes the K1679 hindsight-revision lookahead.

    One request (~700 rows, well under FRED's 100000-row cap; no pagination /
    truncation risk, unlike a full-vintage pull). NOTE: ALFRED only began archiving
    real-time vintages for the H.8 charter-size deposit series in 2012-08, so a
    genuine point-in-time test cannot reach back to the GFC (2008) — it covers
    2012-08 onward, which still includes the March-2023 (SVB) regional-bank run.

    Returns DataFrame[date, release_date, value], sorted by date.
    """
    r = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": FRED_START,
            "output_type": 4,  # initial release only
            "realtime_start": "1776-07-04",
            "realtime_end": "9999-12-31",
        },
        timeout=120,
    )
    r.raise_for_status()
    obs = r.json()["observations"]
    rows = []
    for o in obs:
        v = pd.to_numeric(o["value"], errors="coerce")
        if pd.isna(v):
            continue
        rows.append(
            {
                "date": pd.Timestamp(o["date"]),
                "release_date": pd.Timestamp(o["realtime_start"]),
                "value": float(v),
            }
        )
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    return df


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
    hl = np.log(df["High"].astype(float) / df["Low"].astype(float))
    return (PARK_C * hl**2).rename("pk")


# ────────────────────────── signal construction ──────────────────────────


def _transform_signal(small: pd.Series, large: pd.Series) -> pd.DataFrame:
    """
    dep_flight_Nw = -z( log-growth(small, N) - log-growth(large, N) ), trailing 52w z.
    HIGH = deposits fleeing small banks toward large banks = stress. Returns a
    DataFrame indexed by observation date with dep_flight_4w / dep_flight_13w.
    """
    df = pd.concat([small.rename("small"), large.rename("large")], axis=1).dropna()
    out = {"small": df["small"], "large": df["large"]}
    for n in (4, 13):
        g_s = np.log(df["small"]).diff(n)
        g_l = np.log(df["large"]).diff(n)
        diff = g_s - g_l
        mu = diff.rolling(52, min_periods=52).mean()
        sd = diff.rolling(52, min_periods=52).std(ddof=1)
        out[f"dep_flight_{n}w"] = -((diff - mu) / sd)
    return pd.DataFrame(out)


def build_current_vintage_signal(small: pd.Series, large: pd.Series) -> pd.DataFrame:
    """K1679 behaviour: transform on the final-revision series; available_date =
    as_of + PUBLICATION_LAG_DAYS (heuristic)."""
    res = _transform_signal(small, large)
    res.index.name = "as_of"
    res["available_date"] = res.index + timedelta(days=PUBLICATION_LAG_DAYS)
    return res[["dep_flight_4w", "dep_flight_13w", "available_date"]]


def build_pit_signal(small_fr: pd.DataFrame, large_fr: pd.DataFrame) -> pd.DataFrame:
    """
    Point-in-time signal from ALFRED initial-release-only series. The rolling
    growth/z transform is computed on the first-print values (every observation
    enters at the value that was actually public then — no revision is ever used).
    The embargo uses the TRUE release date: available_date = max(small_release,
    large_release) + PIT_BUFFER_DAYS, so the signal for observation week d is only
    usable on a session that opens after BOTH series' first prints of week d.
    """
    small = small_fr.set_index("date")["value"].sort_index()
    large = large_fr.set_index("date")["value"].sort_index()
    small_rel = small_fr.set_index("date")["release_date"]
    large_rel = large_fr.set_index("date")["release_date"]

    tf = _transform_signal(small, large)  # indexed by observation date
    rel = pd.concat(
        [small_rel.rename("s"), large_rel.rename("l")], axis=1
    ).max(axis=1)  # both series must be public
    res = tf[["dep_flight_4w", "dep_flight_13w"]].copy()
    res["release_date"] = rel.reindex(res.index)
    res["available_date"] = res["release_date"] + timedelta(days=PIT_BUFFER_DAYS)
    res.index.name = "as_of"
    res = res.dropna(subset=["release_date"])
    return res[["dep_flight_4w", "dep_flight_13w", "release_date", "available_date"]]


def merge_signal_to_trading_days(
    trading_index: pd.DatetimeIndex, sig: pd.DataFrame
) -> pd.DataFrame:
    """As-of backward merge: trading day t only ever sees a deposit observation
    whose available_date is <= t."""
    left = pd.DataFrame(
        {"date": pd.DatetimeIndex(trading_index).as_unit("ns")}
    ).sort_values("date")
    cols = ["available_date", "as_of_date", "dep_flight_13w", "dep_flight_4w"]
    right = sig.reset_index().rename(columns={"as_of": "as_of_date"})
    right = right[[c for c in cols if c in right.columns]].copy()
    right = right.dropna(subset=["dep_flight_13w", "dep_flight_4w"], how="all").copy()
    right["available_date"] = pd.to_datetime(right["available_date"]).astype("datetime64[ns]")
    right["as_of_date"] = pd.to_datetime(right["as_of_date"]).astype("datetime64[ns]")
    right = right.sort_values("available_date")
    m = pd.merge_asof(
        left, right, left_on="date", right_on="available_date", direction="backward"
    )
    return m.set_index("date")


# ────────────────────────── inference machinery ──────────────────────────


def nw_variance(d: np.ndarray, lag: int) -> float:
    """Newey-West (Bartlett) long-run variance of a mean-zero-centred series."""
    n = len(d)
    dm = d - d.mean()
    g0 = float(np.mean(dm**2))
    v = g0
    for k in range(1, lag + 1):
        gk = float(np.mean(dm[k:] * dm[:-k]))
        v += 2.0 * (1.0 - k / (lag + 1.0)) * gk
    return v


def _hln_corr(n: int, h: int) -> float:
    return float(np.sqrt((n + 1.0 - 2.0 * h + h * (h - 1.0) / n) / n))


def dm_hln(d: np.ndarray, h: int) -> tuple[float, float, float, int]:
    """
    Diebold-Mariano, NW HAC (lag = h) + Harvey-Leybourne-Newbold (1997) correction,
    two-sided against t(n-1). d = loss_aug - loss_base. Negative t => augmented better.
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
    t_hln = float(t_raw * _hln_corr(n, h))
    p = float(2.0 * (1.0 - stats.t.cdf(abs(t_hln), df=n - 1)))
    return (t_raw, t_hln, p, n)


def clark_west(y: np.ndarray, pred_base: np.ndarray, pred_aug: np.ndarray, h: int) -> dict:
    """
    Clark-West (2007) nested-forecast adjusted MSPE test.

        f_t = (y - pred_base)^2 - [ (y - pred_aug)^2 - (pred_base - pred_aug)^2 ]

    Reject H0 (equal MSPE) in favour of the LARGER (augmented) model when the mean
    of f_t is significantly POSITIVE. One-sided upper-tail. HAC truncation lag = h,
    plus the HLN small-sample correction, against t(n-1). This is the correct test
    for the nested HAR (baseline) vs HAR+signal (augmented) comparison; the standard
    DM/HLN in K1679 is biased toward NOT rejecting for nested models.
    """
    y = np.asarray(y, np.float64)
    pb = np.asarray(pred_base, np.float64)
    pa = np.asarray(pred_aug, np.float64)
    f = (y - pb) ** 2 - ((y - pa) ** 2 - (pb - pa) ** 2)
    f = f[np.isfinite(f)]
    n = len(f)
    if n < 30:
        return {"status": "too_short", "n": n}
    v = nw_variance(f, lag=h)
    if v <= 0:
        return {"status": "nonpositive_lrv", "n": n, "fbar": float(f.mean())}
    se = np.sqrt(v / n)
    cw_raw = float(f.mean() / se)
    cw_hln = float(cw_raw * _hln_corr(n, h))
    p_one_raw = float(1.0 - stats.t.cdf(cw_raw, df=n - 1))
    p_one_hln = float(1.0 - stats.t.cdf(cw_hln, df=n - 1))
    return {
        "test": "Clark-West (2007) nested MSPE, one-sided upper-tail",
        "hac_lag": int(h),
        "n": int(n),
        "mean_adjusted_diff_fbar": float(f.mean()),
        "CW_t_raw": cw_raw,
        "CW_t_hln": cw_hln,
        "CW_p_one_sided_raw": p_one_raw,
        "CW_p_one_sided_hln": p_one_hln,
        "reject_equal_mspe_at_05_hln": bool(p_one_hln < 0.05),
        "reject_equal_mspe_at_10_hln": bool(p_one_hln < 0.10),
        "direction": "positive_CW_t_means_augmented(deposit)_better",
    }


def moving_block_bootstrap(d: np.ndarray, block: int, reps: int) -> dict:
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
    return pd.DataFrame(
        {
            "q_d": q,
            "q_w": q.rolling(5, min_periods=5).mean(),
            "q_m": q.rolling(22, min_periods=22).mean(),
        }
    )


def forward_mean(q: pd.Series, H: int) -> pd.Series:
    return q.rolling(H, min_periods=H).mean().shift(-H)


def run_oos(X: np.ndarray, y: np.ndarray, H: int, n_init: int) -> dict:
    """
    Expanding-window OOS with forward-label embargo j + H < i. Returns both the
    FLOORED forecasts (training-min positivity floor, K1679 behaviour) and the RAW
    (un-floored) forecasts, so an MSE-based sensitivity can compare them.
    """
    n, k = X.shape
    Xb = X[:, :-1]

    first_train_end = n_init - H - 1
    if first_train_end < max(k * 5, 60):
        raise RuntimeError("initial training window too small after embargo")

    pb_f, pa_f, pb_r, pa_r, ys = [], [], [], [], []
    n_floor_b = n_floor_a = 0
    embargo_check = {
        "first_origin": int(n_init),
        "first_train_last_row": int(first_train_end),
        "requirement": "j + H < i  =>  last train row j = i - H - 1",
        "holds_for_all_origins": True,
    }

    for i in range(n_init, n):
        j_end = i - H - 1
        if j_end + H >= i:
            embargo_check["holds_for_all_origins"] = False
        sl = slice(0, j_end + 1)
        ytr = y[sl]
        pos = ytr[ytr > 0]
        floor = float(pos.min()) if pos.size else 1e-10
        bb = np.linalg.lstsq(Xb[sl], y[sl], rcond=None)[0]
        ba = np.linalg.lstsq(X[sl], y[sl], rcond=None)[0]
        rb = float(Xb[i] @ bb)
        ra = float(X[i] @ ba)
        pb_r.append(rb)
        pa_r.append(ra)
        fb, fa = rb, ra
        if fb < floor:
            fb = floor
            n_floor_b += 1
        if fa < floor:
            fa = floor
            n_floor_a += 1
        pb_f.append(fb)
        pa_f.append(fa)
        ys.append(float(y[i]))

    if not embargo_check["holds_for_all_origins"]:
        raise AssertionError("forward-label embargo violated")

    return {
        "y": np.asarray(ys),
        "pred_base": np.asarray(pb_f),
        "pred_aug": np.asarray(pa_f),
        "pred_base_raw": np.asarray(pb_r),
        "pred_aug_raw": np.asarray(pa_r),
        "n_floored_base": n_floor_b,
        "n_floored_aug": n_floor_a,
        "embargo_check": embargo_check,
    }


# ────────────────────────── one grid cell ──────────────────────────


def evaluate_cell(
    panel: pd.DataFrame, asset: str, predictor: str, target: str, H: int,
    run_cw: bool = False,
) -> dict:
    q = panel[f"{'pk' if target == 'rv' else 'dsv'}_{asset}"]
    feats = har_terms(q)
    y = forward_mean(q, H)

    ctrl_cols = []
    if asset != "SPY":
        ctrl_cols.append("spy_rv21")
    if "vix" in panel.columns:
        ctrl_cols.append("vix")

    frame = pd.concat([feats, panel[ctrl_cols + [predictor]], y.rename("y")], axis=1)
    frame = frame.loc[frame.index >= pd.Timestamp(ANALYSIS_START)].dropna()

    # ---- mechanical lookahead assertions ----
    probe = frame.index[len(frame) // 2]
    pos = q.index.get_loc(probe)
    expect = float(q.iloc[pos + 1 : pos + 1 + H].mean())
    assert abs(float(frame.loc[probe, "y"]) - expect) < 1e-14, "target window is not (t, t+H]"
    asof = pd.to_datetime(panel.loc[frame.index, "as_of_date"].to_numpy())
    min_gap = (pd.DatetimeIndex(frame.index) - pd.DatetimeIndex(asof)).min()

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

    yt = oos["y"]
    pb, pa = oos["pred_base"], oos["pred_aug"]
    pb_r, pa_r = oos["pred_base_raw"], oos["pred_aug_raw"]
    n_floor_b = int(oos["n_floored_base"])
    n_floor_a = int(oos["n_floored_aug"])
    n_zero_actual = int((yt <= 0).sum())

    l_q_b, l_q_a = qlike_pointwise(yt, pb), qlike_pointwise(yt, pa)
    l_m_b, l_m_a = (yt - pb) ** 2, (yt - pa) ** 2
    l_m_b_raw, l_m_a_raw = (yt - pb_r) ** 2, (yt - pa_r) ** 2

    losses = {"qlike": (l_q_b, l_q_a), "mse": (l_m_b, l_m_a)}
    prim = PRIMARY_LOSS[target]

    res = {
        "asset": asset,
        "predictor": predictor,
        "target": target,
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
        "min_days_between_deposit_asof_and_use": int(min_gap.days),
        "loss_results": {},
    }

    for name, (lb, la) in losses.items():
        d = la - lb
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

    # ---- FIX 3: un-floored MSE sensitivity ----
    d_raw = l_m_a_raw - l_m_b_raw
    t_raw_u, t_hln_u, p_u, n_u = dm_hln(d_raw, h=H)
    res["mse_unfloored_sensitivity"] = {
        "note": (
            "MSE recomputed on RAW (un-floored) OLS forecasts. MSE needs no "
            "positivity floor; this isolates whether the training-min floor "
            "(which clipped ~%d/%d base and %d/%d aug forecasts) was doing the work."
            % (n_floor_b, len(yt), n_floor_a, len(yt))
        ),
        "loss_base_unfloored": float(np.mean(l_m_b_raw)),
        "loss_aug_unfloored": float(np.mean(l_m_a_raw)),
        "improvement_pct_unfloored": float(
            100.0 * (np.mean(l_m_b_raw) - np.mean(l_m_a_raw)) / np.mean(l_m_b_raw)
        ),
        "mean_loss_diff_unfloored": float(np.mean(d_raw)),
        "DM_t_hln_unfloored": t_hln_u,
        "DM_p_value_unfloored": p_u,
        "DM_n": n_u,
        "vs_floored_mse_DM_t_hln": res["loss_results"]["mse"]["DM_t_hln"],
    }

    # ---- FIX 2: Clark-West nested test (strongest cells only) ----
    if run_cw:
        # CW is an MSPE (squared-error) test; run it on the RAW forecasts of the
        # variance/semivariance so no floor distorts the adjustment term.
        res["clark_west"] = clark_west(yt, pb_r, pa_r, h=H)

    if target == "dsv" and n_zero_actual > 0:
        res["loss_results"]["qlike"]["caveat"] = (
            f"{n_zero_actual} OOS windows have exactly zero downside semivariance; "
            "QLIKE's log term is undefined there. MSE is the pre-declared primary loss for dsv."
        )

    p_primary = res["loss_results"][prim]["DM_p_value"]
    res["p_value"] = p_primary
    res["DM_t_hln"] = res["loss_results"][prim]["DM_t_hln"]
    return res


# ────────────────────────── grid runner ──────────────────────────


def run_grid(panel: pd.DataFrame, signal_label: str) -> list[dict]:
    cells = []
    for fam, grid in (("primary", PRIMARY_GRID), ("secondary", SECONDARY_GRID)):
        for g in grid:
            run_cw = any(
                g["asset"] == c["asset"] and g["predictor"] == c["predictor"]
                and g["target"] == c["target"] and g["H"] == c["H"]
                for c in CW_CELLS
            )
            c = evaluate_cell(panel, **g, run_cw=run_cw)
            c["family"] = fam
            c["signal_vintage"] = signal_label
            cells.append(c)
            cwflag = " [CW]" if run_cw else ""
            print(
                f"    [{signal_label:7s}][{fam:9s}] {c['asset']:3s} {c['predictor']:15s} "
                f"{c['target']:3s} H={c['H']:2d}  n={c['n_oos']:4d}  "
                f"DM_t(HLN)={c['DM_t_hln']:+.3f}  p={c['p_value']:.4f}{cwflag}"
            )
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
            c["p_value_adjusted"] = {"note": "declared secondary/falsification family"}
    return cells


def summarise(cells: list[dict]) -> dict:
    prim = [c for c in cells if c["family"] == "primary"]
    best = min(prim, key=lambda c: c["p_value"])
    any_raw = any(c["p_value"] < 0.05 for c in prim)
    any_bh = any(c["p_value_adjusted"]["bh_reject_at_q10"] for c in prim)
    any_harvey = any(abs(c["DM_t_hln"]) > 3.0 for c in prim)
    # Clark-West verdict across the CW cells
    cw = [c for c in cells if "clark_west" in c and c["clark_west"].get("CW_p_one_sided_hln") is not None]
    any_cw_reject = any(c["clark_west"].get("reject_equal_mspe_at_05_hln", False) for c in cw)
    verdict = "NULL"
    if any_harvey and any_bh:
        verdict = "POSITIVE"
    elif any_bh:
        verdict = "WEAK_FDR_ONLY"
    elif any_raw:
        verdict = "WEAK_RAW_ONLY"
    return {
        "verdict_standard_dm": verdict,
        "any_raw_p_below_05": any_raw,
        "any_bh_reject_at_q10": any_bh,
        "any_harvey_abs_t_above_3": any_harvey,
        "clark_west_any_reject_at_05_hln": any_cw_reject,
        "strongest_primary_cell": {
            "asset": best["asset"], "predictor": best["predictor"],
            "target": best["target"], "H": best["H"],
            "DM_t_hln": best["DM_t_hln"], "p_value": best["p_value"],
            "bonferroni": best["p_value_adjusted"]["bonferroni"],
            "bh_q": best["p_value_adjusted"]["benjamini_hochberg_q"],
        },
    }


# ────────────────────────── figures ──────────────────────────


def make_figures(panel_cur: pd.DataFrame, panel_pit: pd.DataFrame,
                 cells_cur: list[dict], cells_pit: list[dict]) -> None:
    # Fig 1 — current-vintage vs point-in-time signal, KRE forward RV overlay
    fig, axes = plt.subplots(2, 1, figsize=(13, 9), height_ratios=[1.2, 1])
    ax = axes[0]
    sc = panel_cur["dep_flight_13w"].dropna()
    sp = panel_pit["dep_flight_13w"].dropna()
    ax.plot(sc.index, sc.values, lw=0.9, color="#9e9e9e",
            label="current-vintage 13w signal (K1679, hindsight-revised)")
    ax.plot(sp.index, sp.values, lw=1.0, color="#b3282d",
            label="point-in-time 13w signal (ALFRED, as-first-known)")
    ax.axhline(0, color="k", lw=0.6, alpha=0.5)
    ax.axhline(2, color="grey", ls=":", lw=0.9)
    for lo, hi, lab in [("2008-09-01", "2009-06-30", "GFC"),
                        ("2023-03-01", "2023-06-30", "SVB / regional-bank stress")]:
        ax.axvspan(pd.Timestamp(lo), pd.Timestamp(hi), color="#ffcc66", alpha=0.30)
    ax.set_ylabel("deposit-flight z (high = flight from small banks)")
    ax.set_title(
        "K1679-rev — point-in-time (ALFRED) vs current-vintage deposit-flight signal\n"
        "the PIT signal removes hindsight revisions; both spike at GFC & SVB",
        fontsize=11)
    ax.legend(loc="upper left", fontsize=8.5)
    ax2 = ax.twinx()
    fwd = forward_mean(panel_cur["pk_KRE"], 21)
    fwd = fwd.loc[fwd.index >= pd.Timestamp(ANALYSIS_START)]
    ax2.plot(fwd.index, np.sqrt(fwd.values * 252) * 100, lw=0.8, color="#1f4e79", alpha=0.6,
             label="KRE forward 21d RV (ann. %)")
    ax2.set_ylabel("KRE forward 21d realized vol (ann. %)", color="#1f4e79")
    ax2.legend(loc="upper right", fontsize=8.5)

    # bottom: DM t before/after PIT for the primary grid
    ax = axes[1]
    pc = [c for c in cells_cur if c["family"] == "primary"]
    pp = [c for c in cells_pit if c["family"] == "primary"]
    labels = [f"{c['predictor'].replace('dep_flight_','')}·{c['target']}·H{c['H']}" for c in pc]
    x = np.arange(len(pc))
    ax.bar(x - 0.2, [c["DM_t_hln"] for c in pc], width=0.4, color="#9e9e9e", label="current vintage")
    ax.bar(x + 0.2, [c["DM_t_hln"] for c in pp], width=0.4, color="#b3282d", label="point-in-time")
    for lv, ls in [(1.96, ":"), (3.0, "--")]:
        ax.axhline(lv, color="k", ls=ls, lw=0.8)
        ax.axhline(-lv, color="k", ls=ls, lw=0.8)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8.5)
    ax.set_ylabel("DM t (Harvey-corrected)\nnegative = deposit signal helps")
    ax.set_title("Primary grid DM t: current vintage vs point-in-time (no cell clears ±1.96)", fontsize=10)
    ax.set_ylim(-3.6, 3.6)
    ax.legend(fontsize=8.5)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "K1679-rev_fig_pit_vs_current.png", dpi=130)
    plt.close(fig)


# ────────────────────────── panel assembly ──────────────────────────


def assemble_panel(sig: pd.DataFrame, px: dict, vix, vix_ok: bool) -> pd.DataFrame:
    cols = {}
    for a in ("KRE", "XLF", "SPY"):
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
    return panel


# ────────────────────────── main ──────────────────────────


def main() -> None:
    t0 = time.time()
    key = get_fred_api_key()

    print("[1/6] FRED H.8 current-vintage deposits …")
    small_cur = fetch_fred_current(FRED_SMALL, key)
    large_cur = fetch_fred_current(FRED_LARGE, key)
    sig_cur = build_current_vintage_signal(small_cur, large_cur)

    print("[2/6] ALFRED point-in-time (initial-release) deposits …")
    small_fr = fetch_fred_first_release(FRED_SMALL, key)
    large_fr = fetch_fred_first_release(FRED_LARGE, key)
    print(f"    first-release rows: small={len(small_fr)} large={len(large_fr)}  "
          f"small first date={small_fr['date'].min().date()} "
          f"first release={small_fr['release_date'].min().date()}")
    sig_pit = build_pit_signal(small_fr, large_fr)
    sig_pit_valid = sig_pit.dropna(subset=["dep_flight_13w", "dep_flight_4w"], how="all")
    print(f"    PIT signal weeks={len(sig_pit_valid)}  "
          f"first available={sig_pit['available_date'].min().date()}  "
          f"last={sig_pit['available_date'].max().date()}")

    print("[3/6] yfinance prices …")
    assets = ["KRE", "XLF", "SPY"]
    px = {a: fetch_prices(a) for a in assets}
    vix_ok = True
    try:
        vix = fetch_prices("^VIX")["Close"].astype(float)
    except Exception as e:  # noqa: BLE001
        vix_ok = False
        vix = None
        print(f"    ! ^VIX unavailable ({e})")

    print("[4/6] panel assembly (current + PIT) …")
    panel_cur = assemble_panel(sig_cur, px, vix, vix_ok)
    panel_pit = assemble_panel(sig_pit, px, vix, vix_ok)

    # construct validity on the PIT signal (must still spike at the runs)
    def _construct(panel):
        svb = panel.loc["2023-03-01":"2023-06-30", "dep_flight_13w"].dropna()
        gfc = panel.loc["2008-09-01":"2009-06-30", "dep_flight_13w"].dropna()
        return {
            "svb_2023_max_signal": float(svb.max()) if len(svb) else None,
            "svb_2023_argmax_date": str(svb.idxmax().date()) if len(svb) else None,
            "gfc_max_signal": float(gfc.max()) if len(gfc) else None,
            "full_sample_mean": float(panel["dep_flight_13w"].mean()),
            "full_sample_std": float(panel["dep_flight_13w"].std()),
        }
    construct_cur = _construct(panel_cur)
    construct_pit = _construct(panel_pit)
    print(f"    construct: current SVB max={construct_cur['svb_2023_max_signal']:.2f}  "
          f"PIT SVB max={construct_pit['svb_2023_max_signal']:.2f}")

    # correlation between the two signals where both defined
    both = pd.concat(
        [panel_cur["dep_flight_13w"].rename("cur"),
         panel_pit["dep_flight_13w"].rename("pit")], axis=1).dropna()
    sig_corr = float(both["cur"].corr(both["pit"])) if len(both) > 10 else None

    print("[5/6] OOS grid — current vintage …")
    cells_cur = run_grid(panel_cur, "current")
    print("[5/6] OOS grid — point-in-time …")
    cells_pit = run_grid(panel_pit, "pit")

    print("[6/6] figures …")
    make_figures(panel_cur, panel_pit, cells_cur, cells_pit)

    summ_cur = summarise(cells_cur)
    summ_pit = summarise(cells_pit)

    results = {
        "experiment_id": "K1679-rev",
        "title": (
            "Regional-bank deposit-flight NULL, revised: ALFRED point-in-time "
            "vintages + Clark-West nested test + un-floored loss sensitivity"
        ),
        "revises": "K1679 (Codex verdict FAIL — 3 method problems)",
        "run_utc": pd.Timestamp.utcnow().isoformat(),
        "seed": SEED,
        "verdict_pit": summ_pit["verdict_standard_dm"],
        "three_fixes": {
            "fix1_alfred_point_in_time": {
                "problem": "K1679 used the current (revised) FRED vintage — lookahead.",
                "fix": ("Full ALFRED vintage history; signal reconstructed at the "
                        "vintage current on each weekly release date; embargo uses "
                        "the true realtime_start + 1d, not a +10d heuristic."),
                "signal_correlation_current_vs_pit": sig_corr,
                "construct_validity_current": construct_cur,
                "construct_validity_pit": construct_pit,
            },
            "fix2_clark_west": {
                "problem": ("Baseline HAR nested in augmented model; standard DM/HLN "
                            "biased toward NOT rejecting (toward the null)."),
                "fix": ("Clark-West (2007) one-sided nested MSPE test on the two "
                        "strongest K1679 cells, HAC lag = H, HLN-corrected."),
                "cells_tested": CW_CELLS,
                "results_current_vintage": {
                    f"{c['predictor']}·{c['target']}·H{c['H']}": c.get("clark_west")
                    for c in cells_cur if "clark_west" in c
                },
                "results_point_in_time": {
                    f"{c['predictor']}·{c['target']}·H{c['H']}": c.get("clark_west")
                    for c in cells_pit if "clark_west" in c
                },
            },
            "fix3_unfloored_sensitivity": {
                "problem": ("Training-min positivity floor also clipped DSV/MSE cells "
                            "that admit exact zeros (strongest dsv cell ~50/53 clipped)."),
                "fix": "Every MSE-based DM recomputed on raw un-floored forecasts.",
                "note": "Per-cell numbers in cells[].mse_unfloored_sensitivity.",
            },
        },
        "summary_current_vintage": summ_cur,
        "summary_point_in_time": summ_pit,
        "data_sources": {
            "deposits_small": f"FRED/ALFRED {FRED_SMALL}",
            "deposits_large": f"FRED/ALFRED {FRED_LARGE}",
            "prices": "yfinance auto_adjust=True (KRE, XLF, SPY, ^VIX)",
            "vix_control_available": vix_ok,
        },
        "method": {
            "baseline": "OLS 1 + HAR(d,w,m) + SPY 21d RV + VIX level",
            "augmented": "baseline + deposit-flight signal (only difference)",
            "oos": f"expanding refit, initial train {TRAIN_FRAC:.0%}, embargo j+H<i",
            "dm": "NW HAC lag=H + HLN correction, t(n-1)",
            "clark_west": "CW(2007) one-sided nested MSPE, HAC lag=H + HLN",
            "bootstrap": f"moving-block block=max(10,H) reps={BOOT_REPS} seed={SEED}",
            "multiple_testing": "Bonferroni + BH over primary family m=8",
        },
        "cells_current_vintage": cells_cur,
        "cells_point_in_time": cells_pit,
        "runtime_seconds": None,
    }
    results["runtime_seconds"] = round(time.time() - t0, 1)

    # atomic write
    out = OUT_DIR / "K1679-rev_results.json"
    tmp = OUT_DIR / "K1679-rev_results.json.tmp"
    tmp.write_text(json.dumps(results, indent=2, default=str))
    json.loads(tmp.read_text())  # validate parseable
    os.replace(tmp, out)

    print(f"\nVERDICT (PIT, standard DM): {summ_pit['verdict_standard_dm']}")
    print(f"  PIT strongest cell: {summ_pit['strongest_primary_cell']}")
    print(f"  Clark-West any reject @0.05 (HLN): PIT={summ_pit['clark_west_any_reject_at_05_hln']} "
          f"current={summ_cur['clark_west_any_reject_at_05_hln']}")
    print(f"  signal corr current vs PIT: {sig_corr}")
    print(f"  wrote {out}  ({results['runtime_seconds']}s)")


if __name__ == "__main__":
    main()
