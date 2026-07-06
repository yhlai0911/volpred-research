"""
K1116c Clark-West extension — nested VIX+signal vs VIX increment test (SEVERE-2 fix).

Motivation (vix-sufficiency v4 review, Codex SEVERE-2):
  The main Diebold-Mariano (DM) horse race reports standard DM statistics. For a
  NULL-result paper, the standard DM on NESTED models (VIX-only nested within
  VIX+signal) is conservative against the larger model: under H0 the extra
  estimated parameters inflate the augmented model's MSFE with pure estimation
  noise, biasing DM toward "signal is harmful / no signal." The reviewer asks us
  to also report the Clark-West (2007) MSPE-adjusted statistic (which removes that
  estimation-noise bias and is MORE powerful at detecting a genuine increment) and
  the Harvey-Leybourne-Newbold (1997) small-sample correction. If the null survives
  the MORE powerful Clark-West test, VIX sufficiency is robust rather than an
  artifact of DM's conservativeness.

Key spec note (discovered during this fix): the main-table Family 12/13 numbers use
  the pure alt-data specs M3 (AR1+EPU, NO VIX) and M4 (AR1+FinStress, NO VIX), which
  are NON-nested vs the VIX baseline -> standard DM is appropriate there and Clark-
  West does NOT apply. The genuinely NESTED, VIX-sufficiency-relevant comparison is
  VIX+signal vs VIX. This script computes Clark-West for those nested weekly
  increments: {VIX+EPU vs VIX, VIX+FinStress vs VIX, VIX+all vs VIX (=M5)}.

Loss: squared realized-volatility forecast error (MSFE), the loss for which Clark-
  West is defined. (The paper's headline QLIKE-DM is retained separately.)

Data / pipeline: reuses k1116c weekly SPY+VIX panel, corrected_shift2 variant
  (shift(1) daily EPU, shift(2) weekly fin-stress). IS 2018-2022, OOS 2023-2026,
  h=1 weekly one-step forecasts. n_OOS ~ 170.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats as st

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import k1116c as base  # noqa: E402  reuse fetch/build/dm_hln


IS_END = "2022-12-31"
OOS_START = "2023-01-01"
VARIANT = "corrected_shift2"  # primary spec in main text

# Nested specs: each augmented model NESTS the vix baseline (AR1+VIX).
BASELINE = "vix"  # AR(1)+VIX  (M2)
NESTED_SPECS = {
    "vix_epu": ["USEPU_signal", "WLEMU_signal"],
    "vix_finstress": ["NFCI_signal", "ANFCI_signal", "STLFSI_signal"],
    "vix_all": ["USEPU_signal", "WLEMU_signal", "NFCI_signal", "ANFCI_signal", "STLFSI_signal"],
}


def build_X(df: pd.DataFrame, extra_signal_cols: list[str]) -> pd.DataFrame:
    """AR(1)+VIX (+ optional nested signals). Matches k1116c.make_X conventions."""
    X = pd.DataFrame(index=df.index)
    X["y_lag1"] = df["rv"].shift(1)
    X["vix_lag1"] = df["vix_mean"].shift(1)
    for col in extra_signal_cols:
        if col in df.columns:
            X[col] = df[col]
    return X


def fit_predict(df: pd.DataFrame, extra_cols: list[str]):
    """Fit OLS on IS, predict OOS. Returns (y_oos, pred_oos) aligned pd.Series."""
    df_is = df.loc[:IS_END].copy()
    df_oos = df.loc[OOS_START:].copy()

    X_is = build_X(df_is, extra_cols)
    y_is = df_is["rv"].loc[X_is.index]
    m = X_is.notna().all(axis=1) & y_is.notna()
    X_is, y_is = X_is[m], y_is[m]
    X_is_sm = sm.add_constant(X_is)
    model = sm.OLS(y_is, X_is_sm).fit()

    X_oos = build_X(df_oos, extra_cols)
    mo = X_oos.notna().all(axis=1)
    X_oos = X_oos[mo]
    X_oos_sm = sm.add_constant(X_oos)[X_is_sm.columns]
    y_oos = df_oos["rv"].loc[X_oos.index]
    pred_oos = model.predict(X_oos_sm)
    valid = y_oos.notna() & pred_oos.notna()
    return y_oos[valid], pred_oos[valid]


def nw_var(x: np.ndarray, lag: int) -> float:
    """Newey-West long-run variance of the mean estimator (per-obs)."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    xd = x - x.mean()
    g0 = np.dot(xd, xd) / n
    var = g0
    for k in range(1, lag + 1):
        w = 1.0 - k / (lag + 1.0)
        gk = np.dot(xd[k:], xd[:-k]) / n
        var += 2.0 * w * gk
    return var


def one_sample_t(series: np.ndarray, h: int = 1, nw_lag: int = 0):
    """One-sample HAC t-test of E[series]=0, one-sided (series>0), with HLN correction.
    For h=1 weekly one-step forecasts nw_lag=0 (no MA structure); HLN factor ~ 1."""
    s = np.asarray(series, dtype=float)
    s = s[~np.isnan(s)]
    n = len(s)
    mbar = s.mean()
    lrv = nw_var(s, nw_lag) if nw_lag > 0 else np.var(s, ddof=1)
    se = np.sqrt(lrv / n)
    hln = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    t = (mbar / se) * hln
    p_two = 2 * (1 - st.t.cdf(abs(t), df=n - 1))
    p_one = 1 - st.t.cdf(t, df=n - 1)  # H1: mean>0 (larger model improves)
    return dict(mean=float(mbar), t=float(t), p_two=float(p_two),
                p_one_greater=float(p_one), n=int(n), hln_factor=float(hln))


def main():
    market = base.fetch_spy_vix_weekly()
    views = base.load_altdata_three_views()
    panel = base.build_variant_panel(market, views["weekly_mean"], views["pit"], VARIANT)

    # baseline forecasts (AR1+VIX)
    yb, pb = fit_predict(panel, [])
    results = {
        "experiment_id": "k1116c_clark_west",
        "title": "Clark-West nested increment test (VIX+signal vs VIX) — weekly alt-data families",
        "variant": VARIANT,
        "loss": "squared realized-vol forecast error (MSFE)",
        "baseline": "AR(1)+VIX (M2)",
        "is_end": IS_END,
        "oos_start": OOS_START,
        "h": 1,
        "references": ["Clark-West (2007) JoE 138:291-311",
                       "Harvey-Leybourne-Newbold (1997) IJF 13:281-291",
                       "Diebold-Mariano (1995) JBES 13:253-263"],
        "harvey_threshold": 3.0,
        "specs": {},
    }

    for name, sig_cols in NESTED_SPECS.items():
        ya, pa = fit_predict(panel, sig_cols)
        # align baseline and augmented on common OOS index
        idx = yb.index.intersection(ya.index)
        y = yb.loc[idx].values
        f1 = pb.loc[idx].values  # baseline forecast (restricted)
        f2 = pa.loc[idx].values  # augmented forecast (larger, nests baseline)
        e1sq = (y - f1) ** 2
        e2sq = (y - f2) ** 2

        # Standard DM on MSFE (d = e1^2 - e2^2; positive -> augmented better)
        dm_t, dm_p, dm_n = base.dm_hln(e1sq, e2sq, h=1)

        # Clark-West adjusted: f_hat = e1^2 - [e2^2 - (f1 - f2)^2]
        adj = (f1 - f2) ** 2
        f_hat = e1sq - e2sq + adj
        cw = one_sample_t(f_hat, h=1, nw_lag=0)

        results["specs"][name] = {
            "signals_added": sig_cols,
            "n_oos": int(len(idx)),
            "mspe_baseline": float(np.mean(e1sq)),
            "mspe_augmented": float(np.mean(e2sq)),
            "mspe_adjustment_mean": float(np.mean(adj)),
            "dm_mspe": {"t": dm_t, "p_two": dm_p, "n": dm_n,
                        "note": "standard DM on squared errors; positive t = augmented beats baseline"},
            "clark_west": {"t": cw["t"], "p_one_greater": cw["p_one_greater"],
                           "p_two": cw["p_two"], "hln_factor": cw["hln_factor"],
                           "mspe_adjusted_mean": cw["mean"],
                           "note": "one-sided H1: VIX+signal improves on VIX; |t|>3.0 = Harvey pass"},
            "harvey_pass_cw": bool(cw["t"] > 3.0),
            "verdict": ("CW REJECTS null (signal adds to VIX)" if cw["t"] > 3.0
                        else "CW FAILS to reject: no incremental value beyond VIX (sufficiency holds under nested CW test)"),
        }

    out = HERE / "k1116c_clark_west_results.json"
    out.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    print(f"\n[written] {out}")


if __name__ == "__main__":
    main()
