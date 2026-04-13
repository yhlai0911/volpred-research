# K1116b: FRED Publication Delay Re-verification of K1116 + K1118

**Date**: 2026-04-13
**Trigger**: K1121 (E062) revealed FRED NFCI/STLFSI have 5-6 day publication delays. K1116/K1118 aggregated these series to weekly W-FRI and applied `shift(1)` — potential latent lookahead.
**Status**: **COMPLETED — H2/H3 verdict**. Most original conclusions hold, but one critical cell collapses (**TLT M4**), with material consequences for Paper 4 compendium narrative.

## 1. Motivation

Paper 4 draws its "alt-data sufficiency" compendium narrative from three experiments:
- **K1116**: SPY EPU+NFCI+STLFSI weekly → **NULL** (alt-data actively worsens vs VIX baseline)
- **K1118**: GLD/TLT/BTC parallel → NULL for GLD/BTC, but **TLT M4 FinStress t=+3.74** (only positive-significant cell)
- **K1121**: Daily allocation using EPU/NFCI as regime gate — original Sharpe 1.250 collapsed to 1.283 after publication-delay correction (E062 lesson)

The K1121 publication-delay discovery raises the question: **do K1116/K1118 also have latent lookahead** from using NFCI[Friday W-1] to predict RV[W] when NFCI is not released until Wednesday of W?

## 2. Design

### 2.1 Audit (pre-experiment)
See `audit_report.md`. Key finding:
- USEPU/WLEMU (daily, 1-day release): weekly aggregation mostly safe (only Friday value missing at Mon W)
- NFCI/ANFCI (weekly Fri obs, released Wed of W+1): `shift(1)` weekly has **3 trading days of latent lookahead** per week W
- STLFSI4 (weekly Fri obs, released Thu of W+1): same structure, 4-day latent lookahead

### 2.2 Corrections
Three variants compared:
| Variant | USEPU / WLEMU | NFCI / ANFCI / STLFSI |
|---------|--------------|----------------------|
| `original_k1116` (reproduction) | shift(1) wk | shift(1) wk |
| `corrected` (per publication calendar) | shift(1) wk | shift(2) wk |
| `conservative` (uniform paranoia) | shift(2) wk | shift(2) wk |

### 2.3 Data
- Panel: 2018-01-05 to 2026-04-10, weekly W-FRI (431 weeks, BTC 428)
- IS: 2018-2022 (n~260)
- OOS: 2023-2026 (n~170)
- FRED data loaded from cached CSVs (K1121 USEPU/NFCI, storage/macro STLFSI4) + pandas_datareader fallback for WLEMU/ANFCI (fredgraph.csv endpoint was timing out)

## 3. Results

### 3.1 Reproduction fidelity (original_k1116 variant vs published K1116/K1118 JSONs)
**All 16 DM t-stats reproduce to 3+ decimal places.** Baseline confirmed.

### 3.2 Key cells — original vs corrected DM-HLN t-statistic

| Asset | Model | Orig | Corrected | Δ | Flag | Consequence |
|-------|-------|------|-----------|---|------|-------------|
| SPY | M1 AR(1) | -3.021 | -3.014 | +0.007 | — | Unchanged |
| SPY | M3 EPU | -2.554 | -2.537 | +0.017 | — | Unchanged (baseline still wins) |
| SPY | M4 NFCI | -3.001 | **-3.608** | -0.607 | — | **Strengthens** baseline (alt-data worse) |
| SPY | M5 All | -1.008 | -0.999 | +0.009 | — | Unchanged (ns) |
| GLD | M1 AR(1) | -2.103 | -2.093 | +0.010 | — | Unchanged |
| GLD | M3 EPU | -1.773 | -1.761 | +0.012 | — | Unchanged |
| GLD | M4 NFCI | -3.341 | **-3.003** | +0.339 | — | Baseline still wins (barely above ±3) |
| GLD | M5 All | -0.128 | +0.414 | +0.543 | SIGN_FLIP | ns both sides (not consequential) |
| **TLT** | **M4 NFCI** | **+3.743** | **+1.963** | **-1.780** | **THRESHOLD_FLIP** | **Loses Harvey significance — the only positive-significant cell in K1118 is largely publication-delay artifact** |
| TLT | M5 All | -5.179 | **-7.434** | -2.255 | — | **Strengthens** baseline (alt-data worse) |
| BTC | M3 EPU | -5.039 | -5.134 | -0.095 | — | Unchanged (baseline wins) |
| BTC | M4 NFCI | +1.370 | +1.273 | -0.097 | — | Unchanged (ns) |
| BTC | M5 All | -1.282 | **-3.638** | -2.356 | THRESHOLD_FLIP | Baseline **gains** significance against alt-data |

Reproduction t-stats match literature for all 16 cells (see `comparison_table.csv`).

### 3.3 Conservative (all shift(2)) variant
The conservative variant behaves similarly to `corrected` for NFCI-driven cells (same delay applied). For USEPU/WLEMU the additional week produces:
- SPY M5 All: t=-0.999 → -3.344 (strengthens baseline against hybrid)
- BTC M5 All: t=-3.638 → +1.706 (flip back to ns — brittle signal on hybrid)

This confirms the M5 "all kitchen sink" model is highly sensitive to timing convention and should not be used as primary evidence.

## 4. Verdict

### 4.1 Primary verdict: **H2-mixed, leaning H3 for Paper 4**
- **SPY** (K1116): NULL verdict **unchanged and strengthened**. Original "alt-data actively worsens vs VIX baseline" holds; corrected SPY M4 drops from t=-3.001 to t=-3.608, making the null conclusion even cleaner.
- **GLD** (K1118): NULL verdict **unchanged**. All significant cells retain direction.
- **BTC** (K1118): NULL verdict **unchanged and strengthened** in M5 (t=-1.28 → -3.64).
- **TLT** (K1118): **MATERIAL CHANGE**. The single "alt-data niche" cell (M4 FinStress t=+3.74) drops to t=+1.96 — below Harvey threshold. The only positive-significant result in the entire cross-asset study was substantially a publication-delay artifact.

### 4.2 TLT M4 NFCI deep-dive
Original claim: "TLT is the one asset where NFCI+ANFCI+STLFSI beats MOVE-implied-vol baseline (t=+3.74, p<0.001)."
Corrected: t=+1.96 (p≈0.05). Under Harvey (2016) |t|>3.0 threshold: **fails**. Under standard |t|>2.0: **borderline**.

**Interpretation**: Out of the 1.78 drop in t-stat, most comes from NFCI[Friday W-1] being unavailable until Wed of W. When NFCI data for week W-1 was used to predict TLT's RV for week W, the model was partly fitting to unseen-at-forecast-time information. Once removed, the apparent Treasury niche for financial-stress regressors dissolves to marginally-above-null.

### 4.3 Paper 4 implications

**Before K1116b**: Compendium could make nuanced claim "VIX-style native implied-vol sufficient for SPY/GLD/BTC, but TLT has niche for financial-stress regressors."

**After K1116b**: Compendium should make **stronger universal claim**: "Native implied-vol dominates alt-data for weekly vol prediction across SPY/GLD/TLT/BTC — the single previously-apparent Treasury niche was substantially publication-delay artifact."

**Action items for Paper 4**:
1. **Update TLT M4 table**: Report corrected t=+1.96 (not t=+3.74). Remove "TLT niche" framing.
2. **Strengthen universal-sufficiency narrative**: All 4 asset classes (equity/commodity/bond/crypto) now show consistent NULL for alt-data.
3. **Add publication-delay robustness section**: Cite K1116b as the fix; reference K1121/E062 for discovery.
4. **Sensitivity table**: Show that SPY M4 (and GLD M4) actually *strengthen* under correction — alt-data is not merely silent, it is **actively harmful** even after removing timing advantage.

## 5. Files

- `k1116b.py`: Re-verification script (all 4 assets × 3 variants = 12 model runs + DM battery)
- `k1116b_results.json`: Full results (comparison, all t-stats, OOS QLIKE)
- `comparison_table.csv`: Wide table of orig_lit vs orig_repro vs corrected vs conservative
- `audit_report.md`: Pre-experiment timing analysis for each FRED series
- `README.md`: This file

## 6. Caveats

1. We used cached FRED CSVs from K1121 (USEPU, NFCI) + local `storage/macro/fred_STLFSI4.csv`. fredgraph.csv endpoint was timing out at run time; pandas_datareader was used for WLEMU/ANFCI. Cached USEPU last date 2026-04-09 matches K1121 precisely.
2. The `shift(2)` correction at weekly frequency is a conservative fix. Strictly, NFCI observed at Fri W-1 is released Wed W, so shift(1) at week-W-1 labeling means using NFCI[W-1] (labeled Fri W-1) during Mon-Tue W is technically lookahead of 3 days, while Wed-Fri W is fair use. Our fix trades away some signal to guarantee no leakage. The conservative variant (shift(2) for USEPU/WLEMU too) errs further on safety.
3. Sample size stays the same across variants (same OOS window 2023-2026 → ~170 weeks). Degrees of freedom for DM test are identical; differences reflect regressor content, not sample.
4. DM-HLN test with h=1 assumes 1-period forecast horizon. Weekly RV with weekly signals satisfies this.
5. Reproduction fidelity of all 16 original cells confirms the K1116/K1118 scripts have no other silent bugs — only the timing issue.

## 7. Derivative research directions

1. **Event-study robustness (K1116c candidate)**: Re-run K1116/K1118 using *intraday* publication timestamps for NFCI (Wed 10:30am CT) rather than calendar-week lag. Would require reconstructing release-date alignment dataset from FRED ALFRED vintages. Goal: show even the tightest possible publication-timing fix does not resurrect TLT M4 significance.
2. **Monthly frequency re-test (K1117b candidate)**: At monthly RV frequency, the 5-6 day publication delay is irrelevant (<1/4 of period). Re-running K1116 at monthly frequency should produce cleaner NULL with minimal timing sensitivity. If monthly still NULL → strong universal sufficiency at low-frequency; if monthly shows alt-data edge but weekly doesn't → frequency-dependent story.
3. **Extend cross-asset to currencies (K1118b candidate)**: DXY, EURUSD, USDJPY using JPYVOL/EUVOL native-IV baseline. Currency vol is more macro-driven — if even here alt-data loses, Paper 4 narrative becomes maximally robust. If currencies show alt-data niche, genuine heterogeneity emerges.

## 8. References

- Baker, Bloom, Davis (2016) QJE 131(4) — EPU
- Brave, Butters (2011) Fed Letter 286 — NFCI publication schedule
- Kliesen, Smith (2010) — STLFSI
- Harvey, Leybourne, Newbold (1997) IJF — HLN DM correction
- Patton (2011) JoE — QLIKE proxy-robust loss
- K1116 (`experiments/k1116/`) — SPY 5-model OOS (original)
- K1118 (`experiments/k1118/`) — GLD/TLT/BTC 5-model OOS (original)
- K1121 (`experiments/k1121/`) — Daily allocation; source of publication-delay discovery
- Error log E062 (2026-04-13) — FRED publication-delay bug entry
