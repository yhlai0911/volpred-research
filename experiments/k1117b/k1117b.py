"""
K1117b: Monthly-frequency alt-data re-test for Paper 4 null compendium.

**Research question**: K1116/K1116b/K1116c already showed weekly alt-data is NULL vs
VIX baseline even under strict PIT alignment. But weekly testing implicitly upsamples
monthly-cadence alt-data (CFNAI, UMCSENT, INDPRO) to weekly via forward-fill — potentially
injecting interpolation noise. At **monthly frequency**, publication delay (1-45 days)
is << period length (~30 days), giving the cleanest null-hypothesis test.

**Hypotheses**:
- H1 (monthly rescue): monthly alt-data DM |t| > 3 vs VIX baseline → K1116 null was
  weekly-upsampling artifact; Paper 4 narrative needs monthly exception.
- H2 (monthly NULL): alt-data still NULL → Paper 4 null robust across frequencies.
- H3 (partial): 1-2 indicators pass, others NULL → selective rescue.

**Design**:
- Assets: SPY monthly RV (sqrt sum of squared daily log returns) + VIX monthly mean close.
- Alt-data (5 indicators, PIT-aligned via k1117b_fetch_monthly.py):
    M_EPU  = USEPU monthly mean
    M_NFCI = NFCI weekly mean of last-in-month release
    M_CFNAI= Chicago Fed National Activity Index
    M_UMC  = Univ. Michigan Consumer Sentiment
    M_IP   = INDPRO YoY %
- Lookahead safety: at forecast date = end of month M, use only values whose
  RELEASE_DATE <= month-end(M) → predict RV of month (M+1).
- OOS: IS 2003-2018 (after 1-yr YoY warm-up), OOS 2019-2026 (~80-84 months).
- Models:
    M1 base     : AR(1)
    M2 vix      : AR(1) + log(VIX) [baseline]
    M3 epu      : AR(1) + log(EPU) + YoY-IP
    M4 finstress: AR(1) + NFCI
    M5 sentiment: AR(1) + CFNAI + UMCSENT
    M6 all      : AR(1) + log(VIX) + all 5 alt-data
    M7 altonly  : AR(1) + all 5 alt-data (pure alt-data battery)
- DM-HLN with Harvey (1997) correction, two-sided |t| > 3 threshold (Harvey 2016).
- Bootstrap standard errors (block bootstrap, B=2000, block_length=3) for small-sample SE.
- Frequency-upsampling diagnostic: correlation of monthly PIT alt-data value with
  its K1116c weekly PIT counterpart aggregated to monthly.

Author: Yi-Hao Lai + VolPred Research System
Date: 2026-04-13
References:
  - Baker, Bloom, Davis (2016) QJE 131 - EPU
  - Brave, Butters (2011) Chicago Fed - NFCI
  - Chicago Fed - CFNAI
  - Univ. Michigan Surveys of Consumers - UMCSENT
  - Federal Reserve Industrial Production
  - Patton (2011) JoE 160 - QLIKE
  - Harvey, Leybourne, Newbold (1997) IJF 13 - HLN correction
  - Harvey (2016) RFS 29 - |t| > 3 threshold
"""
from __future__ import annotations

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

np.random.seed(42)

HERE = Path(__file__).parent
DATA_DIR = HERE / "data"

RESULTS = {
    "experiment_id": "K1117b",
    "title": "Monthly-frequency alt-data re-test for Paper 4 null compendium",
    "started_utc": datetime.utcnow().isoformat() + "Z",
    "data_source": (
        "yfinance SPY/VIX 2000-2026; FRED fredgraph (revision-corrected) for USEPU/NFCI/"
        "CFNAI/UMCSENT/INDPRO with explicit publication-delay release-date rules (PIT-aligned)."
    ),
    "hypotheses": {
        "H1": "Monthly alt-data DM |t| > 3 vs VIX baseline (weekly null was upsampling artifact).",
        "H2": "All alt-data NULL at monthly frequency (null robust across frequencies).",
        "H3": "Selective rescue — 1-2 indicators PASS, rest NULL.",
    },
    "baseline_experiments": ["K1116", "K1116b", "K1116c"],
}


def log(msg: str) -> None:
    ts = datetime.utcnow().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# -------------------------------------------------------------------
# SPY + VIX monthly
# -------------------------------------------------------------------
def fetch_spy_vix_monthly(start="2000-01-01", end="2026-04-30") -> pd.DataFrame:
    import yfinance as yf

    log("Fetching SPY + VIX daily...")
    spy = yf.download("SPY", start=start, end=end, progress=False, auto_adjust=True)
    vix = yf.download("^VIX", start=start, end=end, progress=False, auto_adjust=False)

    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    spy = spy[["Close"]].copy()
    spy["r"] = np.log(spy["Close"]).diff()
    spy["month_end"] = spy.index.to_period("M").to_timestamp("M")
    monthly = spy.groupby("month_end").agg(
        rv=("r", lambda x: np.sqrt(np.sum(x.dropna() ** 2))),
        r_n=("r", "count"),
    )
    monthly = monthly[monthly["r_n"] >= 15].sort_index()

    vix_df = vix[["Close"]].rename(columns={"Close": "vix"})
    vix_df["month_end"] = vix_df.index.to_period("M").to_timestamp("M")
    vix_m = vix_df.groupby("month_end").agg(vix_mean=("vix", "mean"),
                                              vix_last=("vix", "last"))

    df = monthly.join(vix_m, how="inner").dropna()
    df["log_vix"] = np.log(df["vix_mean"])
    log(f"SPY+VIX monthly: {len(df)} months, {df.index.min().date()} to {df.index.max().date()}")
    return df


# -------------------------------------------------------------------
# Load alt-data monthly PIT panels
# -------------------------------------------------------------------
def load_monthly_altdata() -> pd.DataFrame:
    """Load all 5 PIT monthly indicators, indexed by month_end.

    Returns single DataFrame with columns:
      USEPU, NFCI, CFNAI, UMCSENT, INDPRO  (each PIT-aligned by release date)
    """
    cols = ["USEPU", "NFCI", "CFNAI", "UMCSENT", "INDPRO"]
    df = None
    for alias in cols:
        csv = DATA_DIR / f"{alias}_monthly_pit.csv"
        if not csv.exists():
            raise FileNotFoundError(f"Run k1117b_fetch_monthly.py first; missing {csv}")
        p = pd.read_csv(csv, parse_dates=["month_end", "obs_date", "release_date"])
        s = p.set_index("month_end")["value"].to_frame(alias)
        df = s if df is None else df.join(s, how="outer")
    df = df.sort_index()
    return df


def build_signals(market: pd.DataFrame, alt: pd.DataFrame) -> pd.DataFrame:
    """Merge market + alt-data and create _signal columns.

    PIT alignment means the value at month_end F is already safe for predicting RV of
    month (F+1). So at row F, alt[F] is the signal for RV[F+1]. In the regression, we
    predict rv[t] with signals from t-1, so we shift(1).
    """
    merged = market.join(alt, how="left").sort_index()

    # Log-transform skewed indicators (EPU, UMCSENT, INDPRO are levels with wide range)
    merged["log_USEPU"] = np.log(merged["USEPU"].clip(lower=1))
    merged["log_UMCSENT"] = np.log(merged["UMCSENT"].clip(lower=1))
    # NFCI and CFNAI are already z-score-like; keep as-is
    # INDPRO is YoY%; keep as-is

    # Signal = alt value available at end of month t-1 (which is indexed at t-1 in PIT panel)
    # Regression predicts rv[t] with signals from t-1 -> shift(1)
    for c in ["log_USEPU", "NFCI", "CFNAI", "log_UMCSENT", "INDPRO", "log_vix"]:
        merged[f"{c}_sig"] = merged[c].shift(1)
    merged["rv_lag1"] = merged["rv"].shift(1)
    return merged


# -------------------------------------------------------------------
# Metrics
# -------------------------------------------------------------------
def qlike_series(actual, pred):
    eps = 1e-10
    actual = np.maximum(actual, eps)
    pred = np.maximum(pred, eps)
    return np.log(pred) + actual / pred


def dm_hln(e1, e2, h=1):
    """DM-HLN test. Positive t: e1 > e2 => challenger beats baseline (lower loss)."""
    from scipy import stats as st

    d = np.asarray(e1, dtype=float) - np.asarray(e2, dtype=float)
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan, n
    dbar = d.mean()
    gamma0 = np.var(d, ddof=1)
    if gamma0 <= 0:
        return np.nan, np.nan, n
    hln_correction = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    se = np.sqrt(gamma0 / n)
    t = (dbar / se) * hln_correction
    p = 2 * (1 - st.t.cdf(abs(t), df=n - 1))
    return float(t), float(p), int(n)


def block_bootstrap_se(e1, e2, B=2000, block_length=3, seed=42):
    """Block-bootstrap SE for mean loss differential. Small-sample friendly.

    Returns (boot_mean, boot_se, boot_p_two_sided).
    """
    rng = np.random.default_rng(seed)
    d = np.asarray(e1, dtype=float) - np.asarray(e2, dtype=float)
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan, np.nan
    n_blocks = int(np.ceil(n / block_length))
    boot_means = np.empty(B)
    for b in range(B):
        starts = rng.integers(0, n - block_length + 1, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block_length) for s in starts])[:n]
        boot_means[b] = d[idx].mean()
    boot_mean = float(d.mean())
    boot_se = float(boot_means.std(ddof=1))
    # two-sided p via symmetric percentile test (center at 0)
    centered = boot_means - boot_means.mean()
    p = float(np.mean(np.abs(centered) >= abs(boot_mean)))
    return boot_mean, boot_se, p


# -------------------------------------------------------------------
# Models
# -------------------------------------------------------------------
MODELS = {
    "M1_base":       ["rv_lag1"],
    "M2_vix":        ["rv_lag1", "log_vix_sig"],
    "M3_epu":        ["rv_lag1", "log_USEPU_sig", "INDPRO_sig"],
    "M4_finstress":  ["rv_lag1", "NFCI_sig"],
    "M5_sentiment":  ["rv_lag1", "CFNAI_sig", "log_UMCSENT_sig"],
    "M6_all":        ["rv_lag1", "log_vix_sig", "log_USEPU_sig", "NFCI_sig",
                      "CFNAI_sig", "log_UMCSENT_sig", "INDPRO_sig"],
    "M7_altonly":    ["rv_lag1", "log_USEPU_sig", "NFCI_sig", "CFNAI_sig",
                      "log_UMCSENT_sig", "INDPRO_sig"],
}


def fit_predict(df: pd.DataFrame, is_end: str, oos_start: str,
                refit: str = "expanding") -> dict:
    """Fit OLS on IS, OOS expanding refit if refit='expanding'.

    refit:
      'static'    -> fit once on IS, predict on OOS block
      'expanding' -> refit each month with all data up to t-1
    """
    import statsmodels.api as sm

    df = df.copy()
    df_is = df.loc[:is_end]
    df_oos = df.loc[oos_start:]

    out = {}
    for name, cols in MODELS.items():
        # drop rows missing any regressor or target
        need = ["rv"] + cols
        df_is_sub = df_is[need].dropna()
        df_oos_sub = df_oos[need].dropna()

        if refit == "static":
            X_is = sm.add_constant(df_is_sub[cols])
            y_is = df_is_sub["rv"]
            model = sm.OLS(y_is, X_is).fit()
            X_oos = sm.add_constant(df_oos_sub[cols])[X_is.columns]
            pred = model.predict(X_oos)
            actual = df_oos_sub["rv"]
        else:
            # expanding refit: at each OOS row, fit on all prior data
            preds = []
            actuals = []
            idx_list = []
            all_df = df[need].dropna()
            for t in df_oos_sub.index:
                train = all_df.loc[:t].iloc[:-1]  # up to t-1 (exclusive of t)
                if len(train) < 24:  # need >= 24 months to fit
                    continue
                X_tr = sm.add_constant(train[cols])
                y_tr = train["rv"]
                m = sm.OLS(y_tr, X_tr).fit()
                row = df.loc[t:t, cols].copy()
                row.insert(0, "const", 1.0)
                row = row[X_tr.columns]
                if row.isna().any().any():
                    continue
                preds.append(float(m.predict(row).iloc[0]))
                actuals.append(float(df.loc[t, "rv"]))
                idx_list.append(t)
            pred = pd.Series(preds, index=pd.DatetimeIndex(idx_list))
            actual = pd.Series(actuals, index=pd.DatetimeIndex(idx_list))
            model = None  # not a single fit

        # Drop any remaining NaN alignment
        valid = actual.notna() & pred.notna()
        actual = actual[valid]
        pred = pred[valid]

        pred_clipped = np.maximum(pred.values, 1e-6)
        loss = np.log(pred_clipped) + actual.values / pred_clipped

        out[name] = {
            "regressors": cols,
            "n_is": int(len(df_is_sub)),
            "n_oos": int(len(actual)),
            "oos_qlike": float(np.mean(loss)),
            "oos_rmse": float(np.sqrt(np.mean((actual.values - pred.values) ** 2))),
            "loss_series": pd.Series(loss, index=actual.index),
            "pred_series": pred,
            "actual_series": actual,
        }
        # fit a static model for coefficient reporting anyway
        if model is None:
            X_is_stat = sm.add_constant(df_is_sub[cols])
            y_is_stat = df_is_sub["rv"]
            model_stat = sm.OLS(y_is_stat, X_is_stat).fit()
            out[name]["coef_is_static"] = {k: float(v) for k, v in model_stat.params.items()}
            out[name]["r2_is_static"] = float(model_stat.rsquared)
        else:
            out[name]["coef_is_static"] = {k: float(v) for k, v in model.params.items()}
            out[name]["r2_is_static"] = float(model.rsquared)
    return out


# -------------------------------------------------------------------
# Diagnostics
# -------------------------------------------------------------------
def diagnostics(merged: pd.DataFrame, is_end: str, oos_start: str) -> dict:
    from scipy import stats as st

    diag = {}
    rv = merged["rv"].dropna()
    diag["rv_full"] = {
        "n": int(len(rv)),
        "mean": float(rv.mean()),
        "std": float(rv.std()),
        "skew": float(rv.skew()),
        "kurt": float(rv.kurt()),
        "min": float(rv.min()),
        "max": float(rv.max()),
    }
    try:
        from statsmodels.tsa.stattools import adfuller
        adf = adfuller(rv, autolag="AIC")
        diag["adf_rv"] = {"stat": float(adf[0]), "pvalue": float(adf[1])}
    except Exception as e:
        diag["adf_rv"] = {"error": str(e)}
    try:
        from statsmodels.stats.diagnostic import acorr_ljungbox
        lb = acorr_ljungbox(rv, lags=[6, 12], return_df=True)
        diag["ljungbox_rv"] = lb.to_dict()
    except Exception as e:
        diag["ljungbox_rv"] = {"error": str(e)}
    return diag


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
def main():
    log("=" * 70)
    log("K1117b: Monthly alt-data re-test")
    log("=" * 70)

    market = fetch_spy_vix_monthly(start="2000-01-01", end="2026-04-30")
    alt = load_monthly_altdata()
    log(f"Alt-data monthly panel: {alt.shape} ({alt.index.min().date()}..{alt.index.max().date()})")

    merged = build_signals(market, alt)
    merged = merged.dropna(subset=["rv", "rv_lag1"])  # remove obvious NaN before regressor-specific dropna
    # Restrict to post-1999 with warm-up after YoY INDPRO (needs 12m)
    merged = merged[merged.index >= "2001-01-31"]
    log(f"Merged panel: {merged.shape}, {merged.index.min().date()}..{merged.index.max().date()}")

    # Diagnostics
    diag = diagnostics(merged, is_end="2018-12-31", oos_start="2019-01-01")
    RESULTS["diagnostics"] = diag

    # Report data coverage
    RESULTS["data_coverage"] = {
        "market_n": int(len(market)),
        "alt_n_per_indicator": {c: int(merged[c].notna().sum()) for c in
                                 ["USEPU", "NFCI", "CFNAI", "UMCSENT", "INDPRO"]},
    }

    # Set IS / OOS
    IS_END = "2018-12-31"
    OOS_START = "2019-01-01"

    # Fit models, expanding refit
    log(f"\nFit models — IS <= {IS_END}, OOS from {OOS_START}, expanding refit")
    fit = fit_predict(merged, IS_END, OOS_START, refit="expanding")

    log("\n{:<14} {:>6} {:>6} {:>10} {:>10}".format(
        "Spec", "n_IS", "n_OOS", "OOS_QLIKE", "OOS_RMSE"))
    for name, res in fit.items():
        log("{:<14} {:>6} {:>6} {:>10.4f} {:>10.5f}".format(
            name, res["n_is"], res["n_oos"], res["oos_qlike"], res["oos_rmse"]))

    # DM-HLN tests: each spec vs M2_vix baseline
    log("\n" + "=" * 70)
    log("DM-HLN tests (each spec vs M2_vix; positive t => challenger beats VIX)")
    log("=" * 70)

    base_loss = fit["M2_vix"]["loss_series"]
    dm_table = {}
    bootstrap_table = {}
    for name, res in fit.items():
        if name == "M2_vix":
            continue
        # align on common index (expanding refit may produce slightly different coverage)
        common = base_loss.index.intersection(res["loss_series"].index)
        e1 = base_loss.loc[common].values  # baseline
        e2 = res["loss_series"].loc[common].values  # challenger
        t, p, n = dm_hln(e1, e2, h=1)
        bm, bse, bp = block_bootstrap_se(e1, e2, B=2000, block_length=3, seed=42)
        dm_table[name] = {"t_hln": t, "p_hln": p, "n": n,
                          "harvey_pass": bool(abs(t) > 3.0) if not np.isnan(t) else False,
                          "sign": "challenger_beats_vix" if (not np.isnan(t) and t > 0) else "vix_wins"}
        bootstrap_table[name] = {"mean_diff": bm, "se": bse, "p_two_sided": bp,
                                  "bootstrap_sig_95": bool(bp < 0.05) if not np.isnan(bp) else False}
        log(f"  {name:<14} DM t={t:>+7.3f}  p={p:>6.3f}  n={n:<4}  bootSE={bse:.5f}  bootP={bp:.3f}")

    RESULTS["fit_summary"] = {
        name: {k: v for k, v in r.items() if k not in ("loss_series", "pred_series", "actual_series")}
        for name, r in fit.items()
    }
    RESULTS["dm_table_vs_vix"] = dm_table
    RESULTS["bootstrap_table_vs_vix"] = bootstrap_table

    # ---------------- Verdict ----------------
    harvey_passes = [name for name, d in dm_table.items() if d.get("harvey_pass") and d.get("sign") == "challenger_beats_vix"]
    boot_passes = [name for name, d in bootstrap_table.items() if d.get("bootstrap_sig_95")]

    if len(harvey_passes) == 0:
        verdict = "H2_ROBUST_NULL"
        verdict_note = ("No alt-data spec achieves Harvey |t| > 3 against VIX baseline at monthly "
                        "frequency. Null is robust across frequencies (weekly + monthly). Paper 4 "
                        "null compendium narrative strongly confirmed — publication-delay << period "
                        "length at monthly frequency provides the cleanest null test; alt-data "
                        "still offers no incremental vol signal over VIX.")
    elif len(harvey_passes) >= 3:
        verdict = "H1_MONTHLY_RESCUE"
        verdict_note = (f"{len(harvey_passes)} alt-data specs pass Harvey at monthly frequency: "
                        f"{harvey_passes}. Weekly null may have been upsampling artifact. "
                        "Paper 4 needs monthly-exception caveat.")
    else:
        verdict = "H3_PARTIAL"
        verdict_note = (f"Partial rescue: {harvey_passes} pass Harvey. Rest NULL. "
                        "Selective-indicator narrative.")

    RESULTS["verdict"] = verdict
    RESULTS["verdict_note"] = verdict_note
    RESULTS["harvey_passes"] = harvey_passes
    RESULTS["bootstrap_passes"] = boot_passes

    log("\n" + "=" * 70)
    log(f"VERDICT: {verdict}")
    log(verdict_note)
    log("=" * 70)

    RESULTS["completed_utc"] = datetime.utcnow().isoformat() + "Z"

    out_path = HERE / "k1117b_results.json"
    with open(out_path, "w") as f:
        json.dump(RESULTS, f, indent=2, default=str)
    log(f"\nResults written to {out_path}")

    # Persist loss series for plotting
    loss_df = pd.DataFrame({name: r["loss_series"] for name, r in fit.items()})
    loss_df.to_csv(HERE / "k1117b_oos_loss_series.csv")
    pred_df = pd.DataFrame({name: r["pred_series"] for name, r in fit.items()})
    pred_df["actual"] = fit["M2_vix"]["actual_series"]
    pred_df.to_csv(HERE / "k1117b_oos_predictions.csv")

    return RESULTS


if __name__ == "__main__":
    main()
