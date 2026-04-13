# K1109 — Pre-registered random sector sample (CONFIRMATORY)

> **TL;DR**: K1106b 的「fabless p=0.004 ***」**沒有**被獨立 confirm。擴大樣本 + 預先登錄之後，ANOVA joint test **FAIL**（p=0.297），fabless coefficient 從 -2.29e-3 縮小到 -1.24e-3（衰減 46%），BH 校正後 **失去顯著性**（p=0.278）。Cherry-pick bias 在此得到清楚的量化證據。

---

## 1. 動機（Why）

K1106b 用 hypothesis-driven 抽樣測「sector heterogeneity of θ₂」，結果：
- N=14 across 7 sectors
- ANOVA F(6,5)=6.87, **p=0.0258**
- fabless β=-2.289e-3, t=-5.16, **p=0.0036 ***

但 E052 發現 K1106b 在 fabless 只挑 MediaTek + Realtek（K1067c 已知負），**沒納入** K1104 中 θ₂>0 的 Novatek (+7.02e-4) 和 Phison。這是 post-hoc 選樣 → 再跑一次 regression 必然得到「顯著」結果，但它只是把已知事實 re-estimate，**不是新證據**。

E052 的結論：「**小樣本分類實驗絕對要 random sample within each category。**」

K1109 的任務：用 pre-registration 的 random sampling 真正檢驗 sector heterogeneity。

---

## 2. Pre-registration（在跑任何估計之前鎖定）

**Pre-reg 時間戳記**：2026-04-13T[UTC]（見 `prereg_sample.json` 的 `pre_registration_timestamp_utc`）

**Git commit**：在 Stage 1 MLE 執行前已單獨 commit `prereg_sample.json`（commit `4c59a41a`）。此 commit hash 可證明樣本清單確實是在看結果前決定。

**樣本設計規則（完整記錄於 `prereg_sample.json`）**：

| Sector | Pool size | Target N | Drawn | Exhausted? |
|---|---|---|---|---|
| foundry | 3 | 3 | 3 | ✓ |
| fabless | 6 | 6 | 6 | ✓ |
| financials | 5 | 5 | 5 | ✓ |
| shipping | 3 | 3 | 3 | ✓ |
| trad_mfg | 5 | 5 | 5 | ✓ |
| ems | 3 | 3 | 3 | ✓ |
| consumer | 6 | 5 | 5 |  |
| tech_other | 2 | 3 | 2 | ✓（pool<target） |
| **Total** | 33 | 33 | **32** | |

Seed：`numpy.random.default_rng(42)`。Consumer 類是唯一實際有隨機性的抽樣（pool 6 → draw 5）；其他類 pool 等於或小於 target，全部納入。

**預先鎖定的假設**：
- **H1 (joint)**: ANOVA F-test p<0.05 **且** BH-FDR 後至少一個 sector dummy 存活
- **H2 (fabless<foundry)**: fabless 係數 p<0.05 **且** β<0
- **H3 (shipping=0)**: shipping 的 bootstrap 95% CI 跨越 0（null result confirm）

**任務中的 pool 定義已保留**，包括：
- tech_other 仍放 2888/2892（實為金控），Stage 3 另做 robustness 排除
- Consumer pool typo（重複的 2330/2881）已依「重複清除」規則處理

---

## 3. 方法（What）

### Stage 1：Per-firm A4f-EAV MLE

完全沿用 K1106b 的 `fit_a4f_eav()` function（4 個初值、L-BFGS-B、Hessian-based SE），不修改任何估計邏輯——這確保 heterogeneity 結論的差異**完全來自樣本差異**，不是模型差異。

共用 cache：把 K1104/K1106b 的 `data/*.parquet` 複製過來，僅新 tickers（6239、3443、2388、2883、2887、2609、1326、2027、3045、2637、1215、2347、1210、2888、2892 共 15 個）需要新下載。

### Stage 2：Firm covariates

- `log_mktcap`（yfinance `Ticker.info`）
- `beta_rolling_0050`（rolling 252-day regression against 0050.TW）
- `earnings_freq_per_year`（新增，K1106b 沒做）

### Stage 3：Confirmatory regression

1. 主迴歸：`θ₂ ~ sector_dummies + log_mktcap_z + beta_rolling_z + earn_freq_z`
2. Reduced：只保留 covariates
3. **ANOVA F-test** joint：所有 sector dummy 同時為 0 嗎？
4. **BH-FDR 校正** 每個 sector dummy 的個別 p-value
5. **Bootstrap 95% CI**（5000 reps，seed 固定）per-sector mean θ₂，firm-level resample
6. **Cross-validation**：列出 K1104 ∩ K1106b ∩ K1109 重複 firm 的 θ₂，檢查估計穩定性

---

## 4. 結果（Findings）

### 4.1 Stage 1：MLE 完成數

31 / 32（2888 Shin Kong FH yfinance 下載失敗；2892 First FH 納入）。

### 4.2 Stage 3：Confirmatory verdict

| Hypothesis | Rule | K1109 result | Verdict |
|---|---|---|---|
| **H1 joint** | ANOVA p<0.05 AND BH survives | F(7,20)=1.31, **p=0.297**; no BH < 0.05 | **FAIL** |
| **H2 fabless<foundry** | p<0.05 AND β<0 | β=-1.24e-3, t=-2.20, **p=0.040** (raw); BH p=0.278 | **PASS raw / FAIL BH** |
| **H3 shipping=0** | 95% CI crosses 0 | CI=[-3.6e-5, +2.5e-4] | **PASS** |

### 4.3 Cherry-pick bias 的量化

| | K1106b (cherry-pick) | K1109 (pre-reg random) | Change |
|---|---|---|---|
| N | 14 | 31 | +121% |
| Fabless β | **-2.289e-3** | **-1.235e-3** | **-46% magnitude** |
| Fabless t-stat | -5.16 | -2.20 | attenuated 57% |
| Fabless p (raw) | 0.0036 | 0.040 | 11x larger |
| Fabless BH-adj p | n/a | 0.278 | not significant |
| ANOVA F | 6.87 (p=0.026) | 1.31 (p=0.297) | collapsed |

**這是 textbook 的 "regression to null" under cherry-pick correction。** K1106b 的 fabless 顯著性是把 6 檔 fabless 中的 2 檔負 sample（MediaTek、Realtek）當全樣本。K1109 納入其他 4 檔（含 K1104 中正的 Novatek +7.02e-4、Phison 等）後，sector mean 從「純負」變成「平均負但散布大」，coefficient 與 significance 都大幅縮水。

### 4.4 Sector-level 結果（bootstrap 95% CI）

| Sector | n | mean θ₂ | Boot 95% CI | Sign consistent? |
|---|---|---|---|---|
| ems | 3 | +4.97e-4 | [+2.2e-5, +7.4e-4] | Positive（CI >0）|
| consumer | 5 | +2.71e-4 | [+4.3e-5, +5.1e-4] | Positive（CI >0）|
| foundry | 3 | +1.11e-4 | [-1.6e-4, +4.3e-4] | Mixed |
| shipping | 3 | +8.8e-5 | [-3.6e-5, +2.5e-4] | Mixed（H3 confirmed）|
| trad_mfg | 5 | +3.7e-5 | [+3.1e-7, +9.5e-5] | Marginal positive |
| financials | 5 | +2.3e-5 | [-5.5e-6, +5.0e-5] | Marginal positive |
| **fabless** | **6** | **-3.8e-4** | **[-1.4e-3, +5.7e-4]** | **Mixed（CI crosses 0）** |
| tech_other | 1 | -1.2e-5 | n/a | Single firm |

**關鍵對比**：K1106b 的「fabless 顯著負」在 K1109 的 bootstrap CI 是 **[-1.4e-3, +5.7e-4]**，CI 跨越 0！個別 t-test p=0.04 可能只是 family-wise error 的產物（7 個 sector dummies 一起跑，BH 校正後就消失）。

### 4.5 Cross-validation（shared firms 17 家）

同一 firm 在 K1104/K1106b/K1109 的 θ₂ **完全一致**。這不意外——三個實驗用同一份 K1106b 的 `fit_a4f_eav()` + 同樣的 full-sample 資料，parquet 共用。意思是「樣本差異 → regression 差異」這個推理是有效的：同一 firm 的 θ₂ 不變，變的是哪些 firms 進 sample。

---

## 5. 結論（Conclusion）

1. **Sector heterogeneity of θ₂ 在嚴謹的 pre-registered test 下 NOT confirmed**。
2. **K1106b 的 fabless p=0.004 *** 是 cherry-pick artifact**。Effect size 縮水 46%，BH 校正後失去顯著性。
3. **可重複的 descriptive pattern**（不算 confirmatory 結論）：
   - EMS 與 consumer sectors mean θ₂ 一致為正（bootstrap CI 不跨 0）。
   - Fabless sector 內部**極度異質**：MediaTek/Realtek 大負，Novatek/FarEastone Info 大正。
   - Financials/trad_mfg 整體接近 0（和 K1106b 結論一致的部分）。
4. **Fabless 的 coefficient 雖然 raw p=0.04，但 BH-FDR 後不 survive。** Harvey (2016) t>3.0 門檻也不達（|t|=2.20）。

---

## 6. 新的 Paper 2 firm-selection rules（REVISED）

**基於 K1109 confirmatory 結果，取代 K1106b 的 tentative rules：**

### 6.1 不以 sector 作為 selection primary key

Sector 的解釋力不足 joint test（ANOVA p=0.30），不能做 Paper 2 的「以 sector 分桶套不同 EAV weight」。

### 6.2 改以 firm-level θ₂ sign 分桶

K1109 直接給出可重複的 firm-level θ₂ 排序。Paper 2 的建議框架：
- **Tier A（θ₂>0 且 t>1.96）**：應用 A4f-EAV（例：Quanta, Hon Hai, Yang Ming, Pres. Chain, 2330, Novatek）
- **Tier B（|t|<1.96）**：fallback 用 A2f（無 EAV term）或 pooled τ
- **Tier C（θ₂<0 且 t<-1.96）**：考慮反向 EAV 或 exclude（例：MediaTek, Realtek）

### 6.3 用 covariates 輔助而非 sector dummies

Regression 中 **log_mktcap_z（t=-2.19, p=0.040）** 和 **beta_rolling_z（t=+1.97, p=0.063）** 的 t-stat 跟 fabless dummy 一樣大，但它們是連續變量、不受 sector 劃分主觀性影響。Paper 2 可以用這兩個 covariate 建 firm-level allocation rule：
- 高 beta × 低 marketCap → 傾向 θ₂<0（但仍需 firm-level estimate 確認）

### 6.4 避免 N<30 就做 sector ANOVA

K1106b 6 dof / 5 dof denominator 的 F 本就 underpowered。K1109 用 N=31 / 7 sectors 也只有 20 denom dof，仍偏小。真正 confirm sector-level claim 需 **N≥50**，每 sector ≥7 firms。這目前超出 task 範圍。

---

## 7. 局限（Limitations）

1. **N=31 仍偏小**：每 sector 3-6 firms。任務表規範的 ideal sample 應該 N≥40/sector≥7。
2. **Pool 幾乎全 exhausted**：只有 consumer 類實際有 random sampling（6→5），其他類 pool 大小直接等於 target，實質上「random sampling」退化為「把 pool 全納入」。但這本身仍然優於 K1106b 的 hypothesis-driven 挑選——pool 的定義本身是 pre-registered 的。
3. **Tech_other 樣本無意義**：n=1（2888 下載失敗），且任務指定的 2888/2892 業種分類有問題。
4. **Full-sample MLE**：θ₂ 是 2010-2025 的一次估計。rolling 估計可能給出不同結論（time-varying heterogeneity 沒測）。
5. **未考慮 survivorship**：32 檔都是 2025 還在上市的大型股。2010 就下市的中小型股未納入。
6. **tau_at_event 的診斷 label 有 1 日錯位**（Codex LOW-level flag，繼承自 K1106b）。不影響 θ₂ regression 主結論。
7. **Consumer 與 EMS 正 θ₂ 可能 spurious**：n=3-5 依然小，bootstrap CI 的 lower bound 只勉強 >0。這些應該視為「待 confirm」而非「已 confirm」。

---

## 8. 衍生方向（3 個，寫回 research_program.md）

1. **D1（N≥50 真 confirmatory sector test）**：納入中型股、退市股、跨市場（港股科技業）擴大樣本。目標 power > 0.8 at α=0.05，effect size 要求 0.15σ。
2. **D2（Firm-level covariate rule，跳過 sector）**：用 K1109 的 31 檔做 `θ₂ ~ log_mktcap + beta + earnings_freq + ind_momentum + float_ratio`，找非 sector 的 predictors。
3. **D3（Rolling θ₂）**：check 哪些 firms 的 θ₂ 在 2010-2015 vs 2016-2025 穩定、哪些反轉。time-varying heterogeneity 可能是 Paper 2 的真正 contribution。

---

## 9. 檔案清單

| 檔案 | 用途 |
|---|---|
| `build_prereg.py` | 生成 pre-reg 樣本（隨機抽樣邏輯） |
| `prereg_sample.json` | **鎖定**的樣本清單（含 timestamp、commit hash） |
| `k1109.py` | 主實驗：MLE + covariates + regression + bootstrap |
| `k1109_results.json` | 完整結果（含所有 firm-level + regression + verdict） |
| `regression_results.json` | Regression-only view（for downstream analysis） |
| `firm_level_results.csv` | 31 firms × (θ₂, t, covariates, sector) |
| `k1109_sector_theta2_forest_plot.png` | Forest plot with bootstrap 95% CI |
| `k1109_vs_k1106b_comparison.png` | Cherry-pick bias quantification |
| `data/*.parquet` | yfinance cache（inherited from K1104/K1106b + 15 new downloads） |

---

## 10. 參考文獻

- Engle, Ghysels, & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. *RES* 95(3).
- Patton (2011). Volatility forecast comparison using imperfect volatility proxies. *J. Econometrics* 160.
- Benjamini & Hochberg (1995). Controlling the False Discovery Rate. *JRSS B* 57(1).
- Harvey (2016). *J Fin Econ* — multiple testing in finance.
- K1067 / K1067b / K1067c / K1103 / K1104 / K1106b — EAV family.

---

*提出: 賴奕豪 · 執行: Claude · 2026-04-13 · Pre-registered & committed BEFORE estimation.*
