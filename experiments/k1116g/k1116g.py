"""
K1116g — Nested Clark-West increment test for the remaining STABLE-DATA daily
signal families of the vix-sufficiency paper (Families 1, 8, 11).

Context
-------
Predecessors:
  * k1116c — weekly alt-data families 12/13 nested CW (all |t|<0.6, null robust)
  * k1116e — highest-IS-signal daily families 2 (VIX term structure) and 4 (VRP),
             the prime CW-flip candidates; both FAIL Harvey |t|>3.0 (CW t=1.69,
             CW t=-0.22), null robust to the more-powerful Clark-West test.

Table 3 of the vix-sufficiency paper (main_v5.tex) reports the standard DM |t|
for every daily regression family. A referee will ask whether the null survives
the STRICTLY-MORE-POWERFUL nested Clark-West (2007) test for the daily families
too. k1116e answered this for the two worst-case (highest in-sample partial
signal) families. This run completes the STABLE-DATA remainder:

  * Family 1  Cross-Asset Volatility Momentum  (paper Table 3: IS t=-1.45, DM|t|=1.45)
  * Family 8  Yield Curve Slope                (paper Table 3: IS t=+2.51, DM|t|=0.84)
  * Family 11 Calendar Anomaly                 (paper Table 3: IS t=-2.39, DM|t|=0.15)

The three daily families still deferred (3 behavioral P/C, 9 Google Trends, 10
overnight VIX) require fragile external data (CBOE put-call ratio, pytrends,
intraday VIX open) and are left to a data-provisioning follow-up. This is NOT a
bounding argument: F1/F8/F11 are the families whose signals can be reconstructed
from Yahoo-Finance price data and date arithmetic alone, so we compute them
honestly here and report whatever CW returns. All three have weak in-sample
signal (|IS t| <= 2.51, vs Family 2's 17.6), so a CW flip is a priori unlikely;
we verify rather than assume.

Faithful-reconstruction note
----------------------------
The paper's original 13-family pipeline scripts are scattered across k730-k1201
and were never consolidated into a single harness. Following the k1116e
precedent, the signals below are rebuilt from the paper's construction prose
(main_v5.tex Section 2.3, Families 1/8/11) under the SAME nested-CW machinery
(fixed IS/OOS split + 22-day embargo, same-sample nested OLS, forward-22d RV
target, HAC nw_lag=21, HLN h=22). As in k1116e, the fixed-split DM here is a
DIRECTIONAL cross-check and is NOT expected to exactly equal Table 3's
expanding-window DM (k1116e's F2 fixed-split DM|t|=1.30 vs Table 3's 0.87). The
DELIVERABLE is the Clark-West column: does the more-powerful nested test flip any
daily-family null? Construction choices are documented per signal below.

Design (identical to k1116e)
----------------------------
* Target: 22-day FORWARD realized vol of SPY, fwd_rv22[t] = std over (t, t+H].
* Baseline (restricted M2):   fwd_rv ~ 1 + VIX_level
* Augmented (nests M2):        fwd_rv ~ 1 + VIX_level + signal_j
* Features are the close-of-day-t information set (no extra shift, matching the
  paper's daily convention); target strictly forward -> no lookahead.
* Same IS/OOS rows for both nested models; 22-day embargo on the IS tail.
* Clark-West f_hat = e1^2 - e2^2 + (f1 - f2)^2, one-sided H1: E[f_hat]>0.
  |t|>3.0 = Harvey (2016) conservative pass. HAC nw_lag=21, HLN h=22.

References: Clark-West (2007) JoE 138:291-311; Harvey-Leybourne-Newbold (1997)
IJF 13:281-291; Harvey-Liu-Zhu (2016) RFS 29:5-68; Diebold-Mariano (1995) JBES.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy import stats as st

HERE = Path(__file__).resolve().parent

START_DATE = "1993-01-01"
END_DATE = "2026-07-01"
IS_END = "2018-12-31"
OOS_START = "2019-01-01"
H = 22                 # forward target horizon (trading days)
NW_LAG = H - 1         # 21: HAC lag for overlapping MA(H-1) forecast errors
HARVEY_THRESHOLD = 3.0
RV_WIN = 22            # realized-vol window for cross-asset momentum
MOM_LAG = 5            # 5-day change of the 22-day RV (Family 1 construction)
ZWIN = 252            # rolling window for lookahead-safe normalization (Family 1)


# ── data ────────────────────────────────────────────────────────────────────
def _flatten(raw: pd.DataFrame) -> pd.DataFrame:
    if isinstance(raw.columns, pd.MultiIndex):
        px = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw["Adj Close"]
    else:
        px = raw
    px.columns = [str(c).replace("^", "") for c in px.columns]
    return px


def _rv22(price: pd.Series) -> pd.Series:
    """22-day BACKWARD realized vol (annualized, x100) from close-to-close log returns."""
    r = np.log(price / price.shift(1))
    return r.rolling(RV_WIN).std() * np.sqrt(252) * 100.0


def _roll_z(x: pd.Series, win: int = ZWIN) -> pd.Series:
    """Lookahead-safe rolling z-score (uses only data up to and including t)."""
    mu = x.rolling(win, min_periods=win // 2).mean()
    sd = x.rolling(win, min_periods=win // 2).std()
    return (x - mu) / sd


def load_panel() -> pd.DataFrame:
    """SPY + VIX panel with forward-22d RV target and Family 1/8/11 signals.

    All signal inputs are close-of-day-t observations (or pure date arithmetic for
    Family 11); no signal peeks past the forecast origin.
    """
    core = _flatten(yf.download(["SPY", "^VIX"], start=START_DATE, end=END_DATE,
                                progress=False, auto_adjust=False))
    df = pd.DataFrame(index=core.index)
    df["SPY"] = core["SPY"]
    df["VIX"] = core["VIX"]
    df = df.dropna(subset=["SPY", "VIX"])

    log_ret = np.log(df["SPY"] / df["SPY"].shift(1))
    # 22-day FORWARD realized vol target: std of the H returns over (t, t+H].
    df["fwd_rv22"] = log_ret.shift(-1).rolling(H).std().shift(-(H - 1)) * np.sqrt(252) * 100.0

    # ── Family 1: Cross-Asset Volatility Momentum ──
    # Paper: "5-day change in 22-day realized volatility for five asset classes:
    # bonds (TLT), oil (USO), U.S. dollar (UUP), gold (GLD), and credit (HYG minus
    # LQD spread). A composite momentum signal averages the normalized changes."
    # Construction: for each asset build 22d RV; the credit "asset" is the HYG-LQD
    # daily log-return spread (its RV measures credit-market turbulence). Take the
    # 5-day change of each 22d RV, z-score each change over a rolling 252-day
    # window (lookahead-safe "normalization"), and average across the five.
    xa = _flatten(yf.download(["TLT", "USO", "UUP", "GLD", "HYG", "LQD"],
                              start=START_DATE, end=END_DATE, progress=False,
                              auto_adjust=False)).reindex(df.index).ffill(limit=3)
    rv = {}
    for tk in ["TLT", "USO", "UUP", "GLD"]:
        if tk in xa.columns:
            rv[tk] = _rv22(xa[tk])
    if "HYG" in xa.columns and "LQD" in xa.columns:
        cr_ret = np.log(xa["HYG"] / xa["HYG"].shift(1)) - np.log(xa["LQD"] / xa["LQD"].shift(1))
        rv["CREDIT"] = cr_ret.rolling(RV_WIN).std() * np.sqrt(252) * 100.0
    zparts = []
    for _, s in rv.items():
        chg = s - s.shift(MOM_LAG)            # 5-day change of the 22d RV
        zparts.append(_roll_z(chg))           # normalized change
    if zparts:
        z = pd.concat(zparts, axis=1)
        # require at least 3 of 5 asset legs present so the composite is meaningful
        df["sig_F1_xasset_mom"] = z.mean(axis=1).where(z.notna().sum(axis=1) >= 3)

    # ── Family 8: Yield Curve Slope ──
    # Paper: "yield curve slope (10Y - 3M Treasury spread)". ^TNX = 10Y note yield,
    # ^IRX = 13-week T-bill yield (both in percent). Slope = TNX - IRX, close-of-t.
    yld = _flatten(yf.download(["^TNX", "^IRX"], start=START_DATE, end=END_DATE,
                               progress=False, auto_adjust=False)).reindex(df.index).ffill(limit=3)
    if "TNX" in yld.columns and "IRX" in yld.columns:
        df["sig_F8_yield_slope"] = yld["TNX"] - yld["IRX"]

    # ── Family 11: Calendar Anomaly ──
    # Paper: "Halloween effect and other calendar anomalies ... monthly/seasonal
    # dummies." Canonical "Sell in May and go away" window = May-Oct. Indicator is
    # pure date arithmetic (no data, no lookahead).
    df["sig_F11_halloween"] = df.index.month.isin([5, 6, 7, 8, 9, 10]).astype(float)

    return df


# ── forward-label fixed split with embargo, same-sample nested estimation ────
def _split_masks(df: pd.DataFrame, valid: pd.Series):
    is_end = pd.Timestamp(IS_END)
    oos_start = pd.Timestamp(OOS_START)
    is_dates = df.index[(df.index <= is_end) & valid]
    embargo_cut = is_dates[-H] if len(is_dates) > H else is_end
    is_mask = valid & (df.index < embargo_cut)
    oos_mask = valid & (df.index >= oos_start)
    return is_mask, oos_mask


def _nw_var(x: np.ndarray, lag: int) -> float:
    x = np.asarray(x, float)
    n = len(x)
    xd = x - x.mean()
    g0 = np.dot(xd, xd) / n
    var = g0
    for k in range(1, lag + 1):
        w = 1.0 - k / (lag + 1.0)
        var += 2.0 * w * (np.dot(xd[k:], xd[:-k]) / n)
    return max(var, g0 / n)


def _one_sample_t(series: np.ndarray, h: int, nw_lag: int):
    s = np.asarray(series, float)
    s = s[~np.isnan(s)]
    n = len(s)
    mbar = s.mean()
    lrv = _nw_var(s, nw_lag)
    se = np.sqrt(lrv / n)
    hln_arg = (n + 1 - 2 * h + h * (h - 1) / n) / n
    hln = np.sqrt(hln_arg) if hln_arg > 0 else float("nan")
    t = (mbar / se) * hln
    p_two = 2 * (1 - st.t.cdf(abs(t), df=n - 1))
    p_one = 1 - st.t.cdf(t, df=n - 1)
    return dict(mean=float(mbar), t=float(t), p_two=float(p_two),
                p_one_greater=float(p_one), n=int(n), hln_factor=float(hln),
                nw_lag=int(nw_lag))


def evaluate_family(df: pd.DataFrame, signal_col: str) -> dict:
    base_feat = pd.DataFrame({"VIX": df["VIX"]}, index=df.index)
    aug_feat = base_feat.assign(**{signal_col: df[signal_col]})
    y = df["fwd_rv22"]

    valid = aug_feat.notna().all(axis=1) & y.notna()
    is_mask, oos_mask = _split_masks(df, valid)

    Xb_is = sm.add_constant(base_feat[is_mask])
    Xa_is = sm.add_constant(aug_feat[is_mask])
    y_is = y[is_mask]
    mb = sm.OLS(y_is, Xb_is).fit()   # restricted: VIX only
    ma = sm.OLS(y_is, Xa_is).fit()   # augmented: VIX + signal (nests restricted)

    Xb_oos = sm.add_constant(base_feat[oos_mask])[Xb_is.columns]
    Xa_oos = sm.add_constant(aug_feat[oos_mask])[Xa_is.columns]
    idx = y[oos_mask].index
    y_v = y[oos_mask].values
    f1 = mb.predict(Xb_oos).values   # baseline (restricted) forecast
    f2 = ma.predict(Xa_oos).values   # augmented forecast
    e1sq = (y_v - f1) ** 2
    e2sq = (y_v - f2) ** 2

    d = e1sq - e2sq
    dm = _one_sample_t(d, h=H, nw_lag=NW_LAG)

    adj = (f1 - f2) ** 2
    f_hat = e1sq - e2sq + adj
    cw = _one_sample_t(f_hat, h=H, nw_lag=NW_LAG)

    is_signal_t = float(ma.tvalues.get(signal_col, np.nan))

    return {
        "signal_col": signal_col,
        "n_is": int(is_mask.sum()),
        "n_oos": int(len(idx)),
        "oos_start": str(idx[0].date()),
        "oos_end": str(idx[-1].date()),
        "is_signal_tstat": is_signal_t,
        "mspe_baseline_vixonly": float(np.mean(e1sq)),
        "mspe_augmented_vixplus": float(np.mean(e2sq)),
        "mspe_adjustment_mean": float(np.mean(adj)),
        "dm_mspe": {"t": dm["t"], "p_two": dm["p_two"], "p_one_greater": dm["p_one_greater"],
                    "n": dm["n"], "hln_factor": dm["hln_factor"], "nw_lag": dm["nw_lag"],
                    "note": "fixed-split DM on squared fwd-RV errors; +t => augmented beats "
                            "VIX-only; directional cross-check, not exact Table-3 expanding-window DM"},
        "clark_west": {"t": cw["t"], "p_one_greater": cw["p_one_greater"], "p_two": cw["p_two"],
                       "hln_factor": cw["hln_factor"], "nw_lag": cw["nw_lag"],
                       "mspe_adjusted_mean": cw["mean"],
                       "note": "one-sided H1: VIX+signal improves on VIX; |t|>3.0 => Harvey pass"},
        "harvey_pass_cw": bool(cw["t"] > HARVEY_THRESHOLD),
        "verdict": ("CW REJECTS null: signal adds incremental power beyond VIX"
                    if cw["t"] > HARVEY_THRESHOLD else
                    "CW FAILS to reject: no incremental value beyond VIX "
                    "(sufficiency holds under the MORE-POWERFUL nested CW test)"),
    }


def main():
    df = load_panel()
    families = {
        "F1_cross_asset_vol_momentum": "sig_F1_xasset_mom",
        "F8_yield_curve_slope": "sig_F8_yield_slope",
        "F11_calendar_halloween": "sig_F11_halloween",
    }
    results = {
        "experiment_id": "k1116g",
        "title": "Nested Clark-West increment test — remaining STABLE-DATA daily signal "
                 "families (F1 cross-asset vol momentum, F8 yield curve slope, "
                 "F11 calendar anomaly) of the vix-sufficiency paper",
        "predecessors": ["k1116c (weekly F12/F13)", "k1116e (daily F2/F4)"],
        "baseline": "fwd_rv22 ~ 1 + VIX_level (M2, restricted)",
        "augmented": "fwd_rv22 ~ 1 + VIX_level + signal_j (nests baseline)",
        "target": "22-day FORWARD realized vol of SPY (annualized, x100)",
        "horizon_H": H,
        "inference_nw_lag": NW_LAG,
        "is_end": IS_END,
        "oos_start": OOS_START,
        "embargo_days": H,
        "harvey_threshold": HARVEY_THRESHOLD,
        "lag_convention": "features = close-of-day-t info set; target accumulates over "
                          "(t, t+H] strictly after the forecast origin -> no lookahead; "
                          "same IS/OOS rows for both nested models",
        "table3_dm_targets": {"F1": 1.45, "F8": 0.84, "F11": 0.15,
                              "note": "paper Table 3 expanding-window DM |t|; fixed-split "
                                      "DM here is directional cross-check only (cf. k1116e)"},
        "references": ["Clark-West (2007) JoE 138:291-311",
                       "Harvey-Leybourne-Newbold (1997) IJF 13:281-291",
                       "Harvey-Liu-Zhu (2016) RFS 29:5-68",
                       "Diebold-Mariano (1995) JBES 13:253-263"],
        "families_covered": list(families.keys()),
        "families_still_deferred": ["F3_behavioral_pcr", "F9_google_trends", "F10_overnight_vix"],
        "deferred_reason": "F3/F9/F10 require fragile external data (CBOE put-call, "
                           "pytrends, intraday VIX open) — data-provisioning follow-up.",
        "specs": {},
    }
    for fam, col in families.items():
        results["specs"][fam] = evaluate_family(df, col)

    out = HERE / "k1116g_results.json"
    out.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    print(f"\n[written] {out}")


if __name__ == "__main__":
    main()
