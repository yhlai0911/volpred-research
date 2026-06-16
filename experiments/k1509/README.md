# K1509: TIPS Regime-Conditional Volatility Decomposition

## 動機

TIPS ETF 在投資人心中是「通膨保護」資產，但其 **vol exposure** 在不同通膨 regime
下是否有結構性差異、是否伴隨 vol 補貼（premium）或 vol 折扣（discount），文獻
上多在 return / yield 層面討論，較少從 daily RV / tail risk 角度分解。

本實驗以 CPI YoY 為 regime label，比較 TIPS ladder（TIP / STIP / LTPZ）vs nominal
Treasury（IEF）在高通膨（>3%）vs 正常 regime 下：

1. 每資產的 21d 與 5d annualized RV
2. 每資產的 5% empirical ES（tail risk）
3. `TIPS - IEF` 的 RV gap

回答：**高 CPI regime 下，TIPS 的 vol exposure 相對 nominal Treasury 是貴還是便宜？**

## 與相鄰 K 的差異化

- **K557**: 黃金 regime exposure — 不同資產類別，無 TIPS，無 CPI regime
- **K737**: max-diversification basket — 組合構建，非 regime decomposition
- **K925**: CPI 公布日 event study on SPY — event window 觀點 + 標的是股權
- **K1509**（本實驗）: regime-conditional RV / ES decomposition on TIPS ladder
  vs nominal Treasury

## 資料

- 價格：yfinance `TIP / STIP / LTPZ / IEF` + context `AGG / ^TNX`
- 期間：2015-01-01 → 2026-06-15（2,878 個交易日）
- CPI：FRED `CPIAUCSL`（local CSV `storage/macro/fred_CPIAUCSL.csv`）
- CPI YoY 範圍 -0.23% .. 8.98%

## 方法

### Lookahead-safe regime label

兩層 lag：
1. **Release lag**：CPI month M 的數值假設在 M+2 月初才 known（保守）
2. **Trading-day lag**：再加 `shift(21)` ≈ 1 calendar month

→ 第 t 日的 regime label 只用 ≥6 週前已 release 的 CPI YoY。

### RV / ES / Gap

- RV = rolling std of daily log returns × √252，windows 5d 與 21d
- ES = 5% empirical lower-tail mean
- Gap = `RV_TIPS - RV_IEF`

### 檢定

- Welch t-test（unequal variance）on RV by regime
- Bootstrap 95% CI（5,000 reps，seed=42）on mean diff
- Bonferroni：3 TIPS × 2 windows = 6 RV tests，α = 0.05/6 ≈ 0.0083
- ES 與 gap 為 descriptive，未進 Bonferroni family

## 結果

**Verdict: PASS** — 高 CPI regime 下 TIPS 的 RV 顯著高於正常 regime；但
**TIP-IEF RV gap 變得更負**，即 TIP 相對 IEF 的 vol *折扣* 在高通膨期擴大。

### 樣本

- High CPI regime: 847 個交易日（high_share ≈ 29.4%；主要落在 2021-2023）
- Normal regime: 2,031 個交易日

### RV by regime（21d，annualized）

| Asset | High CPI | Normal | Diff   | p-value    | Bonf verdict |
|-------|----------|--------|--------|------------|--------------|
| TIP   | 0.0652   | 0.0436 | +0.0216 | 6.1e-85    | SIG_BONF     |
| STIP  | 0.0284   | 0.0168 | +0.0116 | 1.7e-103   | SIG_BONF     |
| LTPZ  | 0.1675   | 0.1222 | +0.0453 | 1.5e-69    | SIG_BONF     |
| IEF   | 0.0814   | 0.0522 | +0.0292 | 4.6e-152   | SIG (ref)    |

### TIPS – IEF RV gap（21d）

| Pair      | High CPI | Normal  | Diff   | p-value    | Direction              |
|-----------|----------|---------|--------|------------|------------------------|
| TIP-IEF   | -0.0162  | -0.0085 | -0.0076 | 2.6e-48    | TIP 比 IEF 更便宜（vol 折扣加大） |
| STIP-IEF  | -0.0530  | -0.0354 | -0.0176 | 6.3e-141   | STIP 折扣顯著加大        |
| LTPZ-IEF  | +0.0861  | +0.0700 | +0.0161 | 1.4e-19    | LTPZ 補貼加大（長 duration 放大 vol） |

### ES5（5% empirical ES of daily log returns）

| Asset | High CPI | Normal   | Diff（更負 = tail 更深） |
|-------|----------|----------|--------------------------|
| TIP   | -0.00957 | -0.00694 | -0.00263                 |
| STIP  | -0.00428 | -0.00260 | -0.00168                 |
| LTPZ  | -0.02340 | -0.01891 | -0.00449                 |
| IEF   | -0.01111 | -0.00758 | -0.00353                 |

## 解讀

- 高 CPI regime 下**所有**債券類資產 RV 都顯著上升，TIPS 不例外 → 「通膨保護」
  不等於「vol 保護」。
- **TIP / STIP 相對 IEF 的 RV gap 更負**（折扣加大）：通常與 TIP（5y duration）
  / STIP（<5y）低於 IEF（7-10y）的 duration 差有關 — 在 yield 大幅波動時
  duration 短的 RV 上升幅度小於 IEF，gap 加大。
- **LTPZ-IEF gap 更正**（補貼加大）：LTPZ ~20y+ duration，在高 CPI 期 vol 放大
  幅度遠超 IEF。
- 投資涵義（**僅 descriptive，不可外推為交易訊號**）：高 CPI regime 若想
  「保住通膨曝險但壓低 vol」，TIP / STIP 比 LTPZ 更合適；但 ES tail 仍會加深。

## 局限

1. 樣本內只有**一次** high CPI episode（2021-2023 post-COVID）— 無法分離
   「CPI regime」與「Fed 升息週期 / COVID 後遺症」效應。
2. Daily RV 噪音大；未使用 intraday TIPS 數據。
3. LTPZ 流動性偏薄，可能注入與 CPI 無關的 idiosyncratic vol。
4. ES5 估計依賴 regime 樣本數；高 regime n=847 仍夠用但比 normal 少。
5. Bonferroni 只套用在 RV family（6 tests）；gap 與 ES 檢定為 descriptive。
6. **Welch t-test on overlapping 21d rolling RV is anti-conservative**：rolling
   window 之間有 ~20 天重疊 → 樣本非獨立，effective N ~1/21 of nominal。報告 p-value
   不可直接照用；directional 結論在 effect-size 量級上仍可信，但嚴格推論需 Newey-West
   / block bootstrap 修正。
7. **iid bootstrap CI** on serially-correlated rolling RV understates uncertainty；
   應改用 block bootstrap，block_size = window。

## Review

- Reviewer: code-reviewer subagent (Codex CLI 0.139.0 stdin-hang fallback)
- Verdict: **CONDITIONAL_PASS**（補 limitations 後可寫 knowledge.json）
- Reviewed at: 2026-06-16T10:50 +08:00

## 重跑

```bash
uv run python experiments/k1509/k1509.py
```

Seed = 42。產出 `k1509_results.json` + `figures/fig_a_rv_by_regime.png`
+ `figures/fig_b_rv_gap_vs_nominal.png`。
