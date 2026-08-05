"""
K1815 -- Nested Clark-West increment test for vix-sufficiency Family 10
(overnight VIX gap), the F10 item flagged "NOT BLOCKED -- execute now" by
`storage/org/departments/publications/adjudications/vix_sufficiency_f3_f9_f10_20260805.md`.

Context
-------
Predecessors (same harness, vix-sufficiency paper's nested-CW robustness check):
  * k1116c -- weekly alt-data families 12/13 (all |t|<0.6, null robust)
  * k1116e -- daily families 2 (VIX term structure) and 4 (VRP), the
              highest-IS-signal candidates (CW t=1.69 / -0.22, both FAIL Harvey)
  * k1116g -- remaining stable-data daily families 1/8/11 (all |t|<=1.50,
              all FAIL Harvey)

main_v5.tex Table 3 reports the standard DM |t| for every daily family. The
nested Clark-West (2007) is a strictly-more-powerful test of the same null.
k1116e/k1116g answered this for 5 of 8 nested-CW-applicable daily families;
F3/F9/F10 were deferred as "blocked on external data." The 2026-08-05
publications-department adjudication found that framing wrong for two of the
three: F10's definition (main_v5.tex:240, |VIX_open,t - VIX_close,t-1|) needs
only the Open column of the daily ^VIX OHLC series already pinned for every
other family via Yahoo Finance -- not intraday tick data. There is no external
dependency and no provisioning decision. This experiment computes it.

The one real trap (per the adjudication): the existing daily-family VIX pin
used elsewhere in this paper's replication package is LAGGED 1 day to enforce
no-lookahead for those families' close-of-day-t convention. F10 must NOT
inherit that lag -- the whole point of the family is the day-t opening
auction, which is disclosed in the paper as the sole exception to the other
families' timing convention. This script downloads its own unlagged ^VIX OHLC
and is deliberately independent of any pre-existing lagged VIX snapshot used
elsewhere in the replication package.

If |CW t| > 3.0 here, that is a finding requiring the paper's headline null to
be qualified, not a result to be suppressed or pre-framed as "expected
immaterial" (adjudication document, explicit instruction). F10's main-table DM
is the largest of the three deferred families (main_v5.tex Table 4, |t|=1.12)
and its opening-auction origin is genuinely outside the other families' shared
information set, so a CW flip here is a priori more plausible than for F1/F8/F11.

Design (identical machinery to k1116e/k1116g; see those files for the shared
nested-CW derivation)
----------------------------------------------------------------------------
* Target: 22-day FORWARD realized vol of SPY, fwd_rv22[t] = std over (t, t+H].
* Baseline (restricted M2):   fwd_rv ~ 1 + VIX_level          (VIX_level = VIX
  close-of-day-t, matching every other family's baseline exactly)
* Augmented (nests M2):        fwd_rv ~ 1 + VIX_level + sig_F10
* sig_F10[t] = |VIX_Open[t] - VIX_Close[t-1]|, both from the UNLAGGED daily
  ^VIX OHLC series (auto_adjust=False). VIX_Open[t] is known at the day-t
  opening auction, strictly before day t's close (used by the baseline) and
  strictly before the target's realization window (t, t+H], which starts
  accumulating only after day t's close -> no lookahead in either the
  baseline or the augmented model.
* Same IS/OOS rows for both nested models; 22-day embargo on the IS tail.
* Clark-West f_hat = e1^2 - e2^2 + (f1 - f2)^2, one-sided H1: E[f_hat]>0.
  |t|>3.0 = Harvey (2016) conservative pass. HAC nw_lag=21, HLN h=22.
* IS <= 2018-12-31, OOS >= 2019-01-01 (identical split to k1116e/k1116g so
  the CW column is directly comparable across all nested-CW-tested families).

References: Clark-West (2007) JoE 138:291-311; Harvey-Leybourne-Newbold (1997)
IJF 13:281-291; Harvey-Liu-Zhu (2016) RFS 29:5-68; Diebold-Mariano (1995) JBES.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy import stats as st

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
from volpred.research.reproduce_spec import finalize_experiment

START_DATE = "1993-01-01"
END_DATE = "2026-07-01"        # matches k1116e/k1116g exactly -> same n_oos, directly comparable CW column
IS_END = "2018-12-31"
OOS_START = "2019-01-01"
H = 22                          # forward target horizon (trading days)
NW_LAG = H - 1                  # 21: HAC lag for overlapping MA(H-1) forecast errors
HARVEY_THRESHOLD = 3.0
SEED = 1815

DATA_DIR = HERE / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


# -- data --------------------------------------------------------------------
def _load_ohlc_unlagged(ticker: str, cache_name: str) -> pd.DataFrame:
    """Download (or read pinned) daily OHLC for `ticker`, auto_adjust=False,
    UNLAGGED. F10's whole point is the raw day-t open, so this must never be
    shifted -- callers apply whatever lag their own convention requires."""
    cache = DATA_DIR / cache_name
    if cache.exists():
        return pd.read_csv(cache, index_col=0, parse_dates=True)
    raw = yf.download(ticker, start=START_DATE, end=END_DATE, progress=False,
                       auto_adjust=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw.index.name = "Date"
    raw.to_csv(cache)
    return raw


def load_panel() -> pd.DataFrame:
    """SPY + VIX panel with forward-22d RV target and the F10 signal.

    VIX_level (baseline) is VIX close-of-day-t, matching every other daily
    family's convention exactly. sig_F10 uses the day-t OPEN together with the
    day-(t-1) close -- both are known before day t's close, so both the
    baseline and the augmented model condition on strictly less information
    than the target's forward realization window requires.
    """
    spy = _load_ohlc_unlagged("SPY", "spy_ohlc_raw.csv")
    vix = _load_ohlc_unlagged("^VIX", "vix_ohlc_raw_unlagged.csv")

    df = pd.DataFrame(index=spy.index)
    df["SPY"] = spy["Close"]
    df["VIX"] = vix["Close"].reindex(df.index)          # close-of-day-t, same as k1116e/g baseline
    df["VIX_OPEN"] = vix["Open"].reindex(df.index)       # day-t opening print, UNLAGGED
    df = df.dropna(subset=["SPY", "VIX", "VIX_OPEN"])

    log_ret = np.log(df["SPY"] / df["SPY"].shift(1))
    # 22-day FORWARD realized vol target: std of the H returns over (t, t+H].
    df["fwd_rv22"] = log_ret.shift(-1).rolling(H).std().shift(-(H - 1)) * np.sqrt(252) * 100.0

    # -- Family 10: Overnight VIX gap --
    # Paper (main_v5.tex:240): |VIX_open,t - VIX_close,t-1|. Both legs come
    # from the SAME unlagged OHLC series; VIX_close,t-1 is just df["VIX"].shift(1).
    df["sig_F10_overnight_vix"] = (df["VIX_OPEN"] - df["VIX"].shift(1)).abs()

    return df


# -- forward-label fixed split with embargo, same-sample nested estimation ---
# (identical to k1116e/k1116g -- kept verbatim so the CW column is comparable)
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
        "n_oos": len(idx),
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
    started_at = pd.Timestamp.utcnow()
    df = load_panel()

    result = evaluate_family(df, "sig_F10_overnight_vix")

    results = {
        "experiment_id": "K1815",
        "title": "Nested Clark-West increment test -- vix-sufficiency Family 10 "
                 "(overnight VIX gap)",
        "predecessors": ["k1116c (weekly F12/F13)", "k1116e (daily F2/F4)",
                          "k1116g (daily F1/F8/F11)"],
        "adjudication": "storage/org/departments/publications/adjudications/"
                         "vix_sufficiency_f3_f9_f10_20260805.md",
        "baseline": "fwd_rv22 ~ 1 + VIX_level (M2, restricted); VIX_level = "
                    "VIX close-of-day-t, identical to k1116e/k1116g baseline",
        "augmented": "fwd_rv22 ~ 1 + VIX_level + sig_F10_overnight_vix (nests baseline)",
        "signal_definition": "sig_F10_overnight_vix[t] = |VIX_Open[t] - VIX_Close[t-1]|, "
                              "from an UNLAGGED daily ^VIX OHLC series pinned "
                              "independently of the lagged VIX snapshot used by every "
                              "other family in this replication package "
                              "(main_v5.tex:240)",
        "target": "22-day FORWARD realized vol of SPY (annualized, x100)",
        "horizon_H": H,
        "inference_nw_lag": NW_LAG,
        "is_end": IS_END,
        "oos_start": OOS_START,
        "embargo_days": H,
        "harvey_threshold": HARVEY_THRESHOLD,
        "lag_convention": "VIX_level baseline feature = close-of-day-t info set (identical "
                          "to k1116e/k1116g); sig_F10 = day-t OPEN vs day-(t-1) CLOSE, both "
                          "known strictly before day t's close and strictly before the "
                          "target's (t, t+H] realization window -> no lookahead in either "
                          "the baseline or the augmented model",
        "table4_dm_target": {"F10": 1.12,
                             "note": "paper main-table DM |t| (main_v5.tex Table 4); "
                                     "fixed-split DM here is a directional cross-check "
                                     "only (cf. k1116e/k1116g), not an exact reproduction "
                                     "of the expanding-window Table-3/4 DM"},
        "references": ["Clark-West (2007) JoE 138:291-311",
                       "Harvey-Leybourne-Newbold (1997) IJF 13:281-291",
                       "Harvey-Liu-Zhu (2016) RFS 29:5-68",
                       "Diebold-Mariano (1995) JBES 13:253-263"],
        "family_covered": "F10_overnight_vix",
        "spec": result,
        "seed": SEED,
    }

    out_path = HERE / "K1815_results.json"
    outputs = []
    finalize_experiment(
        results=results,
        entrypoint=__file__,
        canonical_result=out_path.name,
        inputs=[DATA_DIR / "spy_ohlc_raw.csv", DATA_DIR / "vix_ohlc_raw_unlagged.csv"],
        outputs=outputs,
        seeds=[("numpy", SEED)],
        started_at=started_at.timestamp(),
    )
    print(json.dumps(results, indent=2, default=str))
    print(f"\n[written] {out_path}")


if __name__ == "__main__":
    main()
