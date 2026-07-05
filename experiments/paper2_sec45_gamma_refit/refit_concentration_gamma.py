"""
paper2_sec45_gamma_refit: Reproducible GJR-GARCH gamma for taiwan-vt §sec:tsmc
(TSMC Concentration Robustness, body_v3.tex line 457).

WHY
---
body_v3.tex:457 reports, for the "sub-period concentration analysis":
  - 0050.TW  gamma = 0.124, t = 2.46
  - TSMC     gamma = 0.054, t = 1.07
Neither (gamma, t) pair is byte-traceable to any saved results JSON:
  - 0.124 coincidentally equals K900 amplification.gamma_0050.median_gamma
    = 0.1248 (rolling-252d daily-refit MEDIAN), whose actual HAC t-stat is
    19.857 (NOT 2.46). t = 2.46 has no source.
  - TSMC (0.054, 1.07) not in any JSON; K892 full-sample gives 0.052 / 3.98.
  - The section's own experiment paper2_sec45_tsmc_vt saved VT Sharpe /
    decomposition r^2 but NO gamma estimates.

This script re-estimates GJR-GARCH(1,1) via MLE under the K892 canonical
spec (Normal innovations, Constant mean, arch package robust SE) over the
concentration-relevant windows so the paper can cite a COHERENT, reproducible
(gamma, t) pair for both assets, replacing the untraceable numbers.

SPEC (matches experiments/k892/k892_verify_tw_gamma.py)
------------------------------------------------------
  arch_model(ret_pct, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Constant')
  ret_pct = 100 * simple_return ; 0050.TW cleaned via clean_tw50_data (4:1 split fix)
  t(gamma) = param / robust std-err reported by arch fit.

No look-ahead: pure in-window MLE of a contemporaneous volatility model
(no forecasting / no signal), so no shift() applies. Deterministic (MLE);
rolling median uses a fixed daily step. yfinance download is the only
non-deterministic input (vendor revisions) — n_obs recorded for audit.

Windows
-------
  full_vt   : 2010-01-01 .. 2026-04-17  (K900 rolling-252d sample; the 0.1248 median came from here)
  common_vt : 2020-01-02 .. 2026-04-17  (VT common-eval window per paper2_sec45_tsmc_vt README)

Output: refit_concentration_gamma_results.json
"""
import json
import sys
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model

sys.path.insert(0, "/Users/yhlai0911/volpred-research/src")
from volpred.utils import clean_tw50_data  # noqa: E402

warnings.filterwarnings("ignore")

WINDOWS = {
    "full_vt": ("2010-01-01", "2026-04-17"),
    "common_vt": ("2020-01-02", "2026-04-17"),
}
PAPER_CLAIM = {
    "0050.TW": {"gamma": 0.124, "t": 2.46},
    "2330.TW": {"gamma": 0.054, "t": 1.07},
}


def get_prices(ticker: str) -> pd.Series:
    df = yf.download(ticker, start="2000-01-01", end="2026-04-18", progress=False, auto_adjust=False)
    if df.empty:
        raise ValueError(f"no data for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    prices = df["Close"].dropna()
    if ticker == "0050.TW":
        prices, _ = clean_tw50_data(prices)
    return prices


def fit_gjr(returns: pd.Series) -> dict:
    """K892 canonical GJR-GARCH(1,1) MLE. Returns gamma, t(gamma), n."""
    ret_pct = (returns * 100).dropna()
    am = arch_model(ret_pct, vol="GARCH", p=1, o=1, q=1, dist="normal", mean="Constant")
    res = am.fit(disp="off")
    # arch names the asymmetry term 'gamma[1]'
    gname = next((k for k in res.params.index if k.lower().startswith("gamma")), None)
    if gname is None:
        raise RuntimeError(f"no gamma param in {list(res.params.index)}")
    g = float(res.params[gname])
    se = float(res.std_err[gname])
    t = g / se if se > 0 else float("nan")
    return {"gamma": round(g, 4), "t_gamma": round(t, 4), "std_err": round(se, 5),
            "n_obs": int(ret_pct.shape[0]), "converged": bool(res.convergence_flag == 0)}


def rolling_median_gamma(returns: pd.Series, window: int = 252, step: int = 21) -> dict:
    """Reproduce K900-style rolling-252d gamma: median + HAC t of the series vs 0."""
    ret_pct = (returns * 100).dropna()
    n = ret_pct.shape[0]
    gammas = []
    for end in range(window, n + 1, step):
        seg = ret_pct.iloc[end - window:end]
        try:
            am = arch_model(seg, vol="GARCH", p=1, o=1, q=1, dist="normal", mean="Constant")
            res = am.fit(disp="off")
            gname = next((k for k in res.params.index if k.lower().startswith("gamma")), None)
            if gname is not None:
                gammas.append(float(res.params[gname]))
        except Exception:
            continue
    if not gammas:
        return {"n_windows": 0}
    arr = np.array(gammas)
    # HAC (Newey-West) t of mean vs 0 with lag ~ n^(1/3)
    mean = arr.mean()
    L = int(np.floor(len(arr) ** (1 / 3)))
    dev = arr - mean
    gamma0 = np.mean(dev ** 2)
    lrv = gamma0
    for lag in range(1, L + 1):
        w = 1 - lag / (L + 1)
        cov = np.mean(dev[lag:] * dev[:-lag])
        lrv += 2 * w * cov
    se = np.sqrt(lrv / len(arr))
    hac_t = mean / se if se > 0 else float("nan")
    return {"n_windows": len(arr), "mean_gamma": round(mean, 4),
            "median_gamma": round(float(np.median(arr)), 4),
            "hac_t_of_mean": round(hac_t, 3), "step": step, "window": window}


def main():
    out = {
        "experiment_id": "paper2_sec45_gamma_refit",
        "title": "Reproducible GJR gamma for taiwan-vt sec:tsmc concentration analysis",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "spec": "GJR-GARCH(1,1) Normal Constant-mean MLE (arch), K892 canonical; t=param/robust-SE",
        "paper_claim_body_v3_line457": PAPER_CLAIM,
        "references": ["experiments/k892 (canonical spec)", "experiments/k900 (rolling median 0.1248)"],
        "single_window_fits": {},
        "rolling_252d": {},
    }
    prices = {t: get_prices(t) for t in ("0050.TW", "2330.TW")}
    rets = {t: prices[t].pct_change().dropna() for t in prices}

    for wname, (start, end) in WINDOWS.items():
        out["single_window_fits"][wname] = {"period": [start, end]}
        for t in ("0050.TW", "2330.TW"):
            seg = rets[t].loc[start:end]
            try:
                out["single_window_fits"][wname][t] = fit_gjr(seg)
            except Exception as e:  # noqa: BLE001
                out["single_window_fits"][wname][t] = {"error": str(e)}

    # rolling-252d median over full_vt (to reconcile the 0.124 = K900 median claim)
    for t in ("0050.TW", "2330.TW"):
        seg = rets[t].loc[WINDOWS["full_vt"][0]:WINDOWS["full_vt"][1]]
        try:
            out["rolling_252d"][t] = rolling_median_gamma(seg)
        except Exception as e:  # noqa: BLE001
            out["rolling_252d"][t] = {"error": str(e)}

    path = "experiments/paper2_sec45_gamma_refit/refit_concentration_gamma_results.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("WROTE", path)
    print(json.dumps(out["single_window_fits"], ensure_ascii=False, indent=2))
    print(json.dumps(out["rolling_252d"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
