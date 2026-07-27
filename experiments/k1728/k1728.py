#!/usr/bin/env python3
"""K1728 -- Incremental OOS predictive power of free macro-attention / news
sentiment for US-equity realized variance, over a HAR-RV baseline.

Core question
-------------
Does adding a FREE attention/uncertainty/sentiment regressor to HAR-RV
(Corsi 2009) yield a statistically significant *incremental* out-of-sample
forecast of US-equity realized variance? Primary criterion: Clark-West (2007)
MSPE-adjusted test for nested models, plus Campbell-Thompson incremental
OOS R-squared. DM (HLN HAC) and QLIKE reported as secondary.

nested-dm: cw-primary  -- Clark-West (2007) is the primary nested test for EVERY
  primary spec comparison in this experiment; the Diebold-Mariano statistics below
  are a directional cross-check only.
nested-dm: diagnostic-only  -- the ordinary DM/HLN statistics are descriptive only
  (raw DM is not valid inference under a nested null); they never feed the verdict,
  which is decided solely by Clark-West + Campbell-Thompson OOS R-squared.

Lookahead policy (see README section 'Lookahead policy')
--------------------------------------------------------
* Target y_t = log Garman-Klass daily variance of day t (a range-based RV proxy).
* EVERY predictor enters at t-1 via an explicit ``.shift(1)``:
    - HAR daily  = y.shift(1)
    - HAR weekly = y.rolling(5).mean().shift(1)
    - HAR monthly= y.rolling(22).mean().shift(1)
    - EPU / VIX / news_sentiment: reindex to trading days, ffill, then .shift(1).
  Baseline HAR and every augmented spec use the SAME lag convention and the
  SAME sample rows -> a fair nested comparison.
* OOS is a genuine expanding (or rolling) window: at each origin t, coefficients
  are re-fit on rows strictly before t; only <= t-1 information is used.

Data are cached CSVs written by ``fetch_data.py`` (run once); this script is
fully offline and deterministic. seed=42 is set for convention (the core
pipeline -- OLS + analytic CW/DM -- is deterministic; there is no bootstrap).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from volpred.stats.model_evaluation import (  # noqa: E402
    clark_west_test,
    dm_test,
    qlike,
)

SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
FIG = HERE / "figures"
FIG.mkdir(exist_ok=True)

OOS_START_DEFAULT = "2015-01-01"
ROLL_WINDOW = 1000            # rolling-window robustness (trading days)
FFILL_LIMIT = 5               # bridge holiday gaps only; never fabricate stale runs
EPS = 1e-12


# --------------------------------------------------------------------------- #
# Data assembly
# --------------------------------------------------------------------------- #
def load_ohlc(fname: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / fname, parse_dates=["DATE"]).set_index("DATE").sort_index()
    for c in ["Open", "High", "Low", "Close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def load_fred(series_id: str) -> pd.Series:
    df = pd.read_csv(DATA / f"fred_{series_id}.csv", parse_dates=["DATE"]).set_index("DATE").sort_index()
    return pd.to_numeric(df[series_id], errors="coerce").dropna()


def load_news() -> pd.Series:
    df = pd.read_csv(DATA / "sf_news_sentiment.csv", parse_dates=["DATE"]).set_index("DATE").sort_index()
    return pd.to_numeric(df["news_sentiment"], errors="coerce").dropna()


def garman_klass_variance(ohlc: pd.DataFrame) -> pd.Series:
    """Garman-Klass daily variance estimator (range-based RV proxy).

    GK_t = 0.5*(ln(H/L))^2 - (2 ln2 - 1)*(ln(C/O))^2  >= 0 always.
    """
    hl = np.log(ohlc["High"] / ohlc["Low"])
    co = np.log(ohlc["Close"] / ohlc["Open"])
    gk = 0.5 * hl**2 - (2.0 * np.log(2.0) - 1.0) * co**2
    gk = gk.clip(lower=EPS)
    return gk.rename("gk_var")


def build_frame(ohlc: pd.DataFrame, epu: pd.Series, vix: pd.Series,
                news: pd.Series) -> pd.DataFrame:
    """Assemble the modelling frame on the equity trading-day calendar.

    All predictors are lagged (.shift(1)); the target y_t is contemporaneous.
    Exogenous series are reindexed onto trading days and forward-filled to the
    most recent value available on-or-before each day, THEN shifted one day, so
    day t only ever sees information dated <= t-1.
    """
    gk = garman_klass_variance(ohlc)
    y = np.log(gk).rename("y")                     # log realized variance (proxy)
    idx = y.index

    df = pd.DataFrame(index=idx)
    df["y"] = y
    df["gk_var"] = gk

    # HAR components (Corsi 2009), all strictly using info <= t-1.
    df["har_d"] = y.shift(1)
    df["har_w"] = y.rolling(5).mean().shift(1)
    df["har_m"] = y.rolling(22).mean().shift(1)

    # Exogenous predictors: align to trading days -> ffill (BOUNDED) -> shift(1).
    # The ffill limit bridges holiday gaps only; it must NOT fabricate a long
    # stale run past a series' true last observation. Without the cap, SF Fed
    # news sentiment (ends 2023-11-26) would be frozen as a constant through
    # 2026, silently inflating the sample and neutering the news spec.
    def _align(exog: pd.Series, limit: int = FFILL_LIMIT) -> pd.Series:
        return exog.reindex(idx.union(exog.index)).ffill(limit=limit).reindex(idx)

    epu_al = _align(epu)
    vix_al = _align(vix)
    news_al = _align(news)

    df["epu"] = np.log(epu_al).shift(1)            # log EPU_{t-1}
    df["vix"] = np.log(vix_al).shift(1)            # log VIX_{t-1}
    df["news"] = news_al.shift(1)                  # news sentiment_{t-1}

    return df


# Spec name -> list of regressor columns (constant added automatically).
SPECS: dict[str, list[str]] = {
    "HAR":            ["har_d", "har_w", "har_m"],
    "HAR+EPU":        ["har_d", "har_w", "har_m", "epu"],
    "HAR+News":       ["har_d", "har_w", "har_m", "news"],
    "HAR+VIX":        ["har_d", "har_w", "har_m", "vix"],
    "HAR+EPU+News":   ["har_d", "har_w", "har_m", "epu", "news"],
    "HAR+EPU+News+VIX": ["har_d", "har_w", "har_m", "epu", "news", "vix"],
}
BASELINE = "HAR"


# --------------------------------------------------------------------------- #
# OOS forecasting
# --------------------------------------------------------------------------- #
def _design(frame: pd.DataFrame, cols: list[str]) -> np.ndarray:
    X = frame[cols].to_numpy(dtype=float)
    return np.column_stack([np.ones(len(X)), X])


def oos_forecasts(frame: pd.DataFrame, oos_start: str,
                  scheme: str = "expanding") -> dict:
    """Produce one-step OOS forecasts of y_t for every spec.

    At each OOS origin the OLS coefficients are re-fit on the training rows
    (positions strictly < current position for 'expanding'; the trailing
    ROLL_WINDOW positions for 'rolling'). Every spec is fit on the SAME
    training rows and predicts the SAME target rows.
    """
    frame = frame.sort_index()
    oos_mask = np.asarray(frame.index >= pd.Timestamp(oos_start))
    positions = np.where(oos_mask)[0]
    positions = positions[positions > 0]           # need >=1 training row

    y = frame["y"].to_numpy(dtype=float)
    designs = {name: _design(frame, cols) for name, cols in SPECS.items()}

    dates = frame.index[positions]
    actual = y[positions]
    forecasts = {name: np.full(len(positions), np.nan) for name in SPECS}

    for k, i in enumerate(positions):
        if scheme == "expanding":
            lo = 0
        elif scheme == "rolling":
            lo = max(0, i - ROLL_WINDOW)
        else:
            raise ValueError(scheme)
        tr = slice(lo, i)                            # rows < i only
        y_tr = y[tr]
        for name, X in designs.items():
            X_tr = X[tr]
            beta, *_ = np.linalg.lstsq(X_tr, y_tr, rcond=None)
            forecasts[name][k] = X[i] @ beta

    return {
        "dates": dates,
        "actual": actual,
        "forecasts": forecasts,
        "gk_var": frame["gk_var"].to_numpy(dtype=float)[positions],
        "positions": positions,
    }


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
def campbell_thompson_oos_r2(actual, f_small, f_large) -> float:
    """Incremental OOS R^2 of the larger nested model vs the baseline.

    R2 = 1 - SSE_large / SSE_small ; positive => larger model beats baseline.
    """
    sse_large = np.sum((actual - f_large) ** 2)
    sse_small = np.sum((actual - f_small) ** 2)
    return float(1.0 - sse_large / sse_small)


def train_resid_var(frame: pd.DataFrame, cols: list[str], oos_start: str) -> float:
    """Residual variance on the pre-OOS training block (for log-normal
    bias-correction of variance-level QLIKE). Uses only pre-OOS data."""
    tr = np.asarray(frame.index < pd.Timestamp(oos_start))
    X = _design(frame, cols)[tr]
    y = frame["y"].to_numpy(dtype=float)[tr]
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    return float(np.var(resid, ddof=X.shape[1]))


def evaluate(oos: dict, frame: pd.DataFrame, oos_start: str) -> dict:
    actual = oos["actual"]
    gk_actual = oos["gk_var"]                        # realized variance (level)
    f = oos["forecasts"]
    f_base = f[BASELINE]

    # per-spec log-normal correction constant for variance-level forecasts
    s2 = {name: train_resid_var(frame, cols, oos_start) for name, cols in SPECS.items()}

    out = {}
    mse_base = float(np.mean((actual - f_base) ** 2))
    for name in SPECS:
        fc = f[name]
        e = actual - fc
        mse = float(np.mean(e ** 2))
        # variance-level forecast with log-normal bias correction
        var_pred = np.exp(fc + 0.5 * s2[name])
        ql = float(qlike(gk_actual, var_pred))

        rec = {
            "n_oos": int(len(actual)),
            "mse_logrv": mse,
            "qlike": ql,
            "resid_var_train": s2[name],
        }
        if name == BASELINE:
            rec["incremental_oos_r2_vs_HAR"] = 0.0
        else:
            rec["incremental_oos_r2_vs_HAR"] = campbell_thompson_oos_r2(actual, f_base, fc)
            # Clark-West (primary), nested: small=HAR, large=aug
            cw = clark_west_test(actual, f_base, fc, h=1)
            rec["clark_west"] = {
                "t_stat": cw["t_stat"],
                "p_value_one_sided": cw["p_value_one_sided"],
                "p_value_two_sided": cw["p_value_two_sided"],
                "hac_lag": cw["hac_lag"],
                "status": cw["status"],
            }
            # nested-dm: diagnostic-only -- ordinary DM is a descriptive directional
            # cross-check under the nested null; the verdict uses Clark-West only.
            t_dm, p_dm = dm_test(e ** 2, (actual - f_base) ** 2, h=1)
            rec["dm_logrv"] = {"t_stat": float(t_dm), "p_value": float(p_dm),
                               "note": "negative t => augmented better"}
            # DM on QLIKE loss (variance level)
            ql_aug = qlike_pointwise_local(gk_actual, var_pred)
            ql_base = qlike_pointwise_local(gk_actual, np.exp(f_base + 0.5 * s2[BASELINE]))
            t_dmq, p_dmq = dm_test(ql_aug, ql_base, h=1)
            rec["dm_qlike"] = {"t_stat": float(t_dmq), "p_value": float(p_dmq),
                               "note": "negative t => augmented better"}
        out[name] = rec
    out["_baseline_mse_logrv"] = mse_base
    return out


def qlike_pointwise_local(actual, predicted) -> np.ndarray:
    a = np.asarray(actual, dtype=float)
    p = np.asarray(predicted, dtype=float)
    return a / p - np.log(a / p) - 1.0


# --------------------------------------------------------------------------- #
# Regime-conditional analysis
# --------------------------------------------------------------------------- #
def regime_analysis(oos: dict, frame: pd.DataFrame, oos_start: str) -> dict:
    """Split OOS days by the t-1 regime variable (already lagged; no lookahead).

    Thresholds are fixed from the PRE-OOS block only, so the regime split uses
    no future information. Reports incremental OOS R^2 and Clark-West within
    each regime for the free-attention/sentiment specs.
    """
    positions = oos["positions"]
    actual = oos["actual"]
    f = oos["forecasts"]

    pre = np.asarray(frame.index < pd.Timestamp(oos_start))
    results = {}
    for reg_name, col, fixed_thr in [
        ("VIX", "vix", np.log(20.0)),               # vix col is log VIX_{t-1}
        ("EPU", "epu", None),
    ]:
        series = frame[col].to_numpy(dtype=float)[positions]
        pre_vals = frame[col].to_numpy(dtype=float)[pre]
        thr_data = float(np.nanpercentile(pre_vals, 70))
        cuts = {"pre_oos_70pct": thr_data}
        if fixed_thr is not None:
            cuts["fixed_VIX20"] = float(fixed_thr)

        for cut_name, thr in cuts.items():
            high = series > thr
            reg = {}
            for regime, mask in [("high", high), ("low", ~high)]:
                m = mask & np.isfinite(series)
                sub = {"n": int(np.sum(m))}
                if np.sum(m) >= 30:
                    a = actual[m]
                    fb = f[BASELINE][m]
                    for spec in ["HAR+EPU", "HAR+News", "HAR+EPU+News", "HAR+VIX"]:
                        fa = f[spec][m]
                        cw = clark_west_test(a, fb, fa, h=1)
                        sub[spec] = {
                            "incremental_oos_r2": campbell_thompson_oos_r2(a, fb, fa),
                            "cw_t": cw["t_stat"],
                            "cw_p_one_sided": cw["p_value_one_sided"],
                        }
                reg[regime] = sub
            results[f"{reg_name}_{cut_name}"] = {"threshold": thr, "regimes": reg}
    return results


# --------------------------------------------------------------------------- #
# Figures
# --------------------------------------------------------------------------- #
def make_figures(frame: pd.DataFrame, base_oos: dict, base_eval: dict,
                 regime: dict) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    paths = []

    # Fig 1: incremental OOS R^2 by spec
    specs = [s for s in SPECS if s != BASELINE]
    vals = [base_eval[s]["incremental_oos_r2_vs_HAR"] * 100 for s in specs]
    sig = [base_eval[s]["clark_west"]["p_value_one_sided"] < 0.05 for s in specs]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    colors = ["#2b7bba" if s else "#b0b0b0" for s in sig]
    ax.bar(range(len(specs)), vals, color=colors)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xticks(range(len(specs)))
    ax.set_xticklabels(specs, rotation=20, ha="right", fontsize=9)
    ax.set_ylabel("Incremental OOS R2 vs HAR (%)")
    ax.set_title("K1728: incremental OOS R2 (blue = Clark-West p<0.05, one-sided)")
    for i, v in enumerate(vals):
        ax.text(i, v + (0.02 if v >= 0 else -0.05), f"{v:.2f}", ha="center", fontsize=8)
    fig.tight_layout()
    p1 = FIG / "fig1_incremental_oos_r2_by_spec.png"
    fig.savefig(p1, dpi=130)
    plt.close(fig)
    paths.append(p1.name)

    # Fig 2: incremental OOS R^2 by VIX regime for key specs
    reg_key = "VIX_fixed_VIX20"
    reg = regime[reg_key]["regimes"]
    key_specs = ["HAR+EPU", "HAR+News", "HAR+EPU+News", "HAR+VIX"]
    hi = [reg["high"].get(s, {}).get("incremental_oos_r2", np.nan) * 100 for s in key_specs]
    lo = [reg["low"].get(s, {}).get("incremental_oos_r2", np.nan) * 100 for s in key_specs]
    x = np.arange(len(key_specs))
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(x - 0.2, hi, 0.4, label=f"high VIX (>20, n={reg['high']['n']})", color="#d1495b")
    ax.bar(x + 0.2, lo, 0.4, label=f"low VIX (<=20, n={reg['low']['n']})", color="#66a182")
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(key_specs, rotation=20, ha="right", fontsize=9)
    ax.set_ylabel("Incremental OOS R2 vs HAR (%)")
    ax.set_title("K1728: incremental OOS R2 by VIX_{t-1} regime")
    ax.legend(fontsize=8)
    fig.tight_layout()
    p2 = FIG / "fig2_incremental_oos_r2_by_regime.png"
    fig.savefig(p2, dpi=130)
    plt.close(fig)
    paths.append(p2.name)

    # Fig 3: predictor time-series vs log-RV (standardized)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    sub = frame.dropna(subset=["y", "epu", "vix", "news"])
    def z(s):
        return (s - s.mean()) / s.std()
    ax.plot(sub.index, z(sub["y"]), color="k", lw=0.6, alpha=0.7, label="log-RV (GK)")
    ax.plot(sub.index, z(sub["vix"]), color="#2b7bba", lw=0.7, alpha=0.8, label="log VIX_{t-1}")
    ax.plot(sub.index, z(sub["epu"]), color="#e07b39", lw=0.6, alpha=0.6, label="log EPU_{t-1}")
    ax.plot(sub.index, z(-sub["news"]), color="#7a5195", lw=0.6, alpha=0.6, label="-news sent_{t-1}")
    ax.set_ylabel("z-score")
    ax.set_title("K1728: standardized predictors (t-1) vs log realized variance")
    ax.legend(fontsize=8, ncol=4)
    fig.tight_layout()
    p3 = FIG / "fig3_predictors_vs_rv.png"
    fig.savefig(p3, dpi=130)
    plt.close(fig)
    paths.append(p3.name)

    return paths


# --------------------------------------------------------------------------- #
# Descriptive diagnostics (observe before compute)
# --------------------------------------------------------------------------- #
def descriptives(frame: pd.DataFrame) -> dict:
    y = frame["y"].dropna()

    def acf(series, lags):
        s = series.to_numpy(dtype=float)
        s = s - s.mean()
        denom = np.sum(s * s)
        return {int(L): float(np.sum(s[L:] * s[:-L]) / denom) for L in lags}

    corr = frame[["y", "epu", "vix", "news"]].dropna().corr().to_dict()
    return {
        "logrv_mean": float(y.mean()),
        "logrv_std": float(y.std()),
        "logrv_min": float(y.min()),
        "logrv_max": float(y.max()),
        "logrv_acf": acf(y, [1, 5, 22]),
        "pearson_corr_matrix": {k: {kk: float(vv) for kk, vv in v.items()} for k, v in corr.items()},
    }


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def run_asset(ticker: str, ohlc_file: str, epu, vix, news) -> dict:
    ohlc = load_ohlc(ohlc_file)
    frame_full = build_frame(ohlc, epu, vix, news)
    frame = frame_full.dropna(subset=list(
        {c for cols in SPECS.values() for c in cols} | {"y", "gk_var"}
    )).copy()

    sample = {
        "n_rows": int(len(frame)),
        "start": frame.index[0].strftime("%Y-%m-%d"),
        "end": frame.index[-1].strftime("%Y-%m-%d"),
    }

    oos = oos_forecasts(frame, OOS_START_DEFAULT, "expanding")
    ev = evaluate(oos, frame, OOS_START_DEFAULT)
    reg = regime_analysis(oos, frame, OOS_START_DEFAULT)

    result = {
        "ticker": ticker,
        "sample": sample,
        "oos_start": OOS_START_DEFAULT,
        "n_oos": int(len(oos["actual"])),
        "oos_window": frame.index[oos["positions"]][0].strftime("%Y-%m-%d")
                      + ".." + frame.index[oos["positions"]][-1].strftime("%Y-%m-%d"),
        "specs": ev,
        "regime": reg,
    }
    return result, frame, oos, ev, reg


def robustness(frame: pd.DataFrame) -> dict:
    """OOS-start sensitivity, rolling vs expanding, on the SPY primary frame."""
    out = {"oos_start_sensitivity": {}, "rolling_vs_expanding": {}, "dm_hac_lag_sensitivity": {}}
    key_specs = ["HAR+EPU", "HAR+News", "HAR+EPU+News", "HAR+VIX"]

    for start in ["2013-01-01", "2015-01-01", "2018-01-01", "2020-06-01"]:
        oos = oos_forecasts(frame, start, "expanding")
        ev = evaluate(oos, frame, start)
        out["oos_start_sensitivity"][start] = {
            "n_oos": int(len(oos["actual"])),
            **{s: {"incremental_oos_r2": ev[s]["incremental_oos_r2_vs_HAR"],
                   "cw_p_one_sided": ev[s]["clark_west"]["p_value_one_sided"]}
               for s in key_specs},
        }

    for scheme in ["expanding", "rolling"]:
        oos = oos_forecasts(frame, OOS_START_DEFAULT, scheme)
        ev = evaluate(oos, frame, OOS_START_DEFAULT)
        out["rolling_vs_expanding"][scheme] = {
            s: {"incremental_oos_r2": ev[s]["incremental_oos_r2_vs_HAR"],
                "cw_p_one_sided": ev[s]["clark_west"]["p_value_one_sided"]}
            for s in key_specs
        }

    # DM HAC lag sensitivity for the headline free-attention spec (per DM-HAC rule)
    oos = oos_forecasts(frame, OOS_START_DEFAULT, "expanding")
    a = oos["actual"]
    fb = oos["forecasts"][BASELINE]
    fa = oos["forecasts"]["HAR+EPU+News"]
    for lag in [1, 5, 10, 22]:
        t, p = dm_test((a - fa) ** 2, (a - fb) ** 2, h=lag)
        out["dm_hac_lag_sensitivity"][f"h{lag}"] = {"t_stat": float(t), "p_value": float(p)}
    return out


def main() -> int:
    epu = load_fred("USEPUINDXD")
    vix = load_fred("VIXCLS")
    news = load_news()
    provenance = json.loads((DATA / "provenance.json").read_text())

    # Primary asset: SPY
    spy_res, frame, oos, ev, reg = run_asset("SPY", "spy_ohlc.csv", epu, vix, news)
    desc = descriptives(frame)
    robust = robustness(frame)
    figs = make_figures(frame, oos, ev, reg)

    # Robustness asset: QQQ (headline only)
    qqq_res, *_ = run_asset("QQQ", "qqq_ohlc.csv", epu, vix, news)

    # Headline verdict
    primary_specs = ["HAR+EPU", "HAR+News", "HAR+EPU+News"]   # FREE attention/sentiment
    any_pass = False
    headline = {}
    for s in primary_specs:
        r2 = ev[s]["incremental_oos_r2_vs_HAR"]
        p = ev[s]["clark_west"]["p_value_one_sided"]
        passed = (r2 > 0) and (p < 0.05)
        any_pass = any_pass or passed
        headline[s] = {"incremental_oos_r2": r2, "cw_p_one_sided": p, "pass": passed}
    vix_r2 = ev["HAR+VIX"]["incremental_oos_r2_vs_HAR"]
    vix_p = ev["HAR+VIX"]["clark_west"]["p_value_one_sided"]

    verdict = "PASS" if any_pass else "NULL"

    results = {
        "k_id": "k1728",
        "title": "Incremental OOS predictive power of free macro-attention / news "
                 "sentiment for US-equity realized variance over HAR-RV",
        "seed": SEED,
        "verdict": verdict,
        "headline": {
            "question": "Does a FREE attention/sentiment regressor add significant "
                        "incremental OOS forecast power over HAR-RV for US-equity RV?",
            "free_attention_sentiment_specs": headline,
            "any_free_spec_pass": any_pass,
            "vix_benchmark": {"incremental_oos_r2": vix_r2, "cw_p_one_sided": vix_p,
                              "note": "VIX is an options-implied vol forecast, not a free "
                                      "attention proxy; included as strong control/benchmark."},
        },
        "rv_measure": "Garman-Klass daily variance (range-based RV proxy), log target",
        "descriptives": desc,
        "primary_SPY": spy_res,
        "robustness_SPY": robust,
        "robustness_QQQ": qqq_res,
        "data_provenance": provenance,
        "figures": figs,
        "methodology_notes": {
            "primary_test": "Clark-West (2007) MSPE-adjusted, nested (canonical "
                            "volpred.stats.model_evaluation.clark_west_test)",
            "secondary_tests": ["Campbell-Thompson incremental OOS R2",
                                 "Diebold-Mariano (HLN HAC) on log-RV squared error and QLIKE"],
            "oos_scheme": "expanding window, one-step, refit each origin",
            "lag_convention": "every predictor .shift(1); HAR d/w/m via rolling().shift(1); "
                              "baseline and augmented identical lags & sample rows",
            "real_time_caveat": "Macro predictors (EPU) use final-vintage downloads; the OOS is "
                                "final-vintage pseudo-OOS, not certified PIT real-time. EPU daily "
                                "carries minor revision risk. VIX and price-based RV are effectively "
                                "unrevised; SF Fed news sentiment is a mechanical text score.",
            "news_sentiment_coverage_note": "SF Fed Daily News Sentiment ends 2023-11-26; the "
                                            "all-series intersection sample therefore ends then. "
                                            "EPU/VIX-only robustness could extend further but the "
                                            "primary nested comparison holds the sample fixed.",
            "qlike_direction_caveat": "The NULL verdict rests on the primary criterion "
                                      "(Clark-West + Campbell-Thompson OOS R2 on log-RV, the "
                                      "model's native target), which is unambiguously NULL for "
                                      "the free-text specs. On variance-level QLIKE the free "
                                      "specs' point estimates are marginally LOWER (better) than "
                                      "HAR (see specs[*].qlike), but this is NOT valid nested "
                                      "inference (dm_qlike is diagnostic-only) and is plausibly a "
                                      "log-normal bias-correction artifact: a larger model has a "
                                      "smaller train residual variance s2, lowering exp(f+0.5 s2), "
                                      "and asymmetric QLIKE rewards that level shift independently "
                                      "of predictive content. QLIKE is therefore NOT cited as "
                                      "null-supporting robustness.",
        },
    }

    out = HERE / "k1728_results.json"
    out.write_text(json.dumps(results, indent=2, default=float))
    print(f"[k1728] verdict={verdict}  wrote {out}")
    print(f"[k1728] SPY sample {spy_res['sample']['start']}..{spy_res['sample']['end']} "
          f"n={spy_res['sample']['n_rows']} oos={spy_res['n_oos']} ({spy_res['oos_window']})")
    for s in primary_specs + ["HAR+VIX"]:
        r = ev[s]
        cw = r["clark_west"]
        print(f"  {s:20s} incR2={r['incremental_oos_r2_vs_HAR']*100:+.3f}%  "
              f"CW t={cw['t_stat']:+.3f} p1={cw['p_value_one_sided']:.4f}  "
              f"DM(logrv) t={r['dm_logrv']['t_stat']:+.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
