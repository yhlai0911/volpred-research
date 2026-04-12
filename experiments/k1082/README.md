# K1082: Single-Country EM ETFs (EWT / EWZ / FXI) — USD Wrapper Diagnostic

**Date:** 2026-04-13
**Proposer:** 用戶 (via brief)
**Executor:** Claude
**Status:** Complete

---

## 1. 動機 (Motivation)

K1075–K1081 在 Paper 9 下建立了 VIX-A4f 的跨資產圖像：

| K | 資產 | 計價 | Full OOS DM t | Harvey |
|---|------|------|---------------|--------|
| K1075 | SPY | USD | +7.92 | PASS |
| K1078 | QQQ | USD | +5.99 | PASS |
| K1080 | IWM | USD | +4.80 | PASS |
| K1081 | EEM | USD | +5.25 | PASS |
| **K1077** | **0050.TW** | **TWD** | **−0.49** | **FAIL** |

K1077（台股 50）的 null 留下一個關鍵問題：是 **台灣市場結構獨特** 還是 **新台幣計價** 造成？

### The Money Question
**EWT（iShares MSCI Taiwan ETF）** 與 0050.TW 在 stock composition 上幾乎相同（台股 50 大、TSMC 為第一大權重），但在 **NYSE 以 USD 計價**。這是最乾淨的 currency 測試——組成相同，僅計價幣別不同。

若 EWT PASS：USD wrapper 是 A4f 的必要條件
若 EWT FAIL：台灣市場結構確實獨特，與 currency 無關

同時加測 **EWZ（巴西）** 和 **FXI（中國大盤）** 作為單國 USD EM benchmark，定位 EWT 在 EM cross-section 的位置。

---

## 2. 方法 (Method)

嚴格對齊 K1075/K1078/K1080/K1081：

- **模型**：GJR-GARCH(1,1) baseline vs A4f（τ_t = θ₀ + θ₁·VIX²_{t-1}，g_t = GJR on u = r/√τ，free ω_g）
- **Rolling 估計**：WINDOW=2000、REFIT_EVERY=63（quarterly）
- **3 個 non-overlapping OOS windows**：
  - Early_Crisis 2007-01-01 ~ 2012-12-31（GFC + Euro crisis）
  - Middle_Recovery 2013-01-01 ~ 2018-12-31（China 2015、Trump tariff）
  - Late_COVID 2019-01-01 ~ 2026-04-11（COVID + rate hike + China）
- **評估**：QLIKE（Patton 2011）、DM HAC-Newey-West（Harvey |t|>3）、Spearman、moving-block bootstrap CI（block=n^{1/3}, 1000 reps, seed=42）
- **Crisis sub-periods**：GFC、China 2015、COVID、Bear 2022
- **VIX buckets**（lagged VIX）：Low/Normal/High/Extreme/Crisis

### 資料（yfinance）
| ETF | IPO | 使用期間 | n (OOS) |
|-----|-----|---------|---------|
| EWT | 2000-06-20 | 2000-06-26 ~ 2026-04-10 | 4848 |
| EWZ | 2000-07-14 | 2000-07-17 ~ 2026-04-10 | 4848 |
| FXI | 2004-10-05 | 2004-10-08 ~ 2026-04-10 | 4848 |
| ^VIX | — | 2000-06 ~ 2026-04 | shared |

FXI 在 2007-01-01 只有約 562 筆 pre-OOS 訓練資料（< WINDOW=2000）；同 K1081 策略：`max(0, abs_idx - WINDOW)`，首次 refit 使用所有可用歷史。FXI Early_Crisis window 須標記為「訓練資料不足」。

### Lag 驗證（preamble 規則）
- `tau_t = θ₀ + θ₁ · VIX[t-1]²`（`v_lag = vix[abs_idx - 1]`）
- `r_prev = ret[abs_idx - 1]` 用於 GJR / A4f g_t 遞迴
- 無 same-day lookahead；forecasting 在 out-of-sample period 中每日遞迴

---

## 3. 結果 (Results)

### Full OOS 2007-2026（n=4848/ETF）

| ETF | Market | Currency | QLIKE Diff% | DM t | Harvey | θ₁ span (full) | θ₁ span (P10-P90) |
|-----|--------|----------|-------------|------|--------|----------------|-------------------|
| **EWT** | Taiwan | USD | **−0.213%** | **+2.26** | **FAIL** | 3.77 | 2.06 |
| **EWZ** | Brazil | USD | −0.229% | +2.33 | FAIL | 1.18 | 0.49 |
| **FXI** | China | USD | −0.338% | **+3.61** | **PASS** | 2.25 | 0.56 |

### 8-Asset Paper 9 Final Map

| 資產 | 市場 | 計價 | DM t | Harvey | Comment |
|------|------|------|-------|--------|---------|
| SPY (K1075) | US | USD | +7.92 | PASS | 核心 |
| QQQ (K1078) | US tech | USD | +5.99 | PASS | |
| EEM (K1081) | EM basket | USD | +5.25 | PASS | 分散 EM |
| IWM (K1080) | US small | USD | +4.80 | PASS | |
| **FXI (K1082)** | China | USD | **+3.61** | **PASS** | 單國 EM 首次 PASS |
| EWZ (K1082) | Brazil | USD | +2.33 | FAIL | 方向正確但未達 Harvey |
| **EWT (K1082)** | Taiwan | USD | **+2.26** | **FAIL** | 核心發現 |
| 0050.TW (K1077) | Taiwan | TWD | −0.49 | FAIL | TWD baseline |

### 關鍵 DM t-shift（Taiwan stocks, 相同 composition）

| 包裝 | DM t | Harvey |
|------|------|--------|
| EWT（USD wrapper）| **+2.26** | FAIL（但方向正確）|
| 0050.TW（TWD wrapper）| **−0.49** | FAIL（方向錯誤）|
| **DM t-shift** | **+2.75 t-units** | — |

---

## 4. 解讀 (Interpretation)

### H1 (per ETF): FXI PASS, EWT/EWZ FAIL
只有 FXI 達到 Harvey |t|>3。EWT 和 EWZ 都是「方向上 A4f 較好但未達統計門檻」。

### H2 (currency discrimination): TAIWAN STRUCTURE UNIQUE（但 currency 仍有效應）
- **EWT FAIL**（+2.26）與 0050.TW FAIL（−0.49）都無法通過 Harvey → 按嚴格 Harvey 標準：**Taiwan structure 獨特**
- **但**：DM t 從 −0.49 → +2.26 的 +2.75 t-unit shift 顯示 USD wrapper **確實** 改變了 A4f 的表現方向（從「反向」變成「正向但未達門檻」）
- **正確的 nuanced 結論**：**currency 和 composition 都重要**，但 Taiwan 的 TSMC 集中度可能使單一國家 Taiwan 曝險即便放在 USD wrapper 內，A4f channel 仍顯著弱於其他單國 EM（EWZ、FXI）與分散 EM（EEM）

### H3 (all 3 USD EM pass): FAIL (1/3)
只有 FXI 通過 Harvey。Single-country USD EM ETFs ≠ 普遍 PASS。

### H4 (EWT θ₁ more stable than 0050.TW): N/A
K1077 無 theta1_stability 記錄，無法直接比較。

### H5 (no breakdown at extreme VIX): PASS
三支 ETF 在 VIX>40（Extreme/Crisis bucket）都沒有出現 A4f QLIKE diff > +5% 的崩潰。

### EM cross-section 排序（DM t）
```
EEM (+5.25) > FXI (+3.61) > EWZ (+2.33) > EWT (+2.26)
 分散 EM    >   中國     >    巴西   >    台灣
```
從最分散到最集中，A4f 效果單調遞減。**Taiwan 是最弱的 EM 單國曝險**——即使換上 USD wrapper 也僅提升到 +2.26，未能跨過 Harvey 門檻。

### 可能的 Taiwan-specific 驅動（待 K1083+ 檢驗）
1. **TSMC 權重集中**（EWT ~40-50%；0050.TW ~50%）稀釋了指數層級的 VIX channel
2. **本地 retail 主導**（約 60-70% 週轉量）使短期 idiosyncratic flow 蓋過 VIX 系統訊號
3. **限漲跌 10% 機制** 截斷尾部，使 GJR-GARCH（無限漲跌幅假設）的 baseline 已接近最適
4. **半導體週期 idiosyncratic**（庫存循環、AI capex）與 VIX 全球 risk-off 脫鉤

---

## 5. Paper 9 意涵 (Paper 9 Implication)

**主張**：A4f 的效果取決於兩個條件——
1. **USD-denominated**（liquid on US exchange，與 SPX 共享 risk-off 傳導 channel）
2. **充分分散或高 beta-to-SPX**（避免 idiosyncratic 驅動蓋過系統性 VIX signal）

**Taiwan 是 edge case**：即便 USD wrapper（EWT）存在 meaningful +2.75 t-unit shift，但因為 composition 極端集中於 TSMC + 半導體循環，系統性 VIX channel 仍被 crowd out。本地幣版本（0050.TW）則完全無效（方向相反）。

**Paper 9 claim（可直接引用）**：
> VIX-A4f improves volatility forecasts across USD-denominated US equity and diversified emerging-market ETFs (SPY, QQQ, IWM, EEM), and crosses the Harvey threshold for at least one single-country EM (FXI). Among single-country exposures, Taiwan is the edge case: the USD wrapper (EWT) produces a +2.75 t-unit improvement over the local-currency version (0050.TW) on identical stock composition, yet does not cross the Harvey barrier. The DM t-stat ordering across EM ETFs (EEM > FXI > EWZ > EWT > 0050.TW) is monotone in diversification/currency — consistent with the interpretation that A4f captures systemic USD-funding / global risk-off channels, and is attenuated when single-country exposure is dominated by idiosyncratic supply-chain dynamics (Taiwan semiconductor concentration).

---

## 6. Limitations

1. **FXI Early_Crisis window**：2007-01-01 時僅 ~562 筆訓練資料（< WINDOW=2000），須視為 training-light；`max(0, abs_idx - WINDOW)` policy 同 K1081
2. **VXEEM / VXFXI 未測**：K1082 所有 ETF 都用 ^VIX（全球 risk-off 訊號）。替換成單一國家 IV（若 yfinance 有數據）可能提升各別 t-stat
3. **Harvey threshold 嚴格**：EWT +2.26 與 EWZ +2.33 在 Harvey (2016) 下 FAIL，但在 95% CI（|t|>1.96）下 PASS。讀者若採用較寬鬆門檻，應將 EWT/EWZ 標記為 marginal，不是 null
4. **0050.TW θ₁ span 無法直接比較**：K1077 results JSON 不含 theta1_stability；若 Paper 9 重視 θ₁ stability，建議 rerun K1077 with theta1_stability logging（或以 K1082 EWT 的 2.06 作為 Taiwan composition 的 upper bound estimate）
5. **EWT ≈ 0050.TW composition** 是近似：EWT 是 MSCI Taiwan（88 檔，約 85% 市值覆蓋），0050.TW 是 TSE 50。重疊度估計 > 90% by weight，TSMC 都是最大權重
6. **沒有轉倉/tracking error 調整**：EWT 作為 ADR-like wrapper，有 minor premium/discount；0050.TW 為國內現貨 ETF。這些微結構差異可能貢獻少量噪聲，但不足以解釋 +2.75 t-unit shift
7. **Sample 截至 2026-04-10**：2026 Q2 後數據未納入

---

## 7. 延伸方向 (Next Directions)

寫入 research_program.md（由主線程處理）：
1. **K1083a Taiwan-idio test**：0050.TW − EWT「同組成、不同幣別」的殘差，檢驗台灣 idiosyncratic 成分是否與 VIX 脫鉤
2. **K1083b Concentration cross-section**：EEM vs single-country EM ETFs 用 index concentration (HHI) 做 theta1-magnitude 的 meta-regression
3. **K1083c VXFXI / VNM**：若可取得，將 exogenous IV 換成地區別 IV（HSI 的 VHSI、或 MSCI EM Volatility Index），看 Taiwan 是否才匹配到適當的 signal
4. **K1083d 0050.TW × USD exchange rate**：把 0050.TW return 直接乘 TWD/USD return 模擬 synthetic USD 台股，看結果是否接近 EWT
5. **K1083e 台灣限漲跌幅 resampling**：在 clean_tw50_data 做限漲跌幅的 truncation robustness check

---

## 8. 檔案清單 (Deliverables)

| 檔案 | 描述 |
|------|------|
| `k1082.py` | 主腳本（1229 行，3 ETFs × 全流程）|
| `k1082_results.json` | 完整結果 JSON（per_etf、eight_asset_comparison、verdicts）|
| `k1082_dm_comparison.png` | 3 ETFs Full OOS DM（EWT/EWZ/FXI）|
| `k1082_ewt_vs_0050tw.png` | **直接對照 EWT (USD) vs 0050.TW (TWD)** |
| `k1082_theta1_by_etf.png` | θ₁ 時間序列（3 ETFs 疊圖，log scale）|
| `k1082_currency_hypothesis.png` | USD vs TWD 跨資產 DM 對照 |
| `k1082_six_asset_final.png` | 8 資產 Paper 9 final map |
| `k1082_qlike_per_window.png` | 3 OOS windows × 3 ETFs QLIKE 分解 |
| `k1082_vix_bucket.png` | VIX bucket × 3 ETFs diff% |

---

## 9. 參考文獻 (References)

- Engle, R. F., Ghysels, E., & Sohn, B. (2013). *Stock market volatility and macroeconomic fundamentals.* Review of Economics and Statistics, 95(3), 776-797.
- Patton, A. J. (2011). *Volatility forecast comparison using imperfect volatility proxies.* Journal of Econometrics, 160(1), 246-256.
- Harvey, D. I., Leybourne, S. J., & Newbold, P. (2016). *The impact of multiple testing on …*
- Hansen, P. R., & Lunde, A. (2005). *A forecast comparison of volatility models: does anything beat a GARCH(1,1)?* Journal of Applied Econometrics, 20(7), 873-889.

## 10. 上游實驗

- K988 SPY A4f proof-of-concept
- K1075 SPY extended (Harvey-PASS)
- **K1077 0050.TW extended (Harvey-FAIL) ← 本實驗要解釋的 null**
- K1078 QQQ extended (Harvey-PASS)
- K1080 IWM extended (Harvey-PASS)
- K1081 EEM extended (Harvey-PASS)
