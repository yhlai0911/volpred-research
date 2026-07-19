#!/usr/bin/env python3
"""Paper 8 (volatility-absorption) reproducibility gate for active v3 scope.

2026-07-14 P0-4 rewrite (after K1686 R2 adjudication):
  - K897 bindings retired together with the lagged-proxy simulation (the paper no
    longer prints its interval; Section null_reexam explains the retirement).
  - Table 2 / Table 3 now bind to results/table3_sar_inference.json (P0-3 rebuild:
    pinned snapshot + paired circular moving-block bootstrap, Codex-R2-approved design).
  - New bindings: K1686 contemporaneous-null section, NFP overall ratios (k741),
    Table 4 0050.TW pinned row (C3), Appendix B alpha / adj-R2 (C4, k1418).
No live data fetch. Every check compares a printed manuscript number to its JSON source.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent.parent
PAPER_DIR = Path(__file__).resolve().parent
REPORT_PATH = PAPER_DIR / "reproduce_report.json"


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text())


def rel_diff(actual: float, paper: float) -> float:
    if paper == 0:
        return 0.0
    return abs(actual - paper) / abs(paper) * 100


def approx(actual: float, paper: float, tol_pct: float) -> bool:
    if paper == 0:
        return abs(actual) < 1e-12
    return rel_diff(actual, paper) <= tol_pct


def main() -> int:
    # Canonical BLS-calendar re-run (2026-07-19). The archived proxy JSON at
    # PAPER_DIR/experiments/k741_nfp_event_study_results.json is retained for history but is
    # NO LONGER the gate source: it identifies NFP days by a first-Friday proxy.
    k741 = load_json(PROJECT / "experiments" / "k741" / "k741_nfp_event_study_canonical_results.json")
    k903 = load_json(PROJECT / "experiments" / "k903" / "k903_paper8_robustness_results.json")
    k1418 = load_json(PROJECT / "experiments" / "k1418" / "k1418_results.json")
    k1686 = load_json(PROJECT / "experiments" / "k1686" / "k1686_contemporaneous_null_results.json")
    t3 = load_json(PAPER_DIR / "results" / "table3_sar_inference.json")

    cross_asset = {row["asset"]: row for row in k1418["results"]}
    t3t = t3["table3"]
    t3p = t3["decline_inference_primary"]
    sdc = k1686["sar_decline_comparison"]
    gate = k1686["codex_followup_gate"]
    nfe = k1686["null_free_evidence"]
    mech = k1686["mechanism_diagnostic_within_regime_shock_rate"]
    calib = k1686["calibration_diagnostics"]
    nfp = k741["part_a_historical"]
    nfp_reg = k741["part_b_vix_regimes"]
    nfp_dec = k741["factor_decomposition"]
    nfp_rdt = k741["regime_difference_test"]
    nfp_cells = k741["factorial_cells"]

    claims = [
        # ---- Table 2: regime distribution (pinned; days = n_shock + n_normal) ----
        ("T2 calm days", 1755.0, float(t3t["calm"]["n_shock"] + t3t["calm"]["n_normal"]), 0.0, "table3_sar_inference.table3.calm.n_shock+n_normal"),
        ("T2 normal days", 1571.0, float(t3t["normal"]["n_shock"] + t3t["normal"]["n_normal"]), 0.0, "table3_sar_inference.table3.normal"),
        ("T2 elevated days", 885.0, float(t3t["elevated"]["n_shock"] + t3t["elevated"]["n_normal"]), 0.0, "table3_sar_inference.table3.elevated"),
        ("T2 high days", 432.0, float(t3t["high"]["n_shock"] + t3t["high"]["n_normal"]), 0.0, "table3_sar_inference.table3.high"),
        ("T2 crisis days", 449.0, float(t3t["crisis"]["n_shock"] + t3t["crisis"]["n_normal"]), 0.0, "table3_sar_inference.table3.crisis"),
        ("T2 total shock days", 768.0, float(t3["data"]["n_shock_days"]), 0.0, "table3_sar_inference.data.n_shock_days"),
        ("T2 total days", 5092.0, float(t3["data"]["n_days"]), 0.0, "table3_sar_inference.data.n_days"),
        # ---- Table 3: SAR by regime (P0-3 rebuild, pinned snapshot) ----
        ("T3 calm SAR", 3.15, t3t["calm"]["sar"], 1.0, "table3_sar_inference.table3.calm.sar"),
        ("T3 normal SAR", 2.77, t3t["normal"]["sar"], 1.0, "table3_sar_inference.table3.normal.sar"),
        ("T3 elevated SAR", 2.38, t3t["elevated"]["sar"], 1.0, "table3_sar_inference.table3.elevated.sar"),
        ("T3 high SAR", 2.33, t3t["high"]["sar"], 1.0, "table3_sar_inference.table3.high.sar"),
        ("T3 crisis SAR", 2.45, t3t["crisis"]["sar"], 1.0, "table3_sar_inference.table3.crisis.sar"),
        ("T3 calm shock days", 34.0, float(t3t["calm"]["n_shock"]), 0.0, "table3_sar_inference.table3.calm.n_shock"),
        ("T3 high shock days", 133.0, float(t3t["high"]["n_shock"]), 0.0, "table3_sar_inference.table3.high.n_shock"),
        ("T3 calm mean shock |r|", 1.23, t3t["calm"]["mean_abs_ret_shock"], 1.0, "table3_sar_inference.table3.calm.mean_abs_ret_shock"),
        ("T3 crisis mean shock |r|", 3.00, t3t["crisis"]["mean_abs_ret_shock"], 1.0, "table3_sar_inference.table3.crisis.mean_abs_ret_shock"),
        # delta CI printed as [SAR_j - SAR_calm]; JSON stores calm - SAR_j (sign flipped)
        ("T3 high dSAR CI lo (|.|)", 1.33, t3p["high"]["ci95"][1], 2.0, "table3_sar_inference.decline_inference_primary.high.ci95[1]"),
        ("T3 high dSAR CI hi (|.|)", 0.29, t3p["high"]["ci95"][0], 3.0, "table3_sar_inference.decline_inference_primary.high.ci95[0]"),
        ("T3 high dSAR p", 0.003, t3p["high"]["p_two_sided"], 2.0, "table3_sar_inference.decline_inference_primary.high.p_two_sided"),
        ("T3 normal dSAR p", 0.103, t3p["normal"]["p_two_sided"], 2.0, "table3_sar_inference.decline_inference_primary.normal.p_two_sided"),
        ("T3 crisis dSAR p", 0.012, t3p["crisis"]["p_two_sided"], 2.0, "table3_sar_inference.decline_inference_primary.crisis.p_two_sided"),
        ("T3 elevated dSAR CI lo (|.|)", 1.27, t3p["elevated"]["ci95"][1], 2.0, "table3_sar_inference.decline_inference_primary.elevated.ci95[1]"),
        ("T3 elevated dSAR CI hi (|.|)", 0.32, t3p["elevated"]["ci95"][0], 2.0, "table3_sar_inference.decline_inference_primary.elevated.ci95[0]"),
        ("Headline decline 0.82", 0.82, t3t["calm"]["sar"] - t3t["high"]["sar"], 1.0, "table3_sar_inference (calm.sar - high.sar)"),
        # ---- Section null_reexam: K1686 contemporaneous re-examination ----
        ("K1686 lagged-arm mean", 0.17, k1686["k897_replication_check"]["ours"]["sim_mean"], 3.0, "k1686.k897_replication_check.ours.sim_mean"),
        ("K1686 lagged-arm CI lo", -0.28, k1686["k897_replication_check"]["ours"]["sim_ci_95"][0], 2.0, "k1686.k897_replication_check.ours.sim_ci_95[0]"),
        ("K1686 lagged-arm CI hi", 0.56, k1686["k897_replication_check"]["ours"]["sim_ci_95"][1], 2.0, "k1686.k897_replication_check.ours.sim_ci_95[1]"),
        ("K1686 A null mean", 0.62, sdc["contemporaneous|A"]["sim_mean"], 1.0, "k1686.sar_decline_comparison[contemporaneous|A].sim_mean"),
        ("K1686 A CI lo", 0.08, sdc["contemporaneous|A"]["sim_ci_95"][0], 3.0, "k1686...A.sim_ci_95[0]"),
        ("K1686 A CI hi", 1.06, sdc["contemporaneous|A"]["sim_ci_95"][1], 1.0, "k1686...A.sim_ci_95[1]"),
        ("K1686 A MC p", 0.41, sdc["contemporaneous|A"]["p_value_monte_carlo"], 1.0, "k1686...A.p_value_monte_carlo"),
        ("K1686 A empirical", 0.82, sdc["contemporaneous|A"]["empirical"], 1.0, "k1686...A.empirical"),
        ("K1686 null crisis shock rate", 0.82, mech["sim_contemporaneous_A"][4], 1.0, "k1686.mechanism_diagnostic...sim_contemporaneous_A[4]"),
        ("K1686 emp crisis shock rate", 0.54, mech["empirical"][4], 1.0, "k1686.mechanism_diagnostic...empirical[4]"),
        ("K1686 null calm occupancy", 0.77, calib["regime_occupancy_sim_A_contemporaneous"][0], 1.0, "k1686.calibration_diagnostics.regime_occupancy_sim_A[0]"),
        ("K1686 emp calm occupancy", 0.35, calib["regime_occupancy_empirical"][0], 2.0, "k1686.calibration_diagnostics.regime_occupancy_empirical[0]"),
        ("K1686 C empirical decline", 0.34, sdc["contemporaneous|C"]["empirical"], 1.0, "k1686...C.empirical"),
        ("K1686 threshold share 58%", 0.58, 1.0 - sdc["contemporaneous|C"]["empirical"] / sdc["contemporaneous|A"]["empirical"], 2.0, "k1686 derived: 1 - C.empirical/A.empirical"),
        ("K1686 D-up current decline", -0.12, nfe["up_only_current_regime_decline"], 5.0, "k1686.null_free_evidence.up_only_current_regime_decline"),
        ("K1686 H ambient-up decline", 1.05, gate["empirical_ambient_up"]["point_estimate"], 1.0, "k1686.codex_followup_gate.empirical_ambient_up.point_estimate"),
        ("K1686 H CI lo", 0.33, gate["empirical_ambient_up"]["ci95"][0], 1.0, "k1686.codex_followup_gate.empirical_ambient_up.ci95[0]"),
        ("K1686 H CI hi", 1.76, gate["empirical_ambient_up"]["ci95"][1], 1.0, "k1686.codex_followup_gate.empirical_ambient_up.ci95[1]"),
        ("K1686 H calm SAR", 3.89, k1686["regime_sar"]["contemporaneous|H_up"]["calm (<15)"]["empirical"], 1.0, "k1686.regime_sar[H_up].calm.empirical"),
        ("K1686 H high SAR", 2.84, k1686["regime_sar"]["contemporaneous|H_up"]["high (25-30)"]["empirical"], 1.0, "k1686.regime_sar[H_up].high.empirical"),
        ("K1686 H n calm up", 47.0, float(nfe["n_calm_up_shocks_ambient_regime"]), 0.0, "k1686.null_free_evidence.n_calm_up_shocks_ambient_regime"),
        ("K1686 H n high up", 53.0, float(nfe["n_high_up_shocks_ambient_regime"]), 0.0, "k1686.null_free_evidence.n_high_up_shocks_ambient_regime"),
        ("K1686 paired pooled-up", 0.94, gate["paired_pooled_minus_up_current"]["point_estimate"], 1.0, "k1686.codex_followup_gate.paired_pooled_minus_up_current.point_estimate"),
        ("K1686 paired CI lo", 0.34, gate["paired_pooled_minus_up_current"]["ci95"][0], 2.0, "k1686.codex_followup_gate.paired_pooled_minus_up_current.ci95[0]"),
        ("K1686 paired CI hi", 1.50, gate["paired_pooled_minus_up_current"]["ci95"][1], 1.0, "k1686.codex_followup_gate.paired_pooled_minus_up_current.ci95[1]"),
        ("K1686 same-seed null CI lo", -0.66, gate["same_seed_null_comparison"]["sim_ci_95"][0], 1.0, "k1686.codex_followup_gate.same_seed_null_comparison.sim_ci_95[0]"),
        ("K1686 same-seed null CI hi", 0.99, gate["same_seed_null_comparison"]["sim_ci_95"][1], 1.0, "k1686.codex_followup_gate.same_seed_null_comparison.sim_ci_95[1]"),
        ("K1686 same-seed MC p", 0.033, gate["same_seed_null_comparison"]["p_value_monte_carlo"], 2.0, "k1686.codex_followup_gate.same_seed_null_comparison.p_value_monte_carlo"),
        ("K1686 P* down-shock bound", 28.8, k1686["down_shock_impossibility"]["min_level_for_a_2pt_one_day_fall"], 1.0, "k1686.down_shock_impossibility.min_level_for_a_2pt_one_day_fall"),
        ("K1686 F shock rate", 0.060, calib["shock_rate_sim_F"], 2.0, "k1686.calibration_diagnostics.shock_rate_sim_F"),
        ("K1686 emp shock rate", 0.151, calib["shock_rate_empirical"], 1.0, "k1686.calibration_diagnostics.shock_rate_empirical"),
        # ---- Table 4 / cross-asset (pinned, C3) ----
        ("T4 SPY beta", -0.000273, cross_asset["SPY"]["beta"], 1.0, "k1418.results[SPY].beta"),
        ("T4 SPY t", -1.85, cross_asset["SPY"]["beta_t"], 2.0, "k1418.results[SPY].beta_t"),
        ("T4 GLD beta", -0.000434, cross_asset["GLD"]["beta"], 1.0, "k1418.results[GLD].beta"),
        ("T4 GLD t", -2.90, cross_asset["GLD"]["beta_t"], 2.0, "k1418.results[GLD].beta_t"),
        ("T4 TLT beta", -0.000437, cross_asset["TLT"]["beta"], 1.0, "k1418.results[TLT].beta"),
        ("T4 TLT t", -3.31, cross_asset["TLT"]["beta_t"], 2.0, "k1418.results[TLT].beta_t"),
        ("T4 0050 beta", 0.000092, cross_asset["0050.TW"]["beta"], 2.0, "k1418.results[0050.TW].beta"),
        ("T4 0050 t", 0.28, cross_asset["0050.TW"]["beta_t"], 2.0, "k1418.results[0050.TW].beta_t"),
        # ---- Appendix B alpha / adj-R2 (C4) ----
        ("AppB SPY alpha", 0.0822, cross_asset["SPY"]["alpha"], 1.0, "k1418.results[SPY].alpha"),
        ("AppB GLD alpha", 0.0548, cross_asset["GLD"]["alpha"], 1.0, "k1418.results[GLD].alpha"),
        ("AppB TLT alpha", 0.0531, cross_asset["TLT"]["alpha"], 1.0, "k1418.results[TLT].alpha"),
        ("AppB 0050 alpha", 0.0473, cross_asset["0050.TW"]["alpha"], 1.0, "k1418.results[0050.TW].alpha"),
        ("AppB SPY adjR2", 0.0076, cross_asset["SPY"]["r2_adj"], 3.0, "k1418.results[SPY].r2_adj"),
        ("AppB GLD adjR2", 0.0142, cross_asset["GLD"]["r2_adj"], 3.0, "k1418.results[GLD].r2_adj"),
        ("AppB TLT adjR2", 0.0290, cross_asset["TLT"]["r2_adj"], 3.0, "k1418.results[TLT].r2_adj"),
        ("AppB 0050 adjR2", -0.0013, cross_asset["0050.TW"]["r2_adj"], 5.0, "k1418.results[0050.TW].r2_adj"),
        # ---- Table 5 / NFP (C5) ----
        # Rebound 2026-07-19 onto the canonical BLS-calendar re-run (task assign_1238781f).
        # The old bindings pointed at the archived first-Friday-proxy JSON, which misdates 33 of
        # 194 releases and invents an Oct-2025 event; they also never covered the regime
        # ratio/t/p columns, which is why those three columns drifted unnoticed. All six
        # regime columns are bound now.
        ("T5 NFP ratio vs all", 1.16, nfp["ratio_vs_all"], 1.0, "k741c.part_a_historical.ratio_vs_all"),
        ("T5 NFP p vs all", 0.051, nfp["p_vs_all"], 2.0, "k741c.part_a_historical.p_vs_all"),
        ("T5 NFP ratio vs Friday", 1.19, nfp["ratio_vs_friday"], 1.0, "k741c.part_a_historical.ratio_vs_friday"),
        ("T5 NFP p vs Friday", 0.034, nfp["p_vs_friday"], 2.0, "k741c.part_a_historical.p_vs_friday"),
        ("T5 NFP n", 194.0, float(nfp["n_nfp"]), 0.0, "k741c.part_a_historical.n_nfp"),
        ("T5 NFP total days 4084", 4084.0, float(nfp["n_nfp"] + nfp["n_non_nfp"]), 0.0, "k741c.part_a_historical n_nfp+n_non_nfp"),
        ("T5 Low NFP n", 63.0, float(nfp_reg["Low (VIX<15)"]["n"]), 0.0, "k741c.part_b_vix_regimes.Low.n"),
        ("T5 Low NFP mean abs", 0.527, nfp_reg["Low (VIX<15)"]["mean_abs_return_pct"], 1.0, "k741c.part_b_vix_regimes.Low.mean_abs_return_pct"),
        ("T5 Low NFP ratio", 1.31, nfp_reg["Low (VIX<15)"]["ratio"], 1.0, "k741c.part_b_vix_regimes.Low.ratio"),
        ("T5 Low NFP t", 2.62, nfp_reg["Low (VIX<15)"]["t_stat"], 2.0, "k741c.part_b_vix_regimes.Low.t_stat"),
        ("T5 Low NFP p", 0.009, nfp_reg["Low (VIX<15)"]["p_value"], 3.0, "k741c.part_b_vix_regimes.Low.p_value"),
        ("T5 Medium NFP n", 76.0, float(nfp_reg["Medium (15-20)"]["n"]), 0.0, "k741c.part_b_vix_regimes.Medium.n"),
        ("T5 Medium NFP mean abs", 0.788, nfp_reg["Medium (15-20)"]["mean_abs_return_pct"], 1.0, "k741c.part_b_vix_regimes.Medium.mean_abs_return_pct"),
        ("T5 Medium NFP ratio", 1.23, nfp_reg["Medium (15-20)"]["ratio"], 1.0, "k741c.part_b_vix_regimes.Medium.ratio"),
        ("T5 Medium NFP t", 2.22, nfp_reg["Medium (15-20)"]["t_stat"], 2.0, "k741c.part_b_vix_regimes.Medium.t_stat"),
        ("T5 Medium NFP p", 0.027, nfp_reg["Medium (15-20)"]["p_value"], 3.0, "k741c.part_b_vix_regimes.Medium.p_value"),
        ("T5 Elevated NFP n", 27.0, float(nfp_reg["Elevated (20-25)"]["n"]), 0.0, "k741c.part_b_vix_regimes.Elevated.n"),
        ("T5 Elevated NFP mean abs", 1.046, nfp_reg["Elevated (20-25)"]["mean_abs_return_pct"], 1.0, "k741c.part_b_vix_regimes.Elevated.mean_abs_return_pct"),
        ("T5 Elevated NFP ratio", 1.19, nfp_reg["Elevated (20-25)"]["ratio"], 1.0, "k741c.part_b_vix_regimes.Elevated.ratio"),
        ("T5 Elevated NFP t", 1.14, nfp_reg["Elevated (20-25)"]["t_stat"], 3.0, "k741c.part_b_vix_regimes.Elevated.t_stat"),
        ("T5 Elevated NFP p", 0.253, nfp_reg["Elevated (20-25)"]["p_value"], 1.0, "k741c.part_b_vix_regimes.Elevated.p_value"),
        ("T5 High NFP n", 28.0, float(nfp_reg["High (VIX>=25)"]["n"]), 0.0, "k741c.part_b_vix_regimes.High.n"),
        ("T5 High NFP mean abs", 1.417, nfp_reg["High (VIX>=25)"]["mean_abs_return_pct"], 1.0, "k741c.part_b_vix_regimes.High.mean_abs_return_pct"),
        ("T5 High NFP ratio", 0.94, nfp_reg["High (VIX>=25)"]["ratio"], 1.0, "k741c.part_b_vix_regimes.High.ratio"),
        ("T5 High NFP t", -0.34, nfp_reg["High (VIX>=25)"]["t_stat"], 3.0, "k741c.part_b_vix_regimes.High.t_stat"),
        ("T5 High NFP p", 0.731, nfp_reg["High (VIX>=25)"]["p_value"], 1.0, "k741c.part_b_vix_regimes.High.p_value"),
        # sec:nfp footnote quotes the date-effect decomposition, which is NOT the headline cell.
        # Bound explicitly so the footnote cannot go stale while the gate stays green.
        ("T5 fn date-effect from 1.149", 1.149, nfp_dec["date_effect_at_archived_mapper"]["ratio"][0], 1.0, "k741c.factor_decomposition.date_effect_at_archived_mapper.ratio[0]"),
        ("T5 fn date-effect to 1.151", 1.151, nfp_dec["date_effect_at_archived_mapper"]["ratio"][1], 1.0, "k741c.factor_decomposition.date_effect_at_archived_mapper.ratio[1]"),
        # sec:nfp regime-contrast test (difference-in-significance correction)
        ("T5 regime diff point est", 0.37, nfp_rdt["observed_difference"], 3.0, "k741c.regime_difference_test.observed_difference"),
        ("T5 regime diff CI lo", -0.10, nfp_rdt["ci95"][0], 5.0, "k741c.regime_difference_test.ci95[0]"),
        ("T5 regime diff CI hi", 0.79, nfp_rdt["ci95"][1], 2.0, "k741c.regime_difference_test.ci95[1]"),
        ("T5 regime diff p", 0.115, nfp_rdt["p_two_sided"], 2.0, "k741c.regime_difference_test.p_two_sided"),
        ("T5 regime trend rho observed", -1.00, nfp_rdt["observed_spearman_trend"], 1.0, "k741c.regime_difference_test.observed_spearman_trend"),
        ("T5 regime trend rho boot mean", -0.63, nfp_rdt["spearman_trend_mean"], 3.0, "k741c.regime_difference_test.spearman_trend_mean"),
        # Mapping completeness: headline cell must consume every official release.
        ("T5 headline releases mapped", 194.0, float(nfp_cells["official__forward_mapper"]["n_mapped"]), 0.0, "k741c.factorial_cells.official__forward_mapper.n_mapped"),
        ("T5 headline zero exclusions", 0.0, float(len(nfp_cells["official__forward_mapper"]["excluded_releases"])), 0.0, "k741c.factorial_cells.official__forward_mapper.excluded_releases"),
        ("T5 headline zero lookahead", 0.0, float(len(nfp_cells["official__forward_mapper"]["backward_mapped_lookahead_events"])), 0.0, "k741c.factorial_cells.official__forward_mapper.backward_mapped_lookahead_events"),
        # ---- NSI baseline / thresholds / subperiods / RV / controlled (k903, unchanged) ----
        ("Baseline beta", -0.000267, k903["baseline_regression"]["beta_hat"], 1.0, "k903.baseline_regression.beta_hat"),
        ("Baseline t", -1.77, k903["baseline_regression"]["t_stat_NW"], 2.0, "k903.baseline_regression.t_stat_NW"),
        ("T9 tau=2 N", 768.0, float(k903["task2_table9_alternative_thresholds"]["2.0"]["N_shock"]), 0.0, "k903.task2_table9_alternative_thresholds.2.0.N_shock"),
        ("T9 tau=3 beta", -0.000311, k903["task2_table9_alternative_thresholds"]["3.0"]["beta_hat"], 1.0, "k903.task2_table9_alternative_thresholds.3.0.beta_hat"),
        ("T10 2006-2012 beta", -0.000408, k903["task2_table10_subperiod"]["2006-2012 (GFC era)"]["beta_hat"], 1.0, "k903.task2_table10_subperiod.2006-2012.beta_hat"),
        ("T10 2020-2026 beta", 0.000141, k903["task2_table10_subperiod"]["2020-2026 (COVID era)"]["beta_hat"], 1.0, "k903.task2_table10_subperiod.2020-2026.beta_hat"),
        ("RV-normalized beta", -0.01249, k903["task2_rv_normalization"]["beta_hat"], 1.0, "k903.task2_rv_normalization.beta_hat"),
        ("RV-normalized t", -8.2, k903["task2_rv_normalization"]["t_stat_NW"], 1.0, "k903.task2_rv_normalization.t_stat_NW"),
        ("Controlled beta", -0.000216, k903["task2_controlled_regression"]["beta_VIX"], 1.0, "k903.task2_controlled_regression.beta_VIX"),
        ("Controlled t", -1.26, k903["task2_controlled_regression"]["t_stat_VIX"], 2.0, "k903.task2_controlled_regression.t_stat_VIX"),
    ]

    checks = []
    for metric, paper_value, actual_value, tol_pct, source_path in claims:
        checks.append(
            {
                "metric": metric,
                "paper_value": paper_value,
                "actual_value": actual_value,
                "tol_pct": tol_pct,
                "rel_diff_pct": rel_diff(actual_value, paper_value),
                "status": "match" if approx(actual_value, paper_value, tol_pct) else "mismatch",
                "source_path": source_path,
            }
        )

    # Threshold-style claims (printed as inequalities, checked as booleans)
    bool_claims = [
        ("T3 elevated dSAR p < 0.001", t3p["elevated"]["p_two_sided"] < 0.001, "table3_sar_inference.decline_inference_primary.elevated.p_two_sided"),
        ("K1686 B/C/G all reject p<=0.007", max(sdc["contemporaneous|B"]["p_value_monte_carlo"], sdc["contemporaneous|C"]["p_value_monte_carlo"], sdc["contemporaneous|G"]["p_value_monte_carlo"]) <= 0.007, "k1686 B/C/G p_value_monte_carlo"),
        ("K1686 H CI excludes zero", gate["empirical_ambient_up"]["ci95"][0] > 0, "k1686.codex_followup_gate.empirical_ambient_up.ci95"),
        ("K1686 A in null CI (not rejected)", bool(sdc["contemporaneous|A"]["in_95_ci"]), "k1686...A.in_95_ci"),
        ("T3 block sensitivity same conclusion", all(
            (t3["decline_inference_by_block"][b]["normal"]["ci95"][0] < 0 < t3["decline_inference_by_block"][b]["normal"]["ci95"][1])
            and all(t3["decline_inference_by_block"][b][r]["ci95"][0] > 0 for r in ("elevated", "high", "crisis"))
            for b in ("10", "20", "40", "63")
        ), "table3_sar_inference.decline_inference_by_block"),
    ]
    for metric, ok, source_path in bool_claims:
        checks.append(
            {
                "metric": metric,
                "paper_value": True,
                "actual_value": bool(ok),
                "tol_pct": 0.0,
                "rel_diff_pct": 0.0 if ok else 100.0,
                "status": "match" if ok else "mismatch",
                "source_path": source_path,
            }
        )

    total = len(checks)
    matched = sum(1 for c in checks if c["status"] == "match")
    match_rate = matched / total * 100 if total else 0.0
    alert_level = "green" if match_rate >= 95 else ("amber" if match_rate >= 80 else "red")

    # A 95% rate is a health metric, not a reproducibility certification: with 112 checks it
    # tolerates 5 wrong numbers, so a broken headline can be diluted by unrelated passing rows.
    # Demonstrated adversarially (Codex round-2): forcing the headline p from 0.0506 to 0.20
    # still returned 111/112, gate=pass, exit 0. Any mismatch now fails the gate.
    mismatched = [c["metric"] for c in checks if c["status"] != "match"]
    gate_status = "pass" if not mismatched else "fail"

    print(f"{'Metric':<38} {'Paper':>12} {'Actual':>12} {'diff %':>8} {'status':>10}")
    print("-" * 88)
    for c in checks:
        pv = c["paper_value"]
        av = c["actual_value"]
        pv_s = f"{pv:>12.6f}" if isinstance(pv, float) else f"{str(pv):>12}"
        av_s = f"{av:>12.6f}" if isinstance(av, float) else f"{str(av):>12}"
        print(f"{c['metric'][:36]:<38} {pv_s} {av_s} {c['rel_diff_pct']:>7.2f}% {c['status']:>10}")
    print("-" * 88)
    print(f"Matched: {matched}/{total}  rate: {match_rate:.1f}%  alert: {alert_level}  gate: {gate_status}")
    if mismatched:
        print(f"[gate] FAIL — every bound number must match. Mismatched: {', '.join(mismatched)}")

    report = {
        "paper": "volatility-absorption",
        "paper_version": "v3-active-scope-post-k1686",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "alert_level": alert_level,
        "gate_status": gate_status,
        "match_rate": round(match_rate / 100, 4),
        "verification_rate": f"{match_rate:.1f}%",
        "total_checks": total,
        "matches": matched,
        "mismatches": total - matched,
        "critical_flags": [
            "Active gate restricted to reproducible evidence retained in main_v3.tex",
            "K897 lagged-proxy simulation retired (K1686 R2, 2026-07-14 adjudication); its interval is no longer printed or bound",
            "Legacy shock-type / VRP / hedging tables intentionally excluded pending pinned-snapshot rebuild",
        ],
        "checks": checks,
        "notes": [
            "Coverage: T2 regime distribution (pinned), T3 SAR + paired block-bootstrap inference (P0-3 rebuild), K1686 contemporaneous-null section, T4 pinned cross-asset (incl. 0050.TW C3 fix), Appendix B alpha/adjR2 (C4), T5 NFP overall + regime (C5), baseline NSI, T9 thresholds, T10 subperiods, RV-normalized and controlled regressions.",
            "This gate no longer validates legacy deferred sections that lack stable JSON bindings under the current pinned snapshot.",
        ],
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"[write] {REPORT_PATH.relative_to(PROJECT)}")
    return 0 if gate_status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
