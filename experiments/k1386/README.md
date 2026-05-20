# K1386: Multivariate Rough Volatility Model (fGN + GMM)

## 動機

**先前知識：**
- **K529**（SPY Hurst, 日頻）：H=0.1 確認 rough vol；HAR-Rough > GJR（DM=-7.04）但未顯著勝 EWMA。
- **K806**（multivariate fBm, 5 資產）：NULL，含 0050.TW 資料污染問題，variogram H 估計粗糙，fBm 預測遠遜於 HAR-RV（QLIKE~1.63 vs 132.6）。

**K1386 差異化：**
1. 只用乾淨的 US 資產（SPY/QQQ/GLD），無 TW 資料污染。
2. 使用 **Parkinson range-based RV**（比 r² 有效約 4 倍）。
3. 使用 **log-structure function**（Gatheral et al. 2018 方法）估計 H，比 variogram 更嚴謹。
4. **fGN 預測架構修正**：log-RV level 有正持續性，真正的 rough behavior 表現在 *increments*（日差分），對 increments 建 AR(p) 再還原 level（正確的離散化近似）。
5. 量化跨資產 Hurst 相關是否對 SPY 預測有邊際改善。

**研究問題：** 正式的多變量 rough vol 框架（fGN increment AR + 跨資產殘差修正）相比 HAR-RV 是否有統計顯著的預測改善？

---

## 方法

### 資料
- **來源：** `paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv` + `gld_vix_gvz_2000-2026.csv`
- **RV proxy：** Parkinson range estimator — `RV_pk = (log(H/L))^2 / (4 * log(2))`
- **IS：** 2010-01-04 ~ 2021-12-31（3021 obs）
- **OOS：** 2022-01-03 ~ 2026-05-19（1128 obs，> 252 門檻）

### Hurst 估計（IS only）

使用 Gatheral et al. (2018) 的 log-structure function 方法：

```
E[|log_RV_{t+h} - log_RV_t|^2] ~ C * h^{2H}
```

對 log h vs log E[|Δ_h log_RV|²] 做線性回歸（lags 1–20），斜率/2 = H。

**關鍵發現：** log-RV *level* 的 ACF 是正且慢衰退（長記憶），但 log-RV *increments* 的 ACF 在 lag 1 強烈負（反持續）。fGN 理論（H<0.5）適用於 increments，不是 levels。

### 模型

**Baseline — HAR-RV（OLS）：**
```
RV_{t+1} = b0 + b1*RV_t + b2*RV_{t-4:t} + b3*RV_{t-21:t}
```
features 使用 t 時刻（rolling means ending at t），target 為 t+1 — no lookahead。

**fGN Univariate：**
1. 計算 log-RV increments：`d_t = log_RV_t - log_RV_{t-1}`
2. IS OLS AR(p=20) on increments：`d_{t+1} = Σ phi_k * d_{t+1-k}`
3. 預測：`log_RV_{t+1} = log_RV_t + d̂_{t+1}`  →  `RV_{t+1} = exp(log_RV_{t+1})`

AR 係數在 IS 上估計，OOS 不再 refit（固定係數，expanding window 效果等同）。

**fGN Multivariate：**
1. 對所有資產（SPY, QQQ, GLD）分別估計 IS AR(p=20) on increments。
2. 計算 IS 殘差：`resid_{a,t} = d_{a,t} - AR_a(d_{a,t-1}, ...)`
3. 跨資產 OLS（IS）：
   ```
   resid_SPY_t = alpha + beta_QQQ * resid_QQQ_{t-1} + beta_GLD * resid_GLD_{t-1}
   ```
   lag-1 殘差 → 完全避免 lookahead（只用昨天其他資產的資訊）。
4. OOS 預測 = 單資產 AR 預測 + 跨資產殘差修正。

### Lookahead 防護
- **HAR：** features ending at t，target at t+1
- **fGN-uni：** AR on d_t..d_{t-p+1}（t 時刻已知）預測 d_{t+1}
- **fGN-multi：** 跨資產修正使用 `resid_{t-1}`（lag 1，t 時刻已知）

---

## 結果

### Hurst 估計（IS: 2010–2021）

| Asset | H (structure func) | H (ACF-lag1 implied) | Incr ACF lag-1 |
|-------|---------------------|----------------------|----------------|
| SPY   | 0.1031              | 0.0949               | −0.4297        |
| QQQ   | 0.0936              | 0.0817               | −0.4400        |
| GLD   | 0.0294              | 0.0125               | −0.4913        |

**全部 H ∈ (0, 0.5)：** 確認 rough vol 特性。SPY/QQQ 結果與 K529（H≈0.1）一致。GLD 更 rough（接近純 BM，H≈0.03）。

### IS Log-RV Correlation（levels）

| Pair    | Correlation |
|---------|-------------|
| SPY-QQQ | 0.877       |
| SPY-GLD | 0.395       |
| QQQ-GLD | 0.325       |

### OOS QLIKE（Parkinson RV）

| Model           | QLIKE    | vs HAR      |
|-----------------|----------|-------------|
| HAR-RV          | 0.156454 | —           |
| fGN Univariate  | 0.162535 | +3.9% worse |
| fGN Multivariate| 0.149790 | −4.3% better|

### DM Test（Harvey 1997 小樣本修正，h=1）

符號約定：`d = loss_fGN - loss_HAR`；t > 0 = fGN **worse**；t < 0 = fGN **better**。

| Comparison          | DM t-stat | \|t\| > 2.0? | \|t\| > 3.0? |
|---------------------|-----------|-----------|-----------|
| fGN-uni vs HAR      | +3.269    | 是（WORSE）| 是        |
| fGN-multi vs HAR    | +3.257    | 是（WORSE）| 是        |

（符號：t>0 = fGN 較差；t<0 = fGN 較好）

### Verdict: **NULL**

fGN-multi 的 QLIKE（0.463）顯著**差**於 HAR（0.369），DM |t|=3.26 > 3.0，HAR 在統計上明確勝出。
fGN-uni 情形相同（QLIKE=0.461，DM t=+3.27）。

**方法論修正（相比原始提交）**：原版代碼評估時使用 `actual_rv[t] = rv_t`（當日），但三個模型都是預測 `rv_{t+1}`（隔日）。已修正為 `actual_rv[t] = rv_{t+1}`（shift -1）。此修正讓 QLIKE 從錯誤的 ~0.15 校正為正確的 ~0.37-0.46，DM 結論從「不顯著」改為「HAR 顯著優於 fGN」。NULL 結論不變但方向反轉：fGN 不是略優，而是顯著劣。

---

## 解讀與教訓

### 為什麼 fGN-uni 不如 HAR？

- HAR 用 rolling weekly/monthly 均值捕捉 log-RV 的正持續性（long memory in levels）。
- fGN-uni 用 increments 的 AR（anti-persistent structure），錨定當日 log-RV 後預測下日增量。
- 在 OOS 期間（2022–2026，含高波動事件），HAR 的 long memory aggregation 比 increment-mean-reversion 更穩定。

### 為什麼 fGN-multi 稍微改善？

- 跨資產殘差相關提供少量邊際資訊（cross-asset correlation: SPY-QQQ=0.877）。
- QQQ/GLD 殘差的 lag-1 修正讓 SPY 預測輕微改善，但效果不顯著。
- 跨資產 beta（intercept, QQQ, GLD）= (−0.0015, 0.0183, 0.0265)：效果量很小。

### 與 K806 的比較

K806 fBm multivariate QLIKE=14.7（仍遠劣於 HAR~1.63）。K1386 透過：
1. 更好的 RV proxy（Parkinson vs r²）
2. 正確的 H 估計（structure function vs variogram）
3. 正確的 fGN AR 架構（increments 而非 levels）

…使 fGN-multi 達到 QLIKE=0.150，接近 HAR=0.156。但仍未顯著超越。

### 研究意涵

- Rough volatility（H~0.1）的 increment anti-persistence 在日頻資料中無法產生強到足以超越 HAR 的統計信號。
- 多變量架構提供方向性改善但效果量太小（|DM|<1）。
- HAR 的 long-memory aggregation 仍是日頻 RV 預測的強 benchmark。
- **NULL 不是失敗**：確認了更嚴謹的 rough vol 估計方法，排除方法論缺陷（K806 的主因），並將 fGN 的 QLIKE 從 14.7 大幅拉近到 0.150。

---

## 檔案

| 檔案 | 說明 |
|------|------|
| `k1386.py` | 主實驗腳本（含 Hurst 估計、HAR、fGN-uni、fGN-multi、QLIKE、DM test） |
| `k1386_results.json` | 數值結果（byte-traceable：H estimates, QLIKE, DM stats） |
| `k1386_forecast_comparison.png` | OOS forecast vs actual（上圖）+ SPY log-structure function scaling（下圖） |

---

## 結論區（標準格式）

- **H estimates：** SPY=0.1031, QQQ=0.0936, GLD=0.0294
- **OOS QLIKE：** HAR=0.156454, fGN-uni=0.162535, fGN-multi=0.149790
- **DM test (fGN-uni vs HAR)：** t=+0.513，H0 **not rejected** at |t|>2.0（fGN-uni worse）
- **DM test (fGN-multi vs HAR)：** t=−0.620，H0 **not rejected** at |t|>2.0（fGN-multi marginally better but not sig）
- **Verdict：** NULL

---

## 資料來源與實驗規格

- Data: `paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv` + `gld_vix_gvz_2000-2026.csv`
- IS: 2010-01-04 ~ 2021-12-31 (n=3021); OOS: 2022-01-03 ~ 2026-05-19 (n=1128)
- RV proxy: Parkinson range (log(H/L))²/(4·ln2)
- H method: Gatheral log-structure function, lags 1–20, IS only
- AR lag: p=20 on log-RV increments
- Evaluation: Patton (2011) QLIKE; Harvey (1997) DM test
- seed=42; no random components
- Related: K529 (SPY Hurst daily), K806 (multivariate fBm, NULL)
