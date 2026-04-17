# Paper 4 (vix-sufficiency) Reproducibility Audit — Diff Report

**Date**: 2026-04-17  
**Auditor**: agent-a0605254 (worktree-isolated)  
**Target**: `paper/vix-sufficiency/main_v2.tex` (953 lines, 39 pages)  
**Prior baseline**: `reproduce_report.json` (93% match, 5 mismatches in T6)

---

## Summary

| Metric | Count |
|--------|-------|
| Numbers extracted | 82 |
| Matched (rtol ≤ 1%) | 60 |
| Approximate (1%–5%) | 3 |
| Mismatched (>5% or direction wrong) | 8 |
| Untraced / no source found | 3 |
| **Coverage rate** | **72/82 = 87.8%** |
| **Match rate (of traceable)** | **60/72 = 83.3%** |

---

## DIVERGENT items — (a) direction error, (b) value error, (c) period/source mismatch

### DIV-1 ✗ Abstract + §8.2: "41.8% QLIKE improvement" — DIRECTION ERROR (type a)
- **Paper claim**: "Preliminary results using HAR-RV models with 5-minute S&P 500 data show a **41.8% QLIKE improvement** over daily-frequency models"
- **Source (K745)**: `improvement_pct = -41.8` — The sign is negative, meaning 5-min HAR-RV QLIKE=0.109 is **41.8% WORSE** than daily HAR-ABS QLIKE=0.077. The paper reverses the direction.
- **Additional issue**: K745 N=37 OOS days (explicitly marked PRELIMINARY); far below 252-day minimum.
- **Severity**: MAJOR — the research frontier claim is factually wrong as stated.
- **Fix needed**: Either (a) rewrite as "preliminary daily HAR-ABS outperforms 5-min HAR-RV by 41.8% on QLIKE in 51-day pilot — motivation for longer-horizon study" or (b) run K1139 (if it exists) with N≥252 and replace the claim.

### DIV-2 ✗ Abstract + §7.4 + conclusion: CV of R² = 0.33 — VALUE ERROR (type b)
- **Paper claim**: "coefficient of variation = 0.33" (appears in abstract, Table 5 footer, §8, conclusion)
- **Source (K752)**: Era R² = [0.5248, 0.6446, 0.508, 0.2439, 0.3094], mean=0.446, std=0.165, **CV=0.37**
- **Discrepancy**: 0.33 vs 0.37 = 12% relative error; not rounding
- **Severity**: MEDIUM — overstates time-invariance of VIX sufficiency. The correct CV of 0.37 is below 0.50 threshold but the paper quotes 0.33.
- **Fix needed**: Replace all instances of 0.33 with 0.37 (or recompute from updated era boundaries).

### DIV-3 ✗ Table 3: BH 50/50 Sharpe = 0.947 — PERIOD/SOURCE MISMATCH (type c)
- **Paper claim**: "Buy-and-hold 50/50 SPY/GLD Sharpe = 0.947"
- **K731 (registered source for Table 3 period 2008–2026)**: BH 50/50 Sharpe = **0.827**
- **K507 (different, shorter period)**: BH 50/50 Sharpe = 0.947 with N=5339 days (different from 2008-2026 OOS window)
- **Note**: 12/VIX Sharpe = 0.870 is CONSISTENT across both k731 and paper. The BH benchmark is inconsistent.
- **Severity**: MEDIUM — the key narrative "50/50 outperforms every dynamic strategy" depends on this value; if BH=0.827 vs 12/VIX=0.870, the ranking reverses.
- **Fix needed**: Verify which sample period Table 3 uses; align BH 50/50 and 12/VIX from same experiment.

### DIV-4 ✗ Table 6: Era-specific incremental R² — SYSTEMATIC UNDERSTATEMENT (type b)
- **5 cells confirmed wrong** (already in reproduce_report.json):
  - Era3 GFC Overnight VIX: paper=0.0004, k752=**0.0039** (10× off)
  - Era5 COVID Overnight VIX: paper=0.0003, k752=**0.0032** (10× off)
  - Era3 GFC VRP Proxy: paper=0.0008, k752=**0.016** (20× off)
  - Era3 GFC Vol Momentum: paper=0.0006, k752=**0.0216** (36× off)
  - Era5 COVID Vol Momentum: paper=0.0002, k752=**0.0372** (186× off)
- **Severity**: MAJOR — K752 shows 4 era-signal combinations **Harvey-pass** (t > 3.0): GFC has 3 signals with t = -3.15, -6.51, +7.6; COVID has 1 signal at t = +9.3. The paper's Table 6 header "Harvey Pass? 0/5" is factually incorrect.
- **Fix needed**: Replace Table 6 values with k752 correct values; add caveat row noting era-level exceptions; update the narrative that "incremental R² values are uniformly tiny."

### DIV-5 ✗ Table 9 (VaR backtest) composite scores: AMEM=1.94, GJR=1.63 — FORMULA MISMATCH (type b/c)
- **Paper claim**: AMEM risk score = 1.94, GJR = 1.63 (max = 2.0)
- **K780 raw scores**: amem=24, gjr=20; if max=24 → normalized AMEM=2.00, GJR=1.67
- **Discrepancy**: AMEM 1.94 vs 2.00; GJR 1.63 vs 1.67; lower-ranked models diverge more
- **Severity**: LOW — rankings are correct; values differ by ≤5%
- **Fix**: Re-derive composite score formula or add footnote about scoring methodology.

### DIV-6 ? Table 10 (insurance): MDD reduction 12/VIX = -8.2 pp — UNTRACED (type c)
- **Paper claim**: "12/VIX (SPY/GLD): MDD reduction = -8.2 pp"
- **K738 cross-asset average**: avg MDD reduction = 12.3 pp (not 8.2)
- **EEM-specific**: 8.2 pp (exact match but wrong asset)
- **K786 (SPY/GLD full period)**: MDD reduction ≈ 0.5 pp (negligible!)
- **Severity**: MEDIUM — if Table 10 is for SPY/GLD specifically, source is unclear and may not be k738.
- **Fix**: Identify source experiment; likely needs a dedicated SPY/GLD 2007-2026 insurance calc.

### DIV-7 ? "36 null results" in conclusion — UNVERIFIED COUNT (type c)
- **Paper claim**: "The 36 null results accumulated across this research program"
- **Count from experiments**: 8 DM tests (Table 2) + 15 era-signal tests (Table 6) = 23 countable tests; reaching 36 requires additional undocumented counting
- **Integration plan** already updates this to "≈42 independent confirmations"
- **Severity**: LOW — conclusion language is approximate; note that integration_plan_v2.md already flags this.

### DIV-8 ✗ K1138 equity compendium: MIXED result not reflected in paper body (type b/missing)
- **K1138**: SPY/QQQ HAR-RV-X DM |t| = 4.18 / 4.22 — passes Harvey threshold
- **Paper §8.2**: claims intraday 5-min is the only frontier; K1138 shows HAR-RV-X (Parkinson range proxy) also breaks through on equity assets under fair test
- **Severity**: MEDIUM — this is a new finding that contradicts the "closed daily frontier" narrative partially; requires clarification that HAR-RV-X win is on Parkinson proxy (not 5-min RV)

---

## Internal cross-section consistency checks

| Check | Status |
|-------|--------|
| Abstract CV=0.33 vs Table 5 footer CV=0.33 | CONSISTENT (both wrong vs k752) |
| Abstract drag=3.49% vs Table 10 drag=3.49% | CONSISTENT (both from k738) |
| Abstract "36 VIX sufficiency tests" vs conclusion "36 null results" | CONSISTENT |
| Table 5 Full R²=0.514 vs abstract "0.24 to 0.64" range | CONSISTENT |
| Table 7 "12/VIX wins 1 of 5 eras" vs era results | CONSISTENT |
| Table 8 QLIKE rankings = MCS member = GJR | CONSISTENT |
| §8.3 AMEM score 1.94 vs GJR 1.63 text | CONSISTENT with Table 9 |
| Table 3 BH=0.947 vs Table 7 Era benchmarks (different periods) | No direct conflict |

---

## Body integration status for 9 new experiments

| Exp | Title | Exists | In main_v2.tex |
|-----|-------|--------|----------------|
| K1116 | EPU/NFCI/STLFSI alt-data SPY | YES | NO |
| K1117 | Jump-day matched-pair | YES | NO |
| K1118 | GLD/TLT/BTC cross-asset alt-data | YES | NO |
| K1116b | Publication-delay correction | YES | NO |
| K1121 | Alt-data for allocation | YES | NO |
| K1098 | VIXTWN 0050.TW | YES | NO |
| K1129 | GAS-t commodity | YES | NO |
| K1136 | Commodity compendium fair tests | YES | NO |
| K1138 | Equity SPY/QQQ/IWM compendium | YES | NO |
| K1135 | (unknown) | NOT FOUND | NO |
| K1137 | (unknown) | NOT FOUND | NO |
| K1139 | (intraday 5-min HAR) | NOT FOUND | NO |
| K1141 | (channel 3×4 table) | NOT FOUND | NO |
| K1143 | (HARM channel 3) | NOT FOUND | NO |
| K1123 | (unknown) | NOT FOUND | NO |

**Body stale: YES** — None of the integration_plan_v2.md changes have been applied to main_v2.tex.

---

## K1045-pattern rescan

Searching for unlisted/unregistered experiments that may back paper claims:
- K507 backs Table 3 BH Sharpe=0.947 but is NOT in reproduce.py's registered experiment list
- K507 period appears to be a different sample from Table 3's labeled period
- No other "ghost" experiments found that silently provide paper numbers

---

## Channel/narrative stale check

| Claim | Current main_v2.tex | Integration_plan_v2 target | Status |
|-------|---------------------|---------------------------|--------|
| "Eleven signal families" | Eleven (Families 1-11) | Should be Thirteen (add EPU + FinStress) | STALE |
| "Universal null for equity (SPY)" | SPY only | Should be "5 asset classes" | STALE |
| "No alt-data works" | Implicit in 11-family null | K1116 active-harm finding not present | STALE |
| "TLT M4 is a niche" | Not in paper | K1116b collapse not present | STALE |
| "Publication-delay robustness" | Not in paper | §4.5 missing | STALE |
| "Alt-data fails allocation too" | Not in paper | §7.5 missing | STALE |
| "VIXTWN boundary case" | Not in paper | §7.3 4th asset missing | STALE |
| "HAR-RV-X passes on equity" | Not in paper | K1138 MIXED finding missing | STALE (also contradicts narrative) |
