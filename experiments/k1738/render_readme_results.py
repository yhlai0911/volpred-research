"""Regenerate README section 12 from K1738_results.json.

Every number in the README results section is read from the results JSON so that no figure is
hand-typed and the prose cannot drift from the artifact.  Run after K1738.py.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARK = "## 12. Results as run (generated from `K1738_results.json` — no figure typed by hand)"


def fmt(x, nd=4):
    return "n/a" if x is None else f"{x:+.{nd}f}"


def g(x, spec="%.4g"):
    """Format a possibly-absent number.  Interim artifacts legitimately carry None."""
    return "n/a" if x is None else spec % x


def main() -> int:
    r = json.loads((HERE / "K1738_results.json").read_text(encoding="utf-8"))
    L = [MARK, ""]
    L.append(f"**Verdict: `{r['verdict']}`** — {r['verdict_reason']}")
    L.append("")
    if r.get("causal_claim_cap"):
        L.append(f"> {r['causal_claim_cap']}")
        L.append("")
    s = r["sample"]
    L.append(f"Sample: **{s['n_firm_quarters']:,} firm-quarters**, {s['n_firms']} firms, "
             f"{s['n_quarters']} quarters, {s['date_range'][0]} to {s['date_range'][1]}, "
             f"{s['n_announcement_months']} distinct announcement months. "
             f"Constructible-SUE coverage of frozen announcement records in-span: "
             f"{s['sue_coverage']['coverage']:.1%} "
             f"({s['sue_coverage']['n_sue_constructible']:,}/"
             f"{s['sue_coverage']['n_announcement_records']:,}).")
    L.append("")
    L.append(f"Treatment: {r['treatment_definition']['type']} — "
             f"`{r['treatment_definition']['formula']}`.")
    L.append("")

    if not r.get("run_complete", True):
        L.append(f"⚠️ Partial run. Stages completed: {', '.join(r['stages_completed'])}. "
                 f"Missing: {', '.join(r['stages_missing'])}. Unfinished pre-registered "
                 f"conditions evaluate to False, so the verdict cannot be overstated.")
        L.append("")

    # ---- headline contrast --------------------------------------------------------------------
    L.append("### 12.1 The headline contrast: naive vs OLS-controls vs DML")
    L.append("")
    L.append("Effect on **log** realized vol per 1 treatment unit. A SUE unit is the firm's "
             "historical-surprise scale; it is not the pooled estimation-sample SD. "
             "`q` is Benjamini–Hochberg-adjusted within the 6-hypothesis family F1.")
    L.append("")
    for tname, tlabel in (("signed_sue", "Signed SUE (primary)"), ("abs_sue", "|SUE| (secondary)")):
        if tname not in r.get("estimates", {}):
            continue
        L.append(f"**{tlabel}**")
        L.append("")
        L.append("| horizon | naive OLS | OLS + controls | DML | DML 95% CI | raw p | BH q | vol change / treatment unit |")
        L.append("|---|---|---|---|---|---|---|---|")
        for h in ("h1m", "h2m", "h3m"):
            c = r["estimates"][tname][h]
            d = c["dml"]
            ci = d["ci95"]
            L.append(
                f"| {h[1]}m | {fmt(c['naive_ols']['theta'])} | {fmt(c['ols_controls']['theta'])} "
                f"| **{fmt(d['theta'])}** | [{fmt(ci[0])}, {fmt(ci[1])}] "
                f"| {g(d['p_raw'])} | {g(d.get('q_bh'))} "
                f"| {('%+.2f%%' % d['pct_vol_change_per_treatment_unit']) if d.get('pct_vol_change_per_treatment_unit') is not None else 'n/a'} |"
            )
        L.append("")
        ols_absorbed = [
            r["estimates"][tname][h].get("confounding_absorbed_by_ols_controls_pct")
            for h in ("h1m", "h2m", "h3m")
        ]
        dml_absorbed = [
            r["estimates"][tname][h].get("confounding_absorbed_by_dml_pct")
            for h in ("h1m", "h2m", "h3m")
        ]
        if any(a is not None for a in ols_absorbed):
            L.append("Share of the naive association absorbed by linear controls: "
                     + ", ".join(f"{h[1]}m {a:.0f}%" for h, a in zip(("h1m", "h2m", "h3m"), ols_absorbed)
                                 if a is not None) + ".")
            L.append("Share absorbed by cross-fitted DML nuisance adjustment: "
                     + ", ".join(f"{h[1]}m {a:.0f}%" for h, a in zip(("h1m", "h2m", "h3m"), dml_absorbed)
                                 if a is not None) + ".")
            L.append("")

    # ---- multiple testing ---------------------------------------------------------------------
    if r.get("multiple_testing"):
        L.append("### 12.2 Multiple testing (family F1 = 3 horizons × 2 treatment definitions)")
        L.append("")
        L.append("| estimator | significant at raw p<0.05 | significant after BH (q<0.10) |")
        L.append("|---|---|---|")
        for e, blk in r["multiple_testing"].items():
            L.append(f"| {e} | {blk['n_significant_raw']}/{blk['m_hypotheses']} "
                     f"| {blk['n_significant_bh']}/{blk['m_hypotheses']} |")
        L.append("")

    # ---- subperiods ---------------------------------------------------------------------------
    if r.get("subperiods"):
        L.append("### 12.3 Sub-period stability (signed SUE, DML; family F2)")
        L.append("")
        L.append("Each cell is θ (BH q within the 9-cell F2 family).")
        L.append("")
        L.append("| sub-period | n | 1m | 2m | 3m |")
        L.append("|---|---|---|---|---|")
        for p, blk in r["subperiods"].items():
            if blk.get("status") == "TOO_SMALL":
                L.append(f"| {p} | {blk['n']} | — | — | — |")
                continue
            cells = [
                f"{fmt(blk[h]['theta'])} (q={g(blk[h].get('q_bh_F2'))})" if h in blk else "n/a"
                for h in ("h1m", "h2m", "h3m")
            ]
            L.append(f"| {p} | {blk['n']:,} | {cells[0]} | {cells[1]} | {cells[2]} |")
        L.append("")

    # ---- robustness ---------------------------------------------------------------------------
    if r.get("robustness"):
        L.append("### 12.4 Robustness (within-month = confirmatory F3; others descriptive)")
        L.append("")
        L.append("| spec | 1m | 2m | 3m |")
        L.append("|---|---|---|---|")
        for spec, blk in r["robustness"].items():
            cells = [
                (
                    f"{fmt(blk[h]['theta'])} (q={g(blk[h].get('q_bh_F3'))})"
                    if spec == "within_month_demeaned" and h in blk
                    else fmt(blk[h]["theta"]) if h in blk else "n/a"
                )
                for h in ("h1m", "h2m", "h3m")
            ]
            L.append(f"| {spec} | {cells[0]} | {cells[1]} | {cells[2]} |")
        L.append("")

    # ---- instrument ---------------------------------------------------------------------------
    iv = r.get("instrument_analysis", {})
    L.append("### 12.5 Instrument")
    L.append("")
    if iv.get("status") == "ESTIMATED":
        fs = iv["first_stage"]
        L.append(f"Candidate instrument: {iv['instrument']} (n = {iv['n']:,}).")
        L.append("")
        L.append(f"- **Relevance**: first-stage coefficient {fmt(fs['coef'])}, "
                 f"cluster-robust F = {fs['F_cluster_robust']:.2f} "
                 f"({'weak by the F<10 rule of thumb' if fs['weak_by_stock_yogo_rule_of_thumb'] else 'not weak by the F<10 rule of thumb'}).")
        L.append("- **Exclusion test** (pre-registered: |t| > 1.96 on the instrument in the "
                 "controlled outcome equation ⇒ invalid):")
        for h, e in iv["exclusion_test"].items():
            L.append(f"  - {h}: coefficient {fmt(e['coef_on_instrument'])}, t = {e['t']:+.2f}, "
                     f"p = {g(e['p'])} → "
                     f"{'**violates exclusion**' if e['violates_exclusion'] else 'does not reject exclusion'}")
        L.append("")
        L.append(f"**Instrument valid: `{iv['instrument_valid']}`.** {iv['interpretation']}")
        L.append("")
        if iv.get("tsls"):
            L.append("2SLS estimates (invalid-IV transparency diagnostic only; never causal):")
            L.append("")
            L.append("| horizon | 2SLS | 95% CI | raw p |")
            L.append("|---|---|---|---|")
            for h in ("h1m", "h2m", "h3m"):
                if h in iv["tsls"]:
                    t = iv["tsls"][h]
                    L.append(f"| {h[1]}m | {fmt(t['theta'])} | [{fmt(t['ci95'][0])}, "
                             f"{fmt(t['ci95'][1])}] | {g(t['p_raw'])} |")
            L.append("")
    else:
        L.append(f"Status: `{iv.get('status')}` — no 2SLS estimated.")
        L.append("")

    # ---- prereg checks ------------------------------------------------------------------------
    if r.get("prereg_checks"):
        L.append("### 12.6 Pre-registered criteria, applied verbatim")
        L.append("")
        for k, v in r["prereg_checks"].items():
            L.append(f"- `{k}`: **{v}**")
        L.append("")

    L.append(f"_Generated from `K1738_results.json` (code sha256 `{r['code_sha256'][:16]}…`, "
             f"runtime {r['runtime_seconds']:.0f}s, last checkpoint `{r['last_checkpoint']}`)._")
    L.append("")

    readme = HERE / "README.md"
    text = readme.read_text(encoding="utf-8")
    head = text.split(MARK)[0].rstrip() if MARK in text else text.rstrip()
    # drop the placeholder pointer section if present
    head = head.split("## 11. Results")[0].rstrip()
    readme.write_text(head + "\n\n## 11. Results\n\nSee `K1738_results.json`; the `verdict` field "
                      "there is authoritative. Section 12 below is generated mechanically from "
                      "that file by `render_readme_results.py`.\n\n" + "\n".join(L),
                      encoding="utf-8")
    print(f"README section 12 regenerated; verdict={r['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
