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


def build_readme(r: dict) -> str:
    """Pure renderer: results mapping in, complete README text out."""
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
            "Giacomini-White (2006) **Sec 3.4 unconditional special case** "
            "(h_t = 1, equals a HAC Diebold-Mariano) on Patton QLIKE from a "
            "**paired fixed rolling window**; raw DM and CW demoted to "
            "`feeds_gate=false`",
        ),
        "C2": (
            "\"MDE\" was one injection into one noise path — no repeated sampling, "
            "no false-positive check, non-monotone, and then read backwards as an "
            "exclusion",
            vb["c2_fix_summary"],
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
    A(f"- **Claim scope**: {vb['four_way_alignment']}")
    A("")
    A(
        "> ### What this study did NOT test\n"
        ">\n"
        f"> {vb['conditional_predictive_ability_not_tested']}"
    )
    A("")
    A(vb["gw_name_explanation"])
    A("")
    A(vb["nested_fixed_memory_explanation"])
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
    A(vb["endogeneity_claim_scope"])
    A("")

    # ---- primary results ---------------------------------------------------
    A(f"## {vb['primary_section_heading']}")
    A("")
    A(vb["primary_design_scope"])
    A("")
    A(vb["primary_table_header"])
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
    A(vb["qlike_delta_interpretation"])
    A(vb["primary_detection_outcome_readme"])
    A("")

    # ---- exclusion ---------------------------------------------------------
    A(f"### {vb['bound_section_heading']}")
    A("")
    A(vb["bound_test_intro"])
    A("")
    A(
        f"> **H₀**: {vb['material_gain_null']}. "
        f"{vb['material_gain_rejection_interpretation']}"
    )
    A("")
    A(vb["exclusion_table_header"])
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
    A(vb["exclusion_multiplicity_readme"])
    A("")
    A(vb["exclusion_outcome_readme"])
    A("")
    A(f"### {vb['bound_ci_heading']}")
    A("")
    A(vb["upper_bound_explanation_readme"])
    A("")
    A(vb["family_bound_statement"])
    A("")
    A(vb["bound_literal_scope"])
    A("")
    A(f"**Frozen-bound limitation.** {vb['bound_inversion_limitation']}")
    A("")

    # ---- power -------------------------------------------------------------
    A(f"## {vb['power_section_heading']}")
    A("")
    pw = r["power_simulation"]
    A(vb["power_dgp_readme"])
    A("")
    A(vb["power_grid_note"])
    A("")
    A(vb["power_scope_warning"])
    A("")
    A(vb["power_false_positive_note"])
    A("")
    A(vb["power_curve_intro"])
    A("")
    A(vb["power_curve_table_header"])
    A("|---|---|---|")
    for rb, re_ in zip(pw["BTC"]["curve"], pw["ETH"]["curve"]):
        A(
            f"| {rb['rv_uplift_per_1sd_shock_pct']:+.1f}% "
            f"| {num(rb['power_gw_one_sided_5pct'], 2)} "
            f"| {num(re_['power_gw_one_sided_5pct'], 2)} |"
        )
    A("")
    A(vb["power_is_not_exclusion_readme"])
    A("")
    # ---- robustness --------------------------------------------------------
    A("## Robustness")
    A("")
    A(vb["robustness_registry_intro"])
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
    A(vb["robustness_table_header"])
    A("|---|---|---|")
    for key, label in fams:
        rows = [c for c in r["all_cells"] if c["family"] == key]
        if not rows:
            continue
        zs = [c["primary_inference_gw_qlike"]["z_stat"] for c in rows]
        best = min(zs)
        A(f"| {label} | {len(rows)} | {num(best, 2)} |")
    A("")
    mt = r["multiple_testing"]
    A(vb["robustness_outcome_readme"])
    A("")
    A(f"### {vb['bounded_memory_heading']}")
    A("")
    A(vb["bounded_memory_issue"])
    A("")

    # ---- smearing note -----------------------------------------------------
    A(f"### {vb['smearing_heading']}")
    A("")
    A(vb["smearing_scope"])
    A("")

    # ---- H3 ----------------------------------------------------------------
    A("### H3 — Friday flow → weekend volatility (in-sample, descriptive)")
    A("")
    A(vb["h3_motivation"])
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
    A(vb["h3_weekend_claim_scope"])
    A("")

    # ---- files -------------------------------------------------------------
    # ---- rev1 re-review residuals ------------------------------------------
    resid = r.get("rev1_review_residuals_fixed")
    if resid:
        A("## What a second, independent re-review still found — and what changed")
        A("")
        A(resid["note"])
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
                "Two robustness rows are not bounded-memory methods",
        }
        for i, (key, label) in enumerate(labels.items(), start=1):
            if key in resid:
                A(f"| R{i} | {label} | {resid[key]} |")
        A("")

    A("## Reproducing")
    A("")
    A("```bash")
    A("uv run python experiments/k1709/k1709.py --relabel  # frozen-safe wording only")
    A("uv run python experiments/k1709/k1709.py --render-frozen-figures")
    A("uv run python experiments/k1709/render_readme.py    # JSON-only README render")
    A("uv run --extra dev python -m pytest experiments/k1709/test_k1709.py -q")
    A("uv run --extra dev python -m pytest scripts/tests/test_nested_dm_misuse_ratchet.py -q")
    A("```")
    A("")
    A(f"Seed `{r['seed']}` throughout (OLS is deterministic; the block bootstrap and "
      "the power simulation are seeded explicitly). The results JSON is written "
      "atomically: temp file → parse → `os.replace`.")
    A("")
    A(f"**Point-in-time limitation.** {vb['reproducibility_limitation']}")
    A("")
    A(
        "The committed result endpoint is "
        f"**{r['data_diagnostics']['rv']['BTC']['date_max']}** (last fully closed "
        "UTC day in that run). This records the sample endpoint, not the unarchived "
        "vendor response bytes. Running `k1709.py` without a frozen-only flag is a "
        "new live-data estimate, not a reproduction of this artefact."
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
    A("| `fig2_event_window.png` | Frozen descriptive event plot; see label limitation below |")
    A("| `fig3_oos_qlike.png` | OOS QLIKE + unconditional GW/DM z, primary cells |")
    A("| `fig4_threshold_sensitivity.png` | Unconditional GW/DM z by shock threshold |")
    A("| `fig5_simulated_power.png` | Simulated power (replaces v1's \"MDE\" curve) |")
    A("")
    A(f"**Figure 2 limitation.** {vb['fig2_event_day_limitation']}")
    A("")

    # ---- honest summary ----------------------------------------------------
    A("## What this study does and does not say")
    A("")
    A("**Does say:**")
    A("")
    for key in sorted(k for k in vb if k.startswith("does_say_")):
        if vb[key]:
            A(f"- {vb[key]}")
    A("")
    A("**Does not say:**")
    A("")
    for key in sorted(k for k in vb if k.startswith("does_not_say_")):
        if vb[key]:
            A(f"- {vb[key]}")
    A("")

    return "\n".join(L) + "\n"


def main() -> None:
    r = json.loads(RESULTS.read_text())
    text = build_readme(r)
    tmp = OUT / "README.md.tmp"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, OUT / "README.md")
    print(
        f"README.md rewritten from {RESULTS.name}: "
        f"{len(text.splitlines())} lines, verdict={r['verdict']}"
    )


if __name__ == "__main__":
    main()
