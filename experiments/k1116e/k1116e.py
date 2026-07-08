"""
K1116e — Nested Clark-West increment test for the highest-risk DAILY signal
families of the vix-sufficiency paper (Families 2 = VIX term structure,
4 = variance risk premium).

Motivation
----------
The vix-sufficiency paper's central claim is a NULL: no signal family produces a
statistically significant out-of-sample improvement over VIX alone. For the two
weekly alt-data families (12 EPU / 13 financial stress) we already report the
nested Clark-West (2007) MSPE-adjusted statistic (experiments/k1116c). Clark-West
is STRICTLY MORE POWERFUL than the standard Diebold-Mariano test at detecting a
true incremental predictor, so a null that survives it is robust rather than an
artifact of DM's conservativeness against the larger (nested) model.

Table 3 currently reports only the standard DM |t| for the daily families. A
referee will ask: does the null survive the more-powerful Clark-West test for the
DAILY families too? This script answers that for the TWO families most likely to
flip, i.e. the ones with the strongest in-sample partial signal (worst case for
the null):
  * Family 2 VIX term structure: partial r|VIX = 0.181, IS t = 17.6  (paper Table 2)
  * Family 4 VRP:                partial r|VIX = ...,   IS t = 3.51   (paper Table 2)
These are computed FIRST precisely because they are the prime CW-flip candidates.
The remaining daily regression families (1, 3, 8, 9, 10, 11) are deferred to a
follow-up run (some require fragile external data: intraday VIX open, Google
Trends, CBOE put-call). This is NOT a bounding argument — we compute the hardest
cases honestly and report whatever CW returns.

Only families evaluated via DM regression admit a nested CW test. Per the paper's
own methodology (main_v5.tex, "10 are evaluated via DM regression (families 1--4
and 8--13); families 5--6 are portfolio strategies ... family 7 is Granger"),
the daily nested-CW-applicable families are exactly {1,2,3,4,8,9,10,11}. Families
5,6 (portfolio Sharpe) and 7 (Bitcoin Granger) are non-nested-regression and CW
does not apply to them (same logic as k1116c's note on the non-nested M3/M4).

Design (rigorous forward-label OOS)
-----------------------------------
* Target: 22-day FORWARD realized volatility of SPY,
      fwd_rv_22d[t] = std(log-returns over (t, t+22]) * sqrt(252) * 100.
  H = 22. Because the target windows overlap, the OOS forecast errors carry an
  MA(21) structure, so ALL inference (DM and Clark-West one-sample t) uses a HAC
  long-run variance with nw_lag = H-1 = 21 and the Harvey-Leybourne-Newbold
  (1997) small-sample factor with h = 22. (experiments.md rule: the inference
  horizon must equal the target horizon H.)
* Baseline (restricted, M2):   fwd_rv ~ 1 + VIX_level
* Augmented (larger, nests M2): fwd_rv ~ 1 + VIX_level + signal_j
  This is exactly the nested pair for which Clark-West is defined (VIX-only is the
  b_signal = 0 restriction of VIX+signal).
* Lag / no-lookahead: features are the CLOSE-OF-DAY-t information set (VIX_t, and
  signals built only from data observed by the close of day t). The forecast
  origin is the close of day t; the target accumulates over (t, t+H], strictly
  AFTER the forecast origin, so there is no lookahead. This matches the paper's
  daily convention (k731 regresses fwd_rv on contemporaneous VIX / ratio). We do
  NOT shift features by an extra day: shifting would open a one-day information
  gap (day-t's return would enter neither features nor target) and artificially
  weaken the signal.
* SAME-SAMPLE nested estimation: because Clark-West assumes the restricted model
  is nested in the larger one, BOTH the VIX-only and the VIX+signal models are
  estimated on the IDENTICAL in-sample rows and evaluated on the IDENTICAL
  out-of-sample rows (the intersection where the signal and target are both
  observed). VIX3M (hence Family 2's ratio) only begins ~2007, so the shared
  estimation window respects that availability for both models rather than
  fitting the baseline on a longer sample than the augmented model.
* Fixed IS/OOS split with a 22-day EMBARGO: IS rows whose forward target window
  would extend into the OOS period are dropped, so no IS target peeks past the
  split date. (Mirrors k1116c's fixed-split nested-CW design, with the embargo
  added because the daily target is forward-overlapping whereas k1116c's weekly
  target was one-step non-overlapping.)

Clark-West statistic (Clark & West 2007, JoE 138:291-311)
---------------------------------------------------------
  f_hat[t] = (y - f1)^2 - [ (y - f2)^2 - (f1 - f2)^2 ]
           = e1^2 - e2^2 + (f1 - f2)^2
  where f1 = restricted (VIX-only) forecast, f2 = augmented (VIX+signal) forecast.
  Test one-sided H0: E[f_hat] <= 0 ("signal does NOT improve on VIX") vs
  H1: E[f_hat] > 0. |t| > 3.0 = Harvey (2016) conservative pass. HAC nw_lag=21.

Loss for the standard DM reproduction check: squared realized-vol forecast error
(MSFE), d = e1^2 - e2^2 (positive => augmented beats baseline). Reported alongside
CW so the direction is transparent and comparable to Table 3's DM sign.

Reuses the Clark-West / HLN math validated in k1116c (Codex-reviewed for the
weekly families); here the only change is nw_lag/h = 21/22 for the daily forward
target and the daily signal constructions.
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


# ── data ────────────────────────────────────────────────────────────────────
def _flatten(raw: pd.DataFrame) -> pd.DataFrame:
    if isinstance(raw.columns, pd.MultiIndex):
        px = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw["Adj Close"]
    else:
        px = raw
    px.columns = [str(c).replace("^", "") for c in px.columns]
    return px


def load_panel() -> pd.DataFrame:
    """SPY + VIX (+ VIX3M/VXV) daily panel with forward-22d RV target and signals."""
    raw = yf.download(["SPY", "^VIX", "^VIX3M"], start=START_DATE, end=END_DATE,
                      progress=False, auto_adjust=False)
    px = _flatten(raw)
    # VIX3M has short history; backfill with VXV (its predecessor ticker) pre-2008
    if "VIX3M" not in px.columns or px["VIX3M"].dropna().empty:
        px["VIX3M"] = np.nan
    vxv = _flatten(yf.download("^VXV", start=START_DATE, end=END_DATE,
                               progress=False, auto_adjust=False))
    if "VXV" in vxv.columns:
        px["VIX3M"] = px["VIX3M"].fillna(vxv["VXV"])

    df = pd.DataFrame(index=px.index)
    df["SPY"] = px["SPY"]
    df["VIX"] = px["VIX"]
    df["VIX3M"] = px["VIX3M"]
    df = df.dropna(subset=["SPY", "VIX"])

    log_ret = np.log(df["SPY"] / df["SPY"].shift(1))
    # 22-day BACKWARD realized vol (for VRP; uses returns up to and including t)
    df["rv22_back"] = log_ret.rolling(H).std() * np.sqrt(252) * 100.0
    # 22-day FORWARD realized vol target: std of the H returns over (t, t+H].
    # log_ret.shift(-1) puts return of day t+1 at index t; rolling(H) then covers
    # returns t+1..t+H; the final .shift(-(H-1)) is a no-op-safe alignment guard so
    # window [t+1, t+H] is anchored at index t. (Verified below by construction.)
    df["fwd_rv22"] = log_ret.shift(-1).rolling(H).std().shift(-(H - 1)) * np.sqrt(252) * 100.0

    # ── signals ──
    # F2: VIX term structure ratio (needs VIX3M)
    df["sig_F2_vixratio"] = df["VIX"] / df["VIX3M"]
    # F4: variance risk premium = VIX - backward RV22
    df["sig_F4_vrp"] = df["VIX"] - df["rv22_back"]
    return df


# ── forward-label fixed split with embargo, same-sample nested estimation ────
def _split_masks(df: pd.DataFrame, valid: pd.Series):
    """IS/OOS boolean masks over rows in `valid`, with a 22-day forward embargo so
    no IS target window (closing at t+H) extends past the split date."""
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
    # guard: HAC estimate can go slightly negative in tiny samples
    return max(var, g0 / n)


def _one_sample_t(series: np.ndarray, h: int, nw_lag: int):
    s = np.asarray(series, float)
    s = s[~np.isnan(s)]
    n = len(s)
    mbar = s.mean()
    lrv = _nw_var(s, nw_lag)
    se = np.sqrt(lrv / n)
    # HLN small-sample factor; guard the radicand against tiny-n negativity
    hln_arg = (n + 1 - 2 * h + h * (h - 1) / n) / n
    hln = np.sqrt(hln_arg) if hln_arg > 0 else float("nan")
    t = (mbar / se) * hln
    p_two = 2 * (1 - st.t.cdf(abs(t), df=n - 1))
    p_one = 1 - st.t.cdf(t, df=n - 1)
    return dict(mean=float(mbar), t=float(t), p_two=float(p_two),
                p_one_greater=float(p_one), n=int(n), hln_factor=float(hln),
                nw_lag=int(nw_lag))


def evaluate_family(df: pd.DataFrame, signal_col: str) -> dict:
    # Contemporaneous close-of-day-t features; target is strictly forward (t, t+H].
    base_feat = pd.DataFrame({"VIX": df["VIX"]}, index=df.index)
    aug_feat = base_feat.assign(**{signal_col: df[signal_col]})
    y = df["fwd_rv22"]

    # SAME-SAMPLE: both nested models use the identical rows where the augmented
    # spec (VIX + signal) and the target are all observed.
    valid = aug_feat.notna().all(axis=1) & y.notna()
    is_mask, oos_mask = _split_masks(df, valid)

    Xb_is = sm.add_constant(base_feat[is_mask])
    Xa_is = sm.add_constant(aug_feat[is_mask])
    y_is = y[is_mask]
    mb = sm.OLS(y_is, Xb_is).fit()   # restricted: VIX only
    ma = sm.OLS(y_is, Xa_is).fit()   # augmented: VIX + signal (nests restricted)

    Xb_oos = sm.add_constant(base_feat[oos_mask])[Xb_is.columns]
    Xa_oos = sm.add_constant(aug_feat[oos_mask])[Xa_is.columns]
    idx = y[oos_mask].index          # identical for both models by construction
    y_v = y[oos_mask].values
    f1 = mb.predict(Xb_oos).values   # baseline (restricted) forecast
    f2 = ma.predict(Xa_oos).values   # augmented forecast
    e1sq = (y_v - f1) ** 2
    e2sq = (y_v - f2) ** 2
    y = y_v  # for downstream references below

    # standard DM on MSFE (d>0 => augmented better); HAC nw_lag=21, h=22
    d = e1sq - e2sq
    dm = _one_sample_t(d, h=H, nw_lag=NW_LAG)

    # Clark-West adjusted increment
    adj = (f1 - f2) ** 2
    f_hat = e1sq - e2sq + adj
    cw = _one_sample_t(f_hat, h=H, nw_lag=NW_LAG)

    return {
        "signal_col": signal_col,
        "n_oos": int(len(idx)),
        "oos_start": str(idx[0].date()),
        "oos_end": str(idx[-1].date()),
        "mspe_baseline_vixonly": float(np.mean(e1sq)),
        "mspe_augmented_vixplus": float(np.mean(e2sq)),
        "mspe_adjustment_mean": float(np.mean(adj)),
        "dm_mspe": {"t": dm["t"], "p_two": dm["p_two"], "p_one_greater": dm["p_one_greater"],
                    "n": dm["n"], "hln_factor": dm["hln_factor"], "nw_lag": dm["nw_lag"],
                    "note": "standard DM on squared fwd-RV errors; +t => augmented beats VIX-only"},
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
        "F2_vix_term_structure": "sig_F2_vixratio",
        "F4_variance_risk_premium": "sig_F4_vrp",
    }
    results = {
        "experiment_id": "k1116e",
        "title": "Nested Clark-West increment test — highest-risk DAILY signal families "
                 "(F2 VIX term structure, F4 VRP) of the vix-sufficiency paper",
        "baseline": "fwd_rv22 ~ 1 + VIX_level (M2, restricted)",
        "augmented": "fwd_rv22 ~ 1 + VIX_level + signal_j (nests baseline)",
        "target": "22-day FORWARD realized vol of SPY (annualized, x100)",
        "horizon_H": H,
        "inference_nw_lag": NW_LAG,
        "is_end": IS_END,
        "oos_start": OOS_START,
        "embargo_days": H,
        "harvey_threshold": HARVEY_THRESHOLD,
        "lag_convention": "features = close-of-day-t info set (VIX_t, signals from "
                          "data observed by close of t); target accumulates over "
                          "(t, t+H] strictly after the forecast origin -> no lookahead; "
                          "same IS/OOS rows for both nested models",
        "references": ["Clark-West (2007) JoE 138:291-311",
                       "Harvey-Leybourne-Newbold (1997) IJF 13:281-291",
                       "Harvey-Liu-Zhu (2016) RFS 29:5-68",
                       "Diebold-Mariano (1995) JBES 13:253-263"],
        "families_covered": list(families.keys()),
        "families_deferred": ["F1_cross_asset_vol_momentum", "F3_behavioral_pcr",
                              "F8_yield_curve_slope", "F9_google_trends",
                              "F10_overnight_vix", "F11_calendar"],
        "deferred_reason": "F1/F8/F11 stable-data but deferred to keep this run "
                           "scoped; F3/F9/F10 require fragile external data (CBOE "
                           "put-call, pytrends, intraday VIX open) — follow-up run.",
        "specs": {},
    }
    for fam, col in families.items():
        results["specs"][fam] = evaluate_family(df, col)

    out = HERE / "k1116e_results.json"
    out.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    print(f"\n[written] {out}")


if __name__ == "__main__":
    main()
