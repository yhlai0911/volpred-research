# K1660 — Mincer-Zarnowitz Calibration Audit of the VolPred HAR/GARCH Forecast Library

## 動機 / 差異化

VolPred 已累積 **102 組已存 OOS 預測集**（`storage/results/<id>_forecasts.json` + companion `<id>.json`），全出自 HAR/GARCH 家族模型，但這個預測庫**從未做過 calibration 層審計**。既有評估只算 QLIKE / MSE / VaR，沒有回答一個更基本的問題：**這些預測有沒有系統性偏誤（over/under-forecast）？**

Mincer-Zarnowitz (MZ) 迴歸是 forecast-efficiency 的標配檢定（Mincer & Zarnowitz 1969；Patton 2011 review）：

```
realized_t = a + b · forecast_t + ε_t      H0: a = 0  AND  b = 1
```

拒絕 H0 → 該模型 forecast 有系統性 bias。這一層審計**零額外資料成本**、直接提升所有既有預測的可信度。這與過往 MZ 相關 K（K145 MZ-R² peak、cross-asset MZ 三資產、SPY GJR 單點 MZ）的差異：**這是第一次對整個預測庫做系統性、多家族、資料驗證過的 calibration 審計**，而非單一資產/單點 MZ。

## 資料來源（本地、自足）

| 項目 | 內容 |
|---|---|
| 預測 | `storage/results/*_forecasts.json`（per-date `variance_forecast`）+ companion `<id>.json`（asset / model / OOS window / stored `mean_actual_var`） |
| 審計檔數 | **84 檔** MZ 完成（4 個 core 家族 + 1 caveat 家族），其中 **75 檔 n≥200** 進 headline 判定 |
| 資產 | SPY, QQQ, GLD, TLT, EEM, USO, BTC-USD（7 資產） |
| OOS 窗口 | 2023-01→2024-12（47 檔，calm 期）、2025 全年（23 檔）、2022-01→2023-12（4 檔）、2020-2025（1 檔） |
| 樣本數/檔 | 250–502 天（單資產日頻 OOS 時序） |
| Realized 資料 | yfinance OHLC（`auto_adjust=False`），cache 於 `data/`，離線可復現 |

### Realized target 的選擇（最關鍵的方法決策）

GARCH/GJR/EGARCH/CGARCH 預測的是 **close-to-close 條件變異數**（全日，含隔夜）。依 experiment-preamble 的 model-target 匹配表，這些模型的正確 realized target 是 **r² =（log close-to-close return）²**，它是**條件無偏** proxy：E[r²ₜ | Fₜ₋₁] = σ²ₜ。本審計以 **r² 為主要 realized target**。

**尺度一致性**：MZ 兩邊都是 close-to-close variance（forecast = 條件變異數；realized = r²）。**同尺度、不混用。**

**pipeline 存的 `mean_actual_var` 是 Parkinson variance**（`rv_proxy = rv_parkinson`，見 `src/volpred/data/preprocessing.py:159`）。Parkinson 是日內 high-low range 估計，(a) 對 close-to-close forecast 是**錯的尺度**（漏掉隔夜），(b) 本專案早有 K 記錄 Parkinson 系統性低估真實 variance ~34%。本審計**重建 Parkinson 只用於兩個目的**：驗證我的 OHLC 與 pipeline 一致、以及展示 proxy 選擇如何誇大 apparent over-forecast（見下方診斷）。

## 方法（嚴謹）

1. **Unit of analysis = 每個 forecast 檔**（單資產 OOS 時序）。每條 MZ 迴歸都是**單資產時間序列** → Newey-West HAC 建在時間維度上乾淨，**不把跨資產 asset-day 當 iid**（K1355 教訓）。家族判定由 per-file verdict 彙整。
2. **MZ 迴歸**：`realized = a + b·forecast`，OLS 點估 + **Newey-West HAC** 標準誤（lag = ⌊4·(n/100)^(2/9)⌋，n≈500 → lag=5）。報告 â, b̂、對 (0,1) 的 t 檢定、以及 **HAC 版 joint Wald** H0: a=0 ∧ b=1。
3. **兩尺度**：variance-space（主）+ **log-variance space（robustness，對 r² 極端右尾更穩健）**。
4. **判定**：joint Wald p>0.05 → well-calibrated；拒絕且 mean(fc)/mean(r²)>1.05 → over-forecast，<0.95 → under-forecast，介於中間但 slope 偏離 → conditionally-miscalibrated。
5. **Bias-correction（誠實分兩層）**：
   - **Expanding-window（OOS-valid）**：每個 t 用 <t 的資料估 (â,b̂)，`f_adj = max(â+b̂·f, 0.2·f, 1e-8)`（相對 floor 防早窗不穩），對 flagship SPY 家族用 canonical QLIKE（`qlike_pointwise`）+ DM 檢定比較校正前後。
   - **Full-sample（IN-SAMPLE diagnostic）**：全樣本線性校正的 QLIKE 上界，**明確標為 in-sample、不宣稱 OOS 改善**。
6. **固定 seed=42**。Results 用 `os.replace` 原子寫入。

## 結果

### 0. 資料驗證（gate）— PASS

重建 Parkinson variance 對 forecast 日期取平均，vs pipeline 存的 `mean_actual_var`：**median ratio = 1.0000**（84 檔）。→ 我的 yfinance OHLC 與 pipeline 的資料源**完全一致**，r² MZ 建在同一批日期上，可信。

### 1. 家族層 calibration（core 家族，n≥200，r² target）

| 家族 | 檔數 | 資產涵蓋 | median b̂ (var) | median b̂ (log, robust) | median fc/r² | Wald 拒絕率 | verdict 分佈 |
|---|---|---|---|---|---|---|---|
| **GJR-GARCH** | 38 | 7 資產 | 0.55 | 0.76 | 1.07 | 23/38 (61%) | 20 over, **15 well**, 3 cond |
| **GARCH(1,1)** | 25 | 7 資產 | 0.47 | 0.75 | 1.11 | 19/25 (76%) | 13 over, 6 well, 1 under, 5 cond |
| **EGARCH** | 7 | GLD/SPY | 0.13† | 0.43 | 1.13 | 3/7 | 3 over, 2 well, 2 undet |
| **CGARCH** | 5 | GLD/SPY | 0.45 | 0.87 | 1.02 | 5/5 | 2 over, 3 cond |

**整體（75 檔）**：well-calibrated **23（31%）**、over-forecast **38（51%）**、conditionally-miscalibrated 11（15%）、under-forecast 1、undetermined 2。**joint Wald 拒絕 50/75 = 67%**。

† EGARCH var-space b̂=0.13 被 r² 極端右尾扭曲（少數大 r² 落在低 forecast 日 → 高槓桿點壓低 slope）。**log-space b̂=0.43 才是可靠估計**。全 core 檔 **log-space median b̂ = 0.75**（vs var-space 0.51）→ log-space 是 outlier-穩健的 slope，仍 <1。

### 2. Flagship 四家族（SPY, 2023-2024, n≈500）

| 家族 | var-space b̂ | **log-space b̂** | fc/r² | Wald p | 判定 |
|---|---|---|---|---|---|
| GARCH(1,1) | 0.41 | 0.48 | 1.19 | 7.7e-05 | over-forecast |
| GJR-GARCH | 0.63 | **0.68** | 1.07 | 0.04 | over-forecast |
| EGARCH | 0.13† | 0.43 | 1.13 | 2.8e-13 | over-forecast |
| CGARCH | 0.50 | 0.60 | 1.15 | 2.7e-05 | over-forecast |

GJR-GARCH log-space b̂=0.68 與**先前獨立 K**（SPY GJR w=504, 2020-2025, N=1508: β=0.67）**幾乎完全一致** → b<1 是**穩健的結構特徵**，不是本樣本雜訊。

### 3. Proxy-scale 診斷（最 actionable 的發現）

| 度量 | 對 r²（正確 target） | 對 Parkinson（pipeline 用的 proxy） |
|---|---|---|
| median mean(forecast)/mean(realized) | **1.07** | **1.73** |
| median b̂ | 0.51 | 0.42 |

→ **pipeline 過去用 Parkinson 評估，會把 over-forecast 誇大成 73%；改用尺度正確的 r²，真實 level over-forecast 只有 ~7%。** 大部分「apparent over-forecast」是 proxy-bias artifact，不是模型偏誤。

### 4. Bias-correction（誠實 null）

| 家族 | in-sample QLIKE 改善 | **expanding-window OOS 改善** | DM t (p) |
|---|---|---|---|
| GARCH(1,1) | +1.7% | +0.4% | 0.41 (0.68) |
| GJR-GARCH | +0.9% | −0.2% | −0.42 (0.68) |
| EGARCH | +16.6% | +17.3% | 1.08 (0.28) |
| CGARCH | +2.4% | +0.6% | 0.32 (0.75) |

**in-sample 校正可小幅降 QLIKE，但 expanding-window OOS 校正沒有任何一個家族達到統計顯著（所有 DM p>0.27）。** EGARCH 的 +17.3% 點估看似大，但只是把最差校準的 var-space 拉回，DM 仍不顯著。→ **miscalibration 在統計上真實存在，但用 naive 線性 MZ 校正無法在 OOS 穩健改善預測。**

## 判定（Verdict）

1. **不是全面失敗**：31% 的預測 well-calibrated；GJR-GARCH 最佳（15/38 = 39% well-calibrated），level bias 溫和（median fc/r²=1.07）。
2. **溫和 unconditional over-forecast**（fc/r² 1.02–1.13）：與 GARCH 慢速 mean-reversion 一致 —— 這些模型多在高波動的 2022 訓練、預測進入平靜的 2023-2024，變異數降不夠快。
3. **穩健的 conditional over-dispersion（log-space median b̂=0.75<1）**：forecast 相對於單日 r² 稍嫌過度分散；獲先前 K 獨立佐證。
4. **最 actionable 發現 = 尺度修正**：pipeline 的 Parkinson-based 評估**高估 over-forecast**（73% → 真實 7%）。建議 GARCH 家族的 stored 評估改用 r²（或 5-min RV），Parkinson 保留給 range/HAR 類的原生 target。
5. **校正 null**：偏誤真實但 naive 線性 MZ 校正 OOS 不顯著改善 —— 與 VolPred 既有的 "complexity ceiling" 主題一致（精密度改善度量，不改善可投資決策）。

## 限制

- **r² 是極 noisy 的 realized proxy**（比 5-min RV 噪約 8x）。calm 2023-2024 的 R²=0.01–0.05 是**這個 proxy 的預期特性，不代表模型無效**（先前 K：日頻 r² 的 MZ-R² 典型 ~0.29，且在含 COVID/2022 的長樣本才較高）。**calibration 訊號在 slope 推論（HAC-robust），不在 R²。**
- **noisy proxy 不會使 b 偏向 0**（噪音在 y=r² 的殘差、不在 regressor=forecast），但 r² 的極端右尾會讓 **var-space OLS 對高槓桿點敏感** → 本審計以 **log-space b̂ 為穩健 slope**，var-space 僅作對照。
- Joint Wald 在 n≈500 下對微小偏誤也會拒絕；因此**同時報 effect size**（b̂, fc/r² ratio）而非只看 p 值。
- 2 個 EGARCH 檔 var-space HAC cov 非有限（極端 r² 導致），joint test 標 undetermined（已 log，非 silent；log-space 仍可估）。
- GJR-HAR（8 檔，caveat 家族）在 r² target 上多為 over-forecast，但 **HAR 成分原生 target 是日內 RV 不是 r²**，故單獨列示、不進 core headline。

## 相關 K

- **K145**：MZ-R² peak mechanism（horizon 觀點；本審計是 h=1 的 library-wide 版本）
- **Mincer-Zarnowitz cross-asset (2023-2024)**：TLT best / SPY moderate / GLD worst — 本審計把它從 3 資產擴到 7 資產 × 4 家族並加資料驗證
- **SPY GJR w=504 MZ**（β=0.67, R²=0.29）：本審計 log-space b̂=0.68 獨立複現
- **K874e**：MZ-R² 作為 6-layer 比較的 Layer-1 度量之一
- **Parkinson bias K**（5-min RV calibration：Parkinson bias −33.9%）：本審計的 proxy-scale 診斷的理論基礎
- **Complexity ceiling K 群**（QLIKE ceiling / DCC null）：本審計的 bias-correction null 與之呼應

## 文獻

- Mincer, J. & Zarnowitz, V. (1969). *The Evaluation of Economic Forecasts.* NBER. — MZ 迴歸原始出處
- Patton, A. J. (2011). *Volatility forecast comparison using imperfect volatility proxies.* Journal of Econometrics 160(1), 246-256. — noisy proxy 下 forecast evaluation 的理論；QLIKE proxy-robustness
- Diebold, F. X. & Mariano, R. S. (1995). *Comparing Predictive Accuracy.* JBES 13(3), 253-263. — DM 檢定（校正前後 QLIKE 比較）
- Newey, W. K. & West, K. D. (1987). *A Simple, Positive Semi-Definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix.* Econometrica 55(3), 703-708. — HAC 標準誤
- Andersen, T. G. & Bollerslev, T. (1998). *Answering the Skeptics: Yes, Standard Volatility Models Do Provide Accurate Forecasts.* International Economic Review 39(4), 885-905. — r² 作為條件無偏 proxy、GARCH forecast evaluation

## 復現

```bash
cd experiments/k1660_mz_calibration_audit
uv run --active python k1660_mz_calibration_audit.py   # 產 results.json + 2 PNG（OHLC 首跑下載後 cache 於 data/）
```

**產出**：`k1660_mz_calibration_audit_results.json`（per-file â/b̂/HAC-SE/t/Wald-p/verdict + family summary + flagship bias-correction + proxy diagnostic）、`mz_scatter_flagship.png`、`family_calibration_summary.png`。
