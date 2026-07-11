# Paper 4: The True Cost of Volatility Targeting — Insurance Premium Decomposition

**Target Journal**: Finance Research Letters (FRL)
**Status**: `REVISION` — 2026-07-11 Fable finishing pass complete (P0 done; see `EXECUTION.md`). v3 text fixes (2026-07-06, `review_history/v3/fix_log.md`): **S-01** S4 relabelled daily constant-weight, **S-03** S3 Smooth-VoV equation rewritten to continuous-clip form, **C-01** hasbrouck2009 citation restated. 2026-07-11 finishing (`review_history/fable_deep_review_20260711/`): **S-02** cross-OOS covers all 6 two-year windows (2/6 Sharpe-basis wins, honestly reported — S-02 no longer pending); reproduce gate re-scoped to strict same-basis check on claim #9 (raw-Close 62.91 vs disclosed ~63 bps, tolerance 5) → **9/9 green without widened tolerance**; experiment package cleaned (stale `sensitivity_sweep.json` + mislabelled `threshold_0.5_results.json` removed; `_tmp_th*.py` renamed `k811v2_sensitivity_th*.py`); main.tex fixes (§4.4 period-scope split, Eq.3 T/Y notation, abstract+§4.5 "Sharpe-basis" disambiguation). **Before submission**: P1 citation cleanup (C-02–C-09) + one main figure — see `EXECUTION.md`.
**Pages**: 14 | **Citations**: 17

## Data Sources
- SPY, GLD: yfinance (2005-2026)
- VIX: yfinance (^VIX)
- OOS: 2023-01-01 to 2024-12-31

## Reproduction
```bash
uv run python paper/vt-insurance-cost/reproduce.py
```

### Reproduction Status

| Metric | Pre-fix | Post-Sub1 | Current package state |
|---|---|---|---|
| Match rate | 44.4% (4/9) | 88.9% (8/9) | `100%` only under widened `±10 bps` tolerance on claim #9 |
| Alert level | red | amber | `green` in `reproduce_report.json`, but audit 2026-06-10 treats this as over-permissive |
| S1/S2 insurance decomposition (claims #1–#8) | 4/8 | 8/8 | **8/8 exact match** |
| 50/50 SPY/GLD rebalancing premium (claim #9) | −121 bps (divergent) | n/a | **62.91 bps vs paper 54 bps** |

**Residual divergence:** claim #9 only. Root cause = dividend convention asymmetry — K846 paper anchor used `yfinance auto_adjust=True` (Adj Close, 53.67 bps), replication package enforces `auto_adjust=False` raw Close (62.91 bps). The current paper discloses both conventions in `main.tex:184`, but the reproduce gate should not be read as a strict green replication until claim #9 is either split into dual-basis checks or re-anchored to one basis.

### Audit Status (2026-06-10)

- HIGH #1 fixed: DM footnote now matches `strategy_dm_test` implementation.
- HIGH #2 fixed: omitted 2017--18 and 2021--22 windows are explicitly disclosed in `§4.5`.
- HIGH #3 fixed: rebalancing premium is now described as a full-sample average with two negative sub-periods disclosed.
- Remaining open work: run the two omitted cross-OOS windows and tighten the reproduce gate around claim #9.

See `review_history/diagnosis_v1/resolution.md` for closing verdict and handoff. See `review_history/diagnosis_v1/divergence_breakdown.md` for original root-cause analysis. Commits: `a43d13d` (Sub1), `a5ca55e` (Sub2).

## Experiment Files
| File | Description |
|------|-------------|
| k811v2_insurance_premium_vov_fixed.py | Main decomposition — Tables 1 & 2 (generates `k811v2_insurance_premium_vov_fixed_results.json` + `..._cross_oos6_results.json`) |
| k811v2_sensitivity_th{0_5,1_0,1_5}.py | VoV z-threshold sensitivity (generate `k811v2_th{0_5,1_0,1_5}_results.json`) |
| k846_rebalancing_premium.py | 2006–2024 rebalancing premium (headline 54 bps dividend-adjusted anchor; raw-Close ~63 bps verified by reproduce.py) |

## Number Traceability
See `reviews/audit_step1_2.md` for complete traceability table.
All paper-internal numbers verified against K811v2 + K846 experiment JSONs — 0 mismatches. Residual reproduce.py → paper gap on claim #9 is a dividend-convention packaging issue, not a paper-internal drift, but the audit now treats the widened tolerance as a package-level weakness rather than a full resolution.

## Self-Contained Index (2026-04-17)

| File | Status |
|------|--------|
| `data_sources.md` | ✅ All 4 data files documented; pre-downloaded CSVs in data/ |
| `scripts/README.md` | ✅ Reproduction guide for all experiments |
| `results/README.md` | ✅ Table → JSON source mapping |
| `figures/` | ✅ Directory created (no figures in current draft) |
| `experiments.md` | ✅ Full K-number index (K811–K860) |

## Supporting Experiments (K Index)

| K | Title | Key Result |
|---|-------|-----------|
| K811 | Insurance Premium VoV (original) | Pilot; superseded by K811v2 |
| K811v2 | Insurance Premium VoV (fixed) | Main Table 2; 0-mismatch verified |
| K846 | Rebalancing Premium | Isolated rebalancing cost component |
| K860 | Prospect Theory VT | Supplementary behavioral analysis — **unused in final draft** (not cited in main.tex; kept for reference) |
