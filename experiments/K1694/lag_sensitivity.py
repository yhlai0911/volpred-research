"""K1694 — FCM publication-lag sensitivity.

The main script hard-codes ``FCM_LAG_DAYS = 45`` and derives
``avail_date = month_end + 45d`` as a stand-in for the real CFTC publication
date, which was never checked against actual release dates. Lookahead only
appears if the *assumed* lag is shorter than the *actual* one, so the honest
check is whether the primary interaction survives longer assumed lags.

Re-estimates spec1 (FCM HHI x high-vol interaction) for a grid of assumed
lags. Bootstrap is skipped here: Driscoll-Kraay and month-clustered t-stats
are enough to see whether the verdict moves.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import K1694

HERE = Path(__file__).resolve().parent
GRID = [30, 45, 60, 75, 90]


def main() -> None:
    fcm = K1694.build_fcm()
    dcot = K1694.build_dcot()
    rv = K1694.build_vol()

    rows = []
    for lag in GRID:
        f = fcm.copy()
        f["avail_date"] = f["month_end"] + pd.Timedelta(days=lag)
        panel = K1694.build_panel(f, dcot, rv)
        res = K1694.panel_regression(panel)
        s1 = res["spec1_fcm_highvol"]
        rows.append({
            "assumed_lag_days": lag,
            "n_obs": s1["n_obs"],
            "n_months": s1["n_months"],
            "coef_fcm_x_highvol": s1["driscoll_kraay"]["coef"]["fcm_x_highvol"],
            "t_driscoll_kraay": s1["driscoll_kraay"]["tstat"]["fcm_x_highvol"],
            "p_driscoll_kraay": s1["driscoll_kraay"]["pval"]["fcm_x_highvol"],
            "t_cluster_month": s1["cluster_by_month"]["tstat"]["fcm_x_highvol"],
            "rsq_within": s1["rsq_within"],
        })
        print(f"lag={lag:>3}d  n={s1['n_obs']:>5}  coef={rows[-1]['coef_fcm_x_highvol']:.3e}  "
              f"t_DK={rows[-1]['t_driscoll_kraay']:.2f}  t_cl={rows[-1]['t_cluster_month']:.2f}")

    sig = [r for r in rows if abs(r["t_driscoll_kraay"]) > 1.96]
    out = {
        "experiment_id": "K1694",
        "check": "fcm_publication_lag_sensitivity",
        "baseline_lag_days": K1694.FCM_LAG_DAYS,
        "grid": rows,
        "any_lag_significant_at_5pct": bool(sig),
        "conclusion": (
            "NULL verdict is invariant to the assumed FCM publication lag across "
            f"{GRID[0]}-{GRID[-1]} days; no grid point reaches |t|>1.96."
            if not sig else
            "Verdict depends on the assumed publication lag — the real CFTC "
            "release dates must be resolved before any claim is made."
        ),
    }
    (HERE / "K1694_lag_sensitivity.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print("\n" + out["conclusion"])
    print("-> K1694_lag_sensitivity.json")


if __name__ == "__main__":
    main()
