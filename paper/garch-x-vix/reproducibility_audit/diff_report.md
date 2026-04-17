# Paper 9 (garch-x-vix) Reproducibility Audit — Diff Report

**Audit Date**: 2026-04-17  
**Paper Status**: Submitted (under review)  
**Auditor**: Claude Sonnet 4.6 (worktree agent-adb9418c)  
**Protocol**: Three-way consistency: main.tex → script results JSON → tolerance check

---

## Summary Statistics

| Category | Count | Fraction |
|----------|-------|---------|
| ✓ Matched | 86 | 55.5% |
| ≈ Approx (within rtol but note) | 8 | 5.2% |
| ✗ Divergent | 7 | 4.5% |
| ? No-source | 54 | 34.8% |
| **Total extracted** | **155** | 100% |

**Coverage rate**: 65.2% of numbers have source (matched + approx + divergent)  
**Match rate (of sourced)**: 85.1% (86/101 matched or approx among 101 with source)

---

## ✓ Matched Numbers (Key Highlights)

### Core DM/QLIKE Results (Table 3 — ALL 17 models)
All 17 QLIKE values and 16 DM t-statistics from `mcs_dm_results.json` match the paper's Table 3 to 3 decimal places. This is the central horse-race result.

- A4f QLIKE: tex=−8.360 vs script=−8.35979 ✓
- A4f DM t vs GJR: tex=4.03 vs script=4.0304 ✓
- GJR QLIKE: tex=−8.273 vs script=−8.27250 ✓

### MCS Results (Table 5)
- α=0.10: all 17 survive ✓
- α=0.25: GJR eliminated p=0.229 ✓

### Pairwise DM (Table 4)
- A4f vs B2: tex=−3.04 vs script=−3.0396 ✓
- A4f vs B3: tex=−3.73 vs script=−3.7319 ✓

### VaR Backtesting (Tables 8–9 — 30 cells)
All violation rates and p-values match K995 exactly (to 3-4 dp).

### VRP Correlations (Table 10)
- A3f rho=0.819, A2n rho=0.801, A4n rho=0.778, raw rho=0.151 — all match K988b ✓

### ES Results (Table 9)
All Z1/Z2 statistics match K995 ✓

### Giacomini-White Tests
- A4f vs GJR χ²=16.28 vs script=16.278 ✓
- A4f vs B1 χ²=3.77 vs script=3.769 ✓

### Degrees of Freedom
- GJR-t median ν=5.28 vs K995=5.28 ✓
- A4f-t median ν≈8.00 vs K995=7.85 ≈ (small diff)

### VRP Section (K998)
- OOS R²=1.3% vs K998=1.34% ✓
- Variance swap Sharpe=−0.64 vs K998=−0.639 ✓
- Naive sell Sharpe=+0.85 vs K998=+0.845 ✓

---

## ✗ Divergent Cases (7 instances — All need resolution)

### D1: STOXX50E DM t = 3.64 vs K949 FEZ t = 3.84
**Location**: Table 6 (cross-asset), Section 4.3, Abstract  
**tex**: EURO STOXX 50: DM t=3.64; FEZ: DM t=3.45  
**Script**: K949 FEZ DM_MFvsGJR t_stat=3.842  
**Magnitude**: |Δ|=0.20 for STOXX50E, larger for FEZ  
**Root cause**: K949 uses OOS 2016–2025, paper claims OOS 2019–2026. Different estimation periods produce different DM statistics. K949 also uses "MF-GJR" (log-exp spec) not "A4f" (VIX², free ω).  
**Risk**: HIGH — reviewer will check these against Table 6  
**Recommendation**: (a) Run dedicated experiment with exact A4f spec on STOXX50E/FEZ over 2019–2026 OOS period and update Table 6 with verified numbers. If new experiment matches 3.64/3.45, document K949 as preliminary only.

### D2: FEZ DM t = 3.45 — No source
**Location**: Table 6, Abstract, Conclusion  
**tex**: FEZ DM t=3.45 (Harvey sig.)  
**Script**: No experiment found producing this exact number. K949 FEZ=3.84 (different spec/period). K994 does not include FEZ.  
**Risk**: HIGH — paper claims Harvey significance; no verifiable source  
**Recommendation**: (c) Errata pending — must create dedicated FEZ experiment with A4f, OOS 2019–2026, to verify or correct. Cannot proceed with submission replication package without this.

### D3: 0050.TW DM t = 1.44 — Mismatch
**Location**: Table 6  
**tex**: 0050.TW DM t=1.44 (No Harvey sig.)  
**Script**: K997 dm_t=−1.677; K1098 a4f_vix dm_t=2.68  
**Note**: K997 and K1098 use different OOS periods and data configurations. Neither matches 1.44.  
**Risk**: MEDIUM — directional conclusion (not significant) is preserved, but exact number diverges  
**Recommendation**: (a) Identify which experiment produced 1.44, or rerun with canonical settings and update tex.

### D4: GLD+GVZ DM t = 3.17 vs K1085 full OOS t = 4.46
**Location**: Table 6, Abstract  
**tex**: GLD with GVZ DM t=3.17  
**Script**: K1085 full_oos gjr_vs_a4f_gvz dm_t=4.457 (n=2645); K997 A4f_GVZ dm_t=−3.173  
**Root cause**: K997 uses n=1824 (OOS 2019–2026) which matches paper period; K1085 uses full OOS 2007–2026. Paper Table 6 references K1085 but the t=3.17 is from K997.  
**Risk**: LOW-MEDIUM — K997 verifies t=3.17 exactly. Confusion arises from README citing K1085 for this result.  
**Recommendation**: (b) Update results/README.md to correctly attribute GLD t=3.17 to K997 (not K1085). The tex number is verifiable from K997.

### D5: Sensitivity Table (Table 12) baseline DM t = 3.92 vs main table 4.03
**Location**: Table 12 (sensitivity), Section 5.1  
**tex**: Table 12 row "63 days (baseline)" shows DM t=3.92; main Table 3 shows DM t=4.03  
**Script**: mcs_dm_results.json has 4.030379 (the Table 3 value). No sensitivity JSON exists.  
**Root cause**: The 3.92 in sensitivity table appears to be from a different run (possibly K988 direct which gives 4.48, or an intermediate run). The canonical mcs_dm_results.json gives 4.03 for the baseline.  
**Risk**: MEDIUM — different rows in same paper give slightly different numbers for the "same" setting  
**Recommendation**: (c) Errata: add footnote clarifying that sensitivity table uses slightly different computation pipeline; the definitive baseline is Table 3 (t=4.03 from compute_mcs_dm.py).

### D6: n_OOS discrepancy — n=1828 vs n=1825
**Location**: Table 11 footnote  
**tex**: Table 11 footnote says n=1,828  
**Script**: K995 n_oos=1825; mcs_dm_results n_oos=1825  
**Root cause**: Possible data end date difference. 1828 might correspond to a different end date (e.g., 2026-04-08 vs 2026-04-07 with SPY trading days).  
**Risk**: LOW — minor, but reviewers notice footnote inconsistencies  
**Recommendation**: (b) Update Table 11 footnote from n=1,828 to n=1,825 to match K995 and canonical OOS period.

### D7: QQQ VIX-r² correlation in Table 6 — 0.52 vs K994 0.494
**Location**: Table 6  
**tex**: QQQ VIX-r² corr=0.49 (K994 matches at 0.4936); SPY VIX-r² corr=0.52  
**Script**: K994 vix_r2_corr_oos=0.4936 for QQQ (matches); SPY corr=0.52 not directly in K994 JSON  
**Risk**: LOW — within rounding but SPY correlation missing from script output  
**Recommendation**: (a) Add SPY VIX-r² correlation to K988/K995 results JSON, or document source.

---

## ? No-Source Numbers (Critical Missing Sources)

### CRITICAL (Submitted Paper Risk)

**Table 11 — Residual Diagnostics (6 values)**  
Excess kurtosis (3.065/1.238), skewness (−0.856/−0.594), Jarque-Bera (938.8/224.2), kurtosis change −59.6%, JB change −76.1%, skewness change −30.6%.  
These are presented as a dedicated table but have **no corresponding results JSON** in any experiment. The ν shift (5.28→8.00) is sourced from K995, but the distributional statistics themselves are unverifiable from current scripts.  
**Risk**: HIGH — reviewer may request these numbers specifically; currently not reproducible from any script.  
**Action needed**: K995.py should be extended to compute standardized residual diagnostics (kurtosis, skewness, JB) and save to JSON.

**Table 12 — Sensitivity Analysis (12+ values)**  
Refit frequency (21/63/126/252 days), window size (W=1000/1500/2000/2500/3000), VIX variant (VIX9D/VIX3M/ratio) DM t-statistics.  
No dedicated sensitivity experiment JSON. These could come from a sensitivity run of compute_mcs_dm.py or K988.  
**Risk**: HIGH — systematic sensitivity table without reproducible source is a replication package gap.

**Section 5.3 — VIX vs Macro Comparison DM t=4.77**  
"VIX dominates all macroeconomic specifications (DM t=4.77 for VIX vs. best macro model)"  
No experiment JSON found for macro comparison.  
**Risk**: MEDIUM — important methodological claim without traceable source.

**Section 4.3 — Seven Two-Year Windows**  
"7/7 periods, improvements ranging from 4.81% to 8.09% (mean 6.52%), three pass Harvey |t|>3.0, five pass |t|>2.0, pooled t=6.535"  
No sub-period analysis JSON found.  
**Risk**: MEDIUM-HIGH — these statistics support key robustness claim; no source.

---

## DM t Discrepancy: K988 (4.48) vs mcs_dm_results (4.03) vs Paper (4.03)

This is a **known source confusion** documented in experiment_experiences but worth highlighting:
- K988.py produces A4f DM t=4.48 (using K988's internal computation)
- compute_mcs_dm.py produces A4f DM t=4.03 (used in paper)
- Paper correctly cites 4.03 sourced from compute_mcs_dm.py

The README correctly identifies mcs_dm_results.json as the canonical source. This is consistent. The 4.48 in K988 is from a slightly different DM implementation; the 4.03 from the dedicated MCS script is what appears in Tables 3–4.

**Note**: The README.md currently says "DM t=4.03 vs GJR-GARCH (Harvey PASS)" for the key result, which matches mcs_dm_results.json. The K988 DM=4.48 is from K988.py's own DM computation which uses a slightly different denominator treatment.

---

## One-Click Reproducibility Assessment

**From clean clone, running the full sequence:**
```bash
uv run python experiments/k988/k988.py           # Core 11 models
uv run python experiments/k988/k988b_supplement.py  # 6 MIDAS specs
uv run python experiments/k989/k989_mf2_vix2.py    # VIX2 synthesis
uv run python paper/garch-x-vix/compute_mcs_dm.py  # Tables 3-5
uv run python experiments/k995/k995.py             # VaR/ES Tables 8-9
uv run python experiments/k997/k997.py             # Local fear Tables 7-8
uv run python experiments/k998/k998.py             # VRP Section 4.2
uv run python experiments/k1085/k1085.py           # GLD robustness (Fig only)
uv run python experiments/k1088/k1088.py           # USO robustness (Fig only)
uv run python experiments/k1098/k1098.py           # Taiwan robustness
```

**Can reproduce**: Tables 3, 4, 5, 8 (VaR), 9 (ES), 10 (VRP corr), most of 6 (cross-asset)  
**Cannot reproduce**: Tables 11 (residual diagnostics), 12 (sensitivity), FEZ/STOXX50E rows of Table 6, VIX macro comparison, seven two-year sub-period analysis

**Missing scripts to add for full reproducibility**:
1. `experiments/k995/k995.py` — extend to compute residual kurtosis/skewness/JB
2. A dedicated sensitivity experiment (new K number) for Table 12
3. A dedicated STOXX50E/FEZ experiment with A4f spec, OOS 2019–2026
4. A dedicated 0050.TW experiment confirming t=1.44 or updating tex

---

*This report is diagnostic only. No tex files, results JSONs, or shared state were modified.*
