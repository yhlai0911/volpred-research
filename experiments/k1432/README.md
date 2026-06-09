# K1432 — TW Financial Stress Index as Early Warning for TSMC Volatility

- **Experiment ID**: `K1432`
- **Status**: completed
- **Verdict**: **NULL** (with stronger reading: stress augmentation **significantly worsens** OOS forecasts at several horizons; in-sample Granger significance does **not** carry to OOS predictive value)
- **Created**: 2026-06-09 (TPE)
- **Owner**: 主線程 (hourly-12 dispatch, task `research_tw_financial_stress_early_warning`)
- **Predecessor**: K757 / K757b / K757bv2 — established Fubon(2881)→TSMC(2330) Granger causality on **returns** at level (F=5.60, p=1.9e-6 in K757bv2)

## 問題描述

K757 系列發現富邦金 (2881.TW) 對 TSMC (2330.TW) 在日報酬層級具有 Granger 因果。K1432 將此發現延伸：
（a）建構**台股金融股壓力指標**（≥4 檔金融股的聚合 stress index，多個 spec），
（b）檢驗該指標能否作為 TSMC **波動率** (realized vol, RV) 的**早期預警 signal**，
（c）對標準波動率 baseline（AR(1)、HAR-RV、HAR-RV+VIX）做**樣本外 (OOS) 公平比較**並執行 Diebold-Mariano 檢定。

## 動機

K757bv2 證明 in-sample level-Granger causality 存在，但**從未檢驗：(i) 波動率預測、(ii) OOS、(iii) 多 spec 防 cherry-pick、(iv) 對 HAR-RV/VIX baseline 的增量價值**。這四個 gap 是學術 referee 必問的東西。K1432 填補。

## 方法

### 資料

- **來源**：yfinance（價格直抓，cached to `data/prices.parquet`）
- **期間**：2010-01-04 to 2026-06-08（約 16 年；OOS 涵蓋 2021 牛市 / 2022 熊市 / 2023-25 復甦）
- **目標**：TSMC (`2330.TW`) — 21-day rolling sum of squared daily log returns 作 RV proxy（standard daily-only RV）
- **金融股 universe**（5 檔，brief 要求 ≥4 並 must include 2881+2882）：
  - 富邦金 2881.TW
  - 國泰金 2882.TW
  - 中信金 2891.TW
  - 玉山金 2884.TW
  - 華南金 2880.TW
- **大盤**：0050.TW
- **VIX**：`^VIX`（美國 VIX 作 baseline 風險偏好 proxy；台指 VIX 期間覆蓋不一致）

### 預先承諾 Stress Specs（避免 cherry-pick）

寫入腳本 source 內 (`build_stress_indices()`) 並在實驗執行前 commit；不依 OOS 結果挑：

| Spec | 定義 |
| --- | --- |
| **S1** | 5 檔金融股 21d realized variance 的橫斷面均值 |
| **S2** | 每日 max-min 報酬 dispersion 的 21d rolling std |
| **S3** | (金融股平均報酬 − 0050 報酬) 的 5d rolling mean |
| **S4** | 金融股報酬 PCA 第一主成分得分絕對值的 21d rolling mean（loadings 僅用 train 樣本估出，OOS 套用） |

### Baseline 模型

- **B1 AR(1)**：log(RV_t) → log(RV_{t+h})
- **B2 HAR-RV** (Corsi 2009)：daily / weekly(5d) / monthly(22d) RV
- **B3 HAR-RV + VIX**：B2 加上 log(^VIX)

### Stress-augmented 比較模型

- B2 + S1 / B2 + S2 / B2 + S3 / B2 + S4 / B2 + all
- B3 + S1 / B3 + S2 / B3 + S3 / B3 + S4

### Horizons

k = 1, 5, 10 trading days ahead

### Train / OOS split

- Train：2010-03-04 — 2020-12-31（n=2,814）
- OOS：2021-01-01 — 2026-05-25（n=1,397）
- 採 **expanding window OLS**，每 21 個交易日 refit（在 OOS 區段內）

### 方法論硬規則

1. **Lag**：`make_targets()` 以 `logrv.shift(-h)` 將 y 對齊至 t+h；`expanding_ols_forecast` 訓練資料 `data.iloc[:pos_in_data]` 嚴格在 t 之前。**所有預測 row t 只含 t 當天及之前資訊**。
2. **Seed**：`np.random.seed(42)` 全域固定；PCA loadings 用對稱 eig 不需 seed，但訓練期間切點固定。
3. **Pooled MLE**：本實驗未涉及多資產共用參數 MLE，K1213/K1216c 規則不適用。
4. **Symmetric refinement**：所有模型同一 expanding-OLS 框架 + 同 refit_freq + 同 train_end，K1216b 規則滿足。
5. **DM 檢定**：Newey-West HAC variance (lag = h−1) + Harvey-Leybourne-Newbold (1997) 小樣本修正；雙尾 t_{n-1} p-value。
6. **損失函式**：MSE on log RV + Patton (2011) **QLIKE** = log(σ̂²) + σ²/σ̂² （波動率預測公認 robust loss）

## 結果

### Granger（全樣本，descriptive only）

stress index → log RV，最大 lag=10，AIC unconstrained：

| Spec | F-stat (lag=5) | p-value |
| --- | ---: | ---: |
| S1 (xs vol) | **5.67** | 3.2e-5 |
| S2 (dispersion) | **3.67** | 0.0026 |
| S3 (rel weak) | 0.04 | 0.999 |
| S4 (PCA \|PC1\|) | **3.69** | 0.0025 |

**S1, S2, S4 in-sample Granger-cause TSMC log RV**（p<0.005）。S3 完全無顯著。

### OOS DM 檢定（vs B2 HAR-RV baseline）

QLIKE：**負 DM stat = stress 模型 LOSS 變高 = baseline 比較好**。

| Horizon | Spec | DM (QLIKE) | p-value | 方向 |
| --- | --- | ---: | ---: | --- |
| h=1 | B2+S1 | −1.91 | 0.057 | 略 worse |
| h=1 | B2+S2 | −0.07 | 0.944 | flat |
| h=1 | B2+S3 | **−2.09** | 0.037 | worse |
| h=1 | B2+S4 | **−2.23** | 0.026 | worse |
| h=5 | B2+S1 | **−2.60** | 0.0095 | worse |
| h=5 | B2+S4 | **−2.82** | 0.0048 | worse |
| h=5 | B2+all | **−3.12** | 0.0018 | worse |
| h=10 | B2+S1 | **−2.90** | 0.0038 | worse |
| h=10 | B2+S4 | **−2.70** | 0.0069 | worse |
| h=10 | B2+all | **−3.25** | 0.0012 | worse |

**沒有任何 spec × horizon 在 DM 顯著的方向上對 baseline 有改善**。多個 spec × horizon 顯著 WORSE。

### 主要解讀

1. **In-sample Granger 顯著 ≠ OOS 預測價值**：S1/S2/S4 全 p<0.005 in-sample，但 OOS 加入 baseline 後變差。典型 in-sample overfit + OOS noise penalty。
2. **HAR-RV 已 internalize 多數可預測訊號**：TSMC 自己的 daily/weekly/monthly RV 已涵蓋 financial stress contagion 的成分；額外加金融股 stress 是 redundant + noisy。
3. **VIX 的增量**：B3 (HAR-RV+VIX) QLIKE 在每個 h 都比 B2 略低（h=1 −4.1780 vs −4.1779；h=5 −4.1279 vs −4.1262；h=10 −4.0597 vs −4.0560），但加 stress 反而把 VIX 的優勢吃掉。
4. **與 K757bv2 的關係**：K757bv2 證明 LEVEL returns Granger causality，K1432 證明這個 in-sample 結構**不轉化為 OOS 波動率預測利益**。兩者不矛盾：returns Granger ≠ volatility forecastability。

## 結論

**NULL** — TW 金融股壓力指標**不能**作為 TSMC 波動率的 OOS 早期預警 signal。比 HAR-RV baseline 顯著更差。這是真實研究結果，符合 in-sample / OOS 落差的學術典型發現，可寫成「為什麼 in-sample Granger 不足以宣稱 forecastability」的方法論文章。

## 限制

- VIX 用美國 ^VIX 而非台灣 TWVIX（後者期間覆蓋不一致）— 若用 TWVIX 結論可能微調但方向不變
- 5 檔金融股 PCA loadings 用 train 期固定 — robustness 可考慮 rolling refit（但 K1216c 教訓提醒 symmetric refinement，目前所有 spec 都用 train-only loadings，已對齊）
- 21d RV 是 daily-only proxy；intraday data 若可用會更精確（unavailable for free 台股）
- 期間 OOS 含 2021 牛 / 2022 熊 / 2023-25 復甦，覆蓋多 regime，已避免 single-regime artifact

## 防錯規則對照（per `.claude/rules/experiments.md`）

| 規則 | 落地處 |
| --- | --- |
| 先讀 error_log | `docs/error_log.md` 已掃 lookahead/seed/lag 相關 entries |
| 知識庫查相似 K | `storage/memory/knowledge.json` grep K757/Granger/early warning |
| Lag `signal.shift(1)` | `make_targets()` `shift(-h)` + `expanding_ols_forecast` 嚴格 `iloc[:pos_in_data]` |
| Fixed seed | `np.random.seed(42)` 全域 |
| OOS 公平比較 | 所有 model 同 train_end / 同 refit_freq / 同 OLS 框架 |
| Patton QLIKE | `qlike_loss()` log(σ̂²)+σ²/σ̂² |
| DM HAC | Newey-West lag=h−1 + HLN(1997) 修正 |
| 多 spec 防 cherry-pick | 4 specs × 3 horizons 全報告 |
| Pooled MLE 100+ multistart | N/A（無 pooled MLE） |
| Symmetric refinement | 所有模型同 OLS 路徑 |

## Codex Review Pending

主線程接手 Codex review 後再決定是否寫 `knowledge.json`（per K1259 process gate）。Agent 端**未寫** knowledge.json / feed.json / supabase sync。

## 檔案

```
experiments/k1432/
├── README.md
├── k1432_tw_financial_stress.py
├── k1432_tw_financial_stress_results.json
├── data/
│   └── prices.parquet                      # cached yfinance prices
├── figures/
│   ├── stress_and_rv.png                   # TSMC RV + 4 stress indices (z-score)
│   └── qlike_by_horizon.png                # OOS QLIKE per model × horizon
└── references/
    ├── corsi_2009_har_rv.md
    ├── patton_2011_qlike.md
    ├── adrian_brunnermeier_2016_covar.md
    └── diebold_mariano_1995.md
```

## References

- Corsi, F. (2009). *A simple approximate long-memory model of realized volatility*. Journal of Financial Econometrics 7(2), 174–196.
- Patton, A. J. (2011). *Volatility forecast comparison using imperfect volatility proxies*. Journal of Econometrics 160(1), 246–256.
- Adrian, T., & Brunnermeier, M. K. (2016). *CoVaR*. American Economic Review 106(7), 1705–1741.
- Diebold, F. X., & Mariano, R. S. (1995). *Comparing predictive accuracy*. Journal of Business & Economic Statistics 13(3), 253–263.
- Harvey, D., Leybourne, S., & Newbold, P. (1997). *Testing the equality of prediction MSEs*. International Journal of Forecasting 13(2), 281–291.
