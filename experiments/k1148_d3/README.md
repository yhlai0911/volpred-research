# K1148_d3: PASS vs FAIL TW Stock Characteristics

**[提出: Claude (Paper 2 §5 Option 3 heterogeneity subsection), 執行: Claude]**

## Motivation

K1148_d1 found that only **9/29 TW stocks (31%)** pass the OOS DM ≤ -2 threshold for the binary EAV specification in the GJR-VIX²-EAV model. This raises a key question for Paper 2 §5:

> Can we characterize WHICH 9 stocks benefit from modelling earnings-announcement-day variance add-on (EAV), and WHY the other 20 do not?

If we can identify firm-level features (sector, size, earnings frequency, surprise magnitude, pre-event volatility, GJR parameters) that systematically separate PASS from FAIL, **Paper 2 §5 can be rewritten as "EAV effect is firm-heterogeneous, not universal"** — a stronger, more defensible empirical contribution than a naked universal-magnitude claim. This corresponds to Paper 2 **Option 3** (adding a new subsection).

If no feature can reliably discriminate, Option 3 is not viable and the main thread should pivot to Option 1 (IS-only evidence) or Option 2 (OOS heterogeneity without firm-level characterization).

## Method

### Group split (from `experiments/k1148_d1/k1148_d1_results.json`)

- **PASS** (DM_t ≤ -2.0): **9 stocks**
  `2330.TW, 2303.TW, 3035.TW, 3443.TW, 2886.TW, 2603.TW, 2615.TW, 2002.TW, 2637.TW`
- **FAIL** (DM_t > -2.0): **20 stocks**
  `6239.TW, 2454.TW, 2379.TW, 3034.TW, 2881.TW, 2882.TW, 2887.TW, 2609.TW, 1301.TW, 1303.TW, 1326.TW, 2027.TW, 2317.TW, 3045.TW, 2382.TW, 2912.TW, 1215.TW, 2347.TW, 1210.TW, 2892.TW`

### Features extracted (IS window 2010-2019)

16 numeric features grouped:

| Group | Features |
|-------|----------|
| Size | `market_cap_snapshot` (current yfinance, flagged), `avg_dollar_vol_is` (2015-2019 IS avg $ volume) |
| Vol | `is_annualized_vol`, `vol_of_vol` (std of rolling 21-day vol) |
| Return | `is_annualized_return`, `max_drawdown_is` |
| GJR (from K1148_d1 IS fit) | `gjr_alpha`, `gjr_gamma`, `gjr_beta`, `gjr_persistence`, `gjr_theta0` |
| Earnings | `n_surprise_events_is`, `earnings_freq_per_year_is`, `avg_abs_surprise_pct_is`, `mean_surprise_pct_is`, `surprise_symmetry_ratio` |

Sector extracted from yfinance snapshot (time-invariant for TW listed stocks).

**NOTE**: per-stock β_EAV is **not** available — K1148/K1148_d1 share θ_EAV across stocks (pooled). We report only per-stock GJR-component heterogeneity.

### Tests

- **Numeric**: Welch t + Mann-Whitney U + Cohen's d + rank-biserial
- **Categorical (sector)**: Fisher exact on collapsed 2×2 (sector vs not-sector) × (PASS vs FAIL)
- **Multiple comparison**: Benjamini-Hochberg step-up adjustment across 16 numeric p-values and across 6 sector p-values (FDR 10%)
- **Significance gate (Option 3 VIABLE)**: BH adj p < 0.1 **AND** |Cohen's d| > 0.5 (for numeric) OR BH adj Fisher p < 0.1 (for sector)

N=29 is underpowered; the gate is deliberately strict to avoid spurious "heterogeneity" claims.

## Results

### Top 5 numeric features by |d|

| Feature | Cohen's d | Raw t_p | BH adj t_p | BH adj u_p |
|---------|-----------|---------|------------|------------|
| `surprise_symmetry_ratio` | **+1.026** | 0.037 | 0.599 | 0.575 |
| `market_cap_snapshot` | +0.579 | 0.371 | 0.889 | 0.944 |
| `avg_dollar_vol_is` | +0.373 | 0.524 | 0.889 | 0.944 |
| `gjr_gamma` | -0.317 | 0.444 | 0.889 | 0.940 |
| `is_annualized_return` | -0.296 | 0.470 | 0.889 | 0.940 |

- `surprise_symmetry_ratio = |mean(surprise_pct)| / mean(|surprise_pct|)`: PASS μ=0.475, FAIL μ=0.240 — PASS stocks have more **systematically directional** surprises (consistent beat or miss), FAIL stocks surprise more symmetrically.
- Raw p = 0.037 is suggestive, but after BH correction across 16 features adj p = 0.60 (NS). Single-feature "discovery" with N=29 does not survive multiple-comparison control.

### Sector distribution

| Sector | PASS | FAIL | Fisher raw p | BH adj p |
|--------|------|------|--------------|----------|
| Industrials (shipping/steel) | 3/9 (33%) | 1/20 (5%) | **0.076** | 0.456 |
| Consumer Defensive | 0/9 (0%) | 3/20 (15%) | 0.532 | 1.000 |
| Technology | 4/9 (44%) | 7/20 (35%) | 0.694 | 1.000 |
| Basic Materials | 1/9 (11%) | 4/20 (20%) | 1.000 | 1.000 |
| Financial Services | 1/9 (11%) | 4/20 (20%) | 1.000 | 1.000 |
| Consumer Cyclical | 0/9 (0%) | 1/20 (5%) | 1.000 | 1.000 |

Industrials (shipping: 2603, 2615; steel: 2002) is suggestive — raw p=0.076 with 3 of 4 Industrials in PASS — but BH adj p=0.46 is NS. Too few Industrials (N=4) to claim a real effect.

### Verdict gate check

- Numeric features meeting (BH adj p < 0.1 AND |d| > 0.5): **0**
- Sectors meeting BH adj Fisher p < 0.1: **0**

## Verdict: Option 3 REJECTED

PASS group (N=9): slightly more Industrials (3/9 vs 1/20), slightly more systematic earnings-surprise direction (symmetry ratio ~0.48 vs 0.24), marginally larger market cap; **none survive BH correction**.

FAIL group (N=20): slightly more Consumer Defensive + Financial Services, more symmetric (unsigned) surprises; no statistically robust differentiator.

Significant differentiators (BH adj p<0.1, |d|>0.5): **none**

Paper 2 §5 implication:

- **Option 3 REJECTED**: we cannot write a "EAV effect is concentrated in X-type stocks" subsection on defensible statistical grounds. With N=29 and 16 features, the single suggestive pattern (`surprise_symmetry_ratio` d=1.03, raw p=0.037) does not survive BH correction, and the Industrials cluster (3/4) is too small to support a sector claim.
- **Recommendation**: main thread should pivot to either **Option 1 (IS-only evidence)** — lean on pooled θ_EAV t_Hessian=10.43 in K1148_d1 IS fit and K1145's 31-stock in-sample evidence, explicitly labelling OOS panel DM as inconclusive — or **Option 2 (OOS heterogeneity without characterization)** — report the 9-PASS finding as empirical fact but decline to attribute it to firm-level features, citing underpowered N for characterization.
- The exploratory pattern (PASS stocks have more directional earnings surprises and slightly higher Industrials representation) can still be **reported as descriptive narrative in a footnote or appendix**, flagged explicitly as "not surviving multiple-comparison correction, reported for pattern-completeness only." This is safer than promoting it to a main-text claim.

## Caveats

1. **N=29 is underpowered**. Any "significance" is exploratory, not confirmatory. BH FDR control at 10% is mandatory and applied.
2. `market_cap_snapshot` uses CURRENT yfinance info (as of 2026-04-17) — cannot recover historical 2020-era market cap cheaply. Primary size metric is `avg_dollar_vol_is` (2015-2019 IS; historically clean, no lookahead).
3. Sector from yfinance snapshot; TW listed stocks rarely reassigned during 2010-2025, so snapshot ≈ 2020-era sector.
4. Per-stock GJR (alpha/gamma/beta) from K1148_d1 IS fit — pooled θ_EAV was shared across stocks, so per-stock β_EAV heterogeneity is not observable from this specification.
5. Codex review skipped (usage limit hit). Self-review performed on: PASS/FAIL split logic, BH step-up implementation, NaN-safe feature extraction, and N=29 over-claim gate. No HIGH bugs identified in self-review.

## Files

- `k1148_d3.py` — main script
- `k1148_d3_results.json` — full per-feature test output + caveats
- `pass_vs_fail_features.png` — boxplots of all numeric features
- `feature_importance.png` — |Cohen's d| bar chart with BH significance coloring
- `data/sector_info_cache.json` — cached yfinance sector/industry/marketCap
- `run.log` — full run log

## References

- K1148_d1 (binary EAV OOS panel DM; 29 TW stocks; 9 PASS / 20 FAIL)
- K1148 (continuous surprise EAV)
- Benjamini & Hochberg (1995) JRSS-B — step-up FDR control
- Cohen (1988) *Statistical Power Analysis* — effect size interpretation
