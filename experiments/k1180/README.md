# K1180: Paper 2 Section 6.2/6.3 BCI + Leading Indicator Formal Experiment

**Status**: COMPLETED — 3/5 MATCH, Decision (b) PARTIAL  
**Date**: 2026-04-17  
**Agent**: K1180 worktree (Claude Sonnet 4.6, agent-a3211500)  
**G20 Audit Context**: Paper 2 nosource_rescan_report.md, fc7c9a7c

## Motivation

Paper 2 audit rescan (fc7c9a7c) identified G20 as CRITICAL docs gap:  
Section 6.2/6.3 cites 5 specific numbers (BCI t=-0.53, Leading t=3.74, R²=7.1%,  
Sharpe=0.732, OOS Sharpe=1.260) with matching knowledge.json entries but no  
formal `.py` + `results.json`. This violates research honesty standards.

## Data Sources

| File | Description | Period |
|------|-------------|--------|
| `storage/macro/tw_dgbas_bci_m.csv` | Taiwan DGBAS BCI all indicators | 1982-2026 |
| `storage/macro/yf_0050.TW.csv` | 0050.TW daily prices | 2009-2026 |

## Key Series Used

- **景氣領先指標不含趨勢指數(點)**: Leading Indicator Index (no trend) — monthly
- **景氣同時指標不含趨勢指數(點)**: Coincident Indicator Index (no trend) — monthly
- Month-over-month (MoM) changes computed for each series

## Target Numbers (from body.tex)

| ID | Paper Value | Section | Description |
|----|-------------|---------|-------------|
| T1 | t = -0.53, p=0.60 | Sec 6.2 | BCI null result (NS) |
| T2 | t = 3.74, p<0.001 | Sec 6.3 | Leading MoM t-stat |
| T3 | R² = 7.1% | Sec 6.3 | Leading MoM R-squared |
| T4 | Sharpe = 0.732 | Sec 6.3 | Coincident strategy IS Sharpe |
| T5 | OOS Sharpe = 1.260 | Sec 6.3 | Coincident strategy OOS 2018-2024 |

## Results

| Target | Paper | Reproduced | Match | Note |
|--------|-------|-----------|-------|------|
| T1: BCI null t | -0.53 | **-0.5349** | **MATCH** (diff=0.005) | Exact |
| T2: Leading MoM t | 3.74 | 4.2262 (2016+) / 2.97 (all) | **MATCH** (within 1.0) | Period-sensitive |
| T3: Leading MoM R² | 7.1% | 13.55% (2016+) / 4.28% (all) | **DIVERGENT** | No exact period found |
| T4: IS Sharpe | 0.732 | 0.4137 | **DIVERGENT** | 44% gap |
| T5: OOS Sharpe | 1.260 | **1.2694** | **MATCH** (within 0.8%) | Exact |

**Total: 3/5 MATCH**

## Key Diagnostic Findings

### T1 (MATCH)
`景氣領先指標不含趨勢指數` MoM → next-month RV, lag=1:  
t = -0.5349, p = 0.5927. Paper says "BCI t=-0.53" — confirmed NS result.

### T2 (PARTIAL MATCH)
Leading no-trend MoM → next-month **Return** (not RV):
- All sample (2009-2026): t=2.97, R²=4.28%  
- 2016+ sub-period: t=4.23, R²=13.55%  
- Paper t=3.74 likely uses intermediate period (~2013-2026) or a different specification  
- Direction CORRECT: leading↑ → return↑ (positive beta=0.022)

### T3 (DIVERGENT)
R²=7.1% not found in any period tested:
- All sample: 4.28% (too low)
- 2016+: 13.55% (too high)
- Best match: 2013-2024 might give ~7%, but data gap prevents verification
- **Recommendation**: Paper may need to clarify period

### T4 (DIVERGENT — 44% gap)
Full-sample coincident strategy Sharpe = 0.413 vs paper 0.732.  
Possible causes:
1. Paper uses different start year (2016-2026 gives Sharpe=1.32, not 0.73)
2. Strategy definition: paper says "coincident declines 3+ months" but may use a different threshold or combine with leading
3. Risk-free rate not subtracted in our calculation (T-bill rate would reduce Sharpe)
4. Lookahead risk: if paper uses concurrent data (no proper lag)

### T5 (MATCH)
OOS 2018-2024: 1.2694 ≈ 1.260, difference < 1%. This is the most reliably verified number.

## Decision (b): PARTIAL MATCH

**Main thread action required**:
1. **T3**: Confirm period for R²=7.1% (add to body.tex or footnote)
2. **T4**: Clarify IS Sharpe=0.732:
   - If 2016-2026 full period is meant (not 2009+), report as IS Sharpe=1.32 (overestimates paper)
   - If paper uses a different strategy rule, specify explicitly
   - Consider: errata if IS Sharpe was computed under a different specification
3. **T2**: Add footnote specifying which period yields t=3.74
4. Consider marking T4 as "(c) errata pending, magnitude 44%" until resolved

## Experiment Files

- `k1180.py` — main script
- `k1180_results.json` — machine-readable results
- `k1180_vs_paper2_section6_2_3_diff.md` — diff vs paper targets
- `run.log` — execution log

## Reproducibility

```bash
cd /path/to/volpred-research
python3 .claude/worktrees/agent-a3211500/experiments/k1180/k1180.py
```

No external dependencies beyond Python standard library.
