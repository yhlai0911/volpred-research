# Paper 4: The True Cost of Volatility Targeting — Insurance Premium Decomposition

**Target Journal**: Finance Research Letters (FRL)
**Status**: `REVISION` — 2026-07-11 Fable finishing pass complete (P0 done; see `EXECUTION.md`). v3 text fixes (2026-07-06, `review_history/v3/fix_log.md`): **S-01** S4 relabelled daily constant-weight, **S-03** S3 Smooth-VoV equation rewritten to continuous-clip form, **C-01** hasbrouck2009 citation restated. 2026-07-11 finishing (`review_history/fable_deep_review_20260711/`): **S-02** cross-OOS covers all 6 two-year windows (2/6 Sharpe-basis wins, honestly reported — S-02 no longer pending); reproduce gate re-scoped to strict same-basis check on claim #9 (raw-Close 62.91 vs disclosed ~63 bps, tolerance 5) → **9/9 green without widened tolerance**; experiment package cleaned (stale `sensitivity_sweep.json` + mislabelled `threshold_0.5_results.json` removed; `_tmp_th*.py` renamed `k811v2_sensitivity_th*.py`); main.tex fixes (§4.4 period-scope split, Eq.3 T/Y notation, abstract+§4.5 "Sharpe-basis" disambiguation). 2026-07-12 P1: citation cleanup C-02–C-11 (DOIs/issues on all refs, over-attributions softened). **2026-07-13 P1 close-out**: Figure 1 (wealth + VoV-regime shading) integrated into §4.3; stationary-bootstrap 95% CI for the opportunity-cost share integrated into abstract/§3.1/§4.2/Conclusion — the S1 share interval is [50%, 95%] and S2's premium is **not** bounded away from zero, so the headline claim is now stated as an ordering, not a point estimate; reproduce gate re-run against current `main.tex` → **9/9 green at strict tolerance**. **Remaining before submission**: FRL format/word-limit gate (`journal-review` skill) and submission-timing decision (owner call; sequence after vt-crowding-abm to avoid two concurrent VT letters at FRL).
**Pages**: 17 | **Citations**: 18 | **Figures**: 1 | **Tables**: 2

## Data Sources
- SPY, GLD: yfinance (2005-2026)
- VIX: yfinance (^VIX)
- OOS: 2023-01-01 to 2024-12-31

## Reproduction
```bash
uv run python paper/vt-insurance-cost/reproduce.py
```

### Reproduction Status — 9/9 green, strict tolerance (re-run 2026-07-13 against current `main.tex`)

| Metric | Pre-fix | Post-Sub1 | Current package state |
|---|---|---|---|
| Match rate | 44.4% (4/9) | 88.9% (8/9) | **100% (9/9)** at the standard 5 bps / same-basis tolerance — no widening |
| Alert level | red | amber | **green** (`reproduce_report.json`, `timestamp` 2026-07-13) |
| S1/S2 insurance decomposition (claims #1–#8) | 4/8 | 8/8 | **8/8 exact match** |
| 50/50 SPY/GLD rebalancing premium (claim #9) | −121 bps (divergent) | n/a | **62.91 vs 63 bps disclosed** — strict same-basis match |

**Claim #9 basis (resolved, not widened):** the paper carries two dividend conventions and discloses both. The **headline 54 bps** is the dividend-adjusted (`auto_adjust=True`) K846 anchor (53.67 bps); the **replication package** enforces raw Close (`auto_adjust=False`), for which the paper's `main.tex:184` footnote discloses ~63 bps. The gate now checks the replication basis against the value the paper states *for that same basis* (62.91 vs 63, tolerance 5 bps) instead of comparing across conventions with a widened 10 bps band. The earlier "green only under ±10 bps" caveat no longer applies.

### Audit Status (2026-06-10 audit, all items closed)

- HIGH #1 fixed: DM footnote now matches `strategy_dm_test` implementation.
- HIGH #2 fixed: omitted 2017--18 and 2021--22 windows are explicitly disclosed in `§4.5`.
- HIGH #3 fixed: rebalancing premium is now described as a full-sample average with two negative sub-periods disclosed.
- CLOSED 2026-07-06: all six cross-OOS windows re-run (2/6 Sharpe-basis wins, honestly reported).
- CLOSED 2026-07-13: claim #9 gate re-scoped to a strict same-basis check (see above).

### Uncertainty Quantification (added 2026-07-13)

Stationary bootstrap (Politis–Romano, circular, expected block 21 days, 10,000 reps, seed 42) on the opportunity-cost share — `experiments/k811v2_share_bootstrap_ci.py`:

- **S1** share point 90.8%, 95% CI **[50.0%, 94.8%]**; total premium CI [0.87%, 8.13%]/yr (bounded away from zero). The robust claim is the *ordering* (opportunity ≥ direct), not the 91% point estimate.
- **S2** share point 57.1%, **no bounded CI** — the resampled total premium straddles zero (2,295/10,000 reps ≤ 0; CI [−2.63%, 3.99%]/yr). S2's cost reduction cannot be distinguished from zero premium.

Both facts are now stated in the abstract, §3.1, §4.2 and the Conclusion. This *strengthens* the paper's existing decision to treat VoV conditioning as hypothesis-generating rather than a validated rule.

See `review_history/diagnosis_v1/resolution.md` for closing verdict and handoff. See `review_history/diagnosis_v1/divergence_breakdown.md` for original root-cause analysis. Commits: `a43d13d` (Sub1), `a5ca55e` (Sub2).

## Experiment Files
| File | Description |
|------|-------------|
| k811v2_insurance_premium_vov_fixed.py | Main decomposition — Tables 1 & 2 (generates `k811v2_insurance_premium_vov_fixed_results.json` + `..._cross_oos6_results.json`) |
| k811v2_sensitivity_th{0_5,1_0,1_5}.py | VoV z-threshold sensitivity (generate `k811v2_th{0_5,1_0,1_5}_results.json`) |
| k846_rebalancing_premium.py | 2006–2024 rebalancing premium (headline 54 bps dividend-adjusted anchor; raw-Close ~63 bps verified by reproduce.py) |
| k811v2_share_bootstrap_ci.py | Stationary-bootstrap 95% CI for the opportunity-cost share (generates `k811v2_share_bootstrap_ci_results.json`; seed 42) — cited in abstract, §3.1, §4.2, Conclusion |
| k811v2_fig1_wealth_regimes.py | Figure 1 — cumulative wealth S0/S1/S2/S4 with VoV-regime shading (generates `figures/fig1_wealth_regimes.{pdf,png}`; asserts each curve's CAGR against Table 1 before writing) |

## Number Traceability
See `reviews/audit_step1_2.md` for complete traceability table.
All paper-internal numbers verified against K811v2 + K846 experiment JSONs — 0 mismatches. Residual reproduce.py → paper gap on claim #9 is a dividend-convention packaging issue, not a paper-internal drift, but the audit now treats the widened tolerance as a package-level weakness rather than a full resolution.

## Self-Contained Index (2026-04-17)

| File | Status |
|------|--------|
| `data_sources.md` | ✅ All 4 data files documented; pre-downloaded CSVs in data/ |
| `scripts/README.md` | ✅ Reproduction guide for all experiments |
| `results/README.md` | ✅ Table → JSON source mapping |
| `figures/` | ✅ `fig1_wealth_regimes.{pdf,png}` — Figure 1 in `main.tex` §4.3 |
| `experiments.md` | ✅ Full K-number index (K811–K860) |

## Supporting Experiments (K Index)

| K | Title | Key Result |
|---|-------|-----------|
| K811 | Insurance Premium VoV (original) | Pilot; superseded by K811v2 |
| K811v2 | Insurance Premium VoV (fixed) | Main Table 2; 0-mismatch verified |
| K846 | Rebalancing Premium | Isolated rebalancing cost component |
| K860 | Prospect Theory VT | Supplementary behavioral analysis — **unused in final draft** (not cited in main.tex; kept for reference) |
