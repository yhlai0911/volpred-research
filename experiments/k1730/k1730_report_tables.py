"""
K1730 — render the README's result tables straight from the results JSON.

The README is part of the claim surface: the repo's certification gate hashes it
alongside the code precisely because overclaims reach humans through prose, not
through JSON. Hand-copying numbers into a write-up is how a table drifts from
the artifact it describes, so every number in the README's tables is emitted by
this script instead of typed.

Usage:  uv run python k1730_report_tables.py [--json <path>]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).parent
MACRO_ORDER = ["CPI", "NFP", "IP", "UNRATE", "VIX", "TERM"]


def _f(x, nd=4, dash="—"):
    if x is None:
        return dash
    try:
        return f"{float(x):.{nd}f}"
    except (TypeError, ValueError):
        return dash


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(HERE / "k1730_gevreg_midas_ssvs_results.json"))
    args = ap.parse_args()
    r = json.load(open(args.json))

    oos = r["oos"]
    models = list(oos["by_model"].keys())
    out = []

    out.append(f"OOS sample: {oos['n_common_oos']} weekly blocks, "
               f"{oos['oos_start']} → {oos['oos_end']}\n")

    # ---- main results table ------------------------------------------------
    out.append("### Table 1 — Full out-of-sample period\n")
    out.append("| Model | Pinball | 90% cov. | below/above | Kupiec p | CC p | "
               "VaR95 rate | VaR99 rate | PIT χ² p |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for m in models:
        e = oos["by_model"][m]
        iv = e["intervals"]["0.90"]
        v95, v99 = e["var_levels"]["0.950"], e["var_levels"]["0.990"]
        out.append(
            f"| {m} | {_f(e['mean_pinball'], 5)} | {_f(iv['empirical_coverage'], 3)} | "
            f"{iv['below_lower']}/{iv['above_upper']} | {_f(iv['kupiec_uc']['p_value'], 4)} | "
            f"{_f(iv['christoffersen_cc']['p_value'], 4)} | "
            f"{_f(v95['empirical_exceedance_rate'], 4)} | "
            f"{_f(v99['empirical_exceedance_rate'], 4)} | "
            f"{e['pit']['chi2_p_value']:.2e} |")
    out.append("\n*Nominal: 90% coverage, ~48/48 two-sided exceedances, "
               "VaR95 rate 0.050, VaR99 rate 0.010.*\n")

    # ---- DM table ----------------------------------------------------------
    out.append("### Table 2 — Diebold-Mariano, GEVReg-MIDAS-SSVS vs each benchmark\n")
    out.append("*Pinball loss averaged over the τ grid; repo-canonical HAC "
               "bandwidth; Harvey (2016) threshold |t| > 3.*\n")
    out.append("| Comparison | t | p | HAC lag | acf(1) | Favours | Harvey-sig |")
    out.append("|---|---:|---:|---:|---:|---|---|")
    for k, v in oos["dm_tests"].items():
        bench = k.split("_vs_")[-1]
        out.append(
            f"| vs {bench} | {_f(v['t_stat'], 2)} | {_f(v['p_value'], 4)} | "
            f"{v['canonical_hac_lag']} | {_f(v['loss_diff_acf_1_to_5'][0], 3)} | "
            f"{v['favours']} | {'yes' if v['harvey_significant'] else 'no'} |")
    out.append("")

    # ---- ES table ----------------------------------------------------------
    out.append("### Table 3 — Expected-shortfall backtest (McNeil-Frey, bootstrapped)\n")
    out.append("| Model | Level | Exceedances | Mean residual | p |")
    out.append("|---|---:|---:|---:|---:|")
    for m in models:
        for lev in ("0.950", "0.990"):
            es = oos["by_model"][m]["var_levels"][lev].get("expected_shortfall", {})
            if "note" in es:
                out.append(f"| {m} | {lev} | — | — | not identified |")
                continue
            out.append(f"| {m} | {lev} | {es.get('n_exceedances', '—')} | "
                       f"{_f(es.get('mean_residual'), 4)} | {_f(es.get('p_value'), 4)} |")
    out.append("")

    # ---- subperiods --------------------------------------------------------
    out.append("### Table 4 — Subperiods (pinball / 90% coverage)\n")
    subs = [s for s in oos["subperiods"] if "by_model" in oos["subperiods"][s]]
    out.append("| Model | " + " | ".join(f"{s} (n={oos['subperiods'][s]['n']})"
                                         for s in subs) + " |")
    out.append("|---" * (len(subs) + 1) + "|")
    for m in models:
        cells = []
        for s in subs:
            b = oos["subperiods"][s]["by_model"][m]
            cells.append(f"{_f(b['mean_pinball'], 4)} / "
                         f"{_f(b['coverage_0.90']['empirical_coverage'], 3)}")
        out.append(f"| {m} | " + " | ".join(cells) + " |")
    out.append("")

    out.append("### Table 5 — Subperiod DM vs GEV-HAR (no macro)\n")
    out.append("| Subperiod | t | p | Favours |")
    out.append("|---|---:|---:|---|")
    for s in subs:
        d = oos["subperiods"][s]["dm_tests"].get("GEVReg-MIDAS-SSVS_vs_GEV-HAR")
        if d:
            out.append(f"| {s} | {_f(d['t_stat'], 2)} | {_f(d['p_value'], 4)} | "
                       f"{d['favours']} |")
    out.append("")

    # ---- SSVS --------------------------------------------------------------
    ss = r.get("ssvs_summary", {})
    if ss:
        out.append("### Table 6 — SSVS posterior inclusion probabilities\n")
        out.append("| Variable | Mean PIP | Min | Max | Refits with PIP>0.5 |")
        out.append("|---|---:|---:|---:|---:|")
        for v in MACRO_ORDER:
            out.append(f"| {v} | {_f(ss['mean_pip'][v], 3)} | {_f(ss['min_pip'][v], 3)} | "
                       f"{_f(ss['max_pip'][v], 3)} | "
                       f"{ss['n_refits_pip_above_half'][v]}/{ss['n_refits_with_ssvs']} |")
        out.append(f"\nMCMC diagnostics across all refits: worst R-hat "
                   f"{_f(ss['worst_rhat'], 3)}, worst |Geweke z| "
                   f"{_f(ss['worst_geweke_abs_z'], 2)} (ACF-sized bandwidth; "
                   f"{_f(ss.get('worst_geweke_abs_z_fixed_bandwidth'), 2)} under the "
                   f"fixed Newey-West rule), min ESS {_f(ss['min_ess'], 0)}, "
                   f"max cross-chain PIP spread "
                   f"{_f(ss.get('max_pip_chain_spread'), 3)}.")
        tier = ss.get("inference_tier", "unknown")
        out.append(f"\n**Inference tier: {tier.upper()}** — "
                   f"{ss.get('n_refits_meeting_convergence_gate', 0)}/"
                   f"{ss['n_refits_with_ssvs']} refits meet the pre-registered "
                   f"convergence gate {ss.get('convergence_gate')}. "
                   + (ss.get("inference_tier_note", "") if tier != "inference" else "")
                   + "\n")

    mle = r.get("mle_convergence_summary", {})
    if mle:
        out.append("### Table 7 — GEV MLE multistart diagnostics\n")
        out.append(f"- Feasible *starting points*: min "
                   f"{_f(mle['min_feasible_start_rate'], 3)}, mean "
                   f"{_f(mle['mean_feasible_start_rate'], 3)} — a property of the "
                   f"random start distribution, not of the likelihood surface")
        out.append(f"- Starts reaching a feasible *optimum*: min "
                   f"{_f(mle['min_feasible_optimum_rate'], 3)}, mean "
                   f"{_f(mle['mean_feasible_optimum_rate'], 3)}")
        out.append(f"- Basin concentration (feasible optima reaching the best one): "
                   f"min {_f(mle['min_basin_concentration'], 3)}, mean "
                   f"{_f(mle['mean_basin_concentration'], 3)} — this is the only "
                   f"figure here that speaks to multiple optima")
        out.append(f"- Fewest starts reaching the best basin: {mle['min_starts_at_best_basin']} "
                   f"of {r['config']['n_starts']}")
        out.append(f"- All Hessians positive definite: {mle['all_hessians_positive_definite']}")
        out.append(f"- Max Hessian condition number: {_f(mle['max_hessian_condition'], 0)}")
        out.append(f"- Max Nelder-Mead improvement over L-BFGS-B: "
                   f"{mle['max_nelder_mead_improvement']:.2e}")
        out.append(f"- Estimated ξ range across refits: "
                   f"[{_f(mle['xi_range'][0], 3)}, {_f(mle['xi_range'][1], 3)}]\n")

    # ---- placebo -----------------------------------------------------------
    p = r.get("placebo_test")
    if p:
        out.append("### Table 8 — Non-circular lag-shift placebo\n")
        out.append(f"Macro history re-attached at lags {p['shifts_weeks']} weeks; "
                   f"{p['matched_sample_blocks']} blocks scored in every arm "
                   f"(first {p['blocks_dropped_from_every_arm']} dropped "
                   f"from all arms alike).\n")
        out.append("| Arm | Mean pinball |")
        out.append("|---|---:|")
        out.append(f"| real macro (matched sample) | "
                   f"{_f(p['mean_pinball_real_matched'], 5)} |")
        for k, v in sorted(p["mean_pinball_placebo"].items()):
            out.append(f"| {k} | {_f(v, 5)} |")
        out.append(f"| GEV-HAR, no macro at all | "
                   f"{_f(p['mean_pinball_gev_har_no_macro'], 5)} |")
        out.append(f"\n- Placebo arms at least as good as real: "
                   f"{p['n_placebo_at_least_as_good_as_real']}/{p['n_placebo_arms']}"
                   f" → one-sided p = {_f(p['one_sided_p_value'], 3)}")
        out.append(f"- {p['p_value_resolution_note']}")
        ok = all(v["passed"] for v in
                 p["lookahead_recheck_on_shifted_stamps"].values())
        out.append(f"- Point-in-time check re-run on every shifted macro "
                   f"history: {'0 violations' if ok else 'VIOLATIONS PRESENT'}")
        out.append(f"\n{p['interpretation']}\n")

    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
