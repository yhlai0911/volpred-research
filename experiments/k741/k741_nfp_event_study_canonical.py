#!/usr/bin/env python3
"""
K741-canonical: NFP Event Study — official BLS calendar, 2x2 factorial
======================================================================
Companion to `k741_nfp_event_study.py` (2026-03, archived — DO NOT EDIT).

WHY THIS FILE EXISTS
--------------------
The archived k741 identified NFP days with a *first-Friday-of-month proxy*
(`days_until_friday = (4 - d.weekday()) % 7`). Against the official calendar
(FRED/ALFRED release id 50, "Employment Situation") the proxy is wrong for
**33 of 194 months** in this window and invents one event month (2025-10, the
release cancelled during the government shutdown). Those numbers propagated
into `paper/volatility-absorption/main_v3.tex` (abstract, sec:nfp, tab:nfp).

TWO CONFOUNDED CHANGES — WHY THIS IS A 2x2, NOT A 2-ARM DESIGN
--------------------------------------------------------------
Fixing the calendar means changing TWO things, and an earlier revision of this
script conflated them (caught by Codex review 2026-07-19, verdict FAIL):

  (1) DATE SOURCE   : first-Friday proxy      -> official BLS release dates
  (2) MAPPING RULE  : archived release->trading-day mapping -> forward-only

Change (2) is not cosmetic. The archived mapping searches `[nd-1d, nd+3d]` and
takes the FIRST candidate, so when a release lands on a market holiday it
returns the trading day *before* the release — a lookahead. It bites 5 Good
Friday releases (2010-04-02, 2012-04-06, 2015-04-03, 2021-04-02, 2023-04-07),
on which BLS published but US equity markets were shut.

Reporting a single "proxy vs canonical" delta attributes the combined effect to
the calendar. It is not: on this data the mapping fix moves the result MORE than
the date fix does. So we run the full 2x2 and report the marginal effect of each
factor separately. `date_effect` is defined only at a FIXED mapper.

HEADLINE SPEC = official dates + forward-only mapping. That is the only cell
with neither a proxy calendar nor a lookahead, and it is what the paper cites.

SAMPLE WINDOW (second Codex finding)
------------------------------------
The archived script built its frame from 2009-12-01 (warm-up for `VIX_prev`)
and then used the WHOLE frame as the non-NFP control — leaking 21 Dec-2009
control days into a sample the paper describes as "January 2010 to March 2026".
The archived numbers are therefore not the window they claim. Here the warm-up
is retained for lag construction but estimation is sliced to 2010-01-01. This
is a deliberate departure from the archived code, recorded in
`methodology_deltas`; it is NOT a 1:1 item, because the archived behaviour
contradicts the archived label.

PRICE DATA
----------
Both arms share ONE pinned snapshot
(`paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv`, the
paper's 2026-04-19 pinned data) so no cell differs by yfinance drift. An
`archived_reproduction` cell (proxy + archived mapper + unsliced frame) is
emitted purely to demonstrate the re-implementation reproduces the archived
JSON before any fix is applied.

Scope: Parts A and B only — the parts main_v3.tex cites. Archived Parts C
(sector dispersion) and D (strategy) are cited nowhere in the paper (verified by
grep) and need sector ETFs absent from the pinned snapshot.

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
OUT = Path(__file__).resolve().parent / "k741_nfp_event_study_canonical_results.json"

WARMUP_START = "2009-12-01"   # lag construction only
SAMPLE_START = "2010-01-01"   # estimation starts here (paper's stated window)
SAMPLE_END = "2026-03-30"
EVENT_CUTOFF = pd.Timestamp("2026-03-30")

REGIMES = [("Low (VIX<15)", 0, 15), ("Medium (15-20)", 15, 20),
           ("Elevated (20-25)", 20, 25), ("High (VIX>=25)", 25, 999)]


# ──────────────────────────────────────────────────────────────────
# Factor 1: event date source
# ──────────────────────────────────────────────────────────────────

def proxy_nfp_dates():
    """VERBATIM from the archived k741: first Friday of each month."""
    out = []
    for year in range(2010, 2027):
        for month in range(1, 13):
            d = datetime(year, month, 1)
            ff = d + timedelta(days=(4 - d.weekday()) % 7)
            if ff <= datetime(2026, 3, 30):
                out.append(pd.Timestamp(ff))
    return pd.DatetimeIndex(out)


def official_nfp_dates():
    """Official BLS 'Employment Situation' release dates (FRED release id 50)."""
    d = nfp_release_dates("2010-01-01", "2026-03-31", use_cache=False)
    return pd.DatetimeIndex([x for x in d if x <= EVENT_CUTOFF])


# ──────────────────────────────────────────────────────────────────
# Factor 2: release date -> trading day mapping
# ──────────────────────────────────────────────────────────────────

def map_archived(dates, trading_days):
    """Archived rule: window [nd-1d, nd+3d], take first. RETAINS the lookahead."""
    mapped, excluded = {}, []
    for nd in dates:
        if nd in trading_days:
            mapped[nd] = nd
            continue
        cand = trading_days[(trading_days >= nd - timedelta(days=1))
                            & (trading_days <= nd + timedelta(days=3))]
        if len(cand) > 0:
            mapped[nd] = cand[0]
        else:
            excluded.append((nd, "no trading day in [-1d, +3d]"))
    return mapped, excluded


def map_forward(dates, trading_days):
    """Lookahead-safe: the release date if it trades, else the NEXT trading day."""
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
    """Fail loudly rather than return a plausible-but-wrong event set.

    `allow_backward` is True only for the archived-mapper control cells, whose
    whole purpose is to reproduce the lookahead. Their backward maps are
    returned as evidence rather than swallowed; a forward-mapper cell that
    produced one would be a bug and raises.
    """
    backward = [(r, o) for r, o in mapped.items() if o < r]
    if backward and not allow_backward:
        r, o = backward[0]
        raise RuntimeError(f"{label}: BACKWARD mapping {r.date()} -> {o.date()}")
    obs_days = list(mapped.values())
    if len(set(obs_days)) != len(obs_days):
        raise RuntimeError(f"{label}: two releases collided on one trading day")
    return [{"release": str(r.date()), "mapped_to": str(o.date())} for r, o in backward]


# ──────────────────────────────────────────────────────────────────
# Estimation (mirrors archived Part A / Part B)
# ──────────────────────────────────────────────────────────────────

def part_a(d):
    nfp = d[d["IsNFP"]].dropna(subset=["Return"])
    non = d[~d["IsNFP"]].dropna(subset=["Return"])
    fri = d[(d["IsFriday"]) & (~d["IsNFP"])].dropna(subset=["Return"])
    a_nfp, a_non, a_fri = nfp["AbsReturn"], non["AbsReturn"], fri["AbsReturn"]

    t_all, p_all = stats.ttest_ind(a_nfp, a_non)   # equal_var=True, as archived
    t_fri, p_fri = stats.ttest_ind(a_nfp, a_fri)
    _, p_u_all = stats.mannwhitneyu(a_nfp, a_non, alternative="greater")
    ret, vix_chg = nfp["Return"], nfp["VIX_change"].dropna()

    return {
        "n_nfp": int(len(nfp)), "n_non_nfp": int(len(non)),
        "nfp_mean_abs_return_pct": float(a_nfp.mean() * 100),
        "non_nfp_mean_abs_return_pct": float(a_non.mean() * 100),
        "friday_mean_abs_return_pct": float(a_fri.mean() * 100),
        "ratio_vs_all": float(a_nfp.mean() / a_non.mean()),
        "ratio_vs_friday": float(a_nfp.mean() / a_fri.mean()),
        "t_vs_all": float(t_all), "p_vs_all": float(p_all),
        "t_vs_friday": float(t_fri), "p_vs_friday": float(p_fri),
        "wilcoxon_p_vs_all": float(p_u_all),
        "pct_positive": float((ret > 0).mean() * 100),
        "mean_return_pct": float(ret.mean() * 100),
        "vix_drops_pct": float((vix_chg < 0).mean() * 100),
    }


def part_b(d):
    """Regime stats. The archived script only PRINTED the ratio/t/p the paper
    table reports; its JSON stored n and means, so those columns were never
    covered by reproduce.py. We persist them."""
    nfp_v = d[d["IsNFP"]].dropna(subset=["VIX_prev", "Return"])
    non_v = d[~d["IsNFP"]].dropna(subset=["VIX_prev", "Return"])
    out = {}
    for label, lo, hi in REGIMES:
        rn = nfp_v[(nfp_v["VIX_prev"] >= lo) & (nfp_v["VIX_prev"] < hi)]
        ro = non_v[(non_v["VIX_prev"] >= lo) & (non_v["VIX_prev"] < hi)]
        if len(rn) == 0:
            continue
        abs_r, ret, vchg = rn["AbsReturn"], rn["Return"], rn["VIX_change"].dropna()
        rec = {
            "n": int(len(rn)), "n_non_nfp": int(len(ro)),
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
                "t_stat": float(t), "p_value": float(p),
            })
        out[label] = rec
    return out


def run_cell(frame, dates, mapper, label):
    mapped, excluded = mapper(dates, frame.index)
    backward = check_mapping(mapped, label, allow_backward=(mapper is map_archived))
    d = frame.copy()
    d["IsNFP"] = d.index.isin(list(mapped.values()))
    d["IsFriday"] = d.index.dayofweek == 4
    return {
        "part_a_historical": part_a(d), "part_b_vix_regimes": part_b(d),
        "n_releases_in": int(len(dates)), "n_mapped": int(len(mapped)),
        "excluded_releases": [{"release": str(r.date()), "reason": w} for r, w in excluded],
        "backward_mapped_lookahead_events": backward,
    }


def main():
    print("=" * 74)
    print("K741-canonical: NFP event study, official BLS calendar (2x2 factorial)")
    print("=" * 74)

    raw = pd.read_csv(PINNED_CSV, parse_dates=["date"]).set_index("date")
    w = raw.loc[WARMUP_START:SAMPLE_END]
    full = pd.DataFrame(index=w.index)
    full["Close"] = w["spy_adj_close"]
    full["Return"] = full["Close"].pct_change()
    full["AbsReturn"] = full["Return"].abs()
    full["VIX"] = w["vix_close"]
    full["VIX_prev"] = full["VIX"].shift(1)          # lags built on warm-up
    full["VIX_change"] = full["VIX"] - full["VIX_prev"]
    frame = full.loc[SAMPLE_START:]                   # estimation window
    print(f"\nWarm-up frame : {len(full)} rows, {full.index[0].date()} .. {full.index[-1].date()}")
    print(f"Estimation    : {len(frame)} rows, {frame.index[0].date()} .. {frame.index[-1].date()}")

    px, off = proxy_nfp_dates(), official_nfp_dates()
    print(f"Proxy dates: {len(px)}   Official dates: {len(off)}   "
          f"exact match: {len(set(px) & set(off))}")

    cells = {}
    for dlabel, dates in (("proxy", px), ("official", off)):
        for mlabel, mapper in (("archived_mapper", map_archived), ("forward_mapper", map_forward)):
            key = f"{dlabel}__{mlabel}"
            cells[key] = run_cell(frame, dates, mapper, key)
            a = cells[key]["part_a_historical"]
            print(f"\n  {key:<32} N={a['n_nfp']:>3}  ratio={a['ratio_vs_all']:.5f}  "
                  f"p={a['p_vs_all']:.5f}  (vs Fri {a['ratio_vs_friday']:.4f}, p={a['p_vs_friday']:.4f})")

    headline = cells["official__forward_mapper"]

    # Fidelity check against the archived JSON: archived cell, archived (unsliced) frame.
    repro = run_cell(full, px, map_archived, "archived_reproduction")
    ra = repro["part_a_historical"]
    print(f"\n  {'archived_reproduction (unsliced)':<32} N={ra['n_nfp']:>3}  "
          f"ratio={ra['ratio_vs_all']:.5f}  p={ra['p_vs_all']:.5f}   "
          f"[archived JSON: 1.14481 / 0.08138]")

    def pa(k):
        return cells[k]["part_a_historical"]

    decomposition = {
        "note": ("Each factor's marginal effect, holding the other factor FIXED. A single "
                 "proxy-vs-canonical delta mixes the two and misattributes the mapping fix "
                 "to the calendar."),
        "date_effect_at_archived_mapper": {
            "from": "proxy__archived_mapper", "to": "official__archived_mapper",
            "ratio": [pa("proxy__archived_mapper")["ratio_vs_all"], pa("official__archived_mapper")["ratio_vs_all"]],
            "p": [pa("proxy__archived_mapper")["p_vs_all"], pa("official__archived_mapper")["p_vs_all"]],
        },
        "date_effect_at_forward_mapper": {
            "from": "proxy__forward_mapper", "to": "official__forward_mapper",
            "ratio": [pa("proxy__forward_mapper")["ratio_vs_all"], pa("official__forward_mapper")["ratio_vs_all"]],
            "p": [pa("proxy__forward_mapper")["p_vs_all"], pa("official__forward_mapper")["p_vs_all"]],
        },
        "mapper_effect_at_official_dates": {
            "from": "official__archived_mapper", "to": "official__forward_mapper",
            "ratio": [pa("official__archived_mapper")["ratio_vs_all"], pa("official__forward_mapper")["ratio_vs_all"]],
            "p": [pa("official__archived_mapper")["p_vs_all"], pa("official__forward_mapper")["p_vs_all"]],
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
        "experiment_id": "k741-canonical",
        "title": "NFP Event Study — official BLS release calendar, 2x2 factorial",
        "parent_experiment": "k741",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "proposer": "主線程 (task assign_1238781f)",
        "executor": "Claude worktree agent",
        "period": f"{SAMPLE_START} .. {SAMPLE_END}",
        "headline_spec": "official__forward_mapper — official BLS dates, forward-only mapping, 2010-01-01 estimation start",
        "scope": ("Parts A and B only — the parts main_v3.tex cites. Archived Parts C (sector "
                  "dispersion) and D (strategy) are cited nowhere in the paper and need sector "
                  "ETFs absent from the pinned snapshot."),
        "part_a_historical": headline["part_a_historical"],
        "part_b_vix_regimes": headline["part_b_vix_regimes"],
        "factorial_cells": cells,
        "factor_decomposition": decomposition,
        "archived_reproduction_unsliced": repro,
        "provenance": {
            "date_source": "FRED/ALFRED release id 50 (Employment Situation) via volpred.data.event_dates.nfp_release_dates",
            "price_source": str(PINNED_CSV.relative_to(REPO)),
            "price_snapshot_note": ("Paper's pinned 2026-04-19 snapshot; every cell shares it, so no "
                                    "cell-to-cell difference is yfinance drift. The archived k741 JSON "
                                    "used a live 2026-03 pull; see archived_reproduction_unsliced."),
            "requires_env": "FRED_API_KEY",
            "n_proxy_dates": int(len(px)), "n_official_dates": int(len(off)),
            "n_exact_date_matches": int(len(set(px) & set(off))),
            "months_shifted": shifted,
            "phantom_months_in_proxy": phantom,
        },
        "methodology_deltas": [
            {
                "item": "estimation window start",
                "archived": "frame built from 2009-12-01 and used whole as control (21 Dec-2009 control days)",
                "canonical": "warm-up retained for lags; estimation sliced to 2010-01-01",
                "why": ("The archived control set contradicts the archived label 'January 2010 to March "
                        "2026'. Material: at the headline spec the leak moves p from 0.0506 to 0.0479, "
                        "i.e. across the 5% line. Codex review 2026-07-19."),
            },
            {
                "item": "release-date -> trading-day mapping",
                "archived": "window [nd-1d, nd+3d], take first candidate",
                "canonical": "release date if it trades, else next trading day; asserts no backward map",
                "why": ("The archived window returns the trading day BEFORE the release when the release "
                        "falls on a market holiday — a lookahead, hitting 5 Good Friday releases. Treated "
                        "as a separate FACTOR, not folded into the date change, because on this data it "
                        "moves the result more than the calendar does."),
            },
            {
                "item": "t-test variant (NOT changed — flagged for the paper)",
                "archived": "scipy stats.ttest_ind default equal_var=True (Student's)",
                "canonical": "identical, for comparability",
                "why": ("main_v3.tex labelled these 'Welch's t-tests'. Incorrect for k741-sourced numbers: "
                        "the archived script never passes equal_var=False. Sibling k904 does use Welch."),
            },
            {
                "item": "regime ratio / t / p persistence",
                "archived": "printed to stdout only; JSON stored n and means",
                "canonical": "persisted, so reproduce.py can bind them",
                "why": "Those three table columns were never covered by any reproducibility check.",
            },
        ],
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n")

    h = headline["part_a_historical"]
    print(f"\n{'=' * 74}\nHEADLINE (official dates + forward mapper + 2010 window)")
    print(f"  ratio vs all non-NFP : {h['ratio_vs_all']:.4f}x  (t={h['t_vs_all']:.3f}, p={h['p_vs_all']:.4f})")
    print(f"  ratio vs Fridays     : {h['ratio_vs_friday']:.4f}x  (t={h['t_vs_friday']:.3f}, p={h['p_vs_friday']:.4f})")
    print(f"  N_NFP={h['n_nfp']}  N_non={h['n_non_nfp']}  total={h['n_nfp'] + h['n_non_nfp']}")
    for label, rec in headline["part_b_vix_regimes"].items():
        if "ratio" in rec:
            print(f"  {label:<18} n={rec['n']:>3}  |r|={rec['mean_abs_return_pct']:.3f}%  "
                  f"ratio={rec['ratio']:.3f}x  t={rec['t_stat']:.2f}  p={rec['p_value']:.4f}")
    print(f"\nWrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
