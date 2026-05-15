#!/usr/bin/env python3
"""K1306 — SEC 10-K LM-sentiment pilot: do filing-tone deltas predict firm-RV?

Pipeline:
    1) Load filings_index.json from k1306_fetch_edgar.py + raw section text.
    2) Score each filing with LM dictionary (negative / positive / uncertainty / litigious shares).
    3) Compute year-over-year tone-delta per firm.
    4) Fetch daily prices (yfinance) for each ticker + VIX.
    5) Build monthly RV (sum of squared daily log returns) per ticker.
    6) Align: tone_delta_lag (known at filing_date + 1bd embargo) predicts
       average monthly RV over t+1..t+12 forward months.
    7) Per-firm OLS:
         M1 (baseline) : RV_fwd ~ VIX_mean_lag
         M2 (challenger): RV_fwd ~ VIX_mean_lag + tone_delta_neg_lag
    8) Per-firm t-stat for beta_tone; Stouffer combined Z across firms.
    9) OOS QLIKE delta via leave-one-out (small N) + bootstrap CI seed=42, B=500.

Lookahead discipline (NB-critical):
    - tone_delta from filing N is dated at filing_date[N] + 1 business day  (.shift(1) equivalent)
    - VIX_mean is the mean over the 21 trading days BEFORE the filing+1 day
      (i.e. signal known strictly before the prediction window)
    - RV_fwd target is the **average monthly RV over the 12 months AFTER** the embargo date
    - Baseline (M1) and Challenger (M2) use IDENTICAL alignment / lag

Seed: 42 for all bootstrap resampling.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from pandas.tseries.offsets import MonthEnd

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
RAW_DIR = DATA_DIR / "raw"
RESULTS_PATH = HERE / "k1306_results.json"

SEED = 42
N_BOOT = 500
EMBARGO_BD = 1   # 1 business day after filing_date before signal is usable

# ---------------------------------------------------------------------------
# LM dictionary scoring
# ---------------------------------------------------------------------------

def load_lm_dict() -> dict:
    df = pd.read_csv(DATA_DIR / "dict" / "LM_MasterDictionary.csv")
    df["Word"] = df["Word"].str.upper()
    # Build sets of words with non-zero flag in each category
    cats = ["Negative", "Positive", "Uncertainty", "Litigious"]
    return {c: set(df.loc[df[c] > 0, "Word"].tolist()) for c in cats}


_TOKEN_RE = re.compile(r"[A-Za-z]{2,}")

def tokenize(text: str) -> list[str]:
    return [t.upper() for t in _TOKEN_RE.findall(text)]


def score_text(text: str, lm: dict) -> dict:
    toks = tokenize(text)
    n = max(len(toks), 1)
    out = {"n_tokens": len(toks)}
    for cat, vocab in lm.items():
        c = sum(1 for t in toks if t in vocab)
        out[f"{cat.lower()}_count"] = c
        out[f"{cat.lower()}_share"] = c / n
    return out


# ---------------------------------------------------------------------------
# Build filing-level tone table
# ---------------------------------------------------------------------------

def build_tone_table() -> pd.DataFrame:
    idx = json.loads((DATA_DIR / "filings_index.json").read_text())
    lm = load_lm_dict()
    rows = []
    for f in idx["filings"]:
        local_path = HERE.parent.parent / f["local_path"]
        rec = json.loads(local_path.read_text())
        combined = (rec.get("risk_factors", "") or "") + " " + (rec.get("mdna", "") or "")
        s = score_text(combined, lm)
        rows.append({
            "ticker": f["ticker"],
            "filing_date": pd.to_datetime(f["filing_date"]),
            "risk_chars": f["risk_chars"],
            "mdna_chars": f["mdna_chars"],
            **s,
        })
    df = pd.DataFrame(rows).sort_values(["ticker", "filing_date"]).reset_index(drop=True)
    # year-over-year tone change in negative share
    df["tone_delta_neg"] = df.groupby("ticker")["negative_share"].diff()
    df["tone_delta_unc"] = df.groupby("ticker")["uncertainty_share"].diff()
    return df


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

def load_prices(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    import yfinance as yf
    # auto_adjust=True applies splits + dividends; we want pure price returns,
    # so use auto_adjust=False and use 'Adj Close' (total-return adjusted).
    df = yf.download(
        tickers + ["^VIX"],
        start=start,
        end=end,
        auto_adjust=False,
        progress=False,
        group_by="ticker",
    )
    # yfinance returns multi-index columns when given a list
    out = {}
    for t in tickers + ["^VIX"]:
        try:
            sub = df[t]["Adj Close"] if "Adj Close" in df[t].columns else df[t]["Close"]
        except (KeyError, AttributeError):
            sub = df["Adj Close"][t] if "Adj Close" in df.columns.get_level_values(0) else df["Close"][t]
        out[t] = sub
    return pd.DataFrame(out).sort_index()


def compute_monthly_rv(prices: pd.Series) -> pd.Series:
    """Monthly realized variance from daily log returns (sum of r^2 in month)."""
    r = np.log(prices).diff()
    monthly_rv = r.pow(2).resample("ME").sum()
    return monthly_rv


# ---------------------------------------------------------------------------
# Alignment with lookahead discipline
# ---------------------------------------------------------------------------

def build_panel(tone: pd.DataFrame, monthly_rv: pd.DataFrame, daily_vix: pd.Series) -> pd.DataFrame:
    """For each filing-event, attach the prediction target and predictors.

    Predictors (known at embargo_date = filing_date + 1bd):
        - VIX_mean_lag: mean of daily VIX in the 21 trading days BEFORE embargo_date
        - tone_delta_neg: known at filing (from LM scoring), shifted via embargo
    Target:
        - rv_fwd_12m: mean of monthly RV over the 12 months STRICTLY AFTER embargo_date
    """
    bd = pd.tseries.offsets.BusinessDay(EMBARGO_BD)
    rows = []
    for _, ev in tone.iterrows():
        ticker = ev["ticker"]
        fdate = ev["filing_date"]
        embargo = fdate + bd
        # VIX_mean over 21 trading days BEFORE embargo (strict <, so .shift(1) equivalent)
        vix_window = daily_vix[daily_vix.index < embargo].iloc[-21:]
        if len(vix_window) < 15:
            continue
        vix_mean_lag = float(vix_window.mean())

        # Target: monthly RV after embargo, take next 12 month-ends
        # Fix (K1306v2 revised): push lower bound to the month-end of the embargo month
        # using MonthEnd(0), then require index > that month-end so we start strictly from
        # the NEXT complete calendar month. Without this, if embargo is mid-month (e.g.
        # 2023-11-03), the monthly RV at 2023-11-30 satisfies (index > embargo) even though
        # that RV bucket covers the full month of November (including pre-embargo days).
        # MonthEnd(0) snaps embargo to its own month-end; the strict > condition then
        # excludes that partial month and starts from 2023-12-31 onwards.
        # Upper bound: embargo_month_end + 12 months caps the window to 12 forward months.
        rv_series = monthly_rv_for_ticker(monthly_rv, ticker)
        if rv_series is None or rv_series.empty:
            continue
        embargo_month_end = embargo + MonthEnd(0)
        fwd = rv_series[
            (rv_series.index > embargo_month_end) &
            (rv_series.index <= embargo_month_end + MonthEnd(12))
        ].iloc[:12]
        if len(fwd) < 6:  # need at least 6 months forward
            continue
        rv_fwd_12m = float(fwd.mean())

        rows.append({
            "ticker": ticker,
            "filing_date": fdate,
            "embargo_date": embargo,
            "vix_mean_lag": vix_mean_lag,
            "negative_share": ev["negative_share"],
            "uncertainty_share": ev["uncertainty_share"],
            "tone_delta_neg": ev["tone_delta_neg"],
            "tone_delta_unc": ev["tone_delta_unc"],
            "rv_fwd_12m": rv_fwd_12m,
            "n_fwd_months": len(fwd),
        })
    return pd.DataFrame(rows)


def monthly_rv_for_ticker(monthly_rv: pd.DataFrame, ticker: str) -> pd.Series | None:
    if ticker not in monthly_rv.columns:
        return None
    return monthly_rv[ticker].dropna()


# ---------------------------------------------------------------------------
# Per-firm regressions
# ---------------------------------------------------------------------------

def per_firm_ols(panel: pd.DataFrame) -> dict:
    """For each firm with >=3 obs, fit baseline and challenger and return coeffs / t-stats.

    Baseline (M1):  rv_fwd ~ const + vix_mean_lag
    Challenger (M2): rv_fwd ~ const + vix_mean_lag + tone_delta_neg

    DM-style comparison is degenerate at firm-level with N<5 obs (each firm has
    at most 5 filings), so we report:
        - in-sample R^2 / adj-R^2
        - LOO out-of-sample QLIKE for both
        - per-firm beta_tone, t-stat (heteroscedasticity-robust HC1)
    """
    import statsmodels.api as sm

    out_per_firm = {}
    pooled_rows = []
    for ticker, g in panel.groupby("ticker"):
        g = g.dropna(subset=["tone_delta_neg", "vix_mean_lag", "rv_fwd_12m"])
        n_obs = len(g)
        # Fix (K1306v2): M2 has 3 params (const, vix, tone); HC1 needs df>=2 → N>=5.
        # N=3 or N=4 gives df=0 or df=1, making HC1 t-stats numerically invalid.
        if n_obs < 5:
            out_per_firm[ticker] = {"n_obs": int(n_obs), "skipped": "n<5 insufficient df for HC1"}
            continue
        y = g["rv_fwd_12m"].values
        X1 = sm.add_constant(g[["vix_mean_lag"]].values)
        X2 = sm.add_constant(g[["vix_mean_lag", "tone_delta_neg"]].values)
        m1 = sm.OLS(y, X1).fit(cov_type="HC1")
        m2 = sm.OLS(y, X2).fit(cov_type="HC1")

        # LOO out-of-sample QLIKE
        qlike1, qlike2 = loo_qlike(y, X1), loo_qlike(y, X2)
        out_per_firm[ticker] = {
            "n_obs": int(n_obs),
            "m1_r2": float(m1.rsquared),
            "m2_r2": float(m2.rsquared),
            "m1_adj_r2": float(m1.rsquared_adj),
            "m2_adj_r2": float(m2.rsquared_adj),
            "beta_vix": float(m2.params[1]),
            "beta_tone": float(m2.params[2]),
            "t_tone": float(m2.tvalues[2]),
            "p_tone": float(m2.pvalues[2]),
            "qlike_m1": float(qlike1),
            "qlike_m2": float(qlike2),
            "qlike_improvement_pct": float(100 * (qlike1 - qlike2) / qlike1) if qlike1 != 0 else None,
        }

        for _, row in g.iterrows():
            pooled_rows.append({**row.to_dict(), "ticker": ticker})

    # Pooled (fixed-effect via ticker dummies) for combined inference
    pooled = pd.DataFrame(pooled_rows)
    pooled_result = None
    if len(pooled) >= 6:
        import statsmodels.api as sm
        pooled = pooled.dropna(subset=["tone_delta_neg", "vix_mean_lag", "rv_fwd_12m"])
        y = pooled["rv_fwd_12m"].values
        dummies = pd.get_dummies(pooled["ticker"], drop_first=True).astype(float)
        Xp1 = sm.add_constant(pd.concat([pooled[["vix_mean_lag"]], dummies], axis=1).values)
        Xp2 = sm.add_constant(pd.concat([pooled[["vix_mean_lag", "tone_delta_neg"]], dummies], axis=1).values)
        # Fix (K1306v2): check df_resid = N - k >= 2 before fitting HC1.
        # Xp2 has n_firms+2 params (const + vix + tone + (n_firms-1) dummies).
        # HC1 t-stats are invalid when df_resid < 2.
        n_pooled = len(y)
        k_p2 = Xp2.shape[1]
        if n_pooled - k_p2 < 2:
            pooled_result = {
                "n_obs": int(n_pooled),
                "skipped": f"df_resid={n_pooled - k_p2} < 2; pooled HC1 invalid (n_firms too large relative to N)",
            }
        else:
            m1p = sm.OLS(y, Xp1).fit(cov_type="HC1")
            m2p = sm.OLS(y, Xp2).fit(cov_type="HC1")
            # tone_delta_neg coefficient is at index 2 (const=0, vix=1, tone=2, then dummies)
            pooled_result = {
                "n_obs": int(n_pooled),
                "m1_r2": float(m1p.rsquared),
                "m2_r2": float(m2p.rsquared),
                "beta_tone": float(m2p.params[2]),
                "t_tone": float(m2p.tvalues[2]),
                "p_tone": float(m2p.pvalues[2]),
            }

    # Stouffer combined Z across firms with valid t-stats
    z_scores = []
    for ticker, info in out_per_firm.items():
        if "t_tone" in info:
            z_scores.append(info["t_tone"])
    stouffer = None
    if len(z_scores) >= 2:
        from scipy import stats as ss
        z = np.array(z_scores)
        # Treat t as approximate z (small sample caveat — flag in report)
        combined_z = z.sum() / np.sqrt(len(z))
        stouffer = {
            "n_firms": int(len(z)),
            "combined_z": float(combined_z),
            "p_value_two_sided": float(2 * (1 - ss.norm.cdf(abs(combined_z)))),
            "caveat": "t-stats treated as z; valid only for N>=30 per firm — small-sample pilot",
        }

    return {"per_firm": out_per_firm, "pooled": pooled_result, "stouffer": stouffer}


def loo_qlike(y: np.ndarray, X: np.ndarray) -> float:
    """Leave-one-out QLIKE for a tiny sample. Uses ridge with tiny lambda to avoid degenerate solves."""
    import statsmodels.api as sm
    n = len(y)
    preds = np.zeros(n)
    for i in range(n):
        mask = np.ones(n, dtype=bool); mask[i] = False
        try:
            beta = np.linalg.lstsq(X[mask], y[mask], rcond=None)[0]
            preds[i] = X[i] @ beta
        except Exception:
            preds[i] = y[mask].mean()
    # Clip to small positive to avoid log of nonpositive
    preds = np.clip(preds, 1e-8, None)
    yc = np.clip(y, 1e-8, None)
    # QLIKE = mean( y/pred - log(y/pred) - 1 )
    r = yc / preds
    return float(np.mean(r - np.log(r) - 1.0))


# ---------------------------------------------------------------------------
# Bootstrap CI for pooled beta_tone
# ---------------------------------------------------------------------------

def bootstrap_pooled_beta_tone(panel: pd.DataFrame, n_boot: int = N_BOOT, seed: int = SEED) -> dict | None:
    import statsmodels.api as sm
    panel = panel.dropna(subset=["tone_delta_neg", "vix_mean_lag", "rv_fwd_12m"]).reset_index(drop=True)
    if len(panel) < 6:
        return None
    rng = np.random.default_rng(seed)
    betas = []
    n = len(panel)
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        sample = panel.iloc[idx]
        y = sample["rv_fwd_12m"].values
        dummies = pd.get_dummies(sample["ticker"], drop_first=True).astype(float).reset_index(drop=True)
        X = pd.concat([sample[["vix_mean_lag", "tone_delta_neg"]].reset_index(drop=True), dummies], axis=1)
        X = sm.add_constant(X).values
        try:
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            betas.append(beta[2])  # tone_delta_neg coefficient
        except Exception:
            continue
    if not betas:
        return None
    betas = np.array(betas)
    return {
        "n_boot": int(len(betas)),
        "mean": float(betas.mean()),
        "ci_2_5": float(np.quantile(betas, 0.025)),
        "ci_97_5": float(np.quantile(betas, 0.975)),
        "frac_positive": float((betas > 0).mean()),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"K1306 — SEC 10-K LM sentiment pilot (seed={SEED}, B={N_BOOT})")
    tone = build_tone_table()
    print(f"Tone table: {len(tone)} filings across {tone['ticker'].nunique()} firms")
    if tone.empty:
        raise SystemExit("No tone data — aborting")

    tickers = sorted(tone["ticker"].unique().tolist())
    start_d = (tone["filing_date"].min() - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
    end_d = (tone["filing_date"].max() + pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    prices = load_prices(tickers, start=start_d, end=end_d)
    print(f"Prices: {len(prices)} rows for {prices.columns.tolist()}")

    daily_vix = prices["^VIX"].dropna()
    # monthly RV per ticker
    monthly_rv = pd.DataFrame({t: compute_monthly_rv(prices[t].dropna()) for t in tickers})
    print(f"Monthly RV: {monthly_rv.shape}")

    panel = build_panel(tone, monthly_rv, daily_vix)
    print(f"Aligned panel: {len(panel)} firm-filing observations")
    print(panel[["ticker", "filing_date", "vix_mean_lag", "tone_delta_neg", "rv_fwd_12m", "n_fwd_months"]].to_string(index=False))

    ols = per_firm_ols(panel)
    boot = bootstrap_pooled_beta_tone(panel)

    # PASS/NULL verdict per README success criterion
    pass_firms = []
    for t, info in ols["per_firm"].items():
        if "t_tone" not in info:
            continue
        if abs(info["t_tone"]) > 2.0 and (info.get("qlike_improvement_pct") or 0) > 5.0:
            pass_firms.append(t)
    verdict = "PASS" if len(pass_firms) >= 3 else ("CONDITIONAL_PASS" if len(pass_firms) >= 1 else "NULL")

    results = {
        "experiment_id": "K1306",
        "title": "SEC EDGAR 10-K LM-sentiment pilot",
        "verdict": verdict,
        "verdict_rule": "PASS if >=3 firms have |t_tone|>2 AND OOS QLIKE improvement >5%",
        "seed": SEED,
        "n_boot": N_BOOT,
        "n_filings": int(len(tone)),
        "n_firms": int(tone["ticker"].nunique()),
        "n_aligned_obs": int(len(panel)),
        "pass_firms": pass_firms,
        "tickers": tickers,
        "filing_years": sorted(tone["filing_date"].dt.year.unique().tolist()),
        "ols": ols,
        "bootstrap_pooled_beta_tone": boot,
        "panel_summary": {
            "vix_mean_lag": panel["vix_mean_lag"].describe().to_dict(),
            "tone_delta_neg": panel["tone_delta_neg"].describe().to_dict(),
            "rv_fwd_12m": panel["rv_fwd_12m"].describe().to_dict(),
        },
        "lookahead_check": {
            "embargo_business_days": EMBARGO_BD,
            "vix_mean_window": "21 trading days strictly BEFORE embargo_date",
            "target_window": "next 12 monthly RV strictly AFTER embargo_date",
            "baseline_lag_match": True,
            "challenger_lag_match": True,
        },
        "limitations": [
            "Pilot sample only: 5 firms x 5 years, recent EDGAR-API window",
            "META filings missing (CIK submissions API recent-window cutoff)",
            "GOOGL 2020-2022 missing (Alphabet CIK reorg / API window)",
            "MSFT 2023/2024 risk_factors extraction returned <50 chars (heuristic miss; MD&A still extracted)",
            "Per-firm N <=5: t-stats unreliable as z-stats; Stouffer caveated",
            "12-month forward RV window overlaps for adjacent filings — autocorrelation in residuals not corrected",
        ],
        "next_steps_if_PASS": [
            "K1307: full S&P-500 panel with proper FE + Driscoll-Kraay SE",
            "Replace heuristic section extraction with structured XBRL filings tags",
            "Add 8-K event windows for higher-frequency tone updates",
        ],
        "data_files": {
            "filings_index": "experiments/k1306/data/filings_index.json",
            "lm_dictionary": "experiments/k1306/data/dict/LM_MasterDictionary.csv",
            "raw_sections": "experiments/k1306/data/raw/",
        },
        "git_metadata": {
            "code": "experiments/k1306/k1306.py",
            "fetcher": "experiments/k1306/k1306_fetch_edgar.py",
            "readme": "experiments/k1306/README.md",
        },
    }
    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    print(f"\nVerdict: {verdict}  (pass_firms={pass_firms})")
    print(f"Results written to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
