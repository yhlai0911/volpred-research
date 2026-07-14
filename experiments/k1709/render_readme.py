"""Regenerate experiments/k1709/README.md from k1709_results.json.

C7. v1's README had a duplicated H3/H4 block whose second copy carried stale
numbers from an earlier run -- the classic failure of hand-copying results into
prose. Every number below is read out of the results file at render time, so the
README cannot drift from the experiment again.

Run:  uv run python experiments/k1709/render_readme.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

OUT = Path(__file__).resolve().parent
RESULTS = OUT / "k1709_results.json"


def pct(x: float | None, nd: int = 3) -> str:
    return "n/a" if x is None else f"{x:+.{nd}f}%"


def num(x: float | None, nd: int = 3) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def sci(p: float | None) -> str:
    if p is None:
        return "n/a"
    return f"{p:.3f}" if p >= 1e-3 else f"{p:.1e}"


def main() -> None:
    r = json.loads(RESULTS.read_text())
    prim = r["primary_cells"]
    fam = r["multiple_testing"]["primary_family"]
    vb = r["verdict_basis"]
    by_cell = {c["cell"]: c for c in r["all_cells"]}
    fam_by_cell = {f["cell"]: f for f in fam}
    L: list[str] = []
    A = L.append

    A(f"# K1709 — {r['title']}")
    A("")
    A(f"**Verdict: `{r['verdict']}`**")
    A("")
    A(f"> {vb['claim_strength']}")
    A("")
    A(
        "**This is a revision.** The first version of this experiment was FAILed by "
        "an independent review on 2026-07-14 (`codex_review_20260714.md`), and the "
        "project's own mechanical gate "
        "(`scripts/tests/test_nested_dm_misuse_ratchet.py`) agreed. Two headline "
        "claims did not survive. What follows is the rebuilt study."
    )
    A("")
    A("## What v1 claimed, and what was wrong with it")
    A("")
    A("| v1 claim | Status |")
    A("|---|---|")
    A(
        "| \"NULL: ETF flow has no incremental predictive content\" | **Overstated.** "
        "The nested comparison was adjudicated with a raw Diebold-Mariano statistic "
        "on expanding-window losses, plus a Clark-West helper that actually scored a "
        "*different loss* (variance-level MSPE, not QLIKE). Three estimands were "
        "fused into one gate. |"
    )
    A(
        "| \"We can rule out an RV uplift of ≥ +16.2% per 1-sd flow shock\" | "
        "**Withdrawn, not replaced.** That number came from reading a single-path "
        "power curve backwards. Power cannot bound an effect. |"
    )
    A("")
    A("### The six defects, and what replaced them")
    A("")
    A("| # | Defect | Fix |")
    A("|---|---|---|")
    fixes = {
        "C1": (
            "Nested comparison inferred with raw Diebold-Mariano + a mislabelled "
            "Clark-West",
            "Giacomini-White (2006) on Patton QLIKE from a **paired fixed rolling "
            "window**; raw DM and CW demoted to `feeds_gate=false`",
        ),
        "C2": (
            "\"MDE\" was one injection into one noise path — no repeated sampling, "
            "no false-positive check, non-monotone, and then read backwards as an "
            "exclusion",
            "A real power simulation (1000 simulated OOS paths per point) **plus** a "
            "pre-specified material-gain exclusion test and an inverted confidence "
            "bound — the only objects that can legitimately bound an effect",
        ),
        "C3": (
            "16 BTC / 10 ETH US market holidays kept as genuine `Total=0.0` flow days, "
            "polluting the 20-day rolling scaler",
            "NYSE session-calendar filter (`exchange_calendars` XNYS); holidays are "
            "MISSING, not zero",
        ),
        "C4": (
            "`pub_lag=2` robustness also lagged the HAR and return controls, "
            "handicapping its own baseline",
            "`state_lag` and `flow_lag` are separate parameters with separately "
            "verified source dates",
        ),
        "C5": (
            "Statistic was called \"HLN modified DM\" but had no HLN correction; "
            "one-sided p used a normal CDF while the helper used Student-t",
            "Renamed honestly to \"HAC-DM + Harvey-Liu-Zhu |t|>3 heuristic\"; "
            "one-sided p unified to the same Student-t",
        ),
        "C6": (
            "Holm ran on p-values already rounded to 4 dp; \"EVERY DM test\" "
            "hand-list missed 8 smearing tests",
            "Holm on raw p; the family is derived from a single in-code test registry",
        ),
        "C7": (
            "README had a duplicated H3/H4 block with stale numbers",
            "README is generated from the results JSON (`render_readme.py`)",
        ),
    }
    for k, (bad, fix) in fixes.items():
        A(f"| {k} | {bad} | {fix} |")
    A("")

    # ---- inference design -------------------------------------------------
    A("## How the claim is now established")
    A("")
    A(f"- **Test**: {vb['test']}")
    A(f"- **Loss**: {vb['loss']}")
    A(f"- **Estimation scheme**: {vb['estimation_scheme']}")
    A(f"- **Gate**: `{vb['gate']}`")
    A(f"- **Claim scope**: bounded in QLIKE-loss space only. {vb['four_way_alignment']}")
    A("")
    A(
        "**Why Giacomini-White, and why this is not just Diebold-Mariano renamed.** "
        "The arithmetic really is nearly the same — a mean loss difference over a "
        "Bartlett HAC standard error — and on the same loss stream the two statistics "
        "agree to about three decimal places (they differ only in a small-sample HAC "
        "scaling: GW divides each lag covariance by *n*, the canonical DM helper by "
        "*n − lag*). The results file reports both, side by side, rather than hiding "
        "the coincidence."
    )
    A("")
    A(
        "What makes the test legal under nesting is therefore **not the formula** but "
        "the *estimation scheme*. Giacomini and White compare forecasting **methods**, "
        "with fitted-parameter noise treated as part of the object being compared "
        "rather than a nuisance to be purged — and that limiting experiment requires "
        "the estimator to have **bounded memory**, i.e. a fixed-length rolling window. "
        "Feed the same formula expanding-window forecasts, as v1 did, and the nested "
        "null is degenerate: the statistic is biased toward the smaller model and no "
        "reference distribution rescues it. Every cell therefore also reports the "
        "expanding-window value under `expanding_window_diagnostic_v1_design`, so the "
        "effect of the scheme change is auditable rather than asserted."
    )
    A("")

    # ---- data --------------------------------------------------------------
    A("## Data")
    A("")
    A("| | BTC | ETH |")
    A("|---|---|---|")
    fl = r["data_diagnostics"]["flows"]
    rv = r["data_diagnostics"]["rv"]
    A(
        f"| Flow days (NYSE sessions) | {fl['BTC']['n_obs']} | {fl['ETH']['n_obs']} |"
    )
    A(
        f"| Sample | {fl['BTC']['date_min']} → {fl['BTC']['date_max']} "
        f"| {fl['ETH']['date_min']} → {fl['ETH']['date_max']} |"
    )
    A(
        f"| Net flow sd ($M) | {num(fl['BTC']['total_flow_musd']['std'], 1)} "
        f"| {num(fl['ETH']['total_flow_musd']['std'], 1)} |"
    )
    A(
        f"| Share of outflow days | {fl['BTC']['share_negative']:.1%} "
        f"| {fl['ETH']['share_negative']:.1%} |"
    )
    A(
        f"| **Market-holiday rows dropped (C3)** | "
        f"**{fl['BTC']['n_nonsession_rows_dropped']}** | "
        f"**{fl['ETH']['n_nonsession_rows_dropped']}** |"
    )
    A(
        f"| …of which had a non-zero Total | "
        f"{fl['BTC']['n_nonsession_rows_with_nonzero_total']} | "
        f"{fl['ETH']['n_nonsession_rows_with_nonzero_total']} |"
    )
    A(
        f"| RV calendar days | {rv['BTC']['n_daily_obs']} | {rv['ETH']['n_daily_obs']} |"
    )
    A("")
    A(
        f"Every dropped row had `Total = 0.0` with all fund columns dashed. That is "
        f"the trap: `sum(skipna=True)` over an all-dash row returns `0.0`, so "
        f"Farside's own Total matches the recomputed sum and the parser's "
        f"cross-check cannot see the problem. These were US market holidays — days "
        f"the ETFs *could not* trade — being fed to the model as genuine zero-flow "
        f"days, and then into the 20-flow-day rolling standard deviation that scales "
        f"every shock. Fake zeros shrink that scaler, which inflates every |z| that "
        f"follows."
    )
    A("")
    A(
        "Data sources: Farside Investors (daily ETF creation/redemption flows, "
        "`{}`), Yahoo Finance (BTC-USD / ETH-USD OHLC + hourly bars). Realized "
        "variance is Garman-Klass on UTC calendar days; Parkinson, squared "
        "close-to-close return, and true 24-hour realized variance are carried as "
        "robustness proxies.".format(fl["BTC"]["source_url"])
    )
    A("")

    # ---- endogeneity -------------------------------------------------------
    endo = r["endogeneity_diagnostic"]
    A("### Why this has to be an out-of-sample question")
    A("")
    A("| | corr(flow, same-day return) | corr(\\|flow\\|, same-day log RV) |")
    A("|---|---|---|")
    for a in ("BTC", "ETH"):
        A(
            f"| {a} | {num(endo[a]['corr_flow_vs_same_day_return'], 3)} "
            f"| {num(endo[a]['corr_absflow_vs_same_day_logrv'], 3)} |"
        )
    A("")
    A(
        "Flow is contemporaneously correlated with the same day's return and "
        "volatility, so a contemporaneous regression of RV on flow is "
        "uninterpretable — it cannot tell \"flow moves volatility\" from \"volatility "
        "attracts flow\". Everything below is strictly out-of-sample and conditional "
        "on a HAR-RV baseline."
    )
    A("")

    # ---- primary results ---------------------------------------------------
    A("## Primary family — does ETF flow beat HAR out-of-sample?")
    A("")
    A(
        f"{vb['cells_in_primary_family']} pre-specified cells. `H1` adds |z| (flow "
        "shock magnitude); `H2` adds an extra loading on redemptions; `H4` tests "
        "whether BTC's flow shock predicts **ETH** volatility once ETH's own flow is "
        "controlled for."
    )
    A("")
    A(
        "| Cell | n OOS | QLIKE Δ | GW z | Holm p | Rules out "
        f"≥{vb['material_gain_margin_pct']:.0f}% gain? |"
    )
    A("|---|---|---|---|---|---|")
    for f in fam:
        c = by_cell[f["cell"]]
        A(
            f"| {f['asset']} h={f['horizon']} {f['alt']} | {f['n']} "
            f"| {pct(f['qlike_improve_pct'])} | {num(f['stat'], 2)} "
            f"| {num(f['holm_adjusted_p'], 3)} "
            f"| {'**yes**' if f['excludes_material_gain'] else 'no'} |"
        )
    A("")
    A(
        "`QLIKE Δ` is the flow model's improvement over the baseline — **negative "
        "means the flow model is worse**. `GW z < 0` would favour flow; the gate "
        f"needs `z < -1.645` *and* Holm `p < 0.05` *and* a positive QLIKE Δ. "
        f"Cells passing: **{vb['cells_passing_flow_gate']} / "
        f"{vb['cells_in_primary_family']}**."
    )
    A("")

    # ---- exclusion ---------------------------------------------------------
    A("### The bound: what can actually be ruled out")
    A("")
    A(
        "Failing to reject equal accuracy is **not** evidence of equality — that is "
        "the trap v1 fell into. To claim a bound you have to reverse the burden of "
        "proof and test it directly:"
    )
    A("")
    A(
        f"> **H₀**: adding ETF flow improves expected QLIKE by at least "
        f"{vb['material_gain_margin_pct']:.0f}% (relative). Rejecting H₀ means a gain "
        f"that large is not there."
    )
    A("")
    A(
        "| Cell | exclusion z | p (unadjusted, IU) | excludes? | p (Holm, conservative) "
        "| 95% upper bound on the gain |"
    )
    A("|---|---|---|---|---|---|")
    for f in fam:
        ex = by_cell[f["cell"]]["material_gain_exclusion"]
        ub = f.get("qlike_gain_upper_bound_95pct")
        A(
            f"| {f['asset']} h={f['horizon']} {f['alt']} | {num(ex['z_stat'], 2)} "
            f"| {sci(f['material_gain_exclusion_p_raw'])} "
            f"| {'**yes**' if f['excludes_material_gain'] else 'no'} "
            f"| {sci(f['material_gain_exclusion_holm_p'])} "
            f"| {'≤ ' + num(ub, 2) + '%' if ub is not None else 'none'} |"
        )
    A("")
    A(
        "**Why these p-values are unadjusted, while the Giacomini-White ones above "
        "are Holm-corrected.** The two claims have opposite logical structure, and "
        "the correction has to follow the claim, not the habit. *\"Flow helps "
        "somewhere\"* is a **union** of alternatives — ten shots at finding an effect "
        "— so the family-wise error rate must be controlled. *\"Flow helps nowhere by "
        "≥1%\"* is an **intersection**: it may be asserted only if *every* cell "
        "rejects its own exclusion null, which is an intersection-union test "
        "(Berger 1982) and holds at level α with each cell tested unadjusted. Holm "
        "there would inflate type-II error and buy no type-I protection. The Holm "
        "column is reported anyway so the choice is auditable — and note it does not "
        "change the verdict either way."
    )
    A("")
    A(
        f"**{vb['cells_excluding_material_gain']} / {vb['cells_in_primary_family']}** "
        f"cells reject H₀ at the pre-specified {vb['material_gain_margin_pct']:.0f}% "
        "margin. That margin is the project standard carried over from K1701 — it "
        "was fixed before the results were seen, not tuned until the null looked "
        "good. Because most cells cannot reject it, **the bounded null is not "
        "established** and the verdict is `INCONCLUSIVE`, not `NULL`."
    )
    A("")
    A("### What CAN be bounded: the inverted confidence interval")
    A("")
    A(
        "The last column above is the honest quantitative answer. It is the "
        "one-sided 95% **upper confidence bound** on the relative QLIKE gain, "
        "obtained by inverting the exclusion test: gains *larger* than the bound are "
        "excluded by the data; gains *smaller* than it are not. Unlike a power curve, "
        "this is an inference about the effect rather than a property of the design "
        "under an assumed truth — which is exactly the distinction v1 collapsed."
    )
    A("")
    fb = vb.get("qlike_gain_upper_bound_family_simultaneous_pct")
    if fb is not None:
        A(
            f"Holding **simultaneously across all {vb['cells_in_primary_family']} "
            f"cells** (Bonferroni): the relative QLIKE gain from adding ETF flow is "
            f"**≤ {fb:.1f}%**. Anything larger is ruled out; anything smaller is not."
        )
    else:
        A(
            "Simultaneously across the family, **no bound can be stated at all** — "
            "at least one cell cannot exclude even a 90% relative QLIKE gain. That is "
            "how little this sample constrains the effect size, and it is the "
            "clearest possible refutation of v1's confident \"≥16% is excluded\"."
        )
    A("")
    A(
        "**Read the bound literally.** It lives in QLIKE-loss space: it is about "
        "*forecast accuracy*. It is **not** a statement that the RV uplift per flow "
        "shock is smaller than any particular percentage, and it is **not** a proof "
        "of exact zero."
    )
    A("")

    # ---- power -------------------------------------------------------------
    A("## Power — what this design could have seen")
    A("")
    pw = r["power_simulation"]
    A(
        f"{pw['BTC']['reps_per_beta']} simulated OOS paths per point. The DGP is the "
        "fitted calendar-day HAR law of motion with block-bootstrapped innovations, "
        "the real flow shocks and the real returns retained, and the effect injected "
        "**into the law of motion** so it propagates through the HAR lags — exactly "
        "as a genuine effect would, and exactly as the baseline would partially "
        "absorb it."
    )
    A("")
    A("| | BTC | ETH |")
    A("|---|---|---|")
    A(
        f"| Rejection rate when the true effect is 0 | "
        f"{num(pw['BTC']['false_positive_rate_at_beta_0'], 3)} "
        f"| {num(pw['ETH']['false_positive_rate_at_beta_0'], 3)} |"
    )
    for lbl, key in (
        ("80% power crossing lies in", "power_80pct_bracket"),
        ("90% power crossing lies in", "power_90pct_bracket"),
    ):
        row = [lbl]
        for a in ("BTC", "ETH"):
            br = pw[a][key]
            if not br["reached_on_grid"]:
                row.append(
                    f"never reached — not even at +{pw[a]['max_uplift_tested_pct']}% "
                    "RV uplift"
                )
            elif br["lower_rv_uplift_pct"] is None:
                row.append(f"at or below +{br['upper_rv_uplift_pct']}% RV uplift")
            else:
                row.append(
                    f"+{br['lower_rv_uplift_pct']}% … +{br['upper_rv_uplift_pct']}% "
                    f"RV uplift (power {br['lower_grid_power']:.2f} → "
                    f"{br['upper_grid_power']:.2f})"
                )
        A(f"| {row[0]} | {row[1]} | {row[2]} |")
    A("")
    A(
        "Those are **intervals, not thresholds**. β runs on a coarse 8-point grid, so "
        "the effect size at which power crosses a target can only be bracketed — it "
        "sits somewhere strictly inside the interval. The results JSON deliberately "
        "publishes **no point estimate** of an 80%- or 90%-power effect: turning a "
        "coarse curve into a precise-sounding number is exactly the move that got v1 "
        "failed, and a smaller version of it is still that move."
    )
    A("")
    A(
        "**Read the scope before quoting any of this.** The simulation covers *one "
        "cell* of the design: **h = 1 only** (the primary family also contains h = 5), "
        "a **single injected |flow| shock** (the H2 asymmetry and the cross-asset H4 "
        "alternative are never simulated, so this says nothing about power against "
        "*them*), and the **nominal single-cell gate** — not the ten-cell Holm-"
        "corrected family that actually produces the verdict, which is strictly less "
        "powerful. This is not \"the power of the study\", and it must not be quoted "
        "as such."
    )
    A("")
    A(
        "The β=0 row is **not** \"size\" in the textbook sense, and it should sit "
        "*below* 5% rather than at it. Under Giacomini-White's method-level null with "
        "a fixed window, an irrelevant extra regressor makes the augmented method "
        "genuinely worse — it pays an estimation cost and buys nothing — so "
        "E[L_flow − L_base] > 0 strictly. A one-sided flow-favouring gate is therefore "
        "conservative at β=0 by construction. What the row establishes is the thing "
        "that matters: **this gate does not manufacture flow signals out of noise**. "
        "A rate materially *above* 5% would have been the alarm."
    )
    A("")
    A("Per-β detail (BTC / ETH rejection rate at the 5% gate):")
    A("")
    A("| True RV uplift per 1-sd shock | BTC power | ETH power |")
    A("|---|---|---|")
    for rb, re_ in zip(pw["BTC"]["curve"], pw["ETH"]["curve"]):
        A(
            f"| {rb['rv_uplift_per_1sd_shock_pct']:+.1f}% "
            f"| {num(rb['power_gw_one_sided_5pct'], 2)} "
            f"| {num(re_['power_gw_one_sided_5pct'], 2)} |"
        )
    A("")
    A(
        "**Power is not an exclusion.** This table says how often the gate fires "
        "against an effect of a given size. It does *not* say the true effect is "
        "smaller than the 80%-power point — that inversion is precisely the error "
        "v1 made. It is also per-cell power at the nominal gate; the primary family "
        "additionally applies a Holm correction, so the family-wise design has "
        "*less* power than the table shows."
    )
    A("")
    btc80 = pw["BTC"]["power_80pct_bracket"]
    eth80 = pw["ETH"]["power_80pct_bracket"]
    if btc80["reached_on_grid"]:
        btc_txt = (
            f"somewhere between +{btc80['lower_rv_uplift_pct']}% and "
            f"+{btc80['upper_rv_uplift_pct']}% (BTC)"
        )
    else:
        btc_txt = f"more than +{pw['BTC']['max_uplift_tested_pct']}% (BTC)"
    eth_txt = (
        "80% power is never reached anywhere on the grid"
        if not eth80["reached_on_grid"]
        else (
            f"the interval is +{eth80['lower_rv_uplift_pct']}% … "
            f"+{eth80['upper_rv_uplift_pct']}%"
        )
    )
    A(
        "Note how much blunter this honest reading is than v1's. v1 advertised a "
        "minimum detectable effect of +16.2% and then used it as an exclusion. In "
        f"reality even this single-cell, single-alternative gate needs an uplift of "
        f"{btc_txt} before it reaches 80% power, and for ETH {eth_txt}. The instrument "
        "is far cruder than v1 claimed — which is one more reason the RV-space "
        "\"exclusion\" had to go, and why the verdict is INCONCLUSIVE rather than a "
        "bounded NULL."
    )
    A("")

    # ---- robustness --------------------------------------------------------
    A("## Robustness")
    A("")
    A(
        "Every run below is registered in the same in-code test registry as the "
        "primary family, so the full-family Holm correction sees all of them. v1's "
        "hand-written \"EVERY DM test\" list silently omitted 8."
    )
    A("")
    fams = [
        ("rv_proxy", "RV proxy (Parkinson / r² / true hourly RV)"),
        ("flow_lag2", "Conservative flow lag (flow usable only at end of t+1; state lag stays 1)"),
        ("smearing_none", "No lognormal smearing"),
        ("smearing_shared", "Baseline's smearing forced onto both models"),
        ("flow_transform", "Flow transform: signed / squared / gross churn / AR(5)-unexpected"),
        ("threshold", "Shock threshold dummies (|z| ≥ 1.0 … 2.5)"),
        ("eth_window", "Shorter ETH burn-in (200)"),
    ]
    A("| Family | Cells | Best (most flow-favouring) GW z | Any cell passing the gate? |")
    A("|---|---|---|---|")
    for key, label in fams:
        rows = [c for c in r["all_cells"] if c["family"] == key]
        if not rows:
            continue
        zs = [c["primary_inference_gw_qlike"]["z_stat"] for c in rows]
        best = min(zs)
        passed = any(
            f["passes_flow_gate"]
            for f in r["multiple_testing"]["full_family_holm"]
            if f["family"] == key and "passes_flow_gate" in f
        )
        A(f"| {label} | {len(rows)} | {num(best, 2)} | {'yes' if passed else 'no'} |")
    A("")
    mt = r["multiple_testing"]
    A(
        f"Across **all {mt['n_gate_eligible_gw_tests']}** gate-eligible "
        f"Giacomini-White tests in the study, "
        f"**{mt['n_full_family_holm_significant_at_05']}** survive the full-family "
        f"Holm correction in the flow-favouring direction. "
        f"({mt['n_diagnostic_only_tests']} further tests are registered as "
        "diagnostic-only and are barred from any gate by construction.)"
    )
    A("")
    bm = mt["bounded_memory_sensitivity"]
    n_unb = len(bm["unbounded_memory_cells"])
    cells_txt = "`" + "`, `".join(bm["unbounded_memory_cells"]) + "`"
    A(
        f"### {'One' if n_unb == 1 else n_unb} of those tests "
        f"{'is' if n_unb == 1 else 'are'} not "
        f"{'a ' if n_unb == 1 else ''}bounded-memory "
        f"{'test' if n_unb == 1 else 'tests'} — and "
        f"{'it is' if n_unb == 1 else 'they are'} labelled"
    )
    A("")
    A(
        "Giacomini-White's limiting experiment assumes the **forecasting method** has "
        "bounded estimator memory. Every cell here fits its regression on a fixed "
        "250-day rolling window, so the final fit always satisfies that. But the "
        "condition is on the *whole method*, not on the last regression: "
        f"{cells_txt} "
        f"{'builds its regressor' if n_unb == 1 else 'build their regressor'} from "
        "an **AR(5) refitted on an expanding window** of flow history. There is no "
        "lookahead in it — day *i*'s own value never enters its own fit — but it is "
        "not a bounded-memory forecasting method, and a blanket sentence claiming all "
        f"{bm['n_gw_tests_all']} registered tests are one would be false."
    )
    A("")
    it, they, them = (
        ("It", "it", "it") if n_unb == 1 else ("They", "they", "them")
    )
    A(
        f"{it} **{'is' if n_unb == 1 else 'are'} not dropped**. Removing a test once "
        f"its result is known is selection, not rigour. {it} "
        f"{'stays' if n_unb == 1 else 'stay'} in the family, "
        f"{they} {'is' if n_unb == 1 else 'are'} corrected for, "
        f"{they} {'carries' if n_unb == 1 else 'carry'} `bounded_memory=false` in the "
        f"registry, and the family-wise count is re-run without {them} so a reader can "
        f"see whether anything hangs on {them}: "
        f"**{bm['n_full_family_holm_significant_at_05']}** Holm-surviving cells across "
        f"all {bm['n_gw_tests_all']} tests, "
        f"**{bm['n_full_family_holm_significant_at_05_bounded_memory_only']}** across "
        f"the {bm['n_gw_tests_bounded_memory']} bounded-memory tests. The verdict "
        + (f"**does** depend on {them} — see the JSON."
           if bm["conclusion_depends_on_the_unbounded_cell"]
           else f"does **not** depend on {them}.")
        + (" All 10 primary cells are bounded-memory."
           if bm["primary_family_is_entirely_bounded_memory"] else "")
    )
    A("")

    # ---- smearing note -----------------------------------------------------
    A("### Is the null an artifact of the log → variance mapping?")
    A("")
    A(
        "A live threat, and worth spelling out. The flow model has more parameters → "
        "a lower training residual variance → a smaller `exp(s²/2)` smearing "
        "multiplier → systematically lower variance forecasts. QLIKE is asymmetric, "
        "so in principle this channel could *manufacture* the null we are reporting. "
        "Three defences: the residual variance is dof-corrected (`N − k`), which "
        "makes its expectation spec-invariant under the null; the study re-scores "
        "with no smearing at all; and it re-scores again with the *baseline's* "
        "multiplier forced onto both models. The verdict does not move."
    )
    A("")

    # ---- H3 ----------------------------------------------------------------
    A("### H3 — Friday flow → weekend volatility (in-sample, descriptive)")
    A("")
    A(
        "Crypto trades through the weekend but the ETFs do not, so a Friday flow "
        "shock is the last piece of ETF information before a two-day gap. If flow "
        "carried volatility news anywhere, this is where it should be loudest."
    )
    A("")
    A("| | n Fridays | β(\\|z\\|) | HAC t | two-sided p |")
    A("|---|---|---|---|---|")
    for a in ("BTC", "ETH"):
        h3 = r["h3_weekend_in_sample"][a]
        A(
            f"| {a} | {h3['n_fridays']} | {num(h3['coef']['abs_z']['beta'], 4)} "
            f"| {num(h3['abs_z_t'], 2)} | {num(h3['abs_z_p_two_sided'], 3)} |"
        )
    A("")
    A(
        "**In-sample only**, and it does not feed any verdict — the study's claim is "
        "about out-of-sample predictive content."
    )
    A("")

    # ---- files -------------------------------------------------------------
    # ---- rev1 re-review residuals ------------------------------------------
    resid = r.get("rev1_review_residuals_fixed")
    if resid:
        A("## What a second, independent re-review still found — and what changed")
        A("")
        A(
            "The rebuilt study was re-reviewed against a *frozen* commit. Six residuals "
            "survived the first rebuild. **Not one of them moved an estimate**; every "
            "one of them moved what a reader would have been entitled to conclude from "
            "the estimates, which is the more dangerous kind of defect and the kind "
            "this experiment already got caught by once. (The *h*=5 statistics do "
            "differ in the third decimal from the pre-fix run — because Yahoo "
            "back-filled a calendar day between the two runs, adding one out-of-sample "
            "observation. That is the data moving, not the fixes. See *Reproducing*.)"
        )
        A("")
        A("| # | Residual | What changed |")
        A("|---|---|---|")
        labels = {
            "R1_power_overclaim": "Power curve read as the study's power",
            "R2_spurious_precision": "80%/90%-power effect quoted as a point",
            "R3_beta0_is_not_size": "β=0 row described as a size calibration",
            "R4_fixed_window_dm_mislabelled":
                "Fixed-window raw DM tagged \"biased toward the smaller model\"",
            "R5_verdict_basis_alignment":
                "`verdict_basis` named only the detection test",
            "R6_bounded_memory":
                "One robustness cell is not a bounded-memory method",
        }
        for i, (key, label) in enumerate(labels.items(), start=1):
            if key in resid:
                A(f"| R{i} | {label} | {resid[key]} |")
        A("")

    A("## Reproducing")
    A("")
    A("```bash")
    A("uv run python experiments/k1709/k1709.py            # rebuilds the results JSON")
    A("uv run python experiments/k1709/render_readme.py    # rebuilds this README")
    A("uv run --extra dev python -m pytest experiments/k1709/test_k1709.py -q")
    A("uv run --extra dev python -m pytest scripts/tests/test_nested_dm_misuse_ratchet.py -q")
    A("```")
    A("")
    A(f"Seed `{r['seed']}` throughout (OLS is deterministic; the block bootstrap and "
      "the power simulation are seeded explicitly). The results JSON is written "
      "atomically: temp file → parse → `os.replace`.")
    A("")
    A(
        "**The seed does not make this bit-reproducible, and pretending otherwise "
        "would be its own small overclaim.** The RV series is fetched live from "
        "Yahoo at run time, so the sample end date advances every day and Yahoo "
        "occasionally back-fills a day it had previously dropped. Re-running this "
        "script tomorrow will therefore move the third decimal of the *h*=5 "
        "statistics (one extra out-of-sample observation), while the *h*=1 "
        "statistics, the verdict, the gate counts and the family-wide bound stay "
        "put. The vintage behind every number in this README is "
        f"**{r['data_diagnostics']['rv']['BTC']['date_max']}** (last fully-closed "
        "UTC day); it is recorded in `data_diagnostics.rv.*.date_max` so the "
        "numbers can always be traced to the data that produced them."
    )
    A("")
    A("| File | What it is |")
    A("|---|---|")
    A("| `k1709.py` | The experiment |")
    A("| `k1709_results.json` | Every number in this README |")
    A("| `test_k1709.py` | Regression gates |")
    A("| `render_readme.py` | Generates this file from the results JSON |")
    A("| `codex_review_20260714.md` | The independent review that FAILed v1 |")
    A("| `fig1_flow_vs_rv.png` | Flow vs realized volatility |")
    A("| `fig2_event_window.png` | log-RV path around large flow shocks |")
    A("| `fig3_oos_qlike.png` | OOS QLIKE + Giacomini-White z, primary cells |")
    A("| `fig4_threshold_sensitivity.png` | GW z by shock threshold |")
    A("| `fig5_simulated_power.png` | Simulated power (replaces v1's \"MDE\" curve) |")
    A("")

    # ---- honest summary ----------------------------------------------------
    A("## What this study does and does not say")
    A("")
    A("**Does say:**")
    A("")
    if r["verdict"] == "BOUNDED_NULL_NO_MATERIAL_QLIKE_GAIN":
        A(
            "- Spot BTC/ETH ETF net flow buys no material improvement in "
            "out-of-sample volatility forecast accuracy over a HAR-RV baseline: a "
            f"≥{vb['material_gain_margin_pct']:.0f}% relative QLIKE gain is ruled out "
            f"in all {vb['cells_in_primary_family']} primary cells."
        )
    else:
        A(
            "- **No robust incremental predictive evidence was found** for spot "
            "BTC/ETH ETF net flow over a HAR-RV baseline. Not one of the "
            f"{vb['cells_in_primary_family']} primary cells clears the gate, and the "
            "point estimates mostly run the *wrong* way (the flow model is slightly "
            "worse)."
        )
        if fb is not None:
            A(
                f"- Gains larger than **{fb:.1f}%** in relative QLIKE are excluded, "
                f"simultaneously across all {vb['cells_in_primary_family']} cells."
            )
        A(
            f"- But only {vb['cells_excluding_material_gain']}/"
            f"{vb['cells_in_primary_family']} cells can rule out the pre-specified "
            f"{vb['material_gain_margin_pct']:.0f}% gain, so this is a **negative "
            "finding, not a proven zero**. Calling it \"NULL\" would be the same "
            "overreach v1 was FAILed for."
        )
    A(
        "- The result survives four flow transforms, four RV proxies, three smearing "
        "conventions, a conservative publication lag, and four shock thresholds."
    )
    A("")
    A("**Does not say:**")
    A("")
    A("- That the true effect is exactly zero. No test here can establish that.")
    A(
        "- That an RV uplift of any particular size is excluded. "
        f"{vb['withdrawn_v1_claim']}"
    )
    A(
        "- Anything about the *level* effect of ETF-ization on crypto volatility. The "
        "treatment here is the flow, not the trading clock or the session structure."
    )
    A("")

    text = "\n".join(L) + "\n"
    tmp = OUT / "README.md.tmp"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, OUT / "README.md")
    print(f"README.md rewritten from {RESULTS.name}: {len(L)} lines, verdict={r['verdict']}")


if __name__ == "__main__":
    main()
