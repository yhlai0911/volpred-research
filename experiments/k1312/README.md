# K1312: GARCH-to-Neural (AAAI 2024) — GARCH-LSTM Volatility Forecasting

**Status**: compute_queued (not yet executed)
**Date**: 2026-05-17
**Author**: K1312 worktree agent

---

## Motivation

VolPred 平台已累積 7 次 ML ceiling 確認（K785 MF2-GARCH、K816v2 GINN、K784 GARCH-GRU、K1263 KAN-GARCH-MIDAS 等），全數 NULL（DM-HLN |t| < 3 vs GJR baseline），顯示直接疊加 ML 於 GJR 的方法無法突破。

**新假說**：Zhao, Zhu, Ng, Lee（AAAI 2024）建立 GARCH family 與 NN 的等價關係（GARCH-NN equivalence），並提出 GARCH-LSTM 架構 — 把 GJR-GARCH 的遞迴更新公式映射為 NN 節點，然後**嵌入** LSTM 作為 structured prior。這個方法的關鍵不同在於：

1. **等價映射（不是殘差輸入）**：GJR variance 更新公式直接對應 RNN 門控，讓 LSTM 的初始歸納偏誤（inductive bias）與 GARCH 一致，而非單純把 GARCH 輸出當作 feature。
2. **可偽證閾值**：如果此 structured inductive prior 也失敗，將成為 ML ceiling 第 8 次確認，強化「市場效率 + GARCH 已抓住大部分可預測 vol 變動」的理論基礎。

**Falsifiable**：
- H0: GARCH-LSTM QLIKE ≡ GJR-GARCH (DM |t| < 3)
- H1: GARCH-LSTM QLIKE 統計顯著更優，三重 gate 全過

---

## 方法

### 核心架構：GARCH-NN Equivalence

Zhao et al. (2024) 的核心定理：標準 GARCH(1,1) 的遞迴更新

```
sigma^2_t = omega + alpha * eps^2_{t-1} + beta * sigma^2_{t-1}
```

等價於下列 RNN 單元（以 exp activation 保正）：

```
h_t = omega + alpha * x_t + beta * h_{t-1}
```

其中 `x_t = eps^2_{t-1}`（已正）、`h_t = sigma^2_t`（已正）。

**GJR-GARCH-NN 擴展**（加入非對稱效應）：

```
h_t = omega + (alpha + gamma * I(eps_{t-1}<0)) * eps^2_{t-1} + beta * h_{t-1}
```

等價於 RNN，輸入 `[eps^2_{t-1}, I(eps_{t-1}<0) * eps^2_{t-1}]`，並額外學習 gamma 參數。

### GARCH-LSTM 實作

**輸入特徵**（全 t-1 lagged，嚴格無 lookahead）：
- `r_{t-1}`：前日報酬（%）
- `r^2_{t-1}`：前日報酬平方（volatile proxy）
- `neg_r2_{t-1}` = `r^2_{t-1} * I(r_{t-1} < 0)`：GJR 非對稱項
- `gjr_var_{t-1}`：前日 GJR-GARCH 濾波方差（GARCH memory）
- `rv22_{t-1}`：22 日滾動已實現波動率（長記憶）
- `vix_{t-1}`：市場隱含波動率水準

**GARCH-LSTM 架構**：

```
Input: [6 features] × window_size=20
    → GARCH-informed input layer (linear, 6→hidden_size)
    → LSTM (hidden_size=32, num_layers=2, dropout=0.1)
    → Output layer (hidden_size→1, exp activation for positivity)
```

- GARCH 初始化：LSTM 的 weight_ih_l0 以 GJR 等價映射初始化（alpha/gamma/beta 對應），其餘層標準初始化。
- 訓練：MSE on sigma^2，Adam lr=1e-3，early stopping（patience=10，validation=最後 20% IS 資料）。
- Refit：每 63 日（quarterly）滾動視窗 1500 obs。
- seed=42 固定 torch/numpy/random。

### Lookahead Policy

**所有 signal 至時間 t 的預測，使用 t-1 時刻已知資訊**：

```python
df[feature_cols] = df[feature_cols].shift(1)  # 嚴格 1-day lag
```

- GJR 濾波：用訓練集 r[:t] 估計 params，再以 `gjr_one_step_forecast(r[:t], var[:t], params)` 得到 sigma^2_t 的預測值（無法看到 r_t）
- GARCH-LSTM：輸入視窗 [t-window_size, t-1] 的特徵（GJR var 是 t-1 的過濾值），預測 sigma^2_t

---

## 資料規格

- **主資產**：SPY（2007-01-01 起，yfinance）
- **次資產**：QQQ
- **OOS 期間**：2021-01-04 → 今
- **In-sample 分割點**：2024-01-01（sub-period stability test）
- **Refit 頻率**：每 63 日（季）
- **Rolling window**：1500 obs（KAN 維持一致，方便比較）

---

## 成功標準（三重 Gate）

與 K1263 一致（ML ceiling 比較框架統一）：

| Gate | 條件 | 意義 |
|------|------|------|
| (a) DM-HLN | `\|t\| > 3.0` 且 t < 0（challenger better） | Harvey 2016 threshold |
| (b) QLIKE 相對改善 | ≥ 5% vs GJR baseline | 經濟顯著性 |
| (c) Sub-period 穩定 | 兩子期間（2021-23 and 2024+）都優 | 非 sample-specific |

三 gate 全過 → ML ceiling 突破候選 / Paper-3 素材
部分通過 → 記錄並分析，探討 regime-specific 表現
全部失敗 → ML ceiling 第 8 次確認 NULL

---

## 參考文獻

1. Zhao, P., Zhu, H., Ng, W.S.H., & Lee, D.L. (2024). "From GARCH to Neural Network for Volatility Forecast." *Proceedings of the Thirty-Eighth AAAI Conference on Artificial Intelligence*, 38(15). arXiv:2402.06642.
2. Engle, R., Ghysels, E., & Sohn, B. (2013). "Stock Market Volatility and Macroeconomic Fundamentals." *Review of Economics & Statistics*, 95(3), 776-797.
3. Patton, A.J. (2011). "Volatility forecast comparison using imperfect volatility proxies." *Journal of Econometrics*, 160(1), 246-256.
4. Harvey, C.R., Liu, Y., & Zhu, H. (2016). "...and the Cross-Section of Expected Returns." *Review of Financial Studies*, 29(1), 5-68.
5. Diebold, F.X. & Mariano, R.S. (1995). "Comparing Predictive Accuracy." *JBES*, 13(3), 253-263.
6. Harvey, D., Leybourne, S., & Newbold, P. (1997). "Testing the equality of prediction mean squared errors." *International Journal of Forecasting*, 13(2), 281-291.
7. Glosten, L.R., Jagannathan, R., & Runkle, D.E. (1993). "On the Relation between the Expected Value and the Volatility of the Nominal Excess Return on Stocks." *Journal of Finance*, 48(5), 1779-1801.

---

## 復現

```bash
cd /path/to/volpred-research
uv run python experiments/k1312/k1312.py
```

輸出：`experiments/k1312/k1312_results.json`
預計執行時間：~30-60 分鐘（GARCH refit × LSTM training × 2 資產）

---

## 差異化 vs 先前 ML 實驗

| 實驗 | 方法 | 結果 | 差異 |
|------|------|------|------|
| K785 | MF2-GARCH | NULL | 雙頻率 GARCH，無 NN |
| K816v2 | GINN | NULL | Physics-informed NN，GARCH 輸出做特徵 |
| K784 | GARCH-GRU | NULL | GRU，GARCH 輸出做特徵 |
| K1263 | KAN-GARCH-MIDAS | NULL | KAN 替換 MIDAS 多項式 |
| **K1312** | **GARCH-LSTM（AAAI 2024）** | **TBD** | **GARCH 等價映射嵌入 LSTM 結構**（不是殘差輸入） |
