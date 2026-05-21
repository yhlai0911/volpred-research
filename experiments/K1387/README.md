# K1387: Risk Parity + Heavy-Tailed DCC — Paolella (2025, JTSA)

## 動機

**先前知識：**
- **K1100d**（DCC-GARCH 系列）：regime-switching DCC NULL result。
- **Knowledge KB**：4-asset RP (SPY+QQQ+GLD+TLT) Sharpe=0.64, MaxDD=39%；SPY+GLD 2-asset RP 表現較佳（Sharpe=1.18）。
- Engle & Sheppard (2002) DCC 標準 Gaussian 假設；Paolella (2025, JTSA) 提出 heavy-tailed 多元分佈改進。

**K1387 差異化：**
1. Gaussian DCC vs Student-t DCC 的直接比較（兩步估計法，non-pooled）。
2. 以風險平價（Equal Risk Contribution, ERC）組合建構框架評估 DCC 品質。
3. SPY + TLT + GLD（3 資產），OOS 2020-2024 含 COVID + 升息期間。
4. 評估指標：QLIKE（DM test）+ VaR Kupiec/Christoffersen + Portfolio Sharpe/MaxDD。

**研究問題：** Student-t DCC 相比 Gaussian DCC 在風險平價組合建構上是否有統計顯著改善？

## 方法

| | 說明 |
|---|---|
| 資產 | SPY, TLT, GLD（股/債/黃金三資產） |
| 全期 | 2015-01-01 ~ 2024-12-31 |
| OOS | 2020-01-01 ~ 2024-12-31（~1250 交易日） |
| IS | 展開窗口（expanding window），初始 250 天 |
| 再平衡 | 每 5 個交易日 refit |

**模型：**
- M0：等權重（1/N），基準
- M1：Inverse-Vol 加權（60 日滾動波動率）
- M2：Gaussian DCC-GARCH(1,1) + ERC 組合
- M3：Student-t DCC-GARCH(1,1) + ERC 組合

**評估：**
- QLIKE（組合層級）+ DM-HLN test（M2 vs M3）
- VaR backtesting：Kupiec + Christoffersen（1% + 5% 水準）
- Risk Contribution RMSE（等風險貢獻是否真的達到）
- Portfolio Sharpe ratio, MaxDD

## Lookahead 政策

- 組合權重 w_t 使用 t-1 時刻的 H 預測（H_{t|t-1}）形成 → 無前視偏誤
- `IS_data = returns[:t]`（嚴格不含 t 時刻，只含 0..t-1）
- GARCH 濾波：`h[t] = omega + alpha * r[t-1]^2 + beta * h[t-1]`（標準 t-1 lag）

## 成功標準

- PASS：DM t > 0 且 p < 0.05（Student-t DCC 在 QLIKE 上顯著勝） + M3 VaR 通過率 ≥ M2
- MIXED：QLIKE 有優勢 OR VaR 有優勢（但非兩者皆優）
- NULL：DM 不顯著 + VaR 無差異

## 相關 K

- K1100d：DCC regime-switching NULL
- K1386：Multivariate rough vol NULL
- K0980v2：Threshold GJR EXPLORATORY_NULL

## 參考文獻

- Paolella, M.S. (2025). "Heavy-tailed multivariate GARCH and DCC." JTSA.
- Engle, R.F. & Sheppard, K. (2002). "Theoretical and empirical properties of DCC." NBER WP.
- Maillard, S., Roncalli, T. & Teïletche, J. (2010). "The properties of equally weighted risk contribution portfolios." JPM.
