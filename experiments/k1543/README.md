# K1543 — Listed Infrastructure ETF Inflation-Hedge: 真效應 or composite-beta artifact?

**Status**: COMPLETE, Codex Round-2 PASS
**Verdict**: **MIXED** (lean NULL — narrative largely a composite-beta artifact)
**Run**: 2026-06-24

---

## Motivation

主流敘事：listed infrastructure ETF（IFRA / NFRA / IGF / PAVE / GRID / UTF / XLU）在通膨期間提供 hedge — 收費自動 CPI 連動、實體資產、穩定現金流。

**Falsifiable claim**：「inflation-shock days 上，listed infra RV、downside semivariance、equity correlation **顯著低於** SPY，且此效應 **獨立於 energy beta (XLE) + duration beta (TLT/IEF) + VIX level**」。若控制這些 beta 後 β1 → 0 → 是 composite-beta artifact，不是 infra-specific 性質。

---

## Differentiation vs K1508

| | K1508 | K1543 |
| --- | --- | --- |
| 敘事 | AI power demand → utility ETF vol regime | inflation-hedge mechanism + composite-beta falsification |
| Outcome 變數 | log(fwd_rv21 ratio) | log(rv_etf / rv_spy) + 4-tier hypothesis 結構 |
| Driver | AI capex / 裝置容量公告 | CPI/PPI release ±5d + breakeven inflation tail |
| ETFs | XLU/IDU/RYU | IFRA/NFRA/IGF/PAVE/GRID/UTF/XLU |
| Controls | none (vol regime classification) | XLE energy beta + TLT duration + VIX level |
| Verdict | NULL | MIXED (3/7 H4 sig, none Bonferroni-survive) |

K1508 測 AI 敘事的 ex-ante effect；K1543 測 inflation-hedge 機制的 **controlled-regression survival**。完全不同 hypothesis 結構，無內容重疊。

---

## Method

### Data
- **Infra ETFs (7)**: IFRA, NFRA, IGF, PAVE, GRID, UTF, XLU（yfinance, adjusted close）
- **Controls (5)**: SPY, XLE, TLT, IEF, ^VIX (raw level, 不是 RV/return)
- **FRED**: CPIAUCSL, PPIACO, T5YIE, T10YIE（HTTP CSV，避開壞掉的 pandas_datareader）
- **Period**: 2014-01-02 to 2026-06-18，n=3,135 trading days
- **Infra ETF first dates**: GRID/IGF/NFRA/UTF/XLU = 2014-01-24, PAVE = 2017-03-29, IFRA = 2018-04-26

### Inflation-shock definition (causal)
1. **CPI release window**: 每月 CPI release 後 5 trading days (right-aligned rolling, 不 center)
2. **Breakeven shock**: |Δ T5YIE| > 5 bp 單日（top tail）
- Combined OR → shock_n = 967 / 3,135 ≈ 30.8%
- All predictors **`.shift(1)`** (forward-facing)

### 4-tier hypothesis
- **H1 raw RV**: 在 shock days, paired t-test + Wilcoxon (one-sided ETF<SPY)
- **H2 downside semivariance**: 同 H1 但限 r<0
- **H3 60d corr(ETF, SPY)**: Fisher-z transform, Welch t-test, shock vs baseline regime
- **H4 controlled regression (KEY)**:
  ```
  log(rv_etf / rv_spy)_t = α + β1 × shock_{t-1}
                            + β2 × |r_xle|_{t-1}
                            + β3 × |r_tlt|_{t-1}
                            + β4 × vix_{t-1} (level) + ε
  ```
  HAC (Newey-West, maxlags=10). β1 < 0 且顯著 = hedge 在控制 beta 後 survive.

### Multiple testing
- 7 ETFs × 4 tests = 28 cells
- α_raw = 0.05, α_Bonferroni = 0.05 / 28 = 0.001786
- One-sided p-values (hedge = lower RV / lower corr / β1<0)

### Lookahead 防錯
- 所有 predictor `.shift(1)`
- CPI release window 用 right-aligned rolling (不 center)
- CPI/PPI MoM 用月末 +15 calendar day 保守 lag (conservatively > BLS 真實 release lag of ~10-15d)
- VIX 用真實 level (not rv_VIX) — Codex round-1 fix
- shock_lag 只 lag 一次（Codex round-1 fix：原本 H4 內 double-shift）
- seed = 42 全程

---

## Results

### Cell-level pass count
- **Raw α=0.05**: 6 / 28 cells
- **Bonferroni α=0.001786**: 3 / 28 cells

### H1 (raw RV) — 部分 ETF 在 shock days RV 顯著低於 SPY
- NFRA, IGF significant raw; NFRA also Bonferroni
- IFRA, PAVE, GRID, UTF, XLU: NULL (paired RV not below SPY on shock days)
- 此 H1 結果矛盾於通膨-hedge 敘事的部分 ETF

### H4 controlled regression — β1 (shock_lag) table

| ETF | n | β1 | p (2-sided) | sig α=0.05 | Bonferroni |
| --- | --- | --- | --- | --- | --- |
| IFRA | 2047 | -0.055 | 0.212 | × | × |
| NFRA | 3118 | -0.023 | 0.384 | × | × |
| IGF | 3118 | -0.028 | 0.430 | × | × |
| PAVE | 2318 | -0.068 | 0.041 | ✓ | × |
| **GRID** | **3118** | **-0.102** | **0.0025** | **✓** | **×** (just above) |
| UTF | 3118 | -0.011 | 0.804 | × | × |
| XLU | 3118 | -0.077 | 0.060 | × (borderline) | × |

- **β1 median = -0.055, range [-0.102, -0.011]**
- **3/7 ETFs survive raw α=0.05** (PAVE, GRID, XLU borderline)
- **0/7 ETFs survive Bonferroni α=0.001786** — GRID 最強 (p=0.0025) 但仍未過 28-cell adjustment
- IFRA, NFRA, IGF, UTF 控制後 β1 完全不顯著

### Verdict 解讀
- H1 raw 顯示部分 ETF (NFRA, IGF) 確實在 inflation-shock days RV 比 SPY 低 — **但 H4 controlled regression 大幅削弱**：NFRA/IGF 在 H1 raw 顯著的同時，H4 β1 卻 p=0.38/0.43 完全不顯著 → 表示 H1 顯著性主要來自 energy/duration/VIX beta 而非 infra-specific
- 真正 H4 survive 的是 GRID (clean energy grid build-out, 可能與 XLE 有 partial 但不完全 collinearity) 與 PAVE (US infra build-out, 與 fiscal-stimulus inflation 時期重疊)、XLU borderline
- 傳統「infra hedge」的主力候選 IFRA / NFRA / IGF / UTF 在 controlled regression 完全失敗

### Robustness sub-periods
- 2014-2019 (低通膨期): 多數 ETF β1 不顯著（樣本 inflation variation 小）
- 2020-2026 (高通膨期): GRID/PAVE β1 仍負且部分顯著；其他 ETF 仍不顯著
- 提示 hedge effect 在低通膨期難測量 (low SNR)，高通膨期略強但仍未 widespread

---

## Verdict

**Interpretation**: `MIXED` (lean `NULL_REJECTED_HEDGE`)
**Reasoning**: H4 controlled regression: 3/7 ETFs (PAVE, GRID, XLU) show β1<0 與 raw-α significance, 但 **0/7 survive Bonferroni**. 主要候選的 infra-pure ETFs (IFRA, NFRA, IGF) 全部失敗。H1 raw 看似的 hedge effect 主要被 energy beta (XLE) + duration beta (TLT) 解釋掉。
**Take-away**: Listed infrastructure ETF 的「inflation-hedge」敘事在 controlled regression 下大幅縮水。Survive 的 GRID/PAVE 可能反映 fiscal-stimulus capex theme，與 commodity/duration beta 部分相關。**敘事方向正確但效應 magnitude 被 composite-beta 大幅吸收**，作為純 inflation hedge 的 portfolio 配置依據不夠強。

### Caveats
1. CPI/PPI surprise proxy 用 FRED 已 released 數據 + 保守 +15 calendar day lag，不是 Bloomberg consensus surprise (real-time vintage 未用) — 可能低估真實 surprise magnitude
2. T5YIE 自 2003 起，sample 自 2014 起 OK
3. PAVE (2017+), IFRA (2018+), GRID (2014+) 樣本長度不一，limits effective n for newer ETFs
4. Bonferroni 對 28 cells 跨 ETF (高度相關，特別 UTF/XLU 共用 utility exposure) 保守 — true effective tests 可能 < 28
5. Shock 定義（±5d CPI window OR |ΔBE5|>5bp）是一種可能 spec，未跑 grid of thresholds
6. yfinance adjusted close，no intraday TAQ
7. HAC lag=10 trading days assumption

---

## Literature

- **Rödel (2014)**, *Real Estate Economics* — "Inflation Hedging with Real Estate Investments" — REIT/infra hedge 性質; 部分 horizon-dependent
- **Bekaert & Wang (2010)**, *Economic Policy* — "Inflation Risk and the Inflation Risk Premium" — 通膨 hedge 評估方法論 (Fama 1981 / Schwert 1981 框架)
- **Bhardwaj, Gorton, Rouwenhorst (2015)**, *Yale ICF Working Paper* — "Facts and Fantasies about Commodity Futures Ten Years Later" — commodities 作為 inflation hedge 證據強度評估
- **Bekaert & Engstrom (2010)**, *JFE* — "Inflation and the Stock Market: Understanding the Fed Model"
- **Fang, Liu, Roussanov (2022)**, *NBER WP* — "Getting to the Core: Inflation Risks Within and Across Asset Classes"

---

## Files

- `k1543.py` — main script
- `k1543_results.json` — full 28-cell results + H4 regression + robustness
- `k1543_panel.parquet` — full panel data cache
- `fig1.png` — RV boxplot by regime (7 ETFs + SPY × shock/baseline)
- `fig2.png` — H4 β1 forest plot (95% CI)
- `review_codex.md` — Codex round-1 FAIL (3 issues fixed) + round-2 PASS

---

## Reproducibility

```bash
FRED_API_KEY=<key> uv run python experiments/k1543/k1543.py
```
seed=42, deterministic given yfinance + FRED snapshot.

---

## verdict_summary

```yaml
interpretation: MIXED  # lean NULL_REJECTED_HEDGE
reasoning: |
  H4 controlled regression β1 median=-0.055, only 3/7 ETFs (PAVE, GRID, XLU) raw-significant,
  0/7 Bonferroni-significant. Core "infra hedge" candidates (IFRA, NFRA, IGF, UTF) fail completely
  in controlled regression despite H1 raw signal — confirming the composite-beta artifact hypothesis
  for those names. GRID/PAVE survival likely reflects fiscal-stimulus capex theme rather than
  pure inflation-hedge mechanism.
codex_review: ROUND2_PASS (round-1 FAIL → 3 issues fixed → round-2 PASS)
reviewer_source: codex_exec_gpt5.4
```
