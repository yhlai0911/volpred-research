# K1313: HAR-RV Probabilistic Quantile Forecasting vs GARCH-Normal VaR

## 動機

在 K784–K1312 的 ML 路線中，連續 8 次 NULL 結果顯示額外的機器學習複雜度無法改善 QLIKE 點預測。K1313 轉換視角：從「已有的 HAR 殘差結構中直接提取概率分佈」切入，探索分位數回歸（HAR-QR）能否提供比 GARCH(1,1)-Normal 更準確的 VaR 覆蓋率。

核心假設：HAR-OLS 的殘差結構含有分佈性資訊（如異質變異、厚尾），而直接對收益序列做分位數回歸（以滯後 RV 為預測子）可能在尾部覆蓋率上優於對稱正態假設的 GARCH。

## 研究問題

**主問題：** HAR-QR（以滯後 RV 為預測子的分位數回歸）是否在 SPY 上提供比 GARCH(1,1)-Normal VaR 更準確的 VaR 覆蓋率？

## 方法

### 資料
- **資產：** SPY（SPDR S&P 500 ETF）
- **期間：** 2010-01-01 ~ 2024-12-31
- **RV proxy：** `rv = log(price_t / price_{t-1})^2`（日平方對數收益）
- **樣本數驗證：** 全期 ≥ 2500 行，OOS ≥ 1500 行

### Lookahead Policy（嚴格執行）

```python
rv = df['rv']
rv_d = rv.shift(1)                       # lag-1（前一日）
rv_w = rv.shift(1).rolling(5).mean()    # lag-1 到 lag-5 平均
rv_m = rv.shift(1).rolling(22).mean()   # lag-1 到 lag-22 平均
```

所有預測子均以 `shift(1)` 為基礎，確保 t 期預測子不含 t 期資訊。

### 三個模型

**M1 - HAR-OLS（基準）：**
- OLS 回歸 `log(rv_t)` on `log(rv_d)`, `log(rv_w)`, `log(rv_m)`
- OOS 預測 σ_t = exp(fitted mean)
- VaR = z_{0.05} × sqrt(σ_t)（Normal 假設）

**M2 - HAR-QR（主要模型）：**
- 直接對 return_t 做分位數回歸
- 預測子：`[sqrt(rv_d), sqrt(rv_w), sqrt(rv_m)]`（vol 尺度）
- 分位數：τ = {0.01, 0.05, 0.10, 0.90, 0.95, 0.99}
- 使用 `statsmodels.regression.quantile_regression.QuantReg`
- VaR = OOS quantile prediction at τ=0.05（and τ=0.01）

**M3 - GARCH(1,1)-Normal（標準 benchmark）：**
- `arch_model(returns, vol='GARCH', p=1, q=1, dist='Normal')`
- OOS VaR 從 conditional variance 推算：VaR = z_α × σ_t

### Walk-Forward OOS
- **OOS 期間：** 2018-01-01 ~ 2024-12-31（約 1750 交易日）
- **Expanding window：** IS 從 2010-01-01，每 21 個交易日 refit
- seed = 42

### 評估指標

1. **Kupiec UC test**（α=0.05 和 α=0.01）
2. **Christoffersen CC test**（條件覆蓋率）
3. **Pinball loss**：所有 τ 計算 M2 pinball 平均
4. **DM test**：M2 vs M3 pinball loss（τ=0.05, τ=0.01）

## 成功標準（Verdict）

- **PASS：** M2 DM test 顯著 (p<0.05)，M2 Kupiec UC p>0.05
- **CONDITIONAL_PASS：** M2 UC 通過但 DM NS；或 DM 顯著但方向有爭議
- **MIXED：** M2 UC/CC 不全通過，但有特定 τ 改善
- **NULL：** M2 UC/CC 均 fail，或比 M3 更差

## 防錯規則

1. Lookahead 最高優先：所有 rv 預測子必須 `shift(1)` 後 rolling
2. Kupiec test 正確公式：`LR = -2 * [n*log(α) + (T-n)*log(1-α) - n*log(n/T) - (T-n)*log(1-(n/T))]`，χ²(1)
3. DM test 用 pinball loss 差值的 HAC t-stat（Newey-West，lag=10）
4. GARCH 收斂失敗時 fallback to `method='slsqp'`

## 與先前研究的差異

| 特徵 | K784/K787（HAR Dir） | K1313（HAR-QR） |
|------|---------------------|-----------------|
| 目標 | 方向分類 | 尾部分佈（VaR） |
| 評估 | Accuracy/Hit ratio | UC/CC/Pinball/DM |
| 模型 | OLS+Logistic | 分位數回歸直接法 |
| Benchmark | Random/HAR point | GARCH-Normal VaR |

K1313 不走 ML 路線，是「從現有 HAR 結構提取分佈資訊」的探索，屬於概率預測方向。
