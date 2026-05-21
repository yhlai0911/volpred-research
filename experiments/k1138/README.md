# K1138: Equity compendium (SPY/QQQ/IWM) robust models

[提出: Claude (user direction), 執行: Claude] · 2026-04-17

---

## v2 修正（2026-05-13）— Codex primary-path review BLOCKING defect fix

**缺陷**：`asset_null` / `model_null` summary flags 只用 `max_t > 2.0` 判定，未同時要求 `DM_HLN_p_BH < 0.05`。此邏輯與 9-cell PASS logic（line 828，正確使用雙條件）不一致，違反 BH-FDR enforcement 原則。

**影響**：
- **IWM** asset-level 判決 **PASS → NULL**（t=+2.064 > 2.0，但 p_BH=0.071 > 0.05，BH 校正後不顯著）
- SPY、QQQ 不受影響（p_BH=0.000137 << 0.05）
- model_null_map：HAR-RV-X 仍 PASS（SPY/QQQ 通過雙條件）；GARCH-MIDAS-X / GAS-t 仍 NULL
- 總體 verdict 維持 **MIXED**（2/9 cells pass 雙條件；pass_count 維持）
- 所有 per-cell DM 統計量（DM_HLN_t, DM_HLN_p_BH）**不變**（原本即正確）

**修正點**（`k1138.py` lines 840/848）：
```python
# BEFORE (incorrect):
asset_null[tk] = 'NULL' if max_t <= 2.0 else 'PASS'

# AFTER (correct):
asset_pass = any(c['DM_HLN_t'] > 2.0 and c['DM_HLN_p_BH'] < 0.05 for c in asset_cells)
asset_null[tk] = 'PASS' if asset_pass else 'NULL'
```

**主要結論調整**：IWM 由「邊界 PASS」改為「NULL（BH 校正後不顯著）」，與其 p_BH=0.071 的表格數字一致。Paper 4 implication 不變：HAR-RV-X 對 large-cap equity（SPY/QQQ）有顯著 VIX marginal value；small-cap IWM NULL 與 Paper 4 universal-null claim 相容。

---

## 問題與動機

K1136 已建立 commodity compendium（USO/GLD/UNG/BTC-USD）下的 "universal robust-method NULL"：GARCH-MIDAS-X + HAR-RV-X + GAS-t（K1129/K1134）全部無法顯著優於 GJR-GARCH baseline。

K1138 擴展測試 Paper 4 的 "universal-null" 宣稱是否跨 asset class 成立：

- **Hypothesis 2 (UNIVERSAL_NULL)**：equity 也全部 NULL → Paper 4 可宣稱 5 asset classes universal null
- **Hypothesis 3 (EQUITY_PASSES)**：equity PASSES → 需要新 Paper 4 subsection 討論 asset-class heterogeneity
- **MIXED**：部分 (asset, model) 組合 PASS → Paper 4 需報告具體 passing combos，不能一概而論

## 方法

### 資料（yfinance，2021-01-04 ~ 2026-04-10 OOS）

| Asset | Period | Obs | Mean % | Std % | Mean Park |
|-------|--------|-----|--------|-------|-----------|
| SPY   | 2000-01 → 2026-04 | 6606 | 0.031 | 1.22 | 1.00 |
| QQQ   | 2000-01 → 2026-04 | 6606 | 0.042 | 1.69 | 2.08 |
| IWM   | 2001-01 → 2026-04 | 6354 | 0.039 | 1.50 | 1.59 |

VIX 來源：yfinance `^VIX`，2000-01-03 ~ 2026-04-10，n=6607。

### 模型（完全對齊 K1136 / K1129 spec）

| Model | Specification | Native target |
|-------|---------------|---------------|
| M1 | GJR-GARCH(1,1) Normal（baseline） | close² (r²) |
| M3 | GARCH-MIDAS-X: τ_t = exp(m + θ·VIX²_monthly_lag1); g_t GJR(1,1) on devolatilized returns | close² (r²) |
| M4 | HAR-RV-X: log(RV_t) = β_0 + β_d log RV_{t-1} + β_w log RV_{t-5:t-1} + β_m log RV_{t-22:t-1} + β_x log(VIX²_{t-1}) | Parkinson RV |
| M5 | HAR-RV 控制組（無 VIX） | Parkinson RV |
| M6 | GAS-t (Creal-Koopman-Lucas 2013)：f_{t+1} = ω + α·S·∇_t + β·f_t, t-dist | close² (r²) |

### 5-min RV 替代方案

**Fallback**：SPY/QQQ/IWM 的 5-min intraday tick 資料在本地 cache 不可得（TAIFEX 5-min 只適用台指期）。改用 Parkinson range-based variance 作 RV proxy，與 K1136 完全一致。此選擇：
1. 確保與 K1136 commodity 的 cross-asset 比較對稱
2. Parkinson 是 low-frequency RV 最好的 feasible proxy（K1134 已驗證）
3. 結果可以直接跟 K1136 對照

### 設計

- **OOS**: 2021-01-04 → 2026-04-10（1323 obs/asset，跨 COVID recovery + 2022 bear + 2024-25 rally）
- **Window**: 1500, **Refit every**: 63 天（與 K1136 一致）
- **Seed**: 42
- **Fair tests**（Patton 2011 model-target matching）：
  - **HAR-RV-X**: M4 vs M5 on Parkinson（within-family VIX marginal contribution）
  - **GARCH-MIDAS-X**: M3 vs M1 on r²（close²-native cross-model）
  - **GAS-t**: M6 vs M1 on r²（close²-native cross-model）
- **BH correction**：9 cells FDR control
- **PASS criterion**：DM_t > +2 AND BH p < 0.05（robust model beats baseline）
- **Harvey joint**：DM_t > +3 AND BH p < 0.05

### Lag 安全（K1121/K1136 教訓）

- VIX_{t-1} 安全（CBOE real-time，無 publication delay）
- MIDAS τ_t 使用**嚴格前一月** VIX² 均值（同月份資料不洩漏）
- HAR regressor 全部 `.shift(1)` 明確寫在代碼

### Codex 審查

嘗試 `codex exec -s read-only` 審查代碼。Codex 回報 quota exceeded（`usage limit... try again at 3:27 PM`）。改為自我審查：

1. ✅ GAS-t spec 與 K1129 逐行對齊（negloglik、fit、forecast state update）
2. ✅ MIDAS-X `build_vix_monthly_lag1` 與 K1136 完全相同（同份程式碼）
3. ✅ HAR-RV-X / HAR-RV `fit_har_rv_x` 與 K1136 完全相同
4. ✅ OOS forecast state semantics 驗證：state_m6_sigma2 = σ²_{t-1}, state_m6_f = f_{t-1}，forecast function 產生 f_t = ω + α·s(r_{t-1}, σ²_{t-1}) + β·f_{t-1}
5. ✅ DM-HLN + BH correction 驗證（BH monotone constraint 正確實作）
6. ✅ 9-cell aggregation 與 brief 規格一致

## 結果

### 9-cell DM-HLN t matrix（fair tests）

|        | HAR-RV-X (M4 vs M5 on Parkinson) | GARCH-MIDAS-X (M3 vs M1 on r²) | GAS-t (M6 vs M1 on r²) |
|--------|-----------------------------------|---------------------------------|-------------------------|
| **SPY** | **t=+4.19, p_BH=0.000 PASS** | t=+1.36, p_BH=0.263 | t=-3.27, p_BH=0.003 |
| **QQQ** | **t=+4.22, p_BH=0.000 PASS** | t=-0.20, p_BH=0.844 | t=-2.81, p_BH=0.011 |
| **IWM** | t=+2.06, p_BH=0.071 | t=+1.01, p_BH=0.402 | t=-0.49, p_BH=0.704 |

**PASS cells passing Harvey joint (t > 3 & BH p < 0.05): 2/9**
（SPY HAR-RV-X、QQQ HAR-RV-X）

IWM HAR-RV-X near miss（t=+2.06 剛過 2 但 BH 校正後 p=0.071）

### Asset-level NULL check（cross-model）

| Asset | max DM_t | best p_BH | 判決 | 詳情 |
|-------|----------|-----------|------|------|
| SPY | +4.19 | 0.000137 | **PASS** | HAR-RV-X（BH adj p<0.05） |
| QQQ | +4.22 | 0.000137 | **PASS** | HAR-RV-X（BH adj p<0.05） |
| IWM | +2.06 | 0.071 | **NULL** | t>2 但 BH 校正後 p=0.071>0.05，不顯著 |

（v2 修正：IWM 由 PASS 改為 NULL；dual criterion t>2.0 AND p_BH<0.05 須同時滿足）

### Model-level NULL check（cross-asset）

| Model | max DM_t | 判決 |
|-------|----------|------|
| **HAR-RV-X** | +4.22 | **PASS**（VIX adds marginal value to HAR for equity）|
| GARCH-MIDAS-X | +1.36 | NULL |
| GAS-t | -0.49 | NULL |

### K1136 commodity vs K1138 equity max DM-t 比較

| Asset class | max fair-test DM_t | NULL/PASS |
|-------------|---------------------|-----------|
| **K1136 Commodity** | | |
| USO   | +1.65 | NULL |
| GLD   | +0.94 | NULL |
| UNG   | +0.74 | NULL |
| BTC-USD | +0.52 | NULL |
| **K1138 Equity** | | |
| SPY   | **+4.19** | **PASS** (p_BH=0.000) |
| QQQ   | **+4.22** | **PASS** (p_BH=0.000) |
| IWM   | **+2.06** | NULL (p_BH=0.071，BH 校正後不顯著) |

**Asset-class heterogeneity**：large-cap equity（SPY/QQQ）max DM-t 是 commodity 的 2.5x 以上；small-cap IWM 邊界 NULL。

### Full QLIKE matrix

**Parkinson target**（HAR-native，M4/M5 比較 fair）：

| Asset | M1 GJR | M3 MIDAS | M4 HAR-X | M5 HAR | M6 GAS-t |
|-------|--------|----------|----------|--------|----------|
| SPY   | 0.488 | 0.473 | **0.347** | 0.390 | 0.543 |
| QQQ   | 0.431 | 0.422 | **0.313** | 0.341 | 0.481 |
| IWM   | 0.362 | 0.358 | **0.276** | 0.290 | 0.401 |

**r² target**（GARCH-native，M3/M6 vs M1 比較 fair）：

| Asset | M1 GJR | M3 MIDAS | M4 HAR-X | M5 HAR | M6 GAS-t |
|-------|--------|----------|----------|--------|----------|
| SPY   | 1.474 | **1.459** | 1.606 | 1.548 | 1.480 |
| QQQ   | 1.456 | 1.460 | 1.478 | 1.428 | 1.494 |
| IWM   | 1.334 | 1.332 | 1.386 | 1.344 | 1.339 |

## Verdict: MIXED

### 9-cell results (asset × model)

|        | SPY  | QQQ  | IWM  |
|--------|------|------|------|
| HAR-RV-X | **t=+4.19 p_BH=0.000** | **t=+4.22 p_BH=0.000** | t=+2.06 p_BH=0.071 |
| GARCH-MIDAS-X | t=+1.36 p_BH=0.263 | t=-0.20 p_BH=0.844 | t=+1.01 p_BH=0.402 |
| GAS-t | t=-3.27 p_BH=0.003 | t=-2.81 p_BH=0.011 | t=-0.49 p_BH=0.704 |

**Cells passing Harvey joint (t>+2 & BH adj p<0.05): 2/9**

**Asset NULL (cross-model)**: SPY→PASS (t=+4.19, p_BH=0.000) / QQQ→PASS (t=+4.22, p_BH=0.000) / IWM→**NULL** (t=+2.06 but p_BH=0.071>0.05)
**Model NULL (cross-asset)**: HAR-RV-X→PASS / GARCH-MIDAS-X→NULL / GAS-t→NULL

（v2 修正：IWM 由 PASS 改為 NULL）

### Paper 4 implication

**結論：MIXED — Universal-null claim 必須限定在特定 model family，不是所有 robust extensions。**

1. **HAR-RV-X（VIX regressor for HAR-RV family）對 large-cap equity 有顯著 marginal value**（SPY t=+4.19 p_BH=0.000, QQQ t=+4.22 p_BH=0.000；IWM t=+2.06 但 p_BH=0.071 BH 校正後 NULL）。SPY/QQQ 的結果 **推翻** K1136 的 "universal" 推論；IWM NULL 在邊界且不通過 FDR。
   - 為什麼 large-cap equity 有效、commodity 無效？VIX 本身就是 SPY option implied vol 的加權平均。VIX 對 S&P 500（及延伸至 QQQ）是 *內生*（endogenous）implied vol measure；對 commodity 和 small-cap（IWM）是 *外生* cross-market spillover measure。HAR 能 exploit 前者但無法 exploit 後者。

2. **GARCH-MIDAS-X 對 equity 和 commodity 都 NULL**（equity max t=+1.36）。MIDAS 的 long-run driver formulation 對 daily vol 沒有增益——這個 "universal null" 是穩健的。

3. **GAS-t 對 equity 是 NEGATIVE（顯著 *比 M1 差*）**：SPY t=-3.27, QQQ t=-2.81 都是顯著負向。這跟 K1129/K1134 commodity 的 NULL 一致但更 extreme——GAS-t 的 score downweight 機制對 equity（volatility-of-volatility 更劇烈）傷害特別大。E065 之前的解讀（"score downweight loses extreme info"）在 equity 上得到更強的支持。

4. **Paper 4 narrative 建議調整**：
   - ~~"Universal robust-method NULL"~~ → **"Exogenous-channel NULL: VIX regressor adds value only in HAR-RV for equity; MIDAS long-run and GAS score-driven both fail universally"**
   - 可以寫一個 new subsection: "Asset-class heterogeneity in VIX-augmented HAR-RV"
   - GAS-t 的 equity NEGATIVE result 本身就是一個重要 finding（不只是 NULL 而是 actively harmful）

### Codex / Gemini 審查摘要

- **Codex**: Quota exceeded（嘗試時 gpt-5.4 額度用完，下次可用時間 3:27 PM）。self-review 完成，確認無 HIGH severity bugs：
  - GAS-t OOS state update（f_t 遞迴）跟 K1129 逐行對齊
  - MIDAS `build_vix_monthly_lag1` 與 K1136 同樣實作（prior-month 嚴格 leakage-safe）
  - HAR regressor `.shift(1)` 明確
  - DM-HLN + BH（Benjamini-Hochberg 1995）monotone correction 正確
- **Gemini**: 未獨立審查（Gemini API 在其他任務中）

## 局限

1. **Parkinson 作 RV proxy**：非 5-min intraday RV。Parkinson 有 scale bias（假設 log-normal price）但 K1134 驗證在排名一致性上表現接近 5-min（Patton 2011 robust）。
2. **IWM HAR-RV-X 只是邊界 PASS**：t=+2.06 剛過門檻但 BH 校正後 p=0.071（未通過 0.05）。需要更多 robust checks（不同 OOS window、rolling）。
3. **VIX 本質是 S&P 500 option IV**：對 SPY/QQQ/IWM（全部 US equity）的「內生性」其實是 asset universe 特性。對日股、歐股可能不同（需要地區 VIX 如 VSTOXX、V2X）。
4. **GAS-t negative result 的解讀**：Score-driven downweight 在高 kurtosis equity regime 可能過度保守。需要 regime-conditional 分析（K1137 候選）。
5. **OOS 2021-2026 含 COVID 餘震 + 2022 bear**：在 calmer regime 可能結論不同（但相同 window 與 K1136 一致）。
6. **M3 MIDAS-X p=0.263/0.844/0.402 全部遠高於 0.05**：確實 NULL。但 simple MIDAS（prior-month mean）不如 full Beta-weighted K-lag。fu ll spec 可能改善但 EGS 2013 Table 3 顯示 simple form 已接近最佳。

## 衍生新方向

1. **K1139 候選：Full Beta-weighted MIDAS for equity**（K1138 MIDAS 只是 simple prior-month mean；若 full MIDAS 對 equity PASS 則 MIDAS 也有 asset-class heterogeneity）
2. **K1140 候選：International equity universal-null extension**（日股/歐股 + 本地 VIX 如 VSTOXX，測試 HAR-RV-X equity PASS 是否跨地區穩健）
3. **K1141 候選：GAS-t NEGATIVE 的機制分析**（為何 equity 比 commodity 傷害更大？Bootstrap 不同 score-scale 配置）
4. **Paper 4 撰寫**：以 K1136 + K1138 為核心兩章，調整 narrative 為 "channel-specific results"

## 檔案

- `k1138.py` — 實驗腳本（~700 行，self-reviewed）
- `k1138_results.json` — 3 assets × 5 models × 2 targets 完整 DM/QLIKE + 9-cell matrix + K1136 比較
- `dm_heatmap_equity.png` — 9-cell DM-HLN t heatmap
- `equity_vs_commodity_fair_tests.png` — K1136 commodity vs K1138 equity 對稱比較
- `run.log` — 完整執行日誌

## 參考

- Engle, Ghysels, Sohn (2013). Stock market volatility and macroeconomic fundamentals. *Review of Economics and Statistics* 95(3):776-797.
- Corsi (2009). A simple approximate long-memory model of realized volatility. *Journal of Financial Econometrics* 7(2):174-196.
- Creal, Koopman, Lucas (2013). Generalized autoregressive score models with applications. *Journal of Applied Econometrics* 28(5):777-795.
- Patton (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics* 160:246-256.
- Harvey, Leybourne, Newbold (1997). Testing the equality of prediction mean squared errors. *International Journal of Forecasting* 13:281-291.
- Harvey (2016). …and the cross-section of expected returns. *Review of Financial Studies* 29(1):5-68.
- Benjamini, Hochberg (1995). Controlling the false discovery rate. *Journal of the Royal Statistical Society B* 57(1):289-300.
- Parkinson (1980). The extreme value method for estimating the variance of the rate of return. *Journal of Business* 53(1):61-65.

## 關聯實驗

- K1129, K1134 (GAS-t NULL on commodity)
- K1136 (GARCH-MIDAS-X + HAR-RV-X NULL on commodity — "universal null" 假說)
- K437, K1038 (earlier GAS-t NULL on equity; K1138 現在完整補足 5 asset classes picture)
- E065 (score-downweight cost in extreme regime — K1138 equity GAS-t NEGATIVE 證據更強)

## 與動機的連結（synthesis）

Paper 4 原本計劃用 "universal robust-method NULL" 作為核心 contribution。K1138 的結果**推翻這個宣稱**但帶來更有結構的 finding：

**Robust extensions 有三種 channel**：
1. **Exogenous daily regressor on within-model** (HAR-RV-X's VIX term)
2. **Exogenous low-frequency driver** (MIDAS long-run τ_t)
3. **Score-driven robustification** (GAS-t Fisher-scaled score)

K1136 + K1138 結果顯示三個 channel 的 universality 各不相同：

| Channel | Commodity | Equity | Conclusion |
|---------|-----------|--------|-----------|
| **HAR+VIX regressor** | NULL | **PASS** (SPY/QQQ strong, BH p<0.001; IWM NULL p_BH=0.071) | Large-cap equity HETEROGENEOUS; small-cap boundary |
| **MIDAS long-run** | NULL | NULL | Universal NULL (sustained) |
| **GAS-t score** | NULL | **NEGATIVE** | Universally unhelpful; equity actively harmful |

這個重新敘事比 "universal null" 更 informative，且每條都有政策/ mechanism 解讀：
- VIX-HAR PASS 只在 equity：因為 VIX 本身就是 S&P IV，對 commodity 是 spillover
- MIDAS universally NULL：monthly frequency 的 long-run driver 對 daily vol 沒有增量 signal
- GAS-t universally unhelpful：score downweight 機制在 high-kurtosis regime 弄巧成拙

**K1138 把 Paper 4 從 "universal null" 升級為 "channel-specific universal claims"——更 rigorous、更可發表、更有 policy implication。**
