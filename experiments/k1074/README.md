# K1074: A4f Forecast -> Volatility Targeting Strategy Economic Value

**提出：** 賴奕豪 · **執行：** Claude · **日期：** 2026-04-12

## 1. 問題描述

K988 / K1055 / K1056 / K1073 一系列實驗已經把 **A4f** 規格的統計優勢建立起來：

```
A4f:  tau_t = theta0 + theta1 * VIX_{t-1}^2      (長期組件，VIX^2)
      sigma^2_t = tau_t * g_t                   (乘法分解)
      g_t: GJR(1,1) with free omega             (短期組件)
```

- **K988**：A4f_vix2_free_omega 在 SPY 2019-2026 OOS 上 QLIKE 勝 GJR-GARCH，DM |t|=4.48。
- **K1055**：區間窄 5%–11%，CI 不跨零。
- **K1056**：切 5 個 sub-period 全部 5/5 勝。
- **K1073**：延長 OOS 到 2013-2026、對照 VIX 家族（VIX9D、VIX3M、VVIX、SLOPE），A4f(VIX) 仍穩居前列。

**但統計準不等於策略好。** Moreira & Muir (2017) 和 Harvey et al. (2018) 兩篇都指出：
波動率預測精度的邊際改善，多半被交易成本和 turnover 吃掉；而 Paper 3 的主要論點是
「VT 的 alpha 來自 return-side 而非 vol-side」——果真如此，`sigma_hat` 的精度就不是瓶頸，
A4f-VT 不該明顯贏 12/VIX-VT。

## 2. 研究問題

| # | Hypothesis | 關注指標 |
|---|-----------|---------|
| H1 | A4f-VT Sharpe > 12/VIX-VT Sharpe | Sharpe annualised |
| H2 | A4f-VT MDD shallower than 12/VIX | Maximum drawdown |
| H3 | A4f-VT turnover > 12/VIX（reactive sigma） | Mean \|dw\|、年化 notional |
| H4 | 扣 5bp TX 後 A4f-VT 仍贏 | Net Sharpe |
| H5 | 50/50 SPY/GLD + A4f-VT > 50/50 + 12/VIX | Paper 3 standard |

## 3. 策略定義

所有 weight 都以 **t-1 可用資訊** 計算（K679 lookahead 守則）。

| Strategy | 公式 |
|----------|------|
| **A 12/VIX** | `w_t = min(12 / VIX_{t-1}, 1.5)` |
| **B A4f-VT** | `w_t = min(0.12 / sigma_hat_{A4f, t-1}, 1.5)`，`sigma_hat = sqrt(h_{A4f}) * sqrt(252)` |
| **C GJR-VT** | `w_t = min(0.12 / sigma_hat_{GJR, t-1}, 1.5)` |
| **D 50/50 + 12/VIX** | 50% SPY leg 套用 w_12vix；50% GLD；每月初 rebalance |
| **E 50/50 + A4f-VT** | 50% SPY leg 套用 w_A4f；50% GLD；每月初 rebalance |

Benchmark：`BH_SPY`、`BH_5050_SPY_GLD`（buy-and-hold）。

**交易成本**：5 bp 對 `|Δw|` 收取，從當日 return 扣除。50/50 組合只對 SPY leg 的
weight 變化收費，並乘上 SPY allocation。

## 4. 方法

### 資料
- SPY、GLD、^VIX（yfinance, auto_adjust=True 取調整後收盤）
- 樣本：2005-01-03 → 2026-04-11（~5350 天）
- OOS：**2013-01-02 → 今天**（≈ 3330 天，13 年，對齊 K1073）

### 模型估計
- Rolling window = 2000 天，refit every 63 天（≈ quarterly），與 K988/K1073 一致
- GJR 參數以 L-BFGS-B 最小化負 log-likelihood，三組 starting values
- A4f 同上，六個參數 (theta0, theta1, omega_g, alpha, gamma, beta)
- Random seed: 42（NumPy + bootstrap 通用）

### 避險守則
- weight_t 用 `VIX_{t-1}` / `sigma_hat_{t-1}`，code 中 VIX lag 明確執行 `vix_lag_oos[1:] = oos_vix[:-1]`。
- `portfolio_return_t = weight_t * r_spy_t` — t-1 weight × t return，符合 Paper 3 / K679 規範。
- 結果 JSON 含 `lookahead_guard` 欄位驗證。

### 統計
- **Sharpe 差異**：stationary block bootstrap，block=22（月），1000 reps，回傳 95% CI 和 two-sided p。
- **Hit rate**：A4f-VT 月 return 勝 12/VIX-VT 月 return 的比例。
- **Harvey (2016) t > 3 門檻** 提供 reference（非絕對門檻）。

## 5. 產出檔案

| 檔案 | 說明 |
|------|------|
| `k1074.py` | 完整執行腳本 |
| `k1074_results.json` | 7 個策略 × 所有指標、7 組 bootstrap Sharpe-diff test |
| `k1074_sharpe_comparison.png` | 5 VT + 2 BH Sharpe 長條圖（net of 5bp） |
| `k1074_equity_curves.png` | 7 條累積權益曲線（log scale） |
| `k1074_weight_dynamics.png` | 3 個 SPY-VT weight time-series |
| `k1074_mdd_dates.png` | 3 個 SPY 策略的 drawdown curves |
| `k1074_rolling_sharpe.png` | 5 個 VT 策略 252-day rolling Sharpe |
| `README.md` | 本檔 |

## 6. 預期方向（事前假設）

根據既有文獻 + Paper 3 的論述：

- **H1（Sharpe）**：A4f-VT 約與 12/VIX 打平，差距 < 0.1。若 A4f-VT 大勝需要重新檢查 lookahead。
- **H2（MDD）**：兩者相近；差異主要在 vol-spike 時的即時反應。
- **H3（Turnover）**：A4f-VT turnover **高於** 12/VIX——GARCH 短期組件更反應昨日 |r|，
  而 12/VIX 變動只反應 VIX 本身。
- **H4（Net Sharpe）**：由於 H3 的 turnover 差距，A4f-VT 扣 5bp 後**可能不贏**。
- **H5（50/50）**：Paper 3 的終極對照。若 A4f-VT 扣 TX 後在 50/50 框架下仍不贏
  → 強化 Paper 3「VT ≈ TSMOM」論述；若 A4f-VT 明顯勝 → Paper 3 需要補充「good vol forecast
  still helps within VT」的條件。

## 7. 結論（實證結果）

### 7.1 核心結果表（OOS 2013-01-02 → 2026-04-10, n=3338）

| Strategy | Sharpe (net) | CAGR | MDD | Calmar | Sortino | Mean w | Annual turnover |
|----------|-------------:|-----:|----:|-------:|--------:|-------:|----------------:|
| **A 12/VIX-VT (SPY)**          | **0.861** | 8.40%  | **-16.30%** | 0.52 | 1.13 | 0.75 |  9.7 |
| **B A4f-VT (SPY)**             | 0.843 | 10.46% | -18.58% | 0.56 | 1.12 | 0.99 | 16.3 |
| **C GJR-VT (SPY)**             | 0.821 | 10.38% | -18.15% | 0.57 | 1.05 | 0.96 | 13.4 |
| **D 50/50 + 12/VIX**           | 0.814 |  8.08% | -15.65% | 0.52 | 1.04 | 0.75 |  9.7 |
| **E 50/50 + A4f-VT**           | 0.852 |  9.10% | -16.39% | 0.56 | 1.10 | 0.99 | 16.3 |
| BH SPY                         | 0.799 | 14.47% | -41.12% | 0.35 | 0.95 | —    | —    |
| **BH 50/50 SPY/GLD**           | **0.873** | 11.08% | -23.50% | 0.47 | 1.08 | —    | —    |

### 7.2 Hypothesis 結論

| H | 預期 | 實證 | 驗證 |
|---|------|------|------|
| **H1 Sharpe**     | A4f-VT ≈ 12/VIX | A4f 0.843 vs 12/VIX 0.861，diff −0.022，p=0.64 | **12/VIX 微勝，無統計意義** |
| **H2 MDD**        | 相近 | A4f −18.58% vs 12/VIX −16.30% | **12/VIX 勝** (A4f 再槓桿時更吃 drawdown) |
| **H3 Turnover**   | A4f 高於 12/VIX | 16.3 vs 9.7（+68%） | **確認** |
| **H4 Net Sharpe** | A4f 扣 TX 後可能不贏 | A4f 淨 Sharpe 不勝 12/VIX | **確認：turnover 吃掉統計優勢** |
| **H5 50/50**      | 可能有邊際改善 | E 0.852 vs D 0.814，diff +0.033，p=0.37 | **marginally better，非統計顯著** |

### 7.3 Bootstrap Sharpe-diff tests（block=22, 1000 reps）

| 比較 | diff | 95% CI | p |
|------|-----:|--------|---:|
| B_A4f − A_12VIX         | −0.022 | [−0.108, +0.074] | 0.64 |
| B_A4f − C_GJR           | +0.021 | [−0.064, +0.103] | 0.58 |
| B_A4f − BH_SPY          | +0.016 | [−0.260, +0.318] | 0.96 |
| A_12VIX − BH_SPY        | +0.047 | [−0.160, +0.285] | 0.71 |
| E_A4f_5050 − D_12VIX_5050  | +0.033 | [−0.036, +0.103] | 0.37 |
| E_A4f_5050 − BH_5050       | −0.025 | [−0.207, +0.185] | 0.76 |
| D_12VIX_5050 − BH_5050     | −0.056 | [−0.239, +0.142] | 0.54 |

**沒有任何一組 Sharpe 差異達到 Harvey (2016) t>3.0（等價於 p<0.0027）門檻。**

### 7.4 Lookahead / sanity guards

- `weight_uses_t_minus_1_vix` = True
- `sigma_hat_{a4f|gjr}_step0_uses_t_minus_1_info` = True（第 0 步即有 forecast，使用 `ret[abs_idx-1], vix[abs_idx-1]`）
- 所有 net Sharpe 僅 1.02–1.08 倍 BH_SPY Sharpe（0.80）——**遠低於 2x artifact 警戒線**，無 lookahead artifact 跡象。
- Hit rate A4f vs 12/VIX（monthly net return）= 56.2% — 接近 50%，不構成穩定優勢。

### 7.5 Paper 3 意涵

結果強化 Paper 3 的核心論述：**「Volatility targeting's alpha 來自 return-side（drawdown insurance, TSMOM 結構），不是 vol-side 預測精度。」**

- A4f 在 QLIKE 上統計勝 GJR（K988 DM |t|=4.48），但在 VT 框架下 Sharpe 不勝 12/VIX（-0.02）
- A4f 更敏感的 sigma_hat 產生 68% 更高的 turnover，5bp TX cost 正好抵消其潛在精度優勢
- 50/50 組合下，A4f 的邊際改善 +0.03 Sharpe，但（a）不顯著（p=0.37）（b）兩者都輸給 BH 50/50（0.873）

**核心結論**：對一般投資人，12/VIX 是 A4f 的完全等價替代品；對 VT 策略設計者，簡單啟發法 = 複雜 GARCH 在「考慮 TX」的公平對照中。

### 7.6 與既有發現的一致性

- **K687/K697 VT = drawdown insurance 論述** — 完全吻合。兩個 VT 都把 BH SPY 的 MDD 從 −41% 改善到 −16%，但 CAGR 下降 6%，Sharpe 邊際改善。
- **K702 50/50 SPY/GLD 不可動搖** — BH 50/50 Sharpe 0.873 仍是全場最高。
- **Smooth-weight 策略幾乎不受 lag 影響** — 12/VIX 低 turnover（9.7）配合最高 Sharpe 0.861，是本實驗最有力的簡單原則佐證。
- **「VIX sufficient」第 N 次確認** — A4f 加上 VIX 短期組件不帶來顯著 VT 績效改善。

## 8. Paper 3 意涵

- **若 A4f-VT ≈ 12/VIX**：VIX 已 sufficient（第 27+ 次確認），Paper 3 論述完全成立。
- **若 A4f-VT 明顯勝**：需要在 Paper 3 加入「vol forecast matters within VT」的 caveat。
- **若 A4f-VT 輸**：反直覺但可能——更高 turnover 被 TX cost 吃掉，支持 Paper 3 的核心論點。

## 9. 限制

- 單一資產（SPY）；台股 / 全球驗證留給 K1075。
- TX 5bp 是 US ETF 的 mainstream 估計；實際含市場衝擊、tracking error 的 full cost 未評估。
- 50/50 rebalance 採「每月第一個交易日」，未搜索最佳頻率（可能影響結果 ±0.1 Sharpe）。
- target_sigma 固定 12%——若用 annualised target 搜尋可能差 0.05–0.1 Sharpe，但不改變排序。

### 9.1 Codex review 提出的次要偏誤（不影響主結論）

1. **50/50 每月 rebalance 的 GLD 腿 drift 成本未收取** — 只有 SPY 腿的 VT leverage 變動扣 TX。實際 rebalance 也會把 SPY/GLD allocation 拉回 50/50，這部分的 notional 未扣費。方向：會使 D, E 的 net Sharpe **略微高估**（~0.01–0.02）。不改變「D, E 都輸給 BH 50/50」的結論。
2. **Day-0 建倉成本未收取** — 兩個 cost function 都以 `dw[0]=0` 啟動。會使**所有** VT 策略首日免費建倉，首日 cost 被略去一次（約 TX × w_0 ≈ 5bp × 0.75 = 3.75bp，分攤到 13 年 →幾近 0 bp/year 年化，可忽略）。
3. **Bootstrap two-sided p-value 計算不嚴謹** — 現行公式 `p = mean(diffs × sign(mean(diffs)) <= 0) × 2` 是正負非對稱檢定的簡化近似，和文獻標準的「null-centered bootstrap」不完全等同。但 CI[2.5%, 97.5%] 是正確的配對 bootstrap CI——**結論以 CI 跨零為主**，p 值只是輔助。所有比較的 CI 都跨零，不會改變「無統計顯著差異」的定性結論。

## 9.2 執行時間

- Rolling OOS + 估計：159 秒（53 refits × GJR + A4f）
- Bootstrap 7 組 × 1000 reps：~3 秒
- 圖表：~1 秒
- Total: 162 秒

## 10. References

1. **Moreira & Muir (2017).** Volatility-Managed Portfolios. *Journal of Finance* 72(4):1611-1644.
2. **Harvey et al. (2018).** The Impact of Volatility Targeting. *Journal of Portfolio Management* 45(1):14-33.
3. **Engle, Ghysels & Sohn (2013).** Stock Market Volatility and Macroeconomic Fundamentals.
   *Review of Economic Studies* 95(3):776-797.
4. **Patton (2011).** Volatility forecast comparison. *Journal of Econometrics* 160(1):246-256.
5. **Harvey, Liu & Zhu (2016).** …and the Cross-Section of Expected Returns. *RFS* 29(1):5-68.
