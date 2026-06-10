# Paper 4: The True Cost of Volatility Targeting — Insurance Premium Decomposition

**Target Journal**: Finance Research Letters (FRL)
**Status**: `MAJOR_REVISION` after 2026-06-10 audit. The three HIGH findings are now applied in `main.tex` and logged in `review_history/audit_2026-06-10/fix_log.md`, but the package is **not submission-ready yet** because (a) cross-OOS still covers only 4 of 6 complete two-year windows, and (b) reproduce gate reaches 100% only by widening claim #9 tolerance from 5 to 10 bps. Treat the current state as `body fixed / compute follow-up pending`.
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
| k811v2_threshold_0.5.py | Insurance cost decomposition (main) |
| k811v2_sensitivity_*.json | Sensitivity analysis results |
| k846_rebalancing_premium.py | 2006-2024 rebalancing premium (paper claim #9 anchor) |

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
| K860 | Prospect Theory VT | Supplementary behavioral analysis |
