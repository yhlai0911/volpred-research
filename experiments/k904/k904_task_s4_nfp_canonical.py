#!/usr/bin/env python3
"""
K904 task_s4_nfp — re-run on the OFFICIAL BLS release calendar
==============================================================
Companion to `k904_paper8_shock_nfp_fix.py` (archived — DO NOT EDIT).

SCOPE — DELIBERATELY NARROW
---------------------------
Re-estimates ONLY `task_s4_nfp` (archived Parts E and F: overall NFP ratio,
vs-Friday ratio, and the by-VIX-regime breakdown).

`task_s2_shock_types` is NOT re-run and NOT touched. It classifies days by
|ΔVIX| > 2 and never reads an NFP date, so the proxy defect cannot reach it.
Re-running it would only inject snapshot noise into a clean result.

WHY
---
The archived k904 used the same first-Friday proxy as k741
(`days_until_friday = (4 - d.weekday()) % 7`). Against the official calendar
that proxy is wrong for 33 of 194 months in the k741 window and invents one
event month (2025-10, cancelled during the shutdown). k904 is the corroborating
reproduction cited alongside k741, so it has to be re-checked on the same
footing.

DESIGN
------
Same two-arm design as `experiments/k741/k741_nfp_event_study_canonical.py`:
both arms run on ONE pinned price snapshot, so canonical-minus-proxy is a pure
date-source effect rather than a mix of date change and yfinance drift. The
archived k904 used a live 2026-04 yfinance pull; that difference is reported
rather than silently absorbed.

Methodology held 1:1 with archived k904 (which differs from k741 on purpose):
Welch's t-test (`equal_var=False`), baseline = ALL non-NFP days, window
2010-01-01..2026-04-05, VIX regime cuts 15/20/25 on VIX_prev.

The one deliberate change is the release-date -> trading-day mapping. Archived
k904 takes the CLOSEST trading day within +/-3 days; for a release on a market
holiday that resolves BACKWARD to the prior trading day — a lookahead. The
canonical arm maps forward only. Recorded in `methodology_deltas`.

Author: VolPred Research System
[提出: 主線程 task assign_1238781f, 執行: Claude worktree agent]
"""

import json
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from scipy import stats

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from volpred.data.event_dates import nfp_release_dates  # noqa: E402

warnings.filterwarnings("ignore")

PINNED_CSV = REPO / "paper" / "volatility-absorption" / "data" / "spy_gld_tlt_qqq_eem_vix_2005-2026.csv"
OUT = Path(__file__).resolve().parent / "k904_task_s4_nfp_canonical_results.json"

WIN_START, WIN_END = "2010-01-01", "2026-04-05"
EVENT_CUTOFF = pd.Timestamp("2026-04-05")

REGIMES = [(0, 15, "Low (V<15)"), (15, 20, "Medium (15<=V<20)"),
           (20, 25, "Elevated (20<=V<25)"), (25, 999, "High (V>=25)")]


def proxy_nfp_dates():
    """VERBATIM from archived k904: first Friday of each month."""
    out = []
    for year in range(2010, 2027):
        for month in range(1, 13):
            d = datetime(year, month, 1)
            ff = d + timedelta(days=(4 - d.weekday()) % 7)
            if ff <= EVENT_CUTOFF.to_pydatetime():
                out.append(pd.Timestamp(ff))
    return pd.DatetimeIndex(out)


def canonical_nfp_dates():
    d = nfp_release_dates("2010-01-01", "2026-04-06", use_cache=False)
    return pd.DatetimeIndex([x for x in d if x <= EVENT_CUTOFF])


def map_archived(dates, trading_days):
    """Archived k904 mapping: closest trading day within +/-3d (can look backward)."""
    out = []
    for nd in dates:
        diffs = abs(trading_days - nd)
        closest = trading_days[diffs.argmin()]
        if abs((closest - nd).days) <= 3:
            out.append(closest)
    return pd.DatetimeIndex(sorted(set(out)))


def map_next_trading_day(dates, trading_days):
    out = []
    for nd in dates:
        if nd in trading_days:
            out.append(nd)
        else:
            fwd = trading_days[trading_days >= nd]
            if len(fwd) > 0 and (fwd[0] - nd).days <= 4:
                out.append(fwd[0])
    return pd.DatetimeIndex(sorted(set(out)))


def estimate(df, nfp_days):
    d = df.copy()
    d["is_NFP"] = d.index.isin(nfp_days)
    d["is_Friday"] = d.index.dayofweek == 4

    nfp = d[d["is_NFP"]]["SPY_AbsReturn"]
    non = d[~d["is_NFP"]]["SPY_AbsReturn"]
    t_o, p_o = stats.ttest_ind(nfp, non, equal_var=False)          # Welch, as archived
    fri = d[(d["is_Friday"]) & (~d["is_NFP"])]["SPY_AbsReturn"]
    t_f, p_f = stats.ttest_ind(nfp, fri, equal_var=False)

    regimes = {}
    for lo, hi, label in REGIMES:
        m = (d["VIX_prev"] >= lo) & (d["VIX_prev"] < hi)
        rn = d[m & d["is_NFP"]]["SPY_AbsReturn"]
        ro = d[m & ~d["is_NFP"]]["SPY_AbsReturn"]
        rec = {"n_nfp": int(len(rn)), "n_non_nfp": int(len(ro))}
        if len(rn) > 0 and len(ro) > 0:
            t, p = stats.ttest_ind(rn, ro, equal_var=False)
            rec.update({
                "mean_abs_return_nfp_pct": float(rn.mean() * 100),
                "mean_abs_return_non_nfp_pct": float(ro.mean() * 100),
                "ratio": float(rn.mean() / ro.mean()),
                "t_stat": float(t),
                "p_value": float(p),
            })
        regimes[label] = rec

    return {
        "overall": {
            "n_nfp": int(len(nfp)),
            "n_non_nfp": int(len(non)),
            "mean_abs_return_nfp_pct": float(nfp.mean() * 100),
            "mean_abs_return_non_nfp_pct": float(non.mean() * 100),
            "ratio": float(nfp.mean() / non.mean()),
            "t_stat": float(t_o),
            "p_value": float(p_o),
        },
        "vs_friday": {
            "n_friday_non_nfp": int(len(fri)),
            "mean_abs_return_friday_non_nfp_pct": float(fri.mean() * 100),
            "ratio_vs_friday": float(nfp.mean() / fri.mean()),
            "t_stat": float(t_f),
            "p_value": float(p_f),
        },
        "by_vix_regime": regimes,
    }


def main():
    print("=" * 72)
    print("K904 task_s4_nfp — official BLS release calendar re-run")
    print("=" * 72)

    raw = pd.read_csv(PINNED_CSV, parse_dates=["date"]).set_index("date")
    full = pd.DataFrame(index=raw.index)
    full["SPY_Return"] = raw["spy_adj_close"].pct_change()
    full["SPY_AbsReturn"] = full["SPY_Return"].abs()
    full["VIX"] = raw["vix_close"]
    full["VIX_prev"] = full["VIX"].shift(1)
    full = full.dropna(subset=["SPY_Return", "VIX", "VIX_prev"])
    df = full.loc[WIN_START:WIN_END]
    td = df.index
    print(f"\nPinned snapshot window: {len(df)} trading days, {td[0].date()} .. {td[-1].date()}")

    px, can = proxy_nfp_dates(), canonical_nfp_dates()
    px_td, can_td = map_archived(px, td), map_next_trading_day(can, td)
    print(f"Proxy     : {len(px)} raw -> {len(px_td)} trading days")
    print(f"Canonical : {len(can)} raw -> {len(can_td)} trading days")

    px_m = {(d.year, d.month): d for d in px}
    can_m = {(d.year, d.month): d for d in can}
    shifted = [{"month": f"{k[0]}-{k[1]:02d}", "proxy": str(px_m[k].date()),
                "canonical": str(can_m[k].date()),
                "shift_days": int((can_m[k] - px_m[k]).days)}
               for k in sorted(set(px_m) & set(can_m)) if px_m[k] != can_m[k]]
    phantom = [{"month": f"{k[0]}-{k[1]:02d}", "proxy_date": str(px_m[k].date())}
               for k in sorted(set(px_m) - set(can_m))]
    print(f"Date diff: {len(shifted)} shifted, {len(phantom)} phantom, "
          f"{len(set(px) & set(can))} exact matches")

    arms = {name: estimate(df, days) for name, days in (("proxy", px_td), ("canonical", can_td))}
    for name, r in arms.items():
        o = r["overall"]
        print(f"\n--- arm: {name} ---")
        print(f"  overall  N={o['n_nfp']}  ratio={o['ratio']:.4f}x  t={o['t_stat']:.3f}  p={o['p_value']:.4f}")
        v = r["vs_friday"]
        print(f"  vs Friday          ratio={v['ratio_vs_friday']:.4f}x  t={v['t_stat']:.3f}  p={v['p_value']:.4f}")
        for label, rec in r["by_vix_regime"].items():
            if "ratio" in rec:
                print(f"  {label:<20} n={rec['n_nfp']:>3}  ratio={rec['ratio']:.3f}x  "
                      f"t={rec['t_stat']:.2f}  p={rec['p_value']:.4f}")

    payload = {
        "experiment_id": "k904-task_s4_nfp-canonical",
        "parent_experiment": "k904",
        "description": "task_s4_nfp re-estimated on official BLS release dates",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "proposer": "主線程 (task assign_1238781f)",
        "executor": "Claude worktree agent",
        "scope_note": ("Only task_s4_nfp is re-run. task_s2_shock_types is untouched: it keys on "
                       "|dVIX| > 2 and never reads an NFP date, so the proxy defect cannot reach it."),
        "methodology": {
            "nfp_identification": "Official BLS Employment Situation release dates (FRED release id 50)",
            "sample_period": f"{WIN_START} to {WIN_END}",
            "comparison_baseline": "ALL non-NFP days",
            "test": "Welch's t-test (unequal variance) — as archived k904",
            "vix_regimes": "<15, 15-20, 20-25, >=25 on VIX_prev",
            "price_source": str(PINNED_CSV.relative_to(REPO)),
        },
        **arms["canonical"],
        "proxy_arm_same_data": arms["proxy"],
        "provenance": {
            "date_source": "FRED/ALFRED release id 50 via volpred.data.event_dates.nfp_release_dates",
            "n_proxy_dates": int(len(px)),
            "n_canonical_dates": int(len(can)),
            "n_exact_date_matches": int(len(set(px) & set(can))),
            "months_shifted": shifted,
            "phantom_months_in_proxy": phantom,
            "price_snapshot_note": ("Archived k904 used a live 2026-04 yfinance pull; this re-run uses "
                                    "the paper's pinned snapshot so both arms share identical prices. "
                                    "Compare canonical vs proxy_arm_same_data for the date effect; "
                                    "compare proxy_arm_same_data vs the archived JSON for snapshot drift."),
        },
        "methodology_deltas": [
            {
                "item": "release-date -> trading-day mapping",
                "archived": "closest trading day within +/-3 days (resolves backward on holidays)",
                "canonical_arm": "release date if it trades, else next trading day",
                "why": ("Backward resolution returns the trading day BEFORE the release for releases on "
                        "market holidays (5 Good Fridays in range) — a lookahead. Forward-only mapping "
                        "is required by .claude/rules/experiments.md."),
            },
        ],
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nWrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
