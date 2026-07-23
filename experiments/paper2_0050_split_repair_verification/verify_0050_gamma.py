"""Verify the 0050.TW Table 1 row (gamma = 0.097, t = 3.60) against the repaired snapshot.

Context
-------
Task paper_0050_snapshot_repoint_20260719. The pinned snapshot
paper/taiwan-vt/data/0050_tw_twii_..._2008-2026.csv carried a x4 level break at
2014-01-02 (repaired 2026-07-19 by scripts/repoint_snapshot_from_db.py). The
paper's Data section claimed the break was handled by "computing returns from
Adj Close", which cannot be true because adj_close jumped with everything else.

This script settles two questions with numbers rather than argument:

  Q1. Does "returns from Adj Close" alone neutralise the break?  (claimed fix)
  Q2. Does "exclude the split date" neutralise it?               (actual fix)

and then reports the full-sample GJR-GARCH gamma on the repaired series, which
is what Table 1 should cite.

Variants (all GJR-GARCH(1,1), Constant mean, Normal, returns x100, BW-robust t,
matching k892's estimator so the numbers are comparable to the cited source):

  repaired            repaired snapshot, every day kept
  repaired_ex_split   repaired snapshot, split date return dropped
  broken              pre-break rows restored to their contaminated x4 level
  broken_ex_split     contaminated, split date return dropped  <- paper's procedure

Run:
  uv run python experiments/paper2_0050_split_repair_verification/verify_0050_gamma.py
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from arch import arch_model

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SNAPSHOT = os.path.join(
    REPO, "paper", "taiwan-vt", "data",
    "0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv",
)
CUT = pd.Timestamp("2014-01-02")
BREAK_FACTOR = 4.0


def load_adj_close() -> pd.Series:
    df = pd.read_csv(SNAPSHOT, parse_dates=["date"]).set_index("date")
    s = df["0050_tw_adj_close"].dropna()
    # the snapshot carries 10 duplicated date rows (2026-05..; see paper2 results
    # JSON known_data_defects) — differencing them would inject fake zero returns
    return s[~s.index.duplicated(keep="first")].sort_index()


def log_returns(prices: pd.Series) -> pd.Series:
    return (np.log(prices / prices.shift(1)) * 100).dropna()


def fit_gjr(returns: pd.Series) -> dict:
    am = arch_model(returns, vol="GARCH", p=1, o=1, q=1, dist="normal", mean="Constant")
    res = am.fit(disp="off", options={"maxiter": 5000})
    return {
        "gamma": float(res.params["gamma[1]"]),
        "gamma_t": float(res.tvalues["gamma[1]"]),
        "alpha": float(res.params["alpha[1]"]),
        "beta": float(res.params["beta[1]"]),
        "persistence": float(res.params["alpha[1]"] + 0.5 * res.params["gamma[1]"] + res.params["beta[1]"]),
        "n_obs": int(res.nobs),
        "convergence": int(res.convergence_flag),
        "log_likelihood": float(res.loglikelihood),
    }


def main() -> None:
    repaired = load_adj_close()

    broken = repaired.copy()
    broken.loc[broken.index < CUT] *= BREAK_FACTOR

    variants = {}
    for name, prices in (("repaired", repaired), ("broken", broken)):
        r = log_returns(prices)
        variants[name] = fit_gjr(r) | {"split_date_return_pct": float(r.loc[CUT])}
        r_ex = r.drop(index=CUT)
        variants[f"{name}_ex_split"] = fit_gjr(r_ex)

    paper_claim = {"gamma": 0.097, "gamma_t": 3.60,
                   "source": "body_v3.tex:53 (cites experiments/k892 full_sample)"}

    out = {
        "experiment_id": "paper2_0050_split_repair_verification",
        "purpose": "Settle whether Adj Close alone (claimed) or excluding the split date "
                   "(actual) neutralises the 0050.TW 2014-01-02 level break, and report "
                   "the full-sample GJR gamma on the repaired snapshot.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {"snapshot": os.path.relpath(SNAPSHOT, REPO),
                 "first": str(repaired.index[0].date()), "last": str(repaired.index[-1].date()),
                 "n_prices": int(len(repaired)), "break_factor_removed": BREAK_FACTOR},
        "method": "GJR-GARCH(1,1) MLE (arch), Constant mean, Normal innovations, "
                  "log returns x100, BW-robust t-values; matches k892's estimator.",
        "paper_claim": paper_claim,
        "variants": variants,
        "findings": {
            "adj_close_alone_fixes_break": abs(variants["broken"]["split_date_return_pct"]) < 5,
            "gamma_shift_from_repair": variants["repaired"]["gamma"] - variants["broken"]["gamma"],
            "gamma_shift_from_excluding_split": variants["broken_ex_split"]["gamma"] - variants["broken"]["gamma"],
        },
    }
    path = os.path.join(HERE, "verify_0050_gamma_results.json")
    with open(path, "w") as fh:
        json.dump(out, fh, indent=2)

    print(f"snapshot {out['data']['first']}..{out['data']['last']}  n={out['data']['n_prices']}")
    print(f"paper claims gamma={paper_claim['gamma']}  t={paper_claim['gamma_t']}\n")
    for name, v in variants.items():
        split_r = v.get("split_date_return_pct")
        extra = f"  split-date return = {split_r:+.2f}%" if split_r is not None else ""
        print(f"  {name:20s} gamma={v['gamma']:.4f}  t={v['gamma_t']:.2f}  "
              f"n={v['n_obs']}  persist={v['persistence']:.4f}{extra}")
    print(f"\nwrote {os.path.relpath(path, REPO)}")


if __name__ == "__main__":
    main()
