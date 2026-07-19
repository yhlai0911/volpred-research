#!/usr/bin/env python3
"""
K741-canonical: NFP Event Study re-run on the OFFICIAL BLS release calendar
===========================================================================
Companion to `k741_nfp_event_study.py` (2026-03, archived — DO NOT EDIT).

WHY THIS FILE EXISTS
--------------------
The archived k741 identified NFP days with a *first-Friday-of-month proxy*
(`days_until_friday = (4 - d.weekday()) % 7`). The 2026-07-19 firstfriday
proxy sweep flagged that proxy as contaminated. Measured against the official
calendar (FRED/ALFRED release id 50, "Employment Situation") over the k741
window, the proxy is wrong for **33 of 194 months** and additionally invents
one event month that does not exist (2025-10, the release cancelled during the
government shutdown). Those numbers propagated verbatim into
`paper/volatility-absorption/main_v3.tex` Table `tab:nfp` and the abstract.

This script does NOT modify the archived experiment. It re-estimates the two
parts that feed the paper (Part A historical, Part B VIX regimes) and reports
proxy vs canonical side by side.

DESIGN: ISOLATING THE DATE EFFECT
---------------------------------
The archived JSON differs from any re-run in TWO ways at once: the date source
AND the price snapshot (it used a live 2026-03 yfinance pull; yfinance
retroactively revises VIX history — the paper documents this in
Section~robustness). Comparing the archived JSON directly against a canonical
re-run would confound the two.

So both arms here run on ONE identical, pinned price snapshot
(`paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv`,
the paper's own 2026-04-19 pinned data):

  arm "proxy"     = first-Friday proxy dates   (archived method, pinned data)
  arm "canonical" = official BLS release dates (pinned data)

  canonical - proxy  ....... the DATE-SOURCE effect (clean; same prices)
  proxy - archived JSON .... the SNAPSHOT-DRIFT effect (reported separately)

Scope: Parts A and B only. The archived Parts C (sector dispersion) and D
(strategy) are NOT cited anywhere in main_v3.tex (verified by grep) and need
sector ETFs absent from the pinned snapshot, so they are deliberately not
re-run here. See README.md.

METHODOLOGY: 1:1 WITH THE ARCHIVED SCRIPT, WITH ONE DELIBERATE EXCEPTION
-----------------------------------------------------------------------
Identical: event window (same-day |r|), ratio definition (mean/mean),
`stats.ttest_ind` with scipy's DEFAULT equal_var=True (Student's, NOT Welch —
see methodology_deltas), `stats.mannwhitneyu(alternative="greater")`,
VIX regime cuts at 15/20/25 on VIX_prev, sample 2010-2026.

Exception (`methodology_deltas` in the output JSON): the archived
release-date -> trading-day mapping searches the window [nd-1d, nd+3d] and
takes the FIRST candidate. When a release lands on a market holiday that
returns the trading day BEFORE the release — a lookahead. It bites 5 Good
Friday releases (2010-04-02, 2012-04-06, 2015-04-03, 2021-04-02, 2023-04-07),
on which BLS published but US equity markets were shut. The canonical arm maps
to the release date itself when it trades, else the NEXT trading day (the day
the reaction can actually occur). Required by .claude/rules/experiments.md
(lookahead is the highest-priority risk). The proxy arm keeps the archived
buggy mapping so the archived result stays reproducible.

Author: VolPred Research System
[提出: 主線程 task assign_1238781f, 執行: Claude worktree agent]
"""

import json
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from volpred.data.event_dates import nfp_release_dates  # noqa: E402

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parents[2]
PINNED_CSV = REPO / "paper" / "volatility-absorption" / "data" / "spy_gld_tlt_qqq_eem_vix_2005-2026.csv"
OUT = Path(__file__).resolve().parent / "k741_nfp_event_study_canonical_results.json"

# Archived k741 window: data 2009-12-01..2026-03-30, events through 2026-03-30.
DATA_START, DATA_END = "2009-12-01", "2026-03-30"
EVENT_CUTOFF = pd.Timestamp("2026-03-30")


# ──────────────────────────────────────────────────────────────────
# Event date construction
# ──────────────────────────────────────────────────────────────────

def proxy_nfp_dates(start_year=2010, end_year=2026):
    """VERBATIM from the archived k741: first Friday of each month."""
    out = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            d = datetime(year, month, 1)
            days_until_friday = (4 - d.weekday()) % 7
            first_friday = d + timedelta(days=days_until_friday)
            if first_friday <= datetime(2026, 3, 30):
                out.append(pd.Timestamp(first_friday))
    return pd.DatetimeIndex(out)


def canonical_nfp_dates():
    """Official BLS 'Employment Situation' release dates (FRED release id 50)."""
    d = nfp_release_dates("2010-01-01", "2026-03-31", use_cache=False)
    return pd.DatetimeIndex([x for x in d if x <= EVENT_CUTOFF])


def map_archived(dates, trading_days):
    """Archived mapping: window [nd-1d, nd+3d], take first. Retains the lookahead."""
    out = []
    for nd in dates:
        if nd in trading_days:
            out.append(nd)
        else:
            cand = trading_days[(trading_days >= nd - timedelta(days=1))
                                & (trading_days <= nd + timedelta(days=3))]
            if len(cand) > 0:
                out.append(cand[0])
    return pd.DatetimeIndex(sorted(set(out)))


def map_next_trading_day(dates, trading_days):
    """Lookahead-safe: the release date if it trades, else the next trading day."""
    out = []
    for nd in dates:
        if nd in trading_days:
            out.append(nd)
        else:
            fwd = trading_days[trading_days >= nd]
            if len(fwd) > 0 and (fwd[0] - nd).days <= 4:
                out.append(fwd[0])
    return pd.DatetimeIndex(sorted(set(out)))


# ──────────────────────────────────────────────────────────────────
# Estimation (mirrors archived Part A / Part B)
# ──────────────────────────────────────────────────────────────────

def build_frame(nfp_trading_days, spy):
    d = spy.copy()
    d["IsNFP"] = d.index.isin(nfp_trading_days)
    d["IsFriday"] = d.index.dayofweek == 4
    return d


def part_a(d):
    nfp = d[d["IsNFP"]].dropna(subset=["Return"])
    non = d[~d["IsNFP"]].dropna(subset=["Return"])
    fri = d[(d["IsFriday"]) & (~d["IsNFP"])].dropna(subset=["Return"])

    a_nfp, a_non, a_fri = nfp["AbsReturn"], non["AbsReturn"], fri["AbsReturn"]
    t_all, p_all = stats.ttest_ind(a_nfp, a_non)          # equal_var=True, as archived
    t_fri, p_fri = stats.ttest_ind(a_nfp, a_fri)
    _, p_u_all = stats.mannwhitneyu(a_nfp, a_non, alternative="greater")

    ret = nfp["Return"]
    vix_chg = nfp["VIX_change"].dropna()
    return {
        "n_nfp": int(len(nfp)),
        "n_non_nfp": int(len(non)),
        "nfp_mean_abs_return_pct": float(a_nfp.mean() * 100),
        "non_nfp_mean_abs_return_pct": float(a_non.mean() * 100),
        "friday_mean_abs_return_pct": float(a_fri.mean() * 100),
        "ratio_vs_all": float(a_nfp.mean() / a_non.mean()),
        "ratio_vs_friday": float(a_nfp.mean() / a_fri.mean()),
        "t_vs_all": float(t_all),
        "p_vs_all": float(p_all),
        "t_vs_friday": float(t_fri),
        "p_vs_friday": float(p_fri),
        "wilcoxon_p_vs_all": float(p_u_all),
        "pct_positive": float((ret > 0).mean() * 100),
        "mean_return_pct": float(ret.mean() * 100),
        "vix_drops_pct": float((vix_chg < 0).mean() * 100),
    }


REGIMES = [("Low (VIX<15)", 0, 15), ("Medium (15-20)", 15, 20),
           ("Elevated (20-25)", 20, 25), ("High (VIX>=25)", 25, 999)]


def part_b(d):
    """Regime stats. NOTE: the archived script only PRINTED the ratio/t/p that
    the paper table reports; its JSON stored just n/means. We persist them."""
    nfp_v = d[(d["IsNFP"])].dropna(subset=["VIX_prev", "Return"])
    non_v = d[(~d["IsNFP"])].dropna(subset=["VIX_prev", "Return"])
    out = {}
    for label, lo, hi in REGIMES:
        rn = nfp_v[(nfp_v["VIX_prev"] >= lo) & (nfp_v["VIX_prev"] < hi)]
        ro = non_v[(non_v["VIX_prev"] >= lo) & (non_v["VIX_prev"] < hi)]
        if len(rn) == 0:
            continue
        abs_r, ret = rn["AbsReturn"], rn["Return"]
        vchg = rn["VIX_change"].dropna()
        rec = {
            "n": int(len(rn)),
            "n_non_nfp": int(len(ro)),
            "mean_abs_return_pct": float(abs_r.mean() * 100),
            "median_abs_return_pct": float(abs_r.median() * 100),
            "std_return_pct": float(ret.std() * 100),
            "mean_return_pct": float(ret.mean() * 100),
            "pct_positive": float((ret > 0).mean() * 100),
            "mean_vix_change": float(vchg.mean()) if len(vchg) else None,
        }
        if len(rn) >= 5 and len(ro) >= 30:
            t, p = stats.ttest_ind(rn["AbsReturn"], ro["AbsReturn"])
            rec.update({
                "non_nfp_mean_abs_return_pct": float(ro["AbsReturn"].mean() * 100),
                "ratio": float(abs_r.mean() / ro["AbsReturn"].mean()),
                "t_stat": float(t),
                "p_value": float(p),
            })
        out[label] = rec
    return out


def main():
    print("=" * 72)
    print("K741-canonical: NFP event study on the official BLS release calendar")
    print("=" * 72)

    raw = pd.read_csv(PINNED_CSV, parse_dates=["date"]).set_index("date")
    spy = pd.DataFrame(index=raw.loc[DATA_START:DATA_END].index)
    w = raw.loc[DATA_START:DATA_END]
    spy["Close"] = w["spy_adj_close"]
    spy["Return"] = spy["Close"].pct_change()
    spy["AbsReturn"] = spy["Return"].abs()
    spy["VIX"] = w["vix_close"]
    spy["VIX_prev"] = spy["VIX"].shift(1)
    spy["VIX_change"] = spy["VIX"] - spy["VIX_prev"]
    td = spy.index
    print(f"\nPinned snapshot: {len(spy)} trading days, {td[0].date()} .. {td[-1].date()}")

    px_dates, can_dates = proxy_nfp_dates(), canonical_nfp_dates()
    px_td = map_archived(px_dates, td)
    can_td = map_next_trading_day(can_dates, td)
    print(f"Proxy     : {len(px_dates)} raw dates -> {len(px_td)} trading days")
    print(f"Canonical : {len(can_dates)} raw dates -> {len(can_td)} trading days")

    # ---- date-level provenance diff (raw release dates, pre-mapping) ----
    px_by_month = {(d.year, d.month): d for d in px_dates}
    can_by_month = {(d.year, d.month): d for d in can_dates}
    shifted = []
    for ym in sorted(set(px_by_month) & set(can_by_month)):
        if px_by_month[ym] != can_by_month[ym]:
            shifted.append({
                "month": f"{ym[0]}-{ym[1]:02d}",
                "proxy": str(px_by_month[ym].date()),
                "canonical": str(can_by_month[ym].date()),
                "shift_days": int((can_by_month[ym] - px_by_month[ym]).days),
            })
    phantom = [{"month": f"{ym[0]}-{ym[1]:02d}", "proxy_date": str(px_by_month[ym].date())}
               for ym in sorted(set(px_by_month) - set(can_by_month))]
    missing = [{"month": f"{ym[0]}-{ym[1]:02d}", "canonical_date": str(can_by_month[ym].date())}
               for ym in sorted(set(can_by_month) - set(px_by_month))]
    print(f"\nDate diff: {len(shifted)} months shifted, {len(phantom)} phantom, "
          f"{len(missing)} missed, "
          f"{len(set(px_dates) & set(can_dates))} exact matches")

    results = {}
    for name, mapped in (("proxy", px_td), ("canonical", can_td)):
        d = build_frame(mapped, spy)
        results[name] = {"part_a_historical": part_a(d), "part_b_vix_regimes": part_b(d)}
        a = results[name]["part_a_historical"]
        print(f"\n--- arm: {name} ---")
        print(f"  N_NFP={a['n_nfp']}  N_non={a['n_non_nfp']}")
        print(f"  ratio vs all    = {a['ratio_vs_all']:.4f}x  (t={a['t_vs_all']:.3f}, p={a['p_vs_all']:.4f})")
        print(f"  ratio vs Friday = {a['ratio_vs_friday']:.4f}x  (t={a['t_vs_friday']:.3f}, p={a['p_vs_friday']:.4f})")
        print(f"  Wilcoxon p      = {a['wilcoxon_p_vs_all']:.4f}")
        for label, rec in results[name]["part_b_vix_regimes"].items():
            if "ratio" in rec:
                print(f"  {label:<18} n={rec['n']:>3}  |r|={rec['mean_abs_return_pct']:.3f}%  "
                      f"ratio={rec['ratio']:.3f}x  t={rec['t_stat']:.2f}  p={rec['p_value']:.4f}")

    payload = {
        "experiment_id": "k741-canonical",
        "title": "NFP Event Study — official BLS release calendar re-run",
        "parent_experiment": "k741",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "proposer": "主線程 (task assign_1238781f)",
        "executor": "Claude worktree agent",
        "period": "2010-01 .. 2026-03",
        "scope": ("Parts A and B only — the parts cited by main_v3.tex. Archived Parts C "
                  "(sector dispersion) and D (strategy) are not referenced by the paper and "
                  "require sector ETFs absent from the pinned snapshot."),
        # canonical arm is the headline; keep the archived schema key names
        "part_a_historical": results["canonical"]["part_a_historical"],
        "part_b_vix_regimes": results["canonical"]["part_b_vix_regimes"],
        "proxy_arm_same_data": results["proxy"],
        "provenance": {
            "date_source": "FRED/ALFRED release id 50 (Employment Situation) via volpred.data.event_dates.nfp_release_dates",
            "price_source": str(PINNED_CSV.relative_to(REPO)),
            "price_snapshot_note": ("Paper's pinned 2026-04-19 snapshot. Both arms share it, so the "
                                    "canonical-minus-proxy delta is a pure date-source effect. The "
                                    "archived k741 JSON used a live 2026-03 yfinance pull, so archived-"
                                    "minus-proxy is snapshot drift, reported separately in the comparison."),
            "n_proxy_dates": int(len(px_dates)),
            "n_canonical_dates": int(len(can_dates)),
            "n_proxy_trading_days": int(len(px_td)),
            "n_canonical_trading_days": int(len(can_td)),
            "n_exact_date_matches": int(len(set(px_dates) & set(can_dates))),
            "months_shifted": shifted,
            "phantom_months_in_proxy": phantom,
            "months_missing_from_proxy": missing,
        },
        "methodology_deltas": [
            {
                "item": "release-date -> trading-day mapping",
                "archived": "window [nd-1d, nd+3d], take first candidate",
                "canonical_arm": "release date if it trades, else next trading day",
                "why": ("The archived window can return the trading day BEFORE the release when the "
                        "release falls on a market holiday — a lookahead. Affects 5 Good Friday "
                        "releases (2010-04-02, 2012-04-06, 2015-04-03, 2021-04-02, 2023-04-07). "
                        "Fixing it is required by .claude/rules/experiments.md. The proxy arm keeps "
                        "the archived mapping so the archived result stays reproducible."),
            },
            {
                "item": "t-test variant (NOT changed — flagged for the paper)",
                "archived": "scipy stats.ttest_ind default equal_var=True (Student's)",
                "canonical_arm": "identical (equal_var=True), for 1:1 comparability",
                "why": ("main_v3.tex abstract and Section~sec:nfp label these 'Welch's t-tests'. That "
                        "label is incorrect for k741-sourced numbers: the archived script never passed "
                        "equal_var=False. Sibling k904 DOES use Welch. This mislabel is independent of "
                        "the date-proxy defect and needs a separate paper correction."),
            },
            {
                "item": "regime ratio / t / p persistence",
                "archived": "computed and printed to stdout only; JSON stored n and means",
                "canonical_arm": "persisted into the results JSON",
                "why": ("The paper table's ratio/t-stat/p columns were transcribed from stdout, so they "
                        "were not machine-checkable by reproduce.py. Now they are."),
            },
        ],
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nWrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
