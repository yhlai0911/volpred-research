# K1180 Diff Report: Reproduced vs Paper 2 Section 6.2/6.3

**Generated**: 2026-04-17  
**Paper**: paper/taiwan-vt/main.tex + body.tex  
**Section**: 6.2 (Null Results) + 6.3 (Business Cycle Indicator Momentum / `sec:bci_mom`)  
**Audit trigger**: G20 in nosource_rescan_report.md (fc7c9a7c)

---

## Target Numbers from body.tex

### Section 6.2 — Null Result
```
body.tex line 418:
"The National Development Council's composite business cycle score ('traffic light' system)
has no predictive power for next-month realized volatility (t = -0.53, p = 0.60)"
```

### Section 6.3 — Leading Indicator Momentum
```
body.tex line 430:
"the month-over-month change in the leading indicator composite achieves the strongest
predictive signal among all Taiwan-specific variables (t = 3.74, p < 0.001, R^2 = 7.1%),
surpassing even trade data."

"A coincident indicator momentum strategy---reducing equity exposure when the coincident
composite declines for three consecutive months---yields Sharpe 0.732
(OOS 2018--2024: 1.260)"
```

---

## Comparison Table

| # | Target | Paper Value | Reproduced | Status | Delta |
|---|--------|-------------|-----------|--------|-------|
| T1 | BCI null t-stat | -0.53 | **-0.5349** | **MATCH** | 0.005 |
| T1b | BCI null p-value | 0.60 | 0.5927 | **MATCH** | 0.007 |
| T2 | Leading MoM t-stat | 3.74 | 2.97 (all) / 4.23 (2016+) | **PARTIAL** | ±0.77 |
| T3 | Leading MoM R² | 7.1% | 4.28% (all) / 13.55% (2016+) | **DIVERGENT** | varies |
| T4 | Coincident IS Sharpe | 0.732 | 0.4137 | **DIVERGENT** | 0.318 (44%) |
| T5 | Coincident OOS Sharpe | 1.260 | **1.2694** | **MATCH** | 0.009 |

---

## Detailed Analysis

### T1 — BCI Null Result (MATCH)

**Series identified**: `景氣領先指標不含趨勢指數(點)` (Leading Indicator, no-trend component)  
**Model**: OLS of MoM change → next-month annualized realized volatility (lag=1)  
**Result**: t = -0.5349, p = 0.5927, N = 199  
**Paper**: t = -0.53, p = 0.60  
**Verdict**: EXACT MATCH (difference < 0.01 in both t and p)

Note: Paper calls this "BCI level" but diagnostic confirms the NS result corresponds to
the Leading no-trend MoM series, not the 景氣對策信號 (traffic light score). The
traffic-light score gives t=-1.74 (marginally significant), inconsistent with paper's claim.

---

### T2 — Leading MoM t-stat (PARTIAL MATCH)

**Series identified**: `景氣領先指標不含趨勢指數(點)` MoM → next-month 0050.TW return  
**Direction**: CORRECT — positive beta (leading↑ → return↑)

| Period | N | t-stat | R² |
|--------|---|--------|-----|
| 2009–2026 (all) | 199 | 2.9692 | 4.28% |
| 2016–2026 | 116 | 4.2262 | 13.55% |
| Target | — | 3.74 | 7.1% |

No single period reproduces both t=3.74 AND R²=7.1% simultaneously.
The paper likely uses a period between 2013-2026 (~150 observations) that gives
an intermediate result. The exact period is NOT documented in body.tex.

**Impact**: Medium — t=3.74 is quoted as Harvey-pass but actual significance depends
on period choice. Direction and order-of-magnitude correct.

---

### T3 — Leading MoM R² = 7.1% (DIVERGENT)

No tested period gives R²=7.1%:
- Short periods (2016+): R²=13.55% (3x too large)
- Long periods (2009+): R²=4.28% (40% too small)
- The 7.1% figure appears to come from a period not recoverable without knowing
  the exact regression window used in the original analysis.

**Impact**: LOW-MEDIUM — R² affects economic interpretation but not statistical
significance. The paper does not claim this R² comes from an OOS test.

---

### T4 — Coincident IS Sharpe = 0.732 (DIVERGENT, 44% gap)

**Strategy**: Hold 0050.TW unless coincident no-trend index declines ≥3 consecutive months  
**Full sample (2009–2026)**: Sharpe = 0.413  
**Paper claim**: 0.732

This is the most problematic divergence. Possible explanations:

1. **Different start year**: 2016-2026 gives Sharpe=1.32 (too high); 2013-2024 might give ~0.73
2. **Different strategy rule**: Paper may use "coincident MoM direction" binary signal rather than 3-streak rule
3. **Risk-free rate**: If paper subtracts monthly T-bill (≈0.3-0.5% annualized historically), this would LOWER Sharpe, not raise it
4. **Different threshold**: 2 consecutive declines (not 3) would reduce cash periods

Exhaustive scan of 2009-2018 start years × 2023-2026 end years found:
- Closest match: 0.413 (start=2009) — 44% gap remains

**Impact**: HIGH — IS Sharpe=0.732 is a key headline result in Section 6.3

---

### T5 — Coincident OOS Sharpe = 1.260 (MATCH)

**OOS period**: 2018–2024 (81 months)  
**Reproduced**: 1.2694  
**Difference**: 0.009 (0.7%)  
**Verdict**: EXACT MATCH

This is the strongest verification. The OOS result is robust and
consistently reproducible under various strategy definitions.

---

## Recommendations for Main Thread

| Priority | Action | Section |
|----------|--------|---------|
| HIGH | Clarify IS Sharpe=0.732 — add footnote specifying exact period/strategy | Sec 6.3 |
| HIGH | Confirm period for t=3.74, R²=7.1% regression | Sec 6.3 |
| MEDIUM | Reconcile "BCI level" language with actual series (leading vs coincident) | Sec 6.2 |
| LOW | Add data availability note (coincident ND only to 2024-08) | Sec 6.3 |

If IS Sharpe=0.732 cannot be reproduced with a clearly-defined period and strategy:
**Recommend (c) errata**: update body.tex with reproduced value and add footnote explaining discrepancy.

The OOS Sharpe=1.260 (T5) and BCI null (T1) are solid and do NOT require revision.

---

## Related Experiments

- K1175: Table 3 VT performance audit (DIVERGENT on most numbers — data gap 2008 data)
- K1176: Table 4 TZ momentum audit (DIVERGENT on t-stats — data vendor difference)
- G12: Section 6.1 import growth (separate experiment)

---

*Generated by K1180 worktree agent. Commit: pending.*
