"""
K1116: Alternative Data (EPU + NFCI + STLFSI) for SPY Vol Prediction — Regime-Conditional Test

Original brief: Google Trends for SPY vol prediction.
  - Knowledge base check found K473/K750/K789 already did Google Trends vol prediction, all NULL.
  - pytrends hit 429 rate limit (trivially reproduces K750 data issues).
  - Per brief fallback ("若 pytrends 無法用 → 用替代：FRED Sentiment Index"):
    pivoted to REAL alternative data from FRED that has NOT been tested for SPY vol.

Data:
  - US Economic Policy Uncertainty (USEPUINDXD, daily, Baker/Bloom/Davis 2016)
  - World EPU (WLEMUINDXD, daily)
  - National Financial Conditions Index (NFCI, weekly, Chicago Fed)
  - St. Louis Fed Financial Stress Index (STLFSI4, weekly)
  - All aggregated to weekly frequency

These are standard academic alternative data sources with established literature:
  - Baker, Bloom, Davis (2016) QJE — EPU construction
  - Brave, Butters (2011) — NFCI construction
  - Kliesen, Smith (2010) — STLFSI
None of these have been tested for SPY weekly vol prediction in our knowledge base
(grep of knowledge.json for 'EPU', 'NFCI', 'STLFSI' returns 0 SPY-vol experiments).

Design:
  - 2018-01 to 2026-04 weekly (same as originally planned)
  - IS: 2018-2022, OOS: 2023-2026
  - 5 models: baseline AR(1), +VIX, +EPU_composite, +NFCI+STLFSI, +ALL
  - Regime-conditional DM: calm/stress/transition (new angle vs K473/K750)
  - BH-adj keyword-level p-values
  - QLIKE loss, DM-HLN test with Harvey correction

Target: SPY weekly realized vol (sum of squared daily log-returns).
All signals lagged by 1 week (signal_{t-1} predicts vol_t) — no lookahead.

Prior NULL experiments tested: K473/K750/K789 (Google Trends, all NULL).
K504 (STLFSI4) returned null in knowledge base search — but narrow test.
This is a broader multi-source alt-data test with regime stratification.
"""
import json
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

OUT_DIR = Path(__file__).parent
RESULTS = {
    "experiment_id": "K1116",
    "title": "Alternative Data (EPU + NFCI + STLFSI) for SPY Vol Prediction — Regime-Conditional",
    "started_utc": datetime.utcnow().isoformat() + "Z",
    "data_source": "FRED (USEPUINDXD, WLEMUINDXD, NFCI, ANFCI, STLFSI4) + yfinance (SPY, VIX)",
    "pivot_from": "Google Trends (pytrends 429 rate-limited; K750 already NULL for GT-vol)",
    "prior_related": {
        "K473": "Google Trends attention -> vol: NULL",
        "K750": "Real Google Trends fear -> vol: NULL (Fear LAGS VIX, reactive)",
        "K789": "Google Trends -> return + tail: NULL",
        "K192": "Google Trends general overfitting warning",
        "K504": "STLFSI4 narrow: NULL (but not in regime-conditional framework)",
    },
    "new_angle": "Regime-conditional DM stratification (calm/stress/transition) on EPU+NFCI+STLFSI",
    "references": [
        "Baker, Bloom, Davis (2016) QJE - EPU index",
        "Brave, Butters (2011) - NFCI",
        "Kliesen, Smith (2010) - STLFSI",
        "Patton (2011) - QLIKE proxy-robust loss",
        "Harvey, Leybourne, Newbold (1997) - HLN DM correction",
    ],
}


def log(msg):
    ts = datetime.utcnow().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def fetch_spy_vix_weekly():
    import yfinance as yf

    log("Fetching SPY + VIX daily 2018-2026...")
    spy = yf.download("SPY", start="2018-01-01", end="2026-04-13", progress=False, auto_adjust=True)
    vix = yf.download("^VIX", start="2018-01-01", end="2026-04-13", progress=False, auto_adjust=False)

    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    spy = spy[["Close"]].copy()
    spy["r"] = np.log(spy["Close"]).diff()

    # Weekly aggregation: RV = sqrt(sum(r^2))
    spy["week"] = spy.index.to_period("W-FRI").to_timestamp("W-FRI")
    weekly = pd.DataFrame(index=spy["week"].unique())
    weekly.index.name = "week"
    weekly["rv"] = spy.groupby("week")["r"].apply(lambda x: np.sqrt(np.sum(x.dropna() ** 2)))
    weekly["r_n"] = spy.groupby("week")["r"].count()
    weekly["r_sum"] = spy.groupby("week")["r"].sum()
    weekly = weekly[weekly["r_n"] >= 4]
    weekly = weekly.sort_index()

    vix_df = vix[["Close"]].rename(columns={"Close": "vix"})
    vix_df["week"] = vix_df.index.to_period("W-FRI").to_timestamp("W-FRI")
    vix_w = vix_df.groupby("week").agg(vix_mean=("vix", "mean"), vix_last=("vix", "last"))

    df = weekly.join(vix_w, how="inner").dropna()
    log(f"Weekly SPY+VIX: {len(df)} weeks, {df.index.min().date()} to {df.index.max().date()}")
    return df


def fetch_fred_altdata():
    """Fetch 5 FRED series, aggregate to weekly."""
    from pandas_datareader import data as pdr

    codes = {
        "USEPU": "USEPUINDXD",  # daily
        "WLEMU": "WLEMUINDXD",  # daily
        "NFCI": "NFCI",  # weekly (Fri)
        "ANFCI": "ANFCI",  # weekly
        "STLFSI": "STLFSI4",  # weekly
    }
    log(f"Fetching FRED alt-data: {list(codes.values())}")
    frames = {}
    for name, code in codes.items():
        try:
            s = pdr.DataReader(code, "fred", "2018-01-01", "2026-04-13")
            s.columns = [name]
            frames[name] = s
            log(f"  {code}: {s.shape}, last={s.index[-1].date()}")
        except Exception as e:
            log(f"  {code}: FAIL {str(e)[:80]}")

    # Aggregate daily to weekly (W-FRI)
    weekly_frames = []
    for name, s in frames.items():
        s = s.copy()
        s["week"] = s.index.to_period("W-FRI").to_timestamp("W-FRI")
        w = s.groupby("week").agg({name: "mean"})
        weekly_frames.append(w)

    out = weekly_frames[0]
    for w in weekly_frames[1:]:
        out = out.join(w, how="outer")
    # forward-fill weekly series where needed (NFCI releases Wednesday for prior Friday)
    out = out.sort_index().ffill(limit=2)
    log(f"FRED weekly merged: {out.shape}, nan_pct_per_col:")
    for c in out.columns:
        log(f"  {c}: {out[c].isna().mean():.2%} missing")
    return out


def qlike(actual, pred):
    eps = 1e-10
    actual = np.maximum(actual, eps)
    pred = np.maximum(pred, eps)
    return np.mean(np.log(pred) + actual / pred)


def dm_hln(e1, e2, h=1):
    """DM-HLN. e1, e2: loss series. Positive t means e1 > e2 -> model-2 (e2) beats model-1."""
    from scipy import stats as st

    d = np.asarray(e1, dtype=float) - np.asarray(e2, dtype=float)
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan
    dbar = d.mean()
    gamma0 = np.var(d, ddof=1)
    if gamma0 <= 0:
        return np.nan, np.nan
    hln_correction = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    se = np.sqrt(gamma0 / n)
    t = (dbar / se) * hln_correction
    p = 2 * (1 - st.t.cdf(abs(t), df=n - 1))
    return t, p


def benjamini_hochberg(p_values):
    p = np.asarray(p_values, dtype=float)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order]
    adjusted = np.minimum.accumulate((ranked * n / np.arange(1, n + 1))[::-1])[::-1]
    adjusted = np.minimum(adjusted, 1.0)
    out = np.empty_like(adjusted)
    out[order] = adjusted
    return out


def main():
    # Step 1: data
    market = fetch_spy_vix_weekly()
    altdata = fetch_fred_altdata()

    df = market.join(altdata, how="inner").dropna()
    log(f"Merged panel: {len(df)} weeks, {df.index.min().date()} to {df.index.max().date()}")

    alt_cols = list(altdata.columns)
    RESULTS["alt_data_columns"] = alt_cols
    RESULTS["n_full"] = int(len(df))

    # IS/OOS split
    is_end = "2022-12-31"
    oos_start = "2023-01-01"
    df_is = df.loc[:is_end].copy()
    df_oos = df.loc[oos_start:].copy()

    RESULTS["n_is"] = int(len(df_is))
    RESULTS["n_oos"] = int(len(df_oos))
    RESULTS["is_period"] = [str(df_is.index.min().date()), str(df_is.index.max().date())]
    RESULTS["oos_period"] = [str(df_oos.index.min().date()), str(df_oos.index.max().date())]
    log(f"IS: {len(df_is)}, OOS: {len(df_oos)}")

    # Descriptive stats
    RESULTS["descriptive_stats"] = {
        c: {
            "mean": float(df[c].mean()),
            "std": float(df[c].std()),
            "min": float(df[c].min()),
            "max": float(df[c].max()),
        }
        for c in ["rv", "vix_mean"] + alt_cols
    }

    # Correlations (IS period, lagged-1 vs rv)
    corr_is = {}
    for c in alt_cols + ["vix_mean"]:
        s = df_is[c].shift(1)
        valid = s.notna() & df_is["rv"].notna()
        corr_is[c] = float(s[valid].corr(df_is["rv"][valid]))
    RESULTS["lag1_corr_with_rv_IS"] = corr_is
    log(f"IS lag-1 correlations with RV: {corr_is}")

    # ---------- Models ----------
    import statsmodels.api as sm

    def make_X(df_sub, spec):
        X = pd.DataFrame(index=df_sub.index)
        X["y_lag1"] = df_sub["rv"].shift(1)
        if spec == "base":
            return X.dropna()
        if spec == "vix":
            X["vix_lag1"] = df_sub["vix_mean"].shift(1)
        elif spec == "epu":
            X["USEPU_lag1"] = df_sub["USEPU"].shift(1)
            X["WLEMU_lag1"] = df_sub["WLEMU"].shift(1)
        elif spec == "finstress":
            X["NFCI_lag1"] = df_sub["NFCI"].shift(1)
            X["ANFCI_lag1"] = df_sub["ANFCI"].shift(1)
            X["STLFSI_lag1"] = df_sub["STLFSI"].shift(1)
        elif spec == "all":
            X["vix_lag1"] = df_sub["vix_mean"].shift(1)
            X["USEPU_lag1"] = df_sub["USEPU"].shift(1)
            X["WLEMU_lag1"] = df_sub["WLEMU"].shift(1)
            X["NFCI_lag1"] = df_sub["NFCI"].shift(1)
            X["ANFCI_lag1"] = df_sub["ANFCI"].shift(1)
            X["STLFSI_lag1"] = df_sub["STLFSI"].shift(1)
        return X.dropna()

    specs = ["base", "vix", "epu", "finstress", "all"]
    model_names = {
        "base": "M1_AR1",
        "vix": "M2_AR1_VIX",
        "epu": "M3_AR1_EPU",
        "finstress": "M4_AR1_FinStress",
        "all": "M5_AR1_All",
    }

    is_results = {}
    fitted_models = {}
    oos_qlike_losses = {}
    oos_forecasts_all = {}

    for spec in specs:
        name = model_names[spec]
        X_is = make_X(df_is, spec)
        y_is = df_is["rv"].loc[X_is.index]
        Xc_is = sm.add_constant(X_is, has_constant="add")
        ols = sm.OLS(y_is, Xc_is).fit()
        fitted_models[name] = (ols, Xc_is.columns.tolist())
        is_results[name] = {
            "r2": float(ols.rsquared),
            "adj_r2": float(ols.rsquared_adj),
            "aic": float(ols.aic),
            "bic": float(ols.bic),
            "n_is": int(len(y_is)),
            "params": {k: float(v) for k, v in ols.params.to_dict().items()},
            "pvalues": {k: float(v) for k, v in ols.pvalues.to_dict().items()},
        }
        # OOS
        X_oos = make_X(df_oos, spec)
        Xc_oos = sm.add_constant(X_oos, has_constant="add")
        Xc_oos = Xc_oos.reindex(columns=Xc_is.columns, fill_value=0.0)
        pred = ols.predict(Xc_oos).clip(lower=1e-6)
        actual = df_oos["rv"].loc[X_oos.index]
        oos_forecasts_all[name] = {"pred": pred, "actual": actual}
        oos_qlike_losses[name] = np.log(pred) + actual / pred

    log("In-sample fits complete")

    RESULTS["is_results"] = is_results

    # ---------- DM tests ----------
    baseline = "M2_AR1_VIX"
    common_idx = oos_qlike_losses[baseline].index
    for m in oos_qlike_losses:
        common_idx = common_idx.intersection(oos_qlike_losses[m].index)

    log(f"Common OOS n: {len(common_idx)}")
    base_loss = oos_qlike_losses[baseline].reindex(common_idx)

    dm_tests = {}
    for m in ["M1_AR1", "M3_AR1_EPU", "M4_AR1_FinStress", "M5_AR1_All"]:
        m_loss = oos_qlike_losses[m].reindex(common_idx)
        # dm_hln(e1, e2): positive t -> e1 > e2 -> model-2 (challenger) beats model-1 (baseline).
        # We pass e1=baseline, e2=challenger, so positive t means challenger beats baseline.
        t, p = dm_hln(base_loss.values, m_loss.values)
        # Harvey PASS only if challenger BEATS baseline significantly (positive t AND |t|>2).
        # Significant NEGATIVE t means challenger is significantly WORSE - not a "pass".
        challenger_beats = (not np.isnan(t)) and (t > 2.0)
        baseline_beats = (not np.isnan(t)) and (t < -2.0)
        dm_tests[f"{baseline}_vs_{m}"] = {
            "t_stat": float(t) if not np.isnan(t) else None,
            "p_value": float(p) if not np.isnan(p) else None,
            "interpretation": (
                f"{m} beats baseline" if challenger_beats
                else (f"baseline beats {m}" if baseline_beats else "indistinguishable")
            ),
            "challenger_wins_harvey": bool(challenger_beats),
            "baseline_wins_harvey": bool(baseline_beats),
            # legacy 'harvey_pass' (|t|>2) retained for ablation only; NOT a success flag
            "abs_t_gt_2": bool(abs(t) > 2.0) if not np.isnan(t) else False,
        }
    RESULTS["dm_tests_full_oos"] = dm_tests

    # IS vs OOS QLIKE comparison
    is_oos_table = {}
    for name in model_names.values():
        # IS QLIKE
        ols, cols = fitted_models[name]
        spec = [k for k, v in model_names.items() if v == name][0]
        X_is = make_X(df_is, spec)
        Xc_is = sm.add_constant(X_is, has_constant="add").reindex(columns=cols, fill_value=0.0)
        pred_is = ols.predict(Xc_is).clip(lower=1e-6)
        actual_is = df_is["rv"].loc[X_is.index]
        is_qlike = float(qlike(actual_is.values, pred_is.values))

        actual_oos = oos_forecasts_all[name]["actual"].reindex(common_idx)
        pred_oos = oos_forecasts_all[name]["pred"].reindex(common_idx)
        oos_qlike = float(qlike(actual_oos.values, pred_oos.values))
        oos_rmse = float(np.sqrt(np.mean((actual_oos.values - pred_oos.values) ** 2)))

        is_oos_table[name] = {
            "IS_R2": is_results[name]["r2"],
            "IS_QLIKE": is_qlike,
            "OOS_QLIKE": oos_qlike,
            "OOS_RMSE": oos_rmse,
            "OOS_n": int(len(common_idx)),
            "divergence_IS_OOS": oos_qlike - is_qlike,
        }
    RESULTS["is_oos_comparison"] = is_oos_table

    # ---------- Regime-conditional DM ----------
    vix_series = df_oos["vix_mean"].reindex(common_idx)
    vix_prev = vix_series.shift(1)
    transition_mask = (vix_prev < 18) & (vix_series >= 22)
    calm_mask = vix_series < 18
    stress_mask = vix_series >= 25
    normal_mask = ~(calm_mask | stress_mask | transition_mask)

    regime_counts = {
        "calm": int(calm_mask.sum()),
        "normal": int(normal_mask.sum()),
        "stress": int(stress_mask.sum()),
        "transition": int(transition_mask.sum()),
    }
    RESULTS["regime_counts_oos"] = regime_counts
    log(f"Regime counts OOS: {regime_counts}")

    dm_by_regime = {}
    for regime_name, mask in [("calm", calm_mask), ("stress", stress_mask), ("transition", transition_mask), ("normal", normal_mask)]:
        n_reg = int(mask.sum())
        if n_reg < 10:
            dm_by_regime[regime_name] = {"n": n_reg, "note": "insufficient n for DM"}
            continue
        dm_by_regime[regime_name] = {"n": n_reg}
        base_sub = base_loss[mask].values
        for m in ["M3_AR1_EPU", "M4_AR1_FinStress", "M5_AR1_All"]:
            m_sub = oos_qlike_losses[m].reindex(common_idx)[mask].values
            t, p = dm_hln(base_sub, m_sub)
            challenger_beats = (not np.isnan(t)) and (t > 2.0)
            baseline_beats = (not np.isnan(t)) and (t < -2.0)
            dm_by_regime[regime_name][f"{baseline}_vs_{m}"] = {
                "t_stat": float(t) if not np.isnan(t) else None,
                "p_value": float(p) if not np.isnan(p) else None,
                "interpretation": (
                    f"{m} beats baseline" if challenger_beats
                    else (f"baseline beats {m}" if baseline_beats else "indistinguishable")
                ),
                "challenger_wins_harvey": bool(challenger_beats),
                "baseline_wins_harvey": bool(baseline_beats),
            }
    RESULTS["dm_tests_by_regime"] = dm_by_regime

    # ---------- Sub-period stability ----------
    subperiod_dm = {}
    for year in [2023, 2024, 2025]:
        yr_mask = pd.Series([d.year == year for d in common_idx], index=common_idx)
        n_yr = int(yr_mask.sum())
        if n_yr < 10:
            subperiod_dm[str(year)] = {"n": n_yr, "note": "insufficient"}
            continue
        subperiod_dm[str(year)] = {"n": n_yr}
        base_sub = base_loss[yr_mask].values
        for m in ["M3_AR1_EPU", "M4_AR1_FinStress", "M5_AR1_All"]:
            m_sub = oos_qlike_losses[m].reindex(common_idx)[yr_mask].values
            t, p = dm_hln(base_sub, m_sub)
            challenger_beats = (not np.isnan(t)) and (t > 2.0)
            baseline_beats = (not np.isnan(t)) and (t < -2.0)
            subperiod_dm[str(year)][f"{baseline}_vs_{m}"] = {
                "t_stat": float(t) if not np.isnan(t) else None,
                "p_value": float(p) if not np.isnan(p) else None,
                "interpretation": (
                    f"{m} beats baseline" if challenger_beats
                    else (f"baseline beats {m}" if baseline_beats else "indistinguishable")
                ),
                "challenger_wins_harvey": bool(challenger_beats),
                "baseline_wins_harvey": bool(baseline_beats),
            }
    RESULTS["subperiod_dm"] = subperiod_dm

    # ---------- Keyword-level BH-adj p-values (H2 analog) ----------
    # Look at M5_AR1_All which has all alt-data regressors; BH on alt-data ones
    m5_pvals = is_results["M5_AR1_All"]["pvalues"]
    alt_regressors = [f"{c}_lag1" for c in alt_cols]
    pvals_for_alt = [m5_pvals.get(r, 1.0) for r in alt_regressors]
    bh_adj = benjamini_hochberg(pvals_for_alt)
    m5_coefs = is_results["M5_AR1_All"]["params"]
    kw_analysis = {}
    for i, r in enumerate(alt_regressors):
        kw_analysis[r] = {
            "coef": float(m5_coefs.get(r, 0.0)),
            "p_value_raw": float(pvals_for_alt[i]),
            "p_value_bh_adj": float(bh_adj[i]),
            "sign": "positive" if m5_coefs.get(r, 0.0) > 0 else "negative",
            "bh_sig_at_10": bool(bh_adj[i] < 0.10),
        }
    RESULTS["keyword_analysis_IS_M5"] = kw_analysis
    RESULTS["n_bh_sig_at_10"] = int(sum(bh_adj < 0.10))

    # ---------- Hypothesis summary ----------
    # H1-base: alt-data challenger SIGNIFICANTLY BEATS baseline (t > +2)
    h1_base_pass = any(
        v.get("challenger_wins_harvey", False)
        for k, v in dm_tests.items()
        if k != f"{baseline}_vs_M1_AR1"  # only alt-data challengers
    )
    # Also track: does baseline beat any challenger (indicates alt-data HURTS)?
    h1_base_baseline_wins = sum(
        v.get("baseline_wins_harvey", False)
        for k, v in dm_tests.items()
        if k != f"{baseline}_vs_M1_AR1"
    )

    # H1-regime: any alt-data model beats baseline in transition OR stress
    h1_regime_pass = False
    for regime in ["transition", "stress"]:
        r = dm_by_regime.get(regime, {})
        if not isinstance(r, dict) or r.get("n", 0) < 10:
            continue
        for k, v in r.items():
            if isinstance(v, dict) and v.get("challenger_wins_harvey", False):
                h1_regime_pass = True

    h2_pass = RESULTS["n_bh_sig_at_10"] >= 2
    # H3-stability: >=2/3 sub-years show challenger winning for any alt-data model
    stability_count = 0
    for yr, d in subperiod_dm.items():
        if not isinstance(d, dict) or d.get("n", 0) < 10:
            continue
        if any(isinstance(v, dict) and v.get("challenger_wins_harvey", False) for v in d.values()):
            stability_count += 1
    h3_pass = stability_count >= 2

    RESULTS["hypothesis_tests"] = {
        "H1_base_full_OOS_challenger_beats_baseline": bool(h1_base_pass),
        "H1_base_full_OOS_baseline_beats_challenger_count": int(h1_base_baseline_wins),
        "H1_regime_transition_or_stress_challenger_wins": bool(h1_regime_pass),
        "H2_BH_sig_at_10_ge_2": bool(h2_pass),
        "H3_sub_period_stability_ge_2of3": bool(h3_pass),
    }

    # QLIKE improvement
    base_oos_qlike = is_oos_table[baseline]["OOS_QLIKE"]
    best_alt = min(["M3_AR1_EPU", "M4_AR1_FinStress", "M5_AR1_All"], key=lambda m: is_oos_table[m]["OOS_QLIKE"])
    best_alt_qlike = is_oos_table[best_alt]["OOS_QLIKE"]
    qlike_improv = (base_oos_qlike - best_alt_qlike) / abs(base_oos_qlike) * 100
    RESULTS["best_alt_model"] = best_alt
    RESULTS["qlike_improvement_pct"] = float(qlike_improv)
    RESULTS["qlike_improvement_5pct_pass"] = bool(qlike_improv > 5.0)

    # Overall verdict: require ALL THREE gates (DM + QLIKE + stability) — per K1100g_d1 lesson
    all_three_pass = h1_base_pass and RESULTS["qlike_improvement_5pct_pass"] and h3_pass
    RESULTS["triple_gate_pass"] = bool(all_three_pass)
    # Note active negative evidence: if baseline beats multiple challengers → alt-data actively HURTS
    active_harm = h1_base_baseline_wins >= 2
    RESULTS["active_harm_alt_data_worse_than_VIX"] = bool(active_harm)
    if all_three_pass:
        verdict = "POSITIVE (triple-gate passed)"
    elif h1_regime_pass and not h1_base_pass:
        verdict = "PARTIAL (only regime-transition/stress)"
    elif active_harm:
        verdict = "NULL (alt-data actively worsens OOS vs VIX baseline)"
    else:
        verdict = "NULL (no significant improvement)"
    RESULTS["overall_verdict"] = verdict

    RESULTS["finished_utc"] = datetime.utcnow().isoformat() + "Z"
    with open(OUT_DIR / "k1116_results.json", "w") as f:
        json.dump(RESULTS, f, indent=2, default=str)
    log(f"Saved -> {OUT_DIR / 'k1116_results.json'}")

    # Summary
    print("\n" + "=" * 80)
    print("K1116 SUMMARY — Alternative Data (EPU + NFCI + STLFSI) for SPY Vol Prediction")
    print("=" * 80)
    print(f"Panel: {RESULTS['n_full']} weeks ({df.index.min().date()} to {df.index.max().date()})")
    print(f"IS n={RESULTS['n_is']}, OOS n={RESULTS['n_oos']}, Common OOS DM n={len(common_idx)}")
    print(f"Regime OOS: {regime_counts}")
    print(f"\nIS vs OOS QLIKE:")
    print(f"  {'Model':<22} {'IS R²':>8} {'IS QLIKE':>12} {'OOS QLIKE':>12} {'OOS RMSE':>12}")
    for name, v in is_oos_table.items():
        print(f"  {name:<22} {v['IS_R2']:>8.4f} {v['IS_QLIKE']:>12.4f} {v['OOS_QLIKE']:>12.4f} {v['OOS_RMSE']:>12.6f}")

    print(f"\nFull OOS DM tests (vs {baseline}):")
    print(f"  (positive t = challenger beats baseline; negative t = baseline beats challenger)")
    for k, v in dm_tests.items():
        t = v["t_stat"]
        if t is None:
            print(f"  {k}: n/a")
        else:
            tag = "*CHALLENGER WINS*" if v["challenger_wins_harvey"] else ("[baseline wins]" if v["baseline_wins_harvey"] else "ns")
            print(f"  {k}: t={t:+.3f} p={v['p_value']:.4f} {tag}")

    print(f"\nRegime-conditional DM (main new analysis):")
    for regime, d in dm_by_regime.items():
        if not isinstance(d, dict) or d.get("n", 0) < 10:
            print(f"  {regime}: n={d.get('n', 0)} (skip)")
            continue
        print(f"  [{regime}] n={d['n']}")
        for k, v in d.items():
            if isinstance(v, dict) and "t_stat" in v and v["t_stat"] is not None:
                tag = "*CHALLENGER WINS*" if v["challenger_wins_harvey"] else ("[baseline wins]" if v["baseline_wins_harvey"] else "ns")
                print(f"    {k}: t={v['t_stat']:+.3f} {tag}")

    print(f"\nBH-adj IS p-values (M5 alt-data regressors):")
    for r, v in kw_analysis.items():
        sig = "*" if v["bh_sig_at_10"] else " "
        print(f"  {sig} {r:<20} coef={v['coef']:+.6f}  raw p={v['p_value_raw']:.4f}  BH p={v['p_value_bh_adj']:.4f}  ({v['sign']})")

    print(f"\nHypothesis tests:")
    for h, p in RESULTS["hypothesis_tests"].items():
        print(f"  {h}: {'PASS' if p else 'fail'}")

    print(f"\nBest alt-data model (OOS QLIKE): {best_alt}")
    print(f"QLIKE improvement vs {baseline}: {qlike_improv:+.2f}% (threshold 5%)")
    print(f"\nOVERALL VERDICT: {RESULTS['overall_verdict']}")


if __name__ == "__main__":
    main()
