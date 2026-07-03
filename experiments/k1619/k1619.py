"""k1619 — Staleness-corrected RV vs naive RV in HAR-RV OOS forecasting.

Research question
-----------------
Illiquid assets exhibit intraday price "staleness" (zero-return / idle intervals
because no trade updates the price). Naive realized variance (RV) sums squared
intraday returns and may be biased when a large fraction of intervals are stale.
Does an idle-time (staleness) correction of RV incrementally improve HAR-RV
out-of-sample volatility forecasting (lower QLIKE, DM/HLN-significant)?

Design (see README.md for full motivation, differentiation, literature)
-----------------------------------------------------------------------
Data     : yfinance hourly bars (interval='1h', period='730d'), ~6 bars/day.
           Assets = liquid benchmark SPY + 3 illiquid ETFs selected by staleness
           diagnostic (VNM Vietnam, EWM Malaysia, EIDO Indonesia).
RV_naive : sum of squared within-day hourly close-to-close log returns.
RV_corr  : idle-time rescaling  RV_corr_d = RV_naive_d / (1 - f_d),
           f_d = fraction of exact-zero within-day returns on day d
           (Bandi-Pirino-Reno 2017 idle-time proxy). First-order de-staling:
           latent variance is assumed to accrue over calendar time, so naive RV
           (which records variance only over the (1-f) active fraction) is
           scaled up to full calendar time. See README for exact caveats.
Eval     : evaluation target = r2_oc = (sum of within-day log returns)^2 =
           squared cumulative intraday return. This is a MODEL-FREE,
           conditionally-unbiased, staleness-IMMUNE proxy (depends only on the
           day's first/last observed price), so it does not favour naive or
           corrected RV. Patton (2011): QLIKE ranking against a conditionally-
           unbiased proxy is consistent for the ranking against true variance.
Model    : HAR-RV (Corsi 2009): RV_t = b0 + b1 RV_{t-1} + b2 RV^w_{t-1}
           + b3 RV^m_{t-1}, expanding-window OLS, one-step-ahead OOS.
Tests    : per-asset mean QLIKE (naive vs corrected) + Diebold-Mariano with
           Harvey-Leybourne-Newbold (1997) small-sample correction, h=1.
           Cross-asset pooled test aggregates the daily loss differential across
           the 3 illiquid assets by DATE first, then DM/HLN on the date series
           (K1355: never treat asset-day as iid).

Anti-error checklist (see README for full mapping)
--------------------------------------------------
* Lookahead: HAR features are explicitly lagged (build_har_features uses
  .shift(1) so row t's predictors come from t-1 and earlier; target = RV_t).
  Expanding OOS trains only on rows whose target day < forecast origin.
* Seed: np.random.seed(42) (design is analytic; seed set per project rule).
* QLIKE: uses volpred.stats.model_evaluation.qlike_pointwise (actual/predicted
  direction) — never hand-written reverse QLIKE.
* Fair proxy: common independent eval target r2_oc for both models.
"""
from __future__ import annotations

import json
import os
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

from volpred.stats.model_evaluation import qlike_pointwise

warnings.simplefilter("ignore", category=FutureWarning)

SEED = 42
np.random.seed(SEED)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
os.makedirs(DATA_DIR, exist_ok=True)

BENCHMARK = "SPY"
ILLIQUID = ["VNM", "EWM", "EIDO"]          # selected by staleness diagnostic
ALL_ASSETS = [BENCHMARK] + ILLIQUID

WARMUP_DAYS = 250          # initial HAR training window (expanding thereafter)
MIN_BARS_PER_DAY = 3       # drop days with too few intraday bars to form RV
NEAR_ZERO_EPS = 1e-4       # near-zero return threshold (robustness only)


# ─────────────────────────── data ───────────────────────────
def fetch_hourly(sym: str) -> pd.Series:
    """Hourly close series (tz-aware UTC index). Cached to CSV for reproducibility."""
    cache = os.path.join(DATA_DIR, f"{sym}_1h.csv")
    if os.path.exists(cache):
        s = pd.read_csv(cache, index_col=0, parse_dates=True)["Close"]
        s.index = pd.to_datetime(s.index, utc=True)
        return s.dropna()
    df = yf.download(sym, period="730d", interval="1h",
                     auto_adjust=True, progress=False, threads=False)
    if df is None or len(df) == 0:
        raise RuntimeError(f"{sym}: empty download")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    close = df["Close"].dropna()
    close.to_frame("Close").to_csv(cache)
    return close


def build_daily(sym: str) -> pd.DataFrame:
    """Aggregate hourly bars to daily RV variants + staleness diagnostics.

    Returns a DataFrame indexed by date with columns:
      RV_naive, RV_corr, r2_oc, idle_frac, nearzero_frac, n_bars
    Only WITHIN-day close-to-close returns are used (the first bar of each day is
    dropped to avoid the overnight gap contaminating RV / staleness).
    """
    close = fetch_hourly(sym)
    day = close.index.normalize()
    logret = np.log(close / close.shift(1))
    # within-day mask: current bar's day == previous bar's day (tz-safe compare)
    same_day = (day.values == pd.Series(day).shift(1).values)
    r = logret[same_day].dropna()
    d = r.index.normalize()

    recs = []
    for gday, grp in pd.Series(r.values, index=d).groupby(level=0):
        vals = grp.values
        nbar = len(vals)
        if nbar < MIN_BARS_PER_DAY:
            continue
        rv_naive = float(np.sum(vals ** 2))
        idle = float(np.mean(vals == 0.0))
        nearzero = float(np.mean(np.abs(vals) < NEAR_ZERO_EPS))
        # idle-time rescaling; guard against f_d==1 (fully stale day -> drop)
        if idle >= 1.0:
            continue
        rv_corr = rv_naive / (1.0 - idle)
        cum = float(np.sum(vals))          # cumulative within-day log return
        r2_oc = cum ** 2                   # model-free unbiased variance proxy
        recs.append({
            "date": pd.Timestamp(gday).tz_localize(None).normalize(),
            "RV_naive": rv_naive,
            "RV_corr": rv_corr,
            "r2_oc": r2_oc,
            "idle_frac": idle,
            "nearzero_frac": nearzero,
            "n_bars": nbar,
        })
    out = pd.DataFrame(recs).set_index("date").sort_index()
    return out


# ─────────────────────────── HAR ───────────────────────────
def build_har_features(rv: pd.Series) -> pd.DataFrame:
    """HAR daily/weekly/monthly regressors, all lagged one day (no lookahead).

    Row t: target = rv_t; predictors = rv_{t-1}, mean(rv_{t-5..t-1}),
    mean(rv_{t-22..t-1}). The explicit .shift(1) guarantees predictors use only
    information available strictly before day t.
    """
    df = pd.DataFrame({"y": rv})
    df["d"] = rv.shift(1)
    df["w"] = rv.rolling(5).mean().shift(1)
    df["m"] = rv.rolling(22).mean().shift(1)
    return df.dropna()


def har_oos_forecast_log(rv: pd.Series, warmup: int) -> pd.DataFrame:
    """Floor-free robustness: HAR fit on LOG RV, forecast exp-transformed.

    Guarantees positive forecasts (no flooring). A Duan (1994)-style smearing
    retransformation correction exp(mean resid^2 / 2) is applied using the
    expanding training residuals so the level forecast is (approximately)
    unbiased. Same lag structure and expanding-OOS discipline as the levels
    version. Used only to check that the NULL conclusion is not an artifact of
    negative-forecast flooring.
    """
    lrv = np.log(rv.clip(lower=1e-16))
    feat = build_har_features(lrv)
    dates = feat.index
    X = np.column_stack([np.ones(len(feat)), feat["d"].values,
                         feat["w"].values, feat["m"].values])
    y = feat["y"].values
    fcsts, fdates = [], []
    for i in range(warmup, len(feat)):
        Xtr, ytr = X[:i], y[:i]
        beta, *_ = np.linalg.lstsq(Xtr, ytr, rcond=None)
        resid = ytr - Xtr @ beta
        smear = float(np.exp(0.5 * np.mean(resid ** 2)))   # log-normal retransform
        pred = float(np.exp(X[i] @ beta)) * smear
        fcsts.append(pred)
        fdates.append(dates[i])
    return pd.DataFrame({"fcst": fcsts}, index=pd.DatetimeIndex(fdates))


def har_oos_forecast(rv: pd.Series, warmup: int) -> pd.DataFrame:
    """Expanding-window one-step-ahead OOS HAR forecasts.

    Returns DataFrame indexed by forecast date with column 'fcst'. For origin i,
    OLS is fit on all feature rows whose target day < day_i (target_end <
    forecast_origin), then used to predict rv at day_i. Forecasts are floored at
    a tiny positive value (QLIKE requires positive variance); the floor count is
    tracked by the caller.
    """
    feat = build_har_features(rv)
    dates = feat.index
    X = np.column_stack([np.ones(len(feat)), feat["d"].values,
                         feat["w"].values, feat["m"].values])
    y = feat["y"].values

    fcsts, fdates, floored = [], [], 0
    for i in range(warmup, len(feat)):
        Xtr, ytr = X[:i], y[:i]          # rows 0..i-1 -> target days < day_i
        beta, *_ = np.linalg.lstsq(Xtr, ytr, rcond=None)
        pred = float(X[i] @ beta)
        # data-driven positive floor: 1st percentile of positive training RV
        # (variance cannot fall below a small historical lower bound). Avoids
        # pathological QLIKE from flooring to a near-zero constant. Applied
        # identically to naive and corrected models -> symmetric, fair.
        pos = ytr[ytr > 0]
        flr = float(np.percentile(pos, 1)) if len(pos) else 1e-10
        if pred <= flr:
            pred = flr
            floored += 1
        fcsts.append(pred)
        fdates.append(dates[i])
    res = pd.DataFrame({"fcst": fcsts}, index=pd.DatetimeIndex(fdates))
    res.attrs["floored"] = floored
    return res


# ─────────────────────── DM + HLN ───────────────────────
def dm_hln(loss1: np.ndarray, loss2: np.ndarray, h: int = 1) -> dict:
    """Diebold-Mariano test with Harvey-Leybourne-Newbold (1997) small-sample
    correction. Newey-West HAC (Bartlett) long-run variance; HLN multiplicative
    factor and Student-t reference (df = T-1).

    d_t = loss1_t - loss2_t. Negative mean(d) => model 1 (loss1) has lower loss
    => model 1 better. Returns t-stat (HLN-corrected), two-sided p, and the sign
    of the difference.
    """
    d = np.asarray(loss1, dtype=np.float64) - np.asarray(loss2, dtype=np.float64)
    d = d[np.isfinite(d)]
    T = len(d)
    if T < 20:
        return {"t_stat": float("nan"), "p_value": float("nan"),
                "mean_diff": float("nan"), "T": T, "note": "too_few_obs"}
    dbar = float(np.mean(d))
    # Newey-West HAC with lags 1..h-1 (standard DM: h=1 -> gamma0 only)
    gamma0 = float(np.mean((d - dbar) ** 2))
    var_d = gamma0
    for lag in range(1, h):
        cov = float(np.mean((d[lag:] - dbar) * (d[:-lag] - dbar)))
        var_d += 2.0 * cov
    if var_d <= 0:
        return {"t_stat": 0.0, "p_value": 1.0, "mean_diff": dbar, "T": T,
                "note": "nonpositive_var"}
    dm = dbar / np.sqrt(var_d / T)
    # HLN small-sample correction factor
    hln_factor = np.sqrt((T + 1 - 2 * h + h * (h - 1) / T) / T)
    dm_hln_stat = dm * hln_factor
    from scipy import stats as _st
    p = 2.0 * (1.0 - _st.t.cdf(abs(dm_hln_stat), df=T - 1))
    return {
        "t_stat": float(dm_hln_stat),
        "p_value": float(p),
        "mean_diff": dbar,                     # <0 => naive better; >0 => corr better
        "T": T,
        "hln_factor": float(hln_factor),
        "better": "naive" if dbar < 0 else "corrected",
    }


# ─────────────────────────── run ───────────────────────────
def run() -> dict:
    results = {
        "experiment_id": "k1619",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": {"source": "yfinance", "interval": "1h", "period": "730d"},
        "design": {
            "benchmark": BENCHMARK, "illiquid": ILLIQUID,
            "rv_naive": "sum of squared within-day hourly log returns",
            "rv_corrected": "idle-time rescaling RV_naive/(1-f), f=exact-zero fraction",
            "eval_target": "r2_oc = squared cumulative within-day log return (model-free, staleness-immune)",
            "model": "HAR-RV (Corsi 2009), expanding-window one-step OOS OLS",
            "dm": "Diebold-Mariano + Harvey-Leybourne-Newbold small-sample, h=1",
            "warmup_days": WARMUP_DAYS,
            "har_convention": "levels OLS; forecasts floored at 1st-pct of positive training RV (data-driven, symmetric naive/corr)",
        },
        "proxy_note": (
            "Evaluation proxy r2_oc (squared cumulative intraday return) is model-free, "
            "conditionally-unbiased and staleness-ROBUST (depends only on the day's first/last "
            "observed price, so it is NOT mechanically tied to the count of zero intraday bars; "
            "endpoints could still be mildly stale), but very noisy. Mean QLIKE levels "
            "are large because the -log(actual) term blows up on near-zero-proxy days; this "
            "term is identical for naive vs corrected forecasts so it CANCELS in the DM "
            "differential. dm_hln_t/p is the valid significance test (Patton 2011 proxy-robust "
            "ranking). Median QLIKE and MSE are reported as interpretable descriptive stats."
        ),
        "staleness_diagnostic": {},
        "per_asset": {},
        "pooled_illiquid": {},
    }

    daily = {}
    for sym in ALL_ASSETS:
        df = build_daily(sym)
        daily[sym] = df
        results["staleness_diagnostic"][sym] = {
            "n_days": int(len(df)),
            "mean_idle_frac": float(df["idle_frac"].mean()),
            "median_idle_frac": float(df["idle_frac"].median()),
            "mean_nearzero_frac": float(df["nearzero_frac"].mean()),
            "mean_bars_per_day": float(df["n_bars"].mean()),
            "period_start": str(df.index.min().date()),
            "period_end": str(df.index.max().date()),
            "mean_RV_naive": float(df["RV_naive"].mean()),
            "mean_RV_corr": float(df["RV_corr"].mean()),
            "mean_r2_oc": float(df["r2_oc"].mean()),
        }

    # per-asset HAR OOS + QLIKE + DM/HLN
    loss_diff_by_date = {}   # for pooled test: date -> loss_naive - loss_corr
    for sym in ALL_ASSETS:
        df = daily[sym]
        rv_naive = df["RV_naive"]
        rv_corr = df["RV_corr"]
        r2 = df["r2_oc"]

        f_naive = har_oos_forecast(rv_naive, WARMUP_DAYS)
        f_corr = har_oos_forecast(rv_corr, WARMUP_DAYS)

        # align on common OOS dates that also have an eval proxy
        common = f_naive.index.intersection(f_corr.index).intersection(r2.index)
        common = common.sort_values()
        actual = r2.loc[common].values
        pn = f_naive.loc[common, "fcst"].values
        pc = f_corr.loc[common, "fcst"].values

        loss_n = qlike_pointwise(actual, pn)
        loss_c = qlike_pointwise(actual, pc)
        # also MSE (vs proxy)
        mse_n = float(np.mean((actual - pn) ** 2))
        mse_c = float(np.mean((actual - pc) ** 2))

        dm = dm_hln(loss_n, loss_c, h=1)   # d = loss_naive - loss_corr

        results["per_asset"][sym] = {
            "n_oos": int(len(common)),
            "oos_start": str(common.min().date()),
            "oos_end": str(common.max().date()),
            # NOTE: mean QLIKE levels are large & dominated by the -log(actual)
            # term on near-zero-proxy days; this term is IDENTICAL for naive and
            # corrected so it cancels exactly in the DM differential (dm_hln_t is
            # the valid inference). Median QLIKE is a robust, interpretable
            # central-tendency comparison; DM is the primary significance test.
            "qlike_naive": float(np.mean(loss_n)),
            "qlike_corrected": float(np.mean(loss_c)),
            "qlike_delta_corr_minus_naive": float(np.mean(loss_c) - np.mean(loss_n)),
            "median_qlike_naive": float(np.median(loss_n)),
            "median_qlike_corrected": float(np.median(loss_c)),
            "median_qlike_delta_corr_minus_naive": float(np.median(loss_c) - np.median(loss_n)),
            "mse_naive": mse_n,
            "mse_corrected": mse_c,
            "mse_better": "corrected" if mse_c < mse_n else "naive",
            "dm_hln_t": dm["t_stat"],
            "dm_hln_p": dm["p_value"],
            "dm_mean_diff_naive_minus_corr": dm["mean_diff"],
            "dm_better": dm.get("better"),
            "harvey_significant_|t|>3": bool(abs(dm["t_stat"]) > 3.0) if np.isfinite(dm["t_stat"]) else False,
            "conventional_significant_p<0.05": bool(dm["p_value"] < 0.05) if np.isfinite(dm["p_value"]) else False,
            "floored_naive": int(f_naive.attrs.get("floored", 0)),
            "floored_corr": int(f_corr.attrs.get("floored", 0)),
        }

        if sym in ILLIQUID:
            loss_diff_by_date[sym] = pd.Series(loss_n - loss_c, index=common)

    # pooled illiquid test (K1355: aggregate by date first, then DM/HLN)
    diff_df = pd.DataFrame(loss_diff_by_date)      # columns = illiquid assets
    daily_mean_diff = diff_df.mean(axis=1).dropna()  # cross-asset mean per date
    # d_pooled = mean(loss_naive - loss_corr); >0 => corrected lower loss (better)
    d = daily_mean_diff.values
    T = len(d)
    dbar = float(np.mean(d))
    gamma0 = float(np.mean((d - dbar) ** 2))
    dm_pooled = dbar / np.sqrt(gamma0 / T) if gamma0 > 0 else 0.0
    hln = np.sqrt((T + 1 - 2 * 1 + 0) / T)
    dm_pooled_hln = dm_pooled * hln
    from scipy import stats as _st
    p_pooled = 2.0 * (1.0 - _st.t.cdf(abs(dm_pooled_hln), df=T - 1))
    results["pooled_illiquid"] = {
        "method": "cross-asset mean of daily (loss_naive - loss_corr) per DATE, then DM+HLN (K1355-compliant)",
        "n_dates": int(T),
        "mean_diff_naive_minus_corr": dbar,   # >0 => corrected better
        "dm_hln_t": float(dm_pooled_hln),
        "dm_hln_p": float(p_pooled),
        "better": "corrected" if dbar > 0 else "naive",
        "harvey_significant_|t|>3": bool(abs(dm_pooled_hln) > 3.0),
        "conventional_significant_p<0.05": bool(p_pooled < 0.05),
    }

    # robustness: floor-free log-HAR (guarantees positive forecasts, no flooring)
    rob = {"note": "log-HAR (fit on log RV, exp+smearing retransform) — no flooring; "
                   "checks the NULL is not an artifact of negative-forecast flooring"}
    log_diff_by_date = {}
    for sym in ALL_ASSETS:
        df = daily[sym]
        r2 = df["r2_oc"]
        fn = har_oos_forecast_log(df["RV_naive"], WARMUP_DAYS)
        fc = har_oos_forecast_log(df["RV_corr"], WARMUP_DAYS)
        common = fn.index.intersection(fc.index).intersection(r2.index).sort_values()
        a = r2.loc[common].values
        ln = qlike_pointwise(a, fn.loc[common, "fcst"].values)
        lc = qlike_pointwise(a, fc.loc[common, "fcst"].values)
        dm = dm_hln(ln, lc, h=1)
        rob[sym] = {
            "dm_hln_t": dm["t_stat"], "dm_hln_p": dm["p_value"],
            "better": dm.get("better"),
            "harvey_significant_|t|>3": bool(abs(dm["t_stat"]) > 3.0) if np.isfinite(dm["t_stat"]) else False,
        }
        if sym in ILLIQUID:
            log_diff_by_date[sym] = pd.Series(ln - lc, index=common)
    from scipy import stats as _st2
    ldf = pd.DataFrame(log_diff_by_date).mean(axis=1).dropna()
    dd = ldf.values
    Tt = len(dd)
    dbar_l = float(np.mean(dd))
    g0 = float(np.mean((dd - dbar_l) ** 2))
    tp = (dbar_l / np.sqrt(g0 / Tt)) * np.sqrt((Tt - 1) / Tt) if g0 > 0 else 0.0
    rob["pooled_illiquid"] = {
        "dm_hln_t": float(tp),
        "dm_hln_p": float(2.0 * (1.0 - _st2.t.cdf(abs(tp), df=Tt - 1))),
        "better": "corrected" if dbar_l > 0 else "naive",
        "harvey_significant_|t|>3": bool(abs(tp) > 3.0),
    }
    results["robustness_log_har"] = rob

    # verdict
    illiq = [results["per_asset"][s] for s in ILLIQUID]
    n_improved = sum(1 for r in illiq if r["qlike_delta_corr_minus_naive"] < 0)
    n_sig_improve = sum(1 for r in illiq
                        if r["qlike_delta_corr_minus_naive"] < 0 and r["harvey_significant_|t|>3"])
    results["verdict"] = {
        "n_illiquid_qlike_improved_by_correction": n_improved,
        "n_illiquid_harvey_significant_improvement": n_sig_improve,
        "summary": (
            "NULL/NEGATIVE: staleness (idle-time) correction does not yield a "
            "Harvey-significant QLIKE improvement over naive RV in HAR OOS forecasting"
            if n_sig_improve == 0 else
            "POSITIVE: idle-time correction gives Harvey-significant QLIKE improvement"
        ),
    }
    return results, daily


def main():
    results, daily = run()
    out_path = os.path.join(HERE, "k1619_results.json")
    with open(out_path, "w") as fh:
        json.dump(results, fh, indent=2)
    print(f"wrote {out_path}")

    # ---- console summary ----
    print("\n=== STALENESS DIAGNOSTIC (mean exact-zero idle fraction) ===")
    for sym in ALL_ASSETS:
        s = results["staleness_diagnostic"][sym]
        print(f"  {sym:5s}  idle={s['mean_idle_frac']*100:6.3f}%  "
              f"days={s['n_days']:4d}  bars/day={s['mean_bars_per_day']:.2f}")
    print("\n=== PER-ASSET QLIKE (naive vs corrected) + DM/HLN ===")
    for sym in ALL_ASSETS:
        r = results["per_asset"][sym]
        print(f"  {sym:5s}  medQLIKE naive={r['median_qlike_naive']:.4f} corr={r['median_qlike_corrected']:.4f}"
              f"  DM/HLN t={r['dm_hln_t']:+.2f} p={r['dm_hln_p']:.3f}"
              f"  QLIKE-better={r['dm_better']}  MSE-better={r['mse_better']}  N={r['n_oos']}")
    p = results["pooled_illiquid"]
    print(f"\n=== POOLED ILLIQUID (date-aggregated) ===\n  t={p['dm_hln_t']:+.2f} "
          f"p={p['dm_hln_p']:.3f} better={p['better']} N={p['n_dates']}")
    print(f"\nVERDICT: {results['verdict']['summary']}")

    make_figures(results, daily)
    return results, daily


# ─────────────────────────── figures ───────────────────────────
def make_figures(results: dict, daily: dict):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Fig 1: staleness diagnostic bar
    fig, ax = plt.subplots(figsize=(7, 4.2))
    syms = ALL_ASSETS
    idle = [results["staleness_diagnostic"][s]["mean_idle_frac"] * 100 for s in syms]
    colors = ["#2c7fb8"] + ["#d95f0e"] * len(ILLIQUID)
    bars = ax.bar(syms, idle, color=colors)
    ax.set_ylabel("Mean intraday zero-return fraction (%)")
    ax.set_title("Fig 1. Price staleness by asset (hourly bars)\nblue = liquid benchmark, orange = illiquid")
    for b, v in zip(bars, idle):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.1, f"{v:.2f}%", ha="center", fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "k1619_fig1_staleness.png"), dpi=130)
    plt.close(fig)

    # Fig 2: DM/HLN t-statistics per asset (the actual inference)
    fig, ax = plt.subplots(figsize=(7.5, 4.4))
    x = np.arange(len(syms))
    tvals = [results["per_asset"][s]["dm_hln_t"] for s in syms]
    # sign convention: d = loss_naive - loss_corr; t>0 => corrected lower loss
    colors = ["#31a354" if t > 0 else "#d95f0e" for t in tvals]
    ax.bar(x, tvals, color=colors, width=0.55)
    for thr, lab in [(3, "Harvey |t|=3"), (1.96, "conv |t|=1.96"),
                     (-1.96, None), (-3, None)]:
        ax.axhline(thr, color="grey", lw=0.8,
                   ls="--" if abs(thr) == 3 else ":")
        if lab:
            ax.text(len(syms) - 0.4, thr + 0.05, lab, fontsize=7, color="grey", ha="right")
    ax.axhline(0, color="black", lw=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels(syms)
    ax.set_ylabel("DM/HLN t-statistic\n(>0 = correction improves; <0 = worsens)")
    ax.set_ylim(-4, 4)
    ax.set_title("Fig 2. Staleness-correction effect on HAR OOS QLIKE (DM/HLN, h=1)\nno asset reaches Harvey |t|>3 -> NULL")
    for i, t in enumerate(tvals):
        ax.text(x[i], t + (0.12 if t >= 0 else -0.28), f"{t:+.2f}", ha="center", fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "k1619_fig2_dmhln.png"), dpi=130)
    plt.close(fig)

    # Fig 3: cumulative loss differential (naive - corrected) over OOS for illiquid
    fig, ax = plt.subplots(figsize=(8, 4.2))
    for sym in ILLIQUID:
        df = daily[sym]
        rv_naive, rv_corr, r2 = df["RV_naive"], df["RV_corr"], df["r2_oc"]
        fn = har_oos_forecast(rv_naive, WARMUP_DAYS)
        fc = har_oos_forecast(rv_corr, WARMUP_DAYS)
        common = fn.index.intersection(fc.index).intersection(r2.index).sort_values()
        a = r2.loc[common].values
        ln = qlike_pointwise(a, fn.loc[common, "fcst"].values)
        lc = qlike_pointwise(a, fc.loc[common, "fcst"].values)
        cum = np.cumsum(ln - lc)     # >0 rising => corrected better; <0 => naive better
        ax.plot(common, cum, label=sym, lw=1.3)
    ax.axhline(0, color="grey", lw=0.8, ls="--")
    ax.set_ylabel("Cumulative QLIKE differential\n(naive − corrected;  >0 = correction helps)")
    ax.set_title("Fig 3. Cumulative OOS QLIKE loss differential over time (illiquid assets)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "k1619_fig3_lossdiff.png"), dpi=130)
    plt.close(fig)
    print("wrote 3 figures")


if __name__ == "__main__":
    main()
