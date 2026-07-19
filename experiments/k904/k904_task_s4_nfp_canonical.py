#!/usr/bin/env python3
"""
K904 task_s4_nfp — official BLS calendar, 2x2 factorial
========================================================
Companion to `k904_paper8_shock_nfp_fix.py` (archived — DO NOT EDIT).

SCOPE — DELIBERATELY NARROW
---------------------------
Re-estimates ONLY `task_s4_nfp` (archived Parts E and F: overall NFP ratio,
vs-Friday ratio, by-VIX-regime breakdown).

`task_s2_shock_types` is NOT re-run and NOT touched. It classifies days by
|dVIX| > 2 and never reads an NFP date, so the proxy defect cannot reach it.
Re-running it would only inject snapshot noise into a clean result.

WHY, AND WHY 2x2
----------------
Archived k904 used the same first-Friday proxy as k741. Correcting it changes
TWO things at once — the date source AND the release->trading-day mapping — and
an earlier revision of this script reported their combined effect as if it were
the calendar's alone (Codex review 2026-07-19, verdict FAIL). The mapping is not
cosmetic: archived k904 takes the CLOSEST trading day within +/-3 days, which
resolves BACKWARD to the day before the release when a release lands on a market
holiday. That is a lookahead, and on this data it moves the result more than the
calendar does.

So: full 2x2 over {proxy, official} x {archived_mapper, forward_mapper}.
`date_effect` is only ever quoted at a FIXED mapper.
HEADLINE = official dates + forward-only mapping.

ENDPOINT (third Codex finding)
------------------------------
The last official release in range, 2026-04-03, is Good Friday: BLS published,
US equity markets were shut, and the reaction falls on Monday 2026-04-06.
Archived k904 sliced prices at 2026-04-05, so an earlier revision of this script
SILENTLY dropped that event from the official arm (195 dates -> 194 mapped)
while the proxy arm still backward-mapped it onto 2026-04-02 — an endpoint
asymmetry on top of the mapper asymmetry. The price window is therefore extended
to 2026-04-06 so the reaction day is observable and both arms carry the same 195
releases. Mapping is asserted (no backward map in forward cells, no collisions)
and any excluded release is recorded with a reason rather than vanishing.

Methodology otherwise 1:1 with archived k904, which differs from k741 on
purpose: Welch's t-test (`equal_var=False`), baseline = ALL non-NFP days, VIX
regime cuts 15/20/25 on VIX_prev, estimation from 2010-01-01 (archived k904
already sliced correctly here — unlike k741, it has no warm-up leak).

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

WIN_START = "2010-01-01"
WIN_END = "2026-04-06"                      # extended so the 2026-04-03 reaction day is observable
EVENT_CUTOFF = pd.Timestamp("2026-04-03")

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


def official_nfp_dates():
    d = nfp_release_dates("2010-01-01", "2026-04-06", use_cache=False)
    return pd.DatetimeIndex([x for x in d if x <= EVENT_CUTOFF])


def map_archived(dates, trading_days):
    """Archived k904 rule: closest trading day within +/-3d. RETAINS the lookahead."""
    mapped, excluded = {}, []
    for nd in dates:
        closest = trading_days[abs(trading_days - nd).argmin()]
        if abs((closest - nd).days) <= 3:
            mapped[nd] = closest
        else:
            excluded.append((nd, "no trading day within +/-3d"))
    return mapped, excluded


def map_forward(dates, trading_days):
    """Lookahead-safe: release date if it trades, else the NEXT trading day."""
    mapped, excluded = {}, []
    for nd in dates:
        if nd in trading_days:
            mapped[nd] = nd
            continue
        fwd = trading_days[trading_days >= nd]
        if len(fwd) > 0 and (fwd[0] - nd).days <= 4:
            mapped[nd] = fwd[0]
        else:
            excluded.append((nd, "no observable reaction day inside sample"))
    return mapped, excluded


def check_mapping(mapped, label, allow_backward):
    backward = [(r, o) for r, o in mapped.items() if o < r]
    if backward and not allow_backward:
        r, o = backward[0]
        raise RuntimeError(f"{label}: BACKWARD mapping {r.date()} -> {o.date()}")
    obs = list(mapped.values())
    if len(set(obs)) != len(obs):
        raise RuntimeError(f"{label}: two releases collided on one trading day")
    return [{"release": str(r.date()), "mapped_to": str(o.date())} for r, o in backward]


def estimate(df, nfp_days):
    d = df.copy()
    d["is_NFP"] = d.index.isin(nfp_days)
    d["is_Friday"] = d.index.dayofweek == 4

    nfp = d[d["is_NFP"]]["SPY_AbsReturn"]
    non = d[~d["is_NFP"]]["SPY_AbsReturn"]
    t_o, p_o = stats.ttest_ind(nfp, non, equal_var=False)      # Welch, as archived
    fri = d[(d["is_Friday"]) & (~d["is_NFP"])]["SPY_AbsReturn"]
    t_f, p_f = stats.ttest_ind(nfp, fri, equal_var=False)

    regimes = {}
    for lo, hi, label in REGIMES:
        m = (d["VIX_prev"] >= lo) & (d["VIX_prev"] < hi)
        rn, ro = d[m & d["is_NFP"]]["SPY_AbsReturn"], d[m & ~d["is_NFP"]]["SPY_AbsReturn"]
        rec = {"n_nfp": int(len(rn)), "n_non_nfp": int(len(ro))}
        if len(rn) > 0 and len(ro) > 0:
            t, p = stats.ttest_ind(rn, ro, equal_var=False)
            rec.update({
                "mean_abs_return_nfp_pct": float(rn.mean() * 100),
                "mean_abs_return_non_nfp_pct": float(ro.mean() * 100),
                "ratio": float(rn.mean() / ro.mean()),
                "t_stat": float(t), "p_value": float(p),
            })
        regimes[label] = rec

    return {
        "overall": {
            "n_nfp": int(len(nfp)), "n_non_nfp": int(len(non)),
            "mean_abs_return_nfp_pct": float(nfp.mean() * 100),
            "mean_abs_return_non_nfp_pct": float(non.mean() * 100),
            "ratio": float(nfp.mean() / non.mean()),
            "t_stat": float(t_o), "p_value": float(p_o),
        },
        "vs_friday": {
            "n_friday_non_nfp": int(len(fri)),
            "mean_abs_return_friday_non_nfp_pct": float(fri.mean() * 100),
            "ratio_vs_friday": float(nfp.mean() / fri.mean()),
            "t_stat": float(t_f), "p_value": float(p_f),
        },
        "by_vix_regime": regimes,
    }


def run_cell(df, dates, mapper, label):
    mapped, excluded = mapper(dates, df.index)
    backward = check_mapping(mapped, label, allow_backward=(mapper is map_archived))
    res = estimate(df, list(mapped.values()))
    res.update({
        "n_releases_in": int(len(dates)), "n_mapped": int(len(mapped)),
        "excluded_releases": [{"release": str(r.date()), "reason": w} for r, w in excluded],
        "backward_mapped_lookahead_events": backward,
    })
    return res


def main():
    print("=" * 74)
    print("K904 task_s4_nfp — official BLS calendar (2x2 factorial)")
    print("=" * 74)

    raw = pd.read_csv(PINNED_CSV, parse_dates=["date"]).set_index("date")
    full = pd.DataFrame(index=raw.index)
    full["SPY_Return"] = raw["spy_adj_close"].pct_change()
    full["SPY_AbsReturn"] = full["SPY_Return"].abs()
    full["VIX"] = raw["vix_close"]
    full["VIX_prev"] = full["VIX"].shift(1)                # lags built pre-slice
    full = full.dropna(subset=["SPY_Return", "VIX", "VIX_prev"])
    df = full.loc[WIN_START:WIN_END]
    print(f"\nEstimation window: {len(df)} trading days, {df.index[0].date()} .. {df.index[-1].date()}")

    px, off = proxy_nfp_dates(), official_nfp_dates()
    print(f"Proxy dates: {len(px)}   Official dates: {len(off)}   "
          f"exact match: {len(set(px) & set(off))}")

    cells = {}
    for dlabel, dates in (("proxy", px), ("official", off)):
        for mlabel, mapper in (("archived_mapper", map_archived), ("forward_mapper", map_forward)):
            key = f"{dlabel}__{mlabel}"
            cells[key] = run_cell(df, dates, mapper, key)
            o = cells[key]["overall"]
            print(f"\n  {key:<30} N={o['n_nfp']:>3} (mapped {cells[key]['n_mapped']}/{cells[key]['n_releases_in']})  "
                  f"ratio={o['ratio']:.5f}  p={o['p_value']:.5f}")

    headline = cells["official__forward_mapper"]

    def ov(k):
        return cells[k]["overall"]

    decomposition = {
        "note": ("Marginal effect of each factor with the other held FIXED. A single "
                 "proxy-vs-canonical delta mixes them and misattributes the mapping fix "
                 "to the calendar."),
        "date_effect_at_archived_mapper": {
            "ratio": [ov("proxy__archived_mapper")["ratio"], ov("official__archived_mapper")["ratio"]],
            "p": [ov("proxy__archived_mapper")["p_value"], ov("official__archived_mapper")["p_value"]],
        },
        "date_effect_at_forward_mapper": {
            "ratio": [ov("proxy__forward_mapper")["ratio"], ov("official__forward_mapper")["ratio"]],
            "p": [ov("proxy__forward_mapper")["p_value"], ov("official__forward_mapper")["p_value"]],
        },
        "mapper_effect_at_official_dates": {
            "ratio": [ov("official__archived_mapper")["ratio"], ov("official__forward_mapper")["ratio"]],
            "p": [ov("official__archived_mapper")["p_value"], ov("official__forward_mapper")["p_value"]],
        },
    }

    px_m = {(d.year, d.month): d for d in px}
    off_m = {(d.year, d.month): d for d in off}
    shifted = [{"month": f"{k[0]}-{k[1]:02d}", "proxy": str(px_m[k].date()),
                "official": str(off_m[k].date()), "shift_days": int((off_m[k] - px_m[k]).days)}
               for k in sorted(set(px_m) & set(off_m)) if px_m[k] != off_m[k]]
    phantom = [{"month": f"{k[0]}-{k[1]:02d}", "proxy_date": str(px_m[k].date())}
               for k in sorted(set(px_m) - set(off_m))]

    payload = {
        "experiment_id": "k904-task_s4_nfp-canonical",
        "parent_experiment": "k904",
        "description": "task_s4_nfp re-estimated on official BLS release dates (2x2 factorial)",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "proposer": "主線程 (task assign_1238781f)",
        "executor": "Claude worktree agent",
        "headline_spec": "official__forward_mapper — official BLS dates, forward-only mapping",
        "scope_note": ("Only task_s4_nfp is re-run. task_s2_shock_types is untouched: it keys on "
                       "|dVIX| > 2 and never reads an NFP date, so the proxy defect cannot reach it."),
        "methodology": {
            "nfp_identification": "Official BLS Employment Situation release dates (FRED release id 50)",
            "sample_period": f"{WIN_START} to {WIN_END}",
            "window_note": ("End extended from archived 2026-04-05 to 2026-04-06 so the reaction day "
                            "for the 2026-04-03 (Good Friday) release is observable; otherwise that "
                            "event is silently dropped from the official arm only."),
            "comparison_baseline": "ALL non-NFP days",
            "test": "Welch's t-test (unequal variance) — as archived k904",
            "vix_regimes": "<15, 15-20, 20-25, >=25 on VIX_prev",
            "price_source": str(PINNED_CSV.relative_to(REPO)),
        },
        **headline,
        "factorial_cells": cells,
        "factor_decomposition": decomposition,
        "provenance": {
            "date_source": "FRED/ALFRED release id 50 via volpred.data.event_dates.nfp_release_dates",
            "requires_env": "FRED_API_KEY",
            "n_proxy_dates": int(len(px)), "n_official_dates": int(len(off)),
            "n_exact_date_matches": int(len(set(px) & set(off))),
            "months_shifted": shifted,
            "phantom_months_in_proxy": phantom,
            "price_snapshot_note": ("Archived k904 used a live 2026-04 yfinance pull; every cell here "
                                    "shares the paper's pinned snapshot, so no cell-to-cell difference "
                                    "is yfinance drift."),
        },
        "methodology_deltas": [
            {
                "item": "release-date -> trading-day mapping",
                "archived": "closest trading day within +/-3 days (resolves backward on holidays)",
                "canonical": "release date if it trades, else next trading day; asserted no backward map",
                "why": ("Backward resolution returns the trading day BEFORE the release for releases on "
                        "market holidays — a lookahead. Treated as a separate FACTOR, not folded into "
                        "the date change."),
            },
            {
                "item": "price window end",
                "archived": "2026-04-05",
                "canonical": "2026-04-06",
                "why": ("The 2026-04-03 release is Good Friday; its reaction day is 2026-04-06. Without "
                        "the extension the official arm silently loses that event while the proxy arm "
                        "backward-maps it onto 2026-04-02, creating an endpoint asymmetry between arms."),
            },
        ],
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n")

    o, v = headline["overall"], headline["vs_friday"]
    print(f"\n{'=' * 74}\nHEADLINE (official dates + forward mapper)")
    print(f"  overall   ratio={o['ratio']:.4f}x  t={o['t_stat']:.3f}  p={o['p_value']:.4f}  "
          f"N={o['n_nfp']}/{o['n_non_nfp']}")
    print(f"  vs Friday ratio={v['ratio_vs_friday']:.4f}x  t={v['t_stat']:.3f}  p={v['p_value']:.4f}")
    for label, rec in headline["by_vix_regime"].items():
        if "ratio" in rec:
            print(f"  {label:<20} n={rec['n_nfp']:>3}  ratio={rec['ratio']:.3f}x  "
                  f"t={rec['t_stat']:.2f}  p={rec['p_value']:.4f}")
    print(f"\nWrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
