"""
paper2_tsmc_gamma_zeromean_sens
================================
Purpose: Provide a *traceable* mean-specification sensitivity for the TSMC (2330.TW)
GJR-GARCH leverage parameter gamma, for the taiwan-vt paper body_v3 disclosure.

Motivation (research honesty):
  paper/taiwan-vt/review_history/gate_fix_v1/gamma_unification_proposal.md:45 records that
  the legacy "TSMC zero-mean gamma=0.039 / t=0.87" figure is UNTRACEABLE -- "no single spec
  reproduces (0.039, 0.87)". It must NOT be reintroduced into the paper as a spec-sensitivity
  number. Instead we re-estimate the zero-mean spec on the SAME canonical full sample as K892
  (Constant-mean primary) so the disclosure carries real provenance.

Reproduces K892 canonical:
  - Constant-mean GJR-GARCH(1,1), Normal, full sample -> gamma=0.0525, t=3.98 (n=6525)
Adds:
  - Zero-mean GJR-GARCH(1,1), Normal, identical sample/pipeline -> real gamma / t

Data pipeline matches experiments/k892/k892_verify_tw_gamma.py exactly:
  ticker=2330.TW, start=2000-01-01, end=2026-04-05, auto_adjust=True (adjusted close),
  Close pct_change, returns*100.

Key result (2026-07-06): TSMC gamma is SIGNIFICANT under BOTH mean specs on the canonical
sample -- Constant-mean gamma=0.0525/t=3.98, Zero-mean gamma=0.0593/t=4.25. This REFUTES the
legacy claim that a zero-mean spec renders TSMC insignificant (0.039/0.87). The leverage
finding is robust to mean specification.
arch MLE is deterministic (analytic optimizer) -> no random seed needed. Reproducibility is
pinned by fixed download window + arch default robust (Bollerslev-Wooldridge) cov.
"""
import json
import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model

TICKER = "2330.TW"
START = "2000-01-01"
END = "2026-04-05"  # match K892 download window to reproduce canonical n_obs=6525


def download_returns(ticker, start, end):
    # auto_adjust=True reproduces the K892 canonical pipeline EXACTLY
    # (Constant-mean gamma=0.0525, t=3.98, n=6525). Verified 2026-07-06.
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if df is None or len(df) == 0:
        raise ValueError(f"No data for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    prices = df["Close"].dropna()
    returns = prices.pct_change().dropna()
    returns = returns.replace([np.inf, -np.inf], np.nan).dropna()
    return returns


def fit_gjr(returns, mean):
    ret_pct = returns * 100.0
    am = arch_model(ret_pct, vol="GARCH", p=1, o=1, q=1, dist="normal", mean=mean)
    res = am.fit(disp="off", options={"maxiter": 5000})
    return {
        "mean_spec": mean,
        "gamma": float(res.params.get("gamma[1]", np.nan)),
        "gamma_se": float(res.std_err.get("gamma[1]", np.nan)),
        "gamma_t": float(res.tvalues.get("gamma[1]", np.nan)),
        "alpha": float(res.params.get("alpha[1]", np.nan)),
        "beta": float(res.params.get("beta[1]", np.nan)),
        "convergence_flag": int(res.convergence_flag),
        "loglik": float(res.loglikelihood),
        "cov_type": "robust (Bollerslev-Wooldridge)",
    }


def main():
    returns = download_returns(TICKER, START, END)
    n_obs = int(len(returns))
    print(f"TSMC {TICKER}: n_obs={n_obs} ({returns.index[0].date()} .. {returns.index[-1].date()})")

    constant = fit_gjr(returns, "Constant")
    zero = fit_gjr(returns, "Zero")

    print(f"Constant-mean: gamma={constant['gamma']:.4f} t={constant['gamma_t']:.2f}")
    print(f"Zero-mean:     gamma={zero['gamma']:.4f} t={zero['gamma_t']:.2f}")

    result = {
        "experiment_id": "paper2_tsmc_gamma_zeromean_sens",
        "purpose": "Traceable mean-spec sensitivity for TSMC gamma (taiwan-vt body_v3 disclosure); "
                   "replaces untraceable legacy 0.039/0.87 with real zero-mean estimate.",
        "ticker": TICKER,
        "sample_start": str(returns.index[0].date()),
        "sample_end": str(returns.index[-1].date()),
        "n_obs": n_obs,
        "download_window": {"start": START, "end": END},
        "method": "GJR-GARCH(1,1) MLE via arch, Normal innovations, robust (BW) cov; "
                  "returns = Close pct_change * 100",
        "canonical_reference": "experiments/k892 full_sample Constant-mean: gamma=0.0525, t=3.98, n=6525",
        "specs": {"constant_mean": constant, "zero_mean": zero},
        "untraceable_number_note": "Legacy 'zero-mean 0.039 / t=0.87' is UNTRACEABLE per "
                                    "gamma_unification_proposal.md:45; superseded by this real estimate.",
    }
    out = "experiments/paper2_tsmc_gamma_zeromean_sens/paper2_tsmc_gamma_zeromean_sens_results.json"
    with open(out, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
