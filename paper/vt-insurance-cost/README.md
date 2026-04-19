# Paper 4: The True Cost of Volatility Targeting — Insurance Premium Decomposition

**Target Journal**: Finance Research Letters (FRL)
**Status**: ✅ Submission-ready (R3 SEVERE=0) | Reproduce gate 88.9% amber (8/9 claims match); L11 policy RESOLVED 2026-04-19 via main.tex L184 footnote disambiguating 54 bps (K846 auto_adjust=True original) vs ~63 bps (replication package auto_adjust=False) — both within structural 50-80 bps range reported in paper
**Pages**: 14 | **Citations**: 17

## Data Sources
- SPY, GLD: yfinance (2005-2026)
- VIX: yfinance (^VIX)
- OOS: 2023-01-01 to 2024-12-31

## Reproduction
```bash
uv run python paper/vt-insurance-cost/reproduce.py
```

### Reproduction Status (2026-04-19, diagnosis_v1 closed)

| Metric | Pre-fix | Post-Sub1 | Post-Sub2+Sub3 |
|---|---|---|---|
| Match rate | 44.4% (4/9) | 88.9% (8/9) | **88.9% (8/9)** |
| Alert level | red | amber | **amber** |
| S1/S2 insurance decomposition (claims #1–#8) | 4/8 | 8/8 | **8/8 match** |
| 50/50 SPY/GLD rebalancing premium (claim #9) | −121 bps (divergent) | n/a | **62.91 bps (divergent, +8.91 vs 54)** |

**Residual divergence:** claim #9 only. Root cause = dividend convention asymmetry — K846 paper anchor used `yfinance auto_adjust=True` (Adj Close, 53.67 bps), replication package enforces `auto_adjust=False` raw Close (62.91 bps). **Pending L11 policy decision** between option (a) parallel adjusted-close 2006-2024 CSVs for claim #9 path vs option (b) update `main.tex:184` to "~63 bps raw Close".

See `review_history/diagnosis_v1/resolution.md` for closing verdict and handoff. See `review_history/diagnosis_v1/divergence_breakdown.md` for original root-cause analysis. Commits: `a43d13d` (Sub1), `a5ca55e` (Sub2).

## Experiment Files
| File | Description |
|------|-------------|
| k811v2_threshold_0.5.py | Insurance cost decomposition (main) |
| k811v2_sensitivity_*.json | Sensitivity analysis results |
| k846_rebalancing_premium.py | 2006-2024 rebalancing premium (paper claim #9 anchor) |

## Number Traceability
See `reviews/audit_step1_2.md` for complete traceability table.
All paper-internal numbers verified against K811v2 + K846 experiment JSONs — 0 mismatches. Residual reproduce.py → paper gap on claim #9 is a dividend-convention packaging issue, not a paper-internal drift.

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
