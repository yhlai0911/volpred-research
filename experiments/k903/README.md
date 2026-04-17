# K903: Paper 1 Tables 2/3 Canonical 2010-Start Replication

- **Experiment ID:** K903
- **Status:** completed
- **Created:** 2026-04-17
- **Extends:** K902 (Paper 1 Tables 1&3 supplement, 2017-start)
- **Author:** worktree agent (agent-a3ad0b51)

## 問題描述

K902 reproducibility audit (diff_report.md) revealed two primary divergences vs Paper 1 main.tex:
- **D1 (Table 3):** Absolute QLIKE values not reproducible — K902 uses 2017-start, paper uses longer training window
- **D2 (Table 2):** Rolling gamma statistics diverge — especially GLD mean γ (paper=-0.067 vs K902=-0.006)

## 動機

Produce canonical Tables 2 and 3 numbers that match Paper 1 main.tex by correcting K902's methodological mismatches.

## 方法 (K902 differences)

K903 makes 4 key changes relative to K902:

1. **data_start=2010-01-01** (K902 used 2017-01-01)
2. **Rolling OOS window w=504** (K902 used expanding window — paper body explicitly: "rolling window approach" and "expanding windows [produce] worst QLIKE")
3. **Rolling step=63 days** (K902 used ~50 — paper: "504-day windows advanced by 63 trading days")
4. **HAC lags=8** (K902 used 5 — paper body.tex: "Newey-West HAC standard errors (8 lags)")

## 結論

### DIVERGENT — K903 still diverges from Paper Tables 2 & 3

**Table 2 (Rolling Gamma):**
- SPY HAC t: K903=11.08 vs Paper=8.30 — divergent (K902 was 6.75)
- GLD mean γ: K903=+0.002 vs Paper=-0.067 — sign different
- GLD HAC t: K903=0.15 vs Paper=-5.79 — sign and magnitude both divergent

**Table 3 (QLIKE):**
- K903 rolling w=504 gives SPY 2023-24 GJR=-8.674, while Paper Table 3 says -9.034
- **BUT**: Paper's own Table 8 (Window Robustness) shows SPY w=504 2023-24 = -8.671, which ≈ K903 (-8.674)!
- This reveals an internal paper inconsistency: Table 3 ≠ Table 8 at same w=504

## 關鍵發現 (Critical Finding)

**K903 actually matches Paper Table 8, NOT Paper Table 3.**

| Source | SPY 2023-2024 GJR QLIKE |
|--------|------------------------|
| K903 (rolling w=504) | -8.674 |
| Paper Table 8 (w=504) | -8.671 |
| Paper Table 3 (GJR) | -9.034 |

**Paper Table 3 and Paper Table 8 are internally inconsistent by 0.363 QLIKE units for the same asset/period/window.**

### Root cause analysis

The persistent gap between K903 and Paper Table 3 absolute QLIKE values suggests Paper Table 3 was computed with a **different OOS methodology** than what's described in the methods section. Possibilities:
- (a) Daily refit (refit every 1 day, not every 63)
- (b) Different warm-up / initialization
- (c) Paper Table 3 numbers were computed with the Python `arch` package which may use different variance initialization

### (a)/(b)/(c) Decision

**Recommendation: (c) errata pending — main thread investigation required**

1. Paper Table 8 (w=504, SPY 2023-24) = -8.671 matches K903 (-8.674) → our methodology is correct
2. Paper Table 3 (SPY 2023-24 GJR) = -9.034 ≠ Table 8 = -8.671 → internal paper inconsistency
3. Paper Table 2 (GLD mean γ = -0.067) requires a fundamentally different data window than what's currently confirmed
4. The qualitative scientific conclusions are confirmed: GJR > GARCH for SPY, not for GLD/TLT/BTC

**Main thread actions needed:**
- Investigate internal inconsistency between Table 3 and Table 8 in paper
- Either: (b) update paper to use K903's methodology (which matches Table 8), OR clarify what's different about Table 3 computation
- For Table 2 gamma values: may need to investigate different data period (2005-2025?) or different GJR estimation constraints

## 檔案

- `k903.py` — script (rolling w=504, step=63, HAC lags=8, data_start=2010)
- `k903_results.json` — full results
- `tables/k903_table2.csv` — Table 2: rolling gamma per asset
- `tables/k903_table3.csv` — Table 3: OOS QLIKE per asset/period
- `k903_vs_paper_diff.md` — cell-by-cell comparison vs paper

## 數據來源

- yfinance, 2005-01-01 to 2026-04-17
- Assets: SPY, QQQ, EEM, GLD, TLT, BTC-USD, SLV (Table 2); SPY, QQQ, GLD, TLT, EEM, BTC-USD (Table 3)
- OOS periods: 2023-01-01 to 2024-12-31 (primary); 2025-01-01 to 2026-03-31 (validation)

## 參考

- K902: original Paper 1 Tables supplement (2017-start, expanding window)
- diff_report.md: audit identifying sample period mismatch as root cause
- Paper body.tex line 74: "rolling window approach, w=504"
- Paper body.tex line 111: "504-day windows advanced by 63 trading days"
- Paper body.tex line 164: "Newey-West HAC standard errors (8 lags)"
- Patton (2011): QLIKE proxy-robust loss function
- Diebold & Mariano (1995): predictive accuracy test
- Harvey et al. (2016): t>3.0 threshold
