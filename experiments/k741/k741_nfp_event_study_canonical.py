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

TEST VARIANT: WELCH, UNCONDITIONALLY (third Codex finding)
----------------------------------------------------------
The archived script called `stats.ttest_ind` without `equal_var`, i.e. it got
scipy's Student's default by omission rather than by decision — while
`main_v3.tex` described the tests as Welch's and the sibling k904 actually
passes `equal_var=False`. The two variants straddle the 5% line on the overall
test (Student p = 0.0506, Welch p = 0.0394), so this cannot be left implicit.

This script fixes the headline on **Welch** and passes `equal_var=` explicitly
everywhere. The rationale is methodological, not empirical:

  * Welch unconditionally is the standard recommendation (Zimmerman 2004;
    Ruxton 2006; Delacre, Lakens & Leys 2017). Welch loses almost no power when
    variances are in fact equal, and conditioning the choice on a variance
    pre-test inflates Type I error — a two-stage procedure is worse than either
    stage alone.
  * It makes k741 consistent with k904 and with what the paper always claimed.

What it is NOT is a choice made because the variances look unequal, and the
JSON records the diagnostic that says so: Brown-Forsythe (median-centred Levene)
gives p = 0.48 for NFP vs all non-NFP. There is no evidence of heteroscedasticity
here; Welch is chosen a priori, not because this sample asked for it.

Nor is it a choice made because it flatters the result. It moves the overall
test from p = 0.051 to p = 0.039, but it moves the *regime* tests — the ones the
absorption narrative leans on — the other way: under Student's + Holm the calm
regime survives multiplicity correction (adj p = 0.036), under Welch + Holm
**nothing does** (smallest adj p = 0.104). Both directions are reported.

MULTIPLE COMPARISONS
--------------------
Part B runs four regime tests and the paper tabulates all four. Holm-Bonferroni
adjusted p-values are computed across that family and persisted for both
variants, so the table note can report them instead of leaving a referee to
notice the omission.

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

import numpy as np
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

# Headline test variant. False => Welch. See module docstring for why this is
# fixed a priori rather than chosen from a variance pre-test. Never rely on
# scipy's default here: the two variants straddle 5% on the overall test.
HEADLINE_EQUAL_VAR = False


def both_variants(x, y):
    """Student's and Welch's for the same pair, plus the variance diagnostic.

    Returned `t`/`p` are the headline variant; `*_student` / `*_welch` are kept
    alongside so the paper can disclose the one it does not report.
    """
    t_s, p_s = stats.ttest_ind(x, y, equal_var=True)
    t_w, p_w = stats.ttest_ind(x, y, equal_var=False)
    # Brown-Forsythe: median-centred Levene, robust to the fat tails of |r|.
    bf = stats.levene(x, y, center="median")
    head_t, head_p = (t_s, p_s) if HEADLINE_EQUAL_VAR else (t_w, p_w)
    return {
        "t": float(head_t), "p": float(head_p),
        "t_student": float(t_s), "p_student": float(p_s),
        "t_welch": float(t_w), "p_welch": float(p_w),
        "sd_ratio": float(np.std(x, ddof=1) / np.std(y, ddof=1)),
        "levene_bf_p": float(bf.pvalue),
    }


def holm(pvals: dict) -> dict:
    """Holm-Bonferroni step-down adjusted p-values over a family of tests."""
    ordered = sorted(pvals.items(), key=lambda kv: kv[1])
    m, running, out = len(ordered), 0.0, {}
    for i, (key, p) in enumerate(ordered):
        running = max(running, min(1.0, (m - i) * p))
        out[key] = running
    return out


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

    v_all = both_variants(a_nfp, a_non)
    v_fri = both_variants(a_nfp, a_fri)
    _, p_u_all = stats.mannwhitneyu(a_nfp, a_non, alternative="greater")
    ret, vix_chg = nfp["Return"], nfp["VIX_change"].dropna()

    return {
        "n_nfp": int(len(nfp)), "n_non_nfp": int(len(non)),
        "nfp_mean_abs_return_pct": float(a_nfp.mean() * 100),
        "non_nfp_mean_abs_return_pct": float(a_non.mean() * 100),
        "friday_mean_abs_return_pct": float(a_fri.mean() * 100),
        "ratio_vs_all": float(a_nfp.mean() / a_non.mean()),
        "ratio_vs_friday": float(a_nfp.mean() / a_fri.mean()),
        "t_vs_all": v_all["t"], "p_vs_all": v_all["p"],
        "t_vs_friday": v_fri["t"], "p_vs_friday": v_fri["p"],
        "test_variants_vs_all": v_all,
        "test_variants_vs_friday": v_fri,
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
            v = both_variants(rn["AbsReturn"], ro["AbsReturn"])
            rec.update({
                "non_nfp_mean_abs_return_pct": float(ro["AbsReturn"].mean() * 100),
                "ratio": float(abs_r.mean() / ro["AbsReturn"].mean()),
                "t_stat": v["t"], "p_value": v["p"],
                "test_variants": v,
            })
        out[label] = rec

    # Holm across the four regime tests. The paper tabulates all four, so the
    # family is the table, and reporting only unadjusted p-values would overstate
    # the calm-regime result. Computed for both variants because which regimes
    # survive depends on that choice — Student's keeps one, Welch keeps none.
    tested = {k: r for k, r in out.items() if "test_variants" in r}
    if tested:
        adj_head = holm({k: r["test_variants"]["p"] for k, r in tested.items()})
        adj_stud = holm({k: r["test_variants"]["p_student"] for k, r in tested.items()})
        adj_welc = holm({k: r["test_variants"]["p_welch"] for k, r in tested.items()})
        for k, r in tested.items():
            r["p_value_holm"] = float(adj_head[k])
            r["test_variants"]["p_student_holm"] = float(adj_stud[k])
            r["test_variants"]["p_welch_holm"] = float(adj_welc[k])
    return out


def regime_difference_test(d, n_boot=10000, block=20, seed=20260719):
    """Directly test the comparative claim, which per-regime tests do NOT establish.

    The paper's hypothesis is `ratio_calm > ratio_high`. Reporting "significant in
    calm, not significant in high" is difference-in-significance, not
    significance-of-difference — two regimes can differ in p-value without their
    ratios differing detectably. So we test the difference itself.

    Circular moving-block bootstrap on the calendar-ordered daily series (block =
    20 days, matching the paper's existing SAR inference) so that volatility
    clustering is preserved; an iid resample would understate the standard error.
    Each replicate re-derives every regime ratio from the resampled days, so the
    event/control split is resampled jointly rather than treated as fixed.

    Also reports an ordered-trend statistic (Spearman rho of ratio against regime
    rank) for the monotone-decline claim.
    """
    rng = np.random.default_rng(seed)
    w = d.dropna(subset=["VIX_prev", "Return"]).copy()
    bounds = {lab: (lo, hi) for lab, lo, hi in REGIMES}

    def ratios(frame):
        out = {}
        for lab, (lo, hi) in bounds.items():
            m = (frame["VIX_prev"] >= lo) & (frame["VIX_prev"] < hi)
            rn = frame.loc[m & frame["IsNFP"], "AbsReturn"]
            ro = frame.loc[m & ~frame["IsNFP"], "AbsReturn"]
            out[lab] = (rn.mean() / ro.mean()) if (len(rn) >= 3 and len(ro) >= 10 and ro.mean() > 0) else np.nan
        return out

    obs = ratios(w)
    low_lab, high_lab = "Low (VIX<15)", "High (VIX>=25)"
    obs_diff = obs[low_lab] - obs[high_lab]
    obs_seq = np.array([obs[lab] for lab, _, _ in REGIMES], dtype=float)
    obs_rho = float(np.corrcoef(np.arange(len(REGIMES), dtype=float),
                                pd.Series(obs_seq).rank().to_numpy())[0, 1])

    T = len(w)
    n_blocks = int(np.ceil(T / block))
    diffs, trends, degenerate = [], [], 0
    ranks = np.arange(len(REGIMES), dtype=float)
    for _ in range(n_boot):
        starts = rng.integers(0, T, size=n_blocks)
        idx = np.concatenate([(np.arange(s, s + block) % T) for s in starts])[:T]
        rep = ratios(w.iloc[idx])
        dd = rep[low_lab] - rep[high_lab]
        seq = np.array([rep[lab] for lab, _, _ in REGIMES], dtype=float)
        if np.isnan(dd) or np.isnan(seq).any():
            degenerate += 1
            continue
        diffs.append(dd)
        # Spearman rho of ratio vs regime rank, computed inline to avoid a scipy call per replicate
        sr = pd.Series(seq).rank().to_numpy()
        trends.append(np.corrcoef(ranks, sr)[0, 1])

    diffs = np.asarray(diffs)
    ci = [float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))]
    # two-sided bootstrap p for H0: diff = 0
    p_boot = float(2 * min((diffs <= 0).mean(), (diffs >= 0).mean()))
    p_boot = min(p_boot, 1.0)

    return {
        "hypothesis": "ratio(VIX<15) - ratio(VIX>=25) > 0  (absorption: NFP impact is smaller in crisis)",
        "method": (f"circular moving-block bootstrap, block={block}d, B={n_boot}, seed={seed}; "
                   "regime ratios re-derived per replicate"),
        "observed_ratio_low": float(obs[low_lab]),
        "observed_ratio_high": float(obs[high_lab]),
        "observed_difference": float(obs_diff),
        "ci95": ci,
        "ci_excludes_zero": bool(ci[0] > 0 or ci[1] < 0),
        "p_two_sided": p_boot,
        "n_replicates_used": int(len(diffs)),
        "n_replicates_degenerate": int(degenerate),
        "observed_spearman_trend": obs_rho,
        "spearman_trend_mean": float(np.mean(trends)) if trends else None,
        "spearman_trend_ci95": [float(np.percentile(trends, 2.5)),
                                float(np.percentile(trends, 97.5))] if trends else None,
        "caveat": ("Small crisis-regime cell (n=28 NFP days) — the interval is wide and this test is "
                   "low-powered. A non-rejection here is NOT evidence the regimes are equal."),
    }


def run_cell(frame, dates, mapper, label):
    mapped, excluded = mapper(dates, frame.index)
    backward = check_mapping(mapped, label, allow_backward=(mapper is map_archived))
    if mapper is map_forward and (excluded or len(mapped) != len(dates)):
        # Fail closed: a headline cell that quietly loses an event still produces
        # plausible numbers. Recording the exclusion in JSON is not enough — nothing
        # downstream reads it. (Codex round-2 finding 4.)
        raise RuntimeError(
            f"{label}: {len(dates) - len(mapped)} release(s) unmapped {excluded!r}; "
            "extend the price window or add an explicit allowlist")
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

    hd = frame.copy()
    hmapped, _ = map_forward(off, frame.index)
    hd["IsNFP"] = hd.index.isin(list(hmapped.values()))
    regime_test = regime_difference_test(hd)
    print(f"\n  regime difference (calm - crisis): {regime_test['observed_difference']:.4f}  "
          f"CI95 {regime_test['ci95'][0]:.3f}..{regime_test['ci95'][1]:.3f}  "
          f"p={regime_test['p_two_sided']:.4f}  "
          f"{'EXCLUDES 0' if regime_test['ci_excludes_zero'] else 'INCLUDES 0'}")
    print(f"  trend (Spearman rho vs regime rank): observed={regime_test['observed_spearman_trend']:.3f} "
          f"boot-mean={regime_test['spearman_trend_mean']:.3f}  "
          f"CI95 {regime_test['spearman_trend_ci95'][0]:.3f}..{regime_test['spearman_trend_ci95'][1]:.3f}")

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

    # Single place the paper can cite for "which test, and what does the other one say".
    ha = headline["part_a_historical"]
    hb = headline["part_b_vix_regimes"]
    reg_tested = {k: r for k, r in hb.items() if "test_variants" in r}
    variant_disclosure = {
        "headline_variant": "student" if HEADLINE_EQUAL_VAR else "welch",
        "chosen_a_priori": True,
        "rationale": ("Welch unconditionally (Zimmerman 2004; Ruxton 2006; Delacre, Lakens & Leys 2017): "
                      "negligible power cost under equal variances, and selecting the variant from a "
                      "variance pre-test inflates Type I error. Also aligns k741 with sibling k904 and "
                      "with the label main_v3.tex already carried."),
        "not_justified_by_heteroscedasticity": {
            "levene_bf_p_vs_all": ha["test_variants_vs_all"]["levene_bf_p"],
            "sd_ratio_vs_all": ha["test_variants_vs_all"]["sd_ratio"],
            "note": ("Brown-Forsythe finds no evidence of unequal variance (p = 0.48, sd ratio 0.94). The "
                     "choice is a priori and would be the same had the diagnostic gone the other way; it is "
                     "recorded here so the rationale is not misread as data-driven."),
        },
        "not_chosen_for_favourability": {
            "overall_p_student": ha["test_variants_vs_all"]["p_student"],
            "overall_p_welch": ha["test_variants_vs_all"]["p_welch"],
            "regime_holm_survivors_student": sorted(
                k for k, r in reg_tested.items() if r["test_variants"]["p_student_holm"] < 0.05),
            "regime_holm_survivors_welch": sorted(
                k for k, r in reg_tested.items() if r["test_variants"]["p_welch_holm"] < 0.05),
            "note": ("Welch helps the overall test across the 5% line but costs the regime family its only "
                     "Holm survivor. The section leans on the regime pattern, so the chosen variant is the "
                     "less flattering one where it matters."),
        },
        "multiplicity": {
            "family": "the four VIX-regime tests tabulated in tab:nfp",
            "method": "Holm-Bonferroni step-down",
            "adjusted_headline": {k: r["p_value_holm"] for k, r in reg_tested.items()},
            "adjusted_student": {k: r["test_variants"]["p_student_holm"] for k, r in reg_tested.items()},
            "adjusted_welch": {k: r["test_variants"]["p_welch_holm"] for k, r in reg_tested.items()},
            "note": ("The overall vs-all and vs-Friday tests are not folded into this family: they are two "
                     "framings of one hypothesis on one sample, reported together rather than screened for "
                     "the smaller p."),
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
        "test_variant_disclosure": variant_disclosure,
        "regime_difference_test": regime_test,
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
                        "2026'. The correction is made for label honesty, not for what it buys: under the "
                        "Student variant the leak happens to straddle 5% (0.0506 corrected vs 0.0479 "
                        "leaked), but under the Welch headline both sides clear it (0.0394 vs 0.0374), so "
                        "that 'decisive' framing was variant-dependent and is not relied on. Codex review "
                        "2026-07-19."),
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
                "item": "t-test variant (CHANGED — now explicit)",
                "archived": "scipy stats.ttest_ind with equal_var omitted, i.e. Student's by default",
                "canonical": "equal_var=False (Welch) passed explicitly at every call site",
                "why": ("The archived choice was an omission, not a decision, and the two variants straddle "
                        "5% on the overall test (Student 0.0506 / Welch 0.0394) — too consequential to leave "
                        "implicit. Welch unconditionally is the standard recommendation (Zimmerman 2004; "
                        "Ruxton 2006; Delacre, Lakens & Leys 2017): it costs almost no power under equal "
                        "variances, and picking the variant from a pre-test inflates Type I error. It also "
                        "matches sibling k904 and what main_v3.tex always claimed. NOT justified by observed "
                        "heteroscedasticity — Brown-Forsythe p = 0.48 shows none — and NOT chosen for "
                        "favourability: it weakens the regime tests the narrative leans on (see multiplicity)."),
            },
            {
                "item": "multiple comparisons across the four regime tests",
                "archived": "none — four regime p-values reported unadjusted",
                "canonical": "Holm-Bonferroni over the four-test family, persisted for both variants",
                "why": ("tab:nfp tabulates four regime tests, so the table is the family. Unadjusted, the "
                        "calm regime reads as the strongest evidence in the section; under Holm at the "
                        "headline Welch variant no regime survives. Omitting this was a submission blocker."),
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
                  f"ratio={rec['ratio']:.3f}x  t={rec['t_stat']:.2f}  p={rec['p_value']:.4f}  "
                  f"Holm={rec['p_value_holm']:.4f}")

    vd = variant_disclosure
    print(f"\nTEST VARIANT: {vd['headline_variant'].upper()} (a priori)")
    print(f"  overall p — Student {vd['not_chosen_for_favourability']['overall_p_student']:.4f} | "
          f"Welch {vd['not_chosen_for_favourability']['overall_p_welch']:.4f}")
    print(f"  Brown-Forsythe p = {vd['not_justified_by_heteroscedasticity']['levene_bf_p_vs_all']:.3f} "
          f"(no evidence of unequal variance — Welch is not justified by this sample)")
    print(f"  regime Holm survivors @5% — Student {vd['not_chosen_for_favourability']['regime_holm_survivors_student'] or 'none'} | "
          f"Welch {vd['not_chosen_for_favourability']['regime_holm_survivors_welch'] or 'none'}")
    print(f"\nWrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
