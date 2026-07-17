"""
credit_stress_firm_level — Firm-level credit stress → high-leverage AI equity vol
=================================================================================

Research question (from owner Telegram msg877, 2026-07-16, "SpaceX 破發" 財經捕手)
-------------------------------------------------------------------------------
Does *issuer-specific* credit-market stress lead the realized volatility of
HIGH-LEVERAGE AI-infrastructure equities (ORCL / IBM / EQIX / DLR / CRM) MORE
than it leads the realized vol of CASH-RICH hyperscalers (MSFT / GOOGL / AAPL /
NVDA / META), *after controlling for VIX*?

This is the ONLY differentiation left versus the prior NULL aggregate work:
    * K872 : FRED HY OAS raw r=0.55 with fwd vol, but HY-VIX corr=0.77;
             delta-R2 after VIX control = 0.0003.  VIX sufficiency.
    * T14  : credit + yield curve add only +1.6% incremental R2 (econ trivial).
    * K1621: EM sovereign-credit vol proxies do NOT lead EM equity vol daily;
             contemporaneous common factor, not a forewarning indicator.
    * K1529: FOMC-window credit stress NULL with free ETF proxies —
             "firm-level or intraday credit-spread data required to reopen".
    * K1538: bond-fund run-pressure proxy weak, below gates.
Every aggregate credit signal is absorbed by VIX.  The article's real claim is
NOT aggregate — it is that LEVERED issuers' OWN credit stress drives their OWN
equity vol.  We test that as a leverage-GROUP differential.

Data limitation (disclosed honestly)
------------------------------------
* Single-name CDS needs Markit (paid) -> unavailable.
* FRED HY/IG OAS (BAMLH0A0HYM2 / BAMLC0A0CM) since the 2024 ICE license change
  only retain a ~3-year rolling window (verified 2026-07-18: both start
  2023-07-17, ~787 obs, NO bear market).  They CANNOT support the 2015-2026
  two-bear-market design, so they are a SHORT-SAMPLE SECONDARY robustness check
  only, flagged underpowered.
* PRIMARY credit signal = HYG-LQD ETF credit-stress proxy (full 2015-2026,
  covers 2020 COVID + 2022 bear).  This is the sanctioned "HY/IG OAS + corporate
  bond ETF proxy" route and follows K1529/K1538 precedent.  It is a DIAGNOSTIC
  PROXY for credit stress, NOT raw issuer CDS.
* Leverage grouping uses CURRENT total-debt / market-cap (yfinance snapshot),
  applied statically to the whole sample — disclosed as a static-classification
  limitation (historical fundamentals not free at daily granularity).
* CRWV (CoreWeave, IPO 2025-03, n~327, no bear market) is a CASE ILLUSTRATION
  only (like the article's SpaceX/SPCX example) and is NOT entered into any test.
* The article's specific figures (-40%, 6/22 -16.5%, US$25bn, 7.5% yield) are
  NOT verified and are NOT used as facts anywhere.

Method (Phase-1 diagnostic; log-HAR + Clark-West, NO GARCH MLE)
--------------------------------------------------------------
Per firm, expanding-window OOS log-HAR (Corsi 2009) on 5-day forward realized
variance:
    M0  HAR         : own rv daily / weekly / monthly
    M1  HAR+VIX     : + log(VIX daily variance)         <- the VIX-control base
    M2  HAR+VIX+CR  : + trailing-5d HYG-LQD credit stress (firm-relevant credit)
Primary incremental test = Clark-West (2007) nested MSPE-adjusted, M1 -> M2
(positive t => credit adds beyond HAR+VIX).  Reported per firm AND per leverage
group with the loss differential DATE-AGGREGATED across the group's firms
(K1355 cross-asset cluster-robust; asset-day iid is NOT the claim).

Firm-level DIFFERENTIAL (the article's testable content) = panel OLS
    fwd_logRV ~ HAR + logVIX + credit + credit x HighLev   (date-clustered SE),
the credit x HighLev coefficient tests whether levered issuers respond MORE.

Raw-vs-controlled (hard bar #3): raw corr(credit, fwd RV) vs partial corr | VIX.
A raw correlation that collapses after VIX control => NULL (K872 shadow).

Lookahead controls (README has the mechanical audit)
----------------------------------------------------
* Every predictor sits at forecast origin t; target = mean daily variance over
  [t+1, t+5], strictly future.  Explicit forward window (no shift off-by-one).
* Expanding OOS refit admits training row j for an origin-i fit only if
  j + H < i (target_end < forecast_origin).
* Raw/partial-corr diagnostics use credit.shift(1) vs same-index RV (explicit
  one-day lag) so the audit is unambiguous.
* Nested comparison uses Clark-West (NOT raw DM) — nested-DM is invalid inference
  and is a repo gate (scripts/experiment_gates.py nested-dm-misuse).
* All randomness seeded.

Author: VolPred autonomous research agent | Data: yfinance + FRED (all free)
"""
from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "src"))
from volpred.stats.model_evaluation import (  # noqa: E402
    qlike_pointwise,        # actual/predicted QLIKE (K783c)
    clark_west_test,        # nested incremental test (avoids nested-DM gate)
)

# ── Reproducibility ──────────────────────────────────────────────────────────
SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
PLOTS = HERE / "plots"
PLOTS.mkdir(exist_ok=True)

# ── Config ───────────────────────────────────────────────────────────────────
START = "2015-01-01"
END = datetime.now(timezone.utc).strftime("%Y-%m-%d")
H = 5                      # forecast horizon (days) = inference horizon
ANNUALIZE = 252
VIX_TICKER = "^VIX"
CREDIT_ETFS = ["HYG", "LQD"]          # HY vs IG -> credit-stress proxy
MIN_TRAIN = 500
REFIT_EVERY = 21
EPS = 1e-8
HARVEY_T = 3.0

# Leverage groups — pre-specified by capital structure, corroborated by current
# total-debt/market-cap (yfinance snapshot, printed at runtime for transparency).
HIGH_LEV = ["ORCL", "IBM", "EQIX", "DLR", "CRM"]     # debt-heavy AI-infra / tech
LOW_LEV = ["MSFT", "GOOGL", "AAPL", "NVDA", "META"]  # cash-rich hyperscalers
CASE_ONLY = ["CRWV"]                                  # short sample, illustration
ALL_FIRMS = HIGH_LEV + LOW_LEV

# Secondary short-sample FRED OAS (2023-07+, no bear market — robustness only)
FRED_HY = "BAMLH0A0HYM2"
FRED_IG = "BAMLC0A0CM"


# ─────────────────────────────────────────────────────────────────────────────
# Data fetch
# ─────────────────────────────────────────────────────────────────────────────
def fetch_yf_close(tickers: list[str]) -> pd.DataFrame:
    import yfinance as yf
    out = {}
    for tk in tickers:
        for attempt in range(3):
            try:
                df = yf.download(tk, start=START, end=END, auto_adjust=True,
                                 progress=False, threads=False)
                if df is None or df.empty:
                    raise ValueError("empty frame")
                col = df["Close"]
                if isinstance(col, pd.DataFrame):
                    col = col.iloc[:, 0]
                out[tk] = col
                break
            except Exception as e:  # noqa: BLE001
                print(f"[yf] {tk} attempt {attempt+1} failed: {e}", file=sys.stderr)
                if attempt == 2:
                    print(f"[yf] {tk} GIVE UP", file=sys.stderr)
    px = pd.DataFrame(out)
    px.index = pd.to_datetime(px.index)
    return px.sort_index()


def fetch_leverage(tickers: list[str]) -> dict:
    """Current total-debt/market-cap + debtToEquity (transparency corroboration)."""
    import yfinance as yf
    lev = {}
    for tk in tickers:
        try:
            info = yf.Ticker(tk).info
            td, mc = info.get("totalDebt"), info.get("marketCap")
            lev[tk] = {
                "debt_to_equity": info.get("debtToEquity"),
                "total_debt_over_mktcap": round(td / mc, 4) if (td and mc) else None,
            }
        except Exception as e:  # noqa: BLE001
            print(f"[lev] {tk} failed: {e}", file=sys.stderr)
            lev[tk] = {"debt_to_equity": None, "total_debt_over_mktcap": None}
    return lev


def fetch_fred_csv(series_id: str) -> pd.Series:
    """FRED via public fredgraph CSV (no API key). Short-sample OAS only."""
    import io
    import urllib.request
    url = (f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
           f"&cosd={START}&coed={END}")
    for attempt in range(3):
        try:
            raw = urllib.request.urlopen(url, timeout=45).read().decode()
            df = pd.read_csv(io.StringIO(raw))
            df.columns = ["date", "value"]
            df["date"] = pd.to_datetime(df["date"])
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            s = df.set_index("date")["value"].dropna()
            s.name = series_id
            return s
        except Exception as e:  # noqa: BLE001
            print(f"[fred] {series_id} attempt {attempt+1} failed: {e}", file=sys.stderr)
    return pd.Series(dtype=float, name=series_id)


# ─────────────────────────────────────────────────────────────────────────────
# Feature engineering (variance scale)
# ─────────────────────────────────────────────────────────────────────────────
def log_returns(px: pd.Series) -> pd.Series:
    return np.log(px / px.shift(1))


def rv_daily(ret: pd.Series) -> pd.Series:
    """Daily variance proxy = r^2 (noisy unbiased proxy for daily variance)."""
    return ret ** 2


def har_components(rv_d: pd.Series) -> pd.DataFrame:
    """HAR daily/weekly/monthly variance components at origin t (info up to t)."""
    return pd.DataFrame({
        "rv_d": rv_d,
        "rv_w": rv_d.rolling(5).mean(),
        "rv_m": rv_d.rolling(22).mean(),
    })


def vix_var_daily(vix_close: pd.Series) -> pd.Series:
    """VIX (annualized %, e.g. 20) -> daily variance (20/100)^2 / 252."""
    return (vix_close / 100.0) ** 2 / ANNUALIZE


def credit_stress_5d(hyg: pd.Series, lqd: pd.Series) -> pd.Series:
    """Trailing-5d cumulative HY underperformance vs IG = credit stress.

    stress_t = -(logret_HYG - logret_LQD) summed over the trailing 5 sessions.
    Positive => HY bonds fell relative to IG => credit conditions deteriorating.
    Value at t uses only closes up to t.
    """
    daily = -(log_returns(hyg) - log_returns(lqd))
    return daily.rolling(5).sum()


def forward_rv(rv_d: pd.Series, h: int = H) -> pd.Series:
    """Target: mean daily variance over [t+1, t+h] (strictly future vs origin t)."""
    vals = rv_d.values
    n = len(vals)
    out = np.full(n, np.nan)
    for i in range(n - h):
        window = vals[i + 1: i + 1 + h]
        if np.all(np.isfinite(window)):
            out[i] = window.mean()
    return pd.Series(out, index=rv_d.index)


# ─────────────────────────────────────────────────────────────────────────────
# Expanding-window OOS log-HAR forecast (enforces target_end < origin: j+H<i)
# ─────────────────────────────────────────────────────────────────────────────
def _design(df: pd.DataFrame, log_cols: list[str], lin_cols: list[str]) -> np.ndarray:
    parts = [np.ones(len(df))]
    for c in log_cols:
        parts.append(np.log(np.maximum(df[c].values, 0.0) + EPS))
    for c in lin_cols:
        parts.append(df[c].values)
    return np.column_stack(parts)


def oos_forecast(feats: pd.DataFrame, target: pd.Series,
                 log_cols: list[str], lin_cols: list[str],
                 min_train: int = MIN_TRAIN) -> pd.DataFrame:
    cols = log_cols + lin_cols
    df = feats[cols].copy()
    df["_y"] = target
    df = df.replace([np.inf, -np.inf], np.nan).dropna()
    if df.empty:
        return pd.DataFrame(columns=["pred", "actual"])
    X = _design(df, log_cols, lin_cols)
    y_raw = df["_y"].values
    y_log = np.log(np.maximum(y_raw, 0.0) + EPS)
    n = len(df)

    preds = np.full(n, np.nan)
    beta = None
    resid_var = 0.0
    last_refit = -10**9
    for i in range(n):
        train_hi = i - H          # rows 0..train_hi-1 satisfy j+H < i
        if train_hi < min_train:
            continue
        if beta is None or (i - last_refit) >= REFIT_EVERY:
            Xtr, ytr = X[:train_hi], y_log[:train_hi]
            beta, *_ = np.linalg.lstsq(Xtr, ytr, rcond=None)
            resid = ytr - Xtr @ beta
            resid_var = float(np.mean(resid ** 2))
            last_refit = i
        yhat = X[i] @ beta
        preds[i] = np.exp(yhat + 0.5 * resid_var) - EPS

    res = pd.DataFrame({"pred": preds, "actual": y_raw}, index=df.index).dropna()
    res["pred"] = res["pred"].clip(lower=EPS)
    res["actual"] = res["actual"].clip(lower=EPS)
    return res


# ─────────────────────────────────────────────────────────────────────────────
# Per-firm build
# ─────────────────────────────────────────────────────────────────────────────
def build_firm(px: pd.Series, vix_var: pd.Series, credit: pd.Series) -> dict:
    """Return aligned features + OOS forecasts for M0/M1/M2 for one firm."""
    ret = log_returns(px)
    rv_d = rv_daily(ret)
    har = har_components(rv_d)
    feats = har.copy()
    feats["vix_var"] = vix_var.reindex(feats.index)
    feats["credit"] = credit.reindex(feats.index)
    target = forward_rv(rv_d, H)

    log_har = ["rv_d", "rv_w", "rv_m"]
    m0 = oos_forecast(feats, target, log_har, [])
    m1 = oos_forecast(feats, target, log_har + ["vix_var"], [])
    m2 = oos_forecast(feats, target, log_har + ["vix_var"], ["credit"])

    # align the three forecast frames on the common OOS index
    common = m0.index.intersection(m1.index).intersection(m2.index)
    out = {
        "rv_d": rv_d, "credit": feats["credit"], "vix_var": feats["vix_var"],
        "target": target,
        "m0": m0.reindex(common), "m1": m1.reindex(common), "m2": m2.reindex(common),
        "common": common,
    }
    return out


def qlike_mean(res: pd.DataFrame) -> float:
    if res.empty:
        return float("nan")
    return float(np.mean(qlike_pointwise(res["actual"].values, res["pred"].values)))


# ─────────────────────────────────────────────────────────────────────────────
# Group-level Clark-West (date-aggregated across firms, K1355)
# ─────────────────────────────────────────────────────────────────────────────
def group_clark_west(firm_data: dict, firms: list[str]) -> dict:
    """Date-aggregate M1->M2 CW loss across a group's firms, then HAC inference."""
    common = None
    for tk in firms:
        idx = firm_data[tk]["common"]
        common = idx if common is None else common.union(idx)
    common = common.sort_values()
    A = np.full((len(common), len(firms)), np.nan)
    FS = np.full_like(A, np.nan)
    FL = np.full_like(A, np.nan)
    for j, tk in enumerate(firms):
        d = firm_data[tk]
        pos = common.get_indexer(d["common"])
        ok = pos >= 0
        A[pos[ok], j] = d["m1"]["actual"].values[ok]
        FS[pos[ok], j] = d["m1"]["pred"].values[ok]
        FL[pos[ok], j] = d["m2"]["pred"].values[ok]
    cw = clark_west_test(A, FS, FL, h=H, aggregate_axis=1)
    return {
        "n_dates": int(cw["n_obs"]),
        "cw_t": float(cw["t_stat"]),
        "cw_p_one_sided": float(cw["p_value_one_sided"]),
        "cw_mean_adj_loss_diff": float(cw["mean_adjusted_loss_diff"]),
        "hac_lag": int(cw["hac_lag"]),
        "harvey_pass": bool(abs(cw["t_stat"]) > HARVEY_T and cw["t_stat"] > 0),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Panel differential: credit x HighLev interaction (date-clustered SE)
# ─────────────────────────────────────────────────────────────────────────────
def panel_interaction(firm_data: dict) -> dict:
    import statsmodels.api as sm
    rows = []
    for tk in ALL_FIRMS:
        d = firm_data[tk]
        rv_d = d["rv_d"]
        tgt = np.log(np.maximum(forward_rv(rv_d, H), 0.0) + EPS)
        df = pd.DataFrame({
            "y": tgt,
            "rv_d": np.log(np.maximum(rv_d, 0.0) + EPS),
            "rv_w": np.log(np.maximum(rv_d.rolling(5).mean(), 0.0) + EPS),
            "rv_m": np.log(np.maximum(rv_d.rolling(22).mean(), 0.0) + EPS),
            "logvix": np.log(np.maximum(d["vix_var"], 0.0) + EPS),
            "credit": d["credit"],
        })
        df["high_lev"] = 1.0 if tk in HIGH_LEV else 0.0
        df["credit_x_high"] = df["credit"] * df["high_lev"]
        df["date"] = df.index
        df = df.replace([np.inf, -np.inf], np.nan).dropna()
        rows.append(df)
    panel = pd.concat(rows, ignore_index=True)
    X = panel[["rv_d", "rv_w", "rv_m", "logvix", "credit", "high_lev", "credit_x_high"]]
    X = sm.add_constant(X)
    model = sm.OLS(panel["y"], X).fit(
        cov_type="cluster", cov_kwds={"groups": panel["date"]})
    return {
        "n_obs": int(model.nobs),
        "n_dates": int(panel["date"].nunique()),
        "beta_credit": float(model.params["credit"]),
        "t_credit": float(model.tvalues["credit"]),
        "beta_credit_x_high": float(model.params["credit_x_high"]),
        "t_credit_x_high": float(model.tvalues["credit_x_high"]),
        "p_credit_x_high": float(model.pvalues["credit_x_high"]),
        "beta_logvix": float(model.params["logvix"]),
        "t_logvix": float(model.tvalues["logvix"]),
        "interaction_harvey_pass": bool(abs(model.tvalues["credit_x_high"]) > HARVEY_T),
        "note": ("credit_x_high>0 & Harvey-sig => levered issuers' vol responds "
                 "MORE to credit beyond VIX (in-sample diagnostic, date-clustered)."),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Raw vs VIX-controlled correlation (hard bar #3), explicit shift(1)
# ─────────────────────────────────────────────────────────────────────────────
def raw_vs_controlled(firm_data: dict, firms: list[str]) -> dict:
    """Pooled raw corr(credit_{t-1}, RV_t) vs partial corr controlling VIX_{t-1}."""
    cr, rv, vx = [], [], []
    for tk in firms:
        d = firm_data[tk]
        credit_lag = d["credit"].shift(1)          # explicit one-day lag
        vix_lag = np.log(np.maximum(d["vix_var"].shift(1), 0.0) + EPS)
        rvd = d["rv_d"]
        df = pd.DataFrame({"c": credit_lag, "v": vix_lag, "r": rvd}).replace(
            [np.inf, -np.inf], np.nan).dropna()
        cr.append(df["c"].values)
        rv.append(df["r"].values)
        vx.append(df["v"].values)
    c = np.concatenate(cr)
    r = np.concatenate(rv)
    v = np.concatenate(vx)
    raw = float(np.corrcoef(c, r)[0, 1])
    # partial corr(c, r | v): residualize both on v then correlate
    def resid(y, x):
        b = np.polyfit(x, y, 1)
        return y - (b[0] * x + b[1])
    pc = float(np.corrcoef(resid(c, v), resid(r, v))[0, 1])
    return {"n": int(len(c)), "raw_corr_credit_rv": round(raw, 4),
            "partial_corr_given_vix": round(pc, 4),
            "raw_minus_partial": round(raw - pc, 4)}


# ─────────────────────────────────────────────────────────────────────────────
# VIX-regime split (K1621 hint): does credit help more in stress?
# ─────────────────────────────────────────────────────────────────────────────
def vix_regime_gain(firm_data: dict, firms: list[str], vix_close: pd.Series) -> dict:
    """QLIKE gain M1->M2, split by VIX>=20 (stress) vs <20 (calm), pooled by firm."""
    thr = 20.0
    out = {}
    for label, mask_hi in [("calm_vix_lt20", False), ("stress_vix_ge20", True)]:
        base, aug = [], []
        for tk in firms:
            d = firm_data[tk]
            idx = d["common"]
            vc = vix_close.reindex(idx)
            m = (vc >= thr) if mask_hi else (vc < thr)
            m = m.values & np.isfinite(vc.values)
            if m.sum() < 30:
                continue
            base.append(qlike_pointwise(d["m1"]["actual"].values[m],
                                        d["m1"]["pred"].values[m]))
            aug.append(qlike_pointwise(d["m2"]["actual"].values[m],
                                       d["m2"]["pred"].values[m]))
        if not base:
            out[label] = {"n": 0, "qlike_gain_pct": None}
            continue
        b = float(np.mean(np.concatenate(base)))
        a = float(np.mean(np.concatenate(aug)))
        out[label] = {"n": int(sum(len(x) for x in base)),
                      "qlike_m1": round(b, 6), "qlike_m2": round(a, 6),
                      "qlike_gain_pct": round(100.0 * (b - a) / b, 3) if b > 0 else None}
    return out


# ─────────────────────────────────────────────────────────────────────────────
# CRWV case illustration (descriptive only — NOT a test)
# ─────────────────────────────────────────────────────────────────────────────
def crwv_case(px_crwv: pd.Series, credit: pd.Series, vix_close: pd.Series) -> dict:
    if px_crwv is None or px_crwv.dropna().shape[0] < 30:
        return {"available": False, "note": "CRWV data insufficient"}
    ret = log_returns(px_crwv)
    rv_d = rv_daily(ret)
    rv20 = np.sqrt(rv_d.rolling(20).mean() * ANNUALIZE)
    df = pd.DataFrame({"rv20": rv20, "credit": credit.reindex(rv_d.index),
                       "vix": vix_close.reindex(rv_d.index)}).dropna()
    contemp = float(np.corrcoef(df["credit"].values, df["rv20"].values)[0, 1]) \
        if len(df) > 30 else float("nan")
    return {
        "available": True, "n_days": int(px_crwv.dropna().shape[0]),
        "first_date": str(px_crwv.dropna().index.min().date()),
        "sample_note": ("post-IPO 2025+ only, NO bear market, single regime — "
                        "CASE ILLUSTRATION, excluded from all formal tests"),
        "contemporaneous_corr_credit_vs_rv20": round(contemp, 4),
        "mean_ann_vol_pct": round(float(df["rv20"].mean() * 100), 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Secondary: short-sample FRED OAS robustness (underpowered, no bear market)
# ─────────────────────────────────────────────────────────────────────────────
def fred_oas_secondary(firm_data: dict, hy: pd.Series, ig: pd.Series) -> dict:
    if hy.dropna().shape[0] < 100:
        return {"available": False, "note": "FRED OAS unavailable"}
    # HY OAS daily change, trailing 5d sum, as an alternative credit signal
    hy_chg5 = hy.diff().rolling(5).sum()
    covered = hy.dropna()
    note = (f"FRED HY OAS window {covered.index.min().date()}.."
            f"{covered.index.max().date()} (n={len(covered)}); "
            "no 2020/2022 bear market -> UNDERPOWERED secondary robustness only.")
    # pooled raw vs partial-corr | VIX using OAS-change signal, HIGH-LEV group
    cr, rv, vx = [], [], []
    for tk in HIGH_LEV:
        d = firm_data[tk]
        sig = hy_chg5.reindex(d["rv_d"].index).shift(1)
        vix_lag = np.log(np.maximum(d["vix_var"].shift(1), 0.0) + EPS)
        df = pd.DataFrame({"c": sig, "v": vix_lag, "r": d["rv_d"]}).replace(
            [np.inf, -np.inf], np.nan).dropna()
        if len(df) < 50:
            continue
        cr.append(df["c"].values); rv.append(df["r"].values); vx.append(df["v"].values)
    if not cr:
        return {"available": True, "note": note, "insufficient_overlap": True}
    c = np.concatenate(cr); r = np.concatenate(rv); v = np.concatenate(vx)
    raw = float(np.corrcoef(c, r)[0, 1])
    def resid(y, x):
        b = np.polyfit(x, y, 1)
        return y - (b[0] * x + b[1])
    pc = float(np.corrcoef(resid(c, v), resid(r, v))[0, 1])
    return {"available": True, "note": note, "n": int(len(c)),
            "highlev_raw_corr_hyoas_rv": round(raw, 4),
            "highlev_partial_corr_given_vix": round(pc, 4)}


# ─────────────────────────────────────────────────────────────────────────────
# Charts
# ─────────────────────────────────────────────────────────────────────────────
def make_charts(res: dict) -> list[str]:
    paths = []
    # 1) per-group CW t-stat + per-firm QLIKE gains
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    groups = ["high_lev", "low_lev"]
    tvals = [res["group_clark_west"][g]["cw_t"] for g in groups]
    colors = ["#c0392b", "#2980b9"]
    axes[0].bar(["HIGH-LEV\n(ORCL/IBM/EQIX/DLR/CRM)", "LOW-LEV\n(MSFT/GOOGL/AAPL/NVDA/META)"],
                tvals, color=colors)
    axes[0].axhline(HARVEY_T, ls="--", c="k", lw=1, label="Harvey |t|=3")
    axes[0].axhline(0, c="gray", lw=0.8)
    axes[0].set_ylabel("Clark-West t (credit beyond HAR+VIX)")
    axes[0].set_title("Does credit add beyond VIX? (date-aggregated, K1355)")
    axes[0].legend()
    firms = ALL_FIRMS
    gains = [res["per_firm"][tk]["qlike_gain_m1_to_m2_pct"] for tk in firms]
    fcol = ["#c0392b" if tk in HIGH_LEV else "#2980b9" for tk in firms]
    axes[1].barh(firms, gains, color=fcol)
    axes[1].axvline(0, c="gray", lw=0.8)
    axes[1].set_xlabel("OOS QLIKE gain M1->M2 (%)  (+ = credit helps)")
    axes[1].set_title("Per-firm incremental value of credit stress")
    plt.tight_layout()
    p1 = PLOTS / "group_incremental.png"
    fig.savefig(p1, dpi=130); plt.close(fig); paths.append(str(p1))

    # 2) raw vs VIX-controlled correlation
    fig, ax = plt.subplots(figsize=(8, 5))
    labels = ["HIGH-LEV", "LOW-LEV"]
    raws = [res["raw_vs_controlled"]["high_lev"]["raw_corr_credit_rv"],
            res["raw_vs_controlled"]["low_lev"]["raw_corr_credit_rv"]]
    parts = [res["raw_vs_controlled"]["high_lev"]["partial_corr_given_vix"],
             res["raw_vs_controlled"]["low_lev"]["partial_corr_given_vix"]]
    x = np.arange(2); w = 0.35
    ax.bar(x - w/2, raws, w, label="raw corr(credit, RV)", color="#e67e22")
    ax.bar(x + w/2, parts, w, label="partial corr | VIX", color="#16a085")
    ax.set_xticks(x); ax.set_xticklabels(labels)
    ax.axhline(0, c="gray", lw=0.8)
    ax.set_ylabel("correlation")
    ax.set_title("Credit->vol: raw vs after controlling VIX (K872 shadow test)")
    ax.legend()
    plt.tight_layout()
    p2 = PLOTS / "raw_vs_controlled.png"
    fig.savefig(p2, dpi=130); plt.close(fig); paths.append(str(p2))

    # 3) VIX-regime split gain
    fig, ax = plt.subplots(figsize=(8, 5))
    regs = ["calm_vix_lt20", "stress_vix_ge20"]
    hi = [res["vix_regime"]["high_lev"][rg].get("qlike_gain_pct") or 0 for rg in regs]
    lo = [res["vix_regime"]["low_lev"][rg].get("qlike_gain_pct") or 0 for rg in regs]
    x = np.arange(2); w = 0.35
    ax.bar(x - w/2, hi, w, label="HIGH-LEV", color="#c0392b")
    ax.bar(x + w/2, lo, w, label="LOW-LEV", color="#2980b9")
    ax.set_xticks(x); ax.set_xticklabels(["Calm (VIX<20)", "Stress (VIX>=20)"])
    ax.axhline(0, c="gray", lw=0.8)
    ax.set_ylabel("QLIKE gain M1->M2 (%)")
    ax.set_title("Credit incremental value by VIX regime (K1621 hypothesis)")
    ax.legend()
    plt.tight_layout()
    p3 = PLOTS / "vix_regime.png"
    fig.savefig(p3, dpi=130); plt.close(fig); paths.append(str(p3))
    return paths


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    print(f"[data] downloading firms + HYG/LQD/VIX ({START}..{END})")
    px = fetch_yf_close(ALL_FIRMS + CASE_ONLY + CREDIT_ETFS + [VIX_TICKER])
    lev = fetch_leverage(ALL_FIRMS + CASE_ONLY)
    hy = fetch_fred_csv(FRED_HY)
    ig = fetch_fred_csv(FRED_IG)

    vix_close = px[VIX_TICKER]
    vix_var = vix_var_daily(vix_close)
    credit = credit_stress_5d(px["HYG"], px["LQD"])

    firm_data = {}
    for tk in ALL_FIRMS:
        if tk not in px.columns or px[tk].notna().sum() < 500:
            print(f"[warn] {tk} insufficient data — skipped", file=sys.stderr)
            continue
        firm_data[tk] = build_firm(px[tk], vix_var, credit)

    usable_high = [t for t in HIGH_LEV if t in firm_data]
    usable_low = [t for t in LOW_LEV if t in firm_data]

    # ---- per-firm QLIKE + CW ----
    per_firm = {}
    for tk in firm_data:
        d = firm_data[tk]
        q0, q1, q2 = qlike_mean(d["m0"]), qlike_mean(d["m1"]), qlike_mean(d["m2"])
        cw = clark_west_test(d["m1"]["actual"].values, d["m1"]["pred"].values,
                             d["m2"]["pred"].values, h=H)
        per_firm[tk] = {
            "group": "high_lev" if tk in HIGH_LEV else "low_lev",
            "leverage": lev.get(tk, {}),
            "n_oos": int(len(d["common"])),
            "qlike_m0_har": round(q0, 6),
            "qlike_m1_har_vix": round(q1, 6),
            "qlike_m2_har_vix_credit": round(q2, 6),
            "qlike_gain_m1_to_m2_pct": round(100.0 * (q1 - q2) / q1, 4) if q1 > 0 else None,
            "vix_gain_m0_to_m1_pct": round(100.0 * (q0 - q1) / q0, 4) if q0 > 0 else None,
            "cw_t_credit_beyond_vix": round(float(cw["t_stat"]), 4),
            "cw_p_one_sided": round(float(cw["p_value_one_sided"]), 4),
            "harvey_pass": bool(abs(cw["t_stat"]) > HARVEY_T and cw["t_stat"] > 0),
        }

    # ---- group CW (date-aggregated K1355) ----
    group_cw = {
        "high_lev": group_clark_west(firm_data, usable_high),
        "low_lev": group_clark_west(firm_data, usable_low),
    }

    # ---- panel differential (interaction) ----
    panel = panel_interaction(firm_data)

    # ---- raw vs controlled ----
    rvc = {
        "high_lev": raw_vs_controlled(firm_data, usable_high),
        "low_lev": raw_vs_controlled(firm_data, usable_low),
    }

    # ---- VIX-regime split ----
    regime = {
        "high_lev": vix_regime_gain(firm_data, usable_high, vix_close),
        "low_lev": vix_regime_gain(firm_data, usable_low, vix_close),
    }

    # ---- CRWV case ----
    crwv = crwv_case(px.get("CRWV"), credit, vix_close)

    # ---- FRED OAS secondary ----
    oas_sec = fred_oas_secondary(firm_data, hy, ig)

    # ---- verdict ----
    hi_cw = group_cw["high_lev"]
    lo_cw = group_cw["low_lev"]
    credit_beats_vix_high = hi_cw["harvey_pass"]
    differential_sig = panel["interaction_harvey_pass"] and panel["beta_credit_x_high"] > 0
    high_gt_low = (hi_cw["cw_t"] > lo_cw["cw_t"]) and (hi_cw["cw_mean_adj_loss_diff"] >
                                                       lo_cw["cw_mean_adj_loss_diff"])
    signal = bool(credit_beats_vix_high and differential_sig and high_gt_low)
    verdict = "SIGNAL" if signal else "NULL"

    results = {
        "experiment_id": "credit_stress_firm_level",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "config": {
            "start": START, "end": END, "horizon_days": H,
            "high_lev_firms": HIGH_LEV, "low_lev_firms": LOW_LEV,
            "case_only": CASE_ONLY,
            "credit_signal_primary": "trailing-5d HYG-LQD credit-stress proxy (ETF)",
            "credit_signal_secondary": "FRED HY/IG OAS change (short-sample 2023-07+)",
            "vix_control": "log(VIX daily variance) as M1 regressor (hard gate)",
            "incremental_test": "Clark-West (2007) nested MSPE-adjusted (NOT raw DM)",
            "pooling": "date-aggregated cross-firm loss (K1355 cluster-robust)",
            "har_spec": "log-HAR (Corsi 2009) + lognormal bias correction",
            "loss": "QLIKE actual/predicted (Patton 2011, K783c)",
            "leverage_metric": "current total-debt/market-cap (yfinance snapshot, static)",
            "proxy_disclaimer": ("HYG-LQD and OAS are DIAGNOSTIC proxies for credit "
                                 "stress; NOT raw single-name CDS (Markit, paid)."),
            "oas_history_note": ("FRED HY/IG OAS retain only ~3yr rolling window since "
                                 "2024 ICE license change (both start 2023-07-17, "
                                 "no bear market) -> secondary/underpowered only."),
        },
        "leverage_snapshot": lev,
        "per_firm": per_firm,
        "group_clark_west": group_cw,
        "panel_interaction": panel,
        "raw_vs_controlled": rvc,
        "vix_regime": regime,
        "crwv_case_illustration": crwv,
        "fred_oas_secondary": oas_sec,
        "prior_null_context": {
            "K872": "HY OAS raw r=0.55 but delta-R2 after VIX = 0.0003 (VIX sufficiency)",
            "T14": "credit+yield only +1.6% incremental R2 (econ trivial)",
            "K1621": "EM sov-credit vol does not lead EM equity vol daily (contemp factor)",
            "K1529": "FOMC credit NULL with free ETF proxies; firm/intraday needed to reopen",
            "K1538": "bond-fund run-pressure proxy weak, below gates",
        },
    }

    charts = make_charts(results)
    results["charts"] = charts

    out = HERE / "credit_stress_firm_level_results.json"
    out.write_text(json.dumps(results, indent=2, default=str))
    print(f"\n[done] verdict={verdict}")
    print(f"  HIGH-LEV group CW t (credit beyond VIX) = {hi_cw['cw_t']:.3f} "
          f"(Harvey pass={hi_cw['harvey_pass']})")
    print(f"  LOW-LEV  group CW t                     = {lo_cw['cw_t']:.3f}")
    print(f"  panel credit x HighLev t = {panel['t_credit_x_high']:.3f} "
          f"(beta={panel['beta_credit_x_high']:.4g})")
    print(f"  raw vs controlled (HIGH-LEV): raw={rvc['high_lev']['raw_corr_credit_rv']} "
          f"partial|VIX={rvc['high_lev']['partial_corr_given_vix']}")
    print(f"  charts: {charts}")
    print(f"  results -> {out}")


if __name__ == "__main__":
    main()
