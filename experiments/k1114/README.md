# K1114: Rolling θ_EAV time-varying heterogeneity for A4f-EAV

[提出: Claude 承接 K1113 STRONG NULL, 執行: Claude]

## 1. 計劃與問題描述
Paper 2 走到 cross-sectional firm-attribute 路線全 NULL：
- K1109 pre-registered N=31 sector ANOVA FAIL（min BH-adj p=0.854）
- K1113 5 個 firm covariates 全 FAIL（max BH-adj p=0.854）
- K1067b/c：UMC θ₂>0 極顯著 / MediaTek θ₂ REVERSE — heterogeneity 真實但無法用 firm attributes 解釋

改變 dimension：不問「哪些公司 θ_EAV>0」，改問「θ_EAV 在同一家公司是否 time-varying？」。
若 YES → Paper 2 可由 "cross-sectional exhaustion" 轉為 "temporal heterogeneity 新 angle"。
若 NULL → Paper 2 真正 exhausted 所有 dimension。

## 2. 動機
1. K1067 三公司 θ₂ pattern（TSMC 0 / UMC +0.39 / MediaTek -負）可能不是 stable firm-level trait，而是
   **window-dependent signal**，只是各家剛好被估在不同時期。
2. Earnings surprise 的資訊內容會隨時間變化：
   - 結構性：analyst coverage 成熟 → earnings pre-annouced → θ 逐年衰退
   - 循環性：calm period 市場聚焦 earnings surprise；crisis period macro drowns out

## 3. 方法
### 模型規格（同 K1067b/c）
```
τ_t = max(θ₀ + θ₁·VIX²_{t-1} + θ₂·EAV_{t-1}, ε)
u_t = r_t / √τ_t
g_t = ω_g + α·u²_{t-1} + γ·u²_{t-1}·I(u<0) + β·g_{t-1}
σ²_t = τ_t · g_t
```

### Rolling 設計
- **Window**: 500 obs（≈ 2 trading years，符合 Hwang & Valls Pereira 2006 n≥500 要求）
- **Step**: 21 obs（≈ 1 month）→ ~115 overlapping windows per stock
- **Period**: 2012-01-01 ~ 2025-12-31（warmup + 2014-2025 rolling 期間，涵蓋 2015 中國股災、2018 貿易戰、2020 COVID、2022 熊市）
- **Stocks**: TSMC（2330.TW）、UMC（2303.TW）、MediaTek（2454.TW）

### 三個 tests（per stock）
| Test | Hypothesis | 統計量 |
|------|-----------|--------|
| 1. Structural trend | θ₂(t) 有時間趨勢 | OLS slope t-stat |
| 2. Cyclical (VIX) | θ₂(t) 與 VIX 相關 | Spearman ρ + t |
| 3. Regime split | θ₂ low-VIX vs high-VIX 分配不同 | Two-sample KS test |

### 統計門檻
- Harvey (2016) |t| > 3.0 for t-based tests
- BH-FDR 調整 3 stocks × 3 tests = **9 p-values**
- 通過 = BH-adj p < 0.05 AND |t|>3.0 (非 KS)

### Lookahead 紀律
- EAV 用 t 當日（post-close announcement 已觀察）
- τ 建立用 VIX_{t-1}、EAV_{t-1}
- VIX percentile 用 **ex-ante trailing**（嚴格只用過去資料），避免 E064 IS-regime degeneracy
- Seed 42（bootstrap 未用但固定 RNG）

## 4. 資料
- **股價**: yfinance 2330.TW / 2303.TW / 2454.TW，auto_adjust=True
- **VIX**: yfinance ^VIX Close，forward-filled 到台股交易日
- **財報公告日**: `財報公告日.txt`（Big5 編碼）

## 5. 預期
如果 Paper 2 exhaustion 真的只是 cross-sectional 表象：
- 至少 1 個 test 在 3 檔中平均過 BH-FDR
- UMC 在早期（2014-2018）θ₂>0 顯著，晚期收斂 → structural trend PASS
- 三檔都在 low-VIX 期間 θ₂ 較高 → regime PASS

如果 Paper 2 真正 exhausted：
- 9 個 test 全部 BH-adj p > 0.05
- θ₂ 呈現 pure noise / random walk pattern

## 6. 結論

**實驗時間**：481 秒（約 8 分鐘）
**有效 rolling fits**：TSMC 128/138、UMC 132/138、MediaTek 124/138

### 六項 θ₂ 分布描述
| Stock | mean θ₂ | pos fraction | K1067 對應 |
|-------|---------|--------------|------------|
| TSMC | -2.62e-4 | 52.3% | NULL（一致） |
| UMC | +8.08e-4 | 85.6% | K1067b +0.39 strong PASS（一致）|
| MediaTek | -1.09e-3 | 39.5% | K1067c REVERSE（一致）|

Rolling 結果**完全重現** K1067 三家公司對比 pattern，方法論校驗通過。

### 三個 tests × 三檔 BH-FDR
| Test × Stock | raw p | BH-adj p | t/stat | verdict |
|---|---|---|---|---|
| TSMC trend | 0.072 | 0.130 | 1.81 | NS |
| TSMC Spearman VIX | 0.577 | 0.577 | 0.56 | NS |
| **TSMC regime KS** | **0.009** | **0.028** | - | **PASS** |
| **UMC trend** | **0.003** | **0.012** | **3.06** | **PASS (Harvey)** |
| UMC Spearman VIX | 0.196 | 0.294 | 1.30 | NS |
| UMC regime KS | 0.375 | 0.421 | - | NS |
| **MediaTek trend** | **7.9e-6** | **7.1e-5** | **4.67** | **PASS (Harvey)** |
| MediaTek Spearman VIX | 0.033 | 0.074 | -2.16 | NS |
| MediaTek regime KS | 0.279 | 0.359 | - | NS |

**3/9 tests PASS BH-FDR**：
- **UMC structural trend（+）** — θ₂ 穩定在正值且隨時間**上升**（slope +4.2e-7/day）
- **MediaTek structural trend（+）** — θ₂ 從深度負值往中性靠近（slope +9.5e-7/day；REVERSE pattern **在削弱**）
- **TSMC regime split** — θ₂ 在 low-VIX 期間（mean +1.4e-4）大於 high-VIX 期間（mean +6.2e-5），symmetric KS distribution-level difference

### ⚠️ 自我質疑（Preamble Rule #5）

MediaTek t=4.67 超過 Harvey 3.5 threshold且不是原先預期，必須自我質疑：

1. **Mechanical / HAC trap**（最大疑慮）：rolling windows step=21、window=500 → 相鄰 θ₂ 估計共享 479/500=96% 觀察值，**高度自相關**。OLS t-stat 假設獨立會**嚴重高估**顯著性。有效獨立樣本數可能只有 ~5-6（2900 天 / 500 天 window），而非 124-132。
2. **Lookahead**：τ_{t} 使用 VIX_{t-1}、EAV_{t-1}，估計只用 window 內資料，regime split 用 ex-ante trailing percentile。無 lookahead。
3. **Overfit**：每個 window 7 params on 500 obs → ratio 71:1，相對保守。但 bounds 可能讓 optimizer 收斂到 local optima。
4. **結果強度超過證據**？MediaTek REVERSE「在削弱」和 UMC「在加強」是可信的 directional story，但 Harvey t>3 不能被字面相信，因為 HAC 未校正。

**保守解讀**：3 個 PASS signals 是 **suggestive**（建議性），不是 conclusive。Paper 2 可以在 limitations 段寫「若 HAC-robust SE 後仍顯著，則 temporal heterogeneity 是真訊號」，但必須**先做 HAC 版本再宣稱**。

### 對 Paper 2 的意義

Paper 2 cross-sectional exhaustion 結論**依然成立**（K1109/K1113 firm-attribute 路線無效），但**溫和翻轉**：
- θ_EAV **不是 time-invariant firm trait**——至少 UMC/MediaTek 結構性變動存在
- 新 angle 可能：「θ_EAV 收斂」假設——當市場成熟化（analyst coverage、公告提前洩漏），所有公司的 θ_EAV 會向 0 收斂
- **必要前置**：K1115 應先做 HAC-robust 重檢驗（Newey-West SE for trend test）

### 衍生 next_tasks（K1115+）
| K ID | 主題 |
|------|------|
| **K1119** | HAC-robust rolling θ trend（K1114 三個 PASS 的 Newey-West SE 重檢）— 最優先 |
| K1120 | Block bootstrap θ₂ 分布驗證（非 overlap-dependent） |
| K1121 | 擴展到 N=10 台股 checking 「θ 收斂」假設（有無 cross-firm trend 一致性） |
| K1122 | Paper 2 大修 — 若 K1119 HAC 仍 PASS，Paper 2 主題從「firm cross-sectional heterogeneity exhausted」轉為「θ 結構性收斂」 |

（注：K1115-K1118 已被佔用；本實驗 derived 方向從 K1119 起算）


## 7. 檔案
- `k1114.py` — 實驗腳本
- `k1114_results.json` — 每檔 rolling θ₂ 序列 + 3 tests 統計量 + BH-FDR table
- `k1114_rolling_theta.png` — 3 檔 θ₂ 時間序列
- `k1114_vix_scatter.png` — θ₂ vs VIX scatter
- `k1114_regime_boxplot.png` — low/high VIX regime 分配 boxplot
- `run.log` — 執行 log

## 8. 參考文獻
- Engle, Ghysels, Sohn (2013). GARCH-MIDAS. RES 95(3):776-797.
- Patton (2011). Volatility forecast comparison.
- Harvey et al. (2016). DM t > 3.0 threshold.
- Hwang & Valls Pereira (2006). GARCH window ≥ 500.
- Benjamini & Hochberg (1995). FDR.

## 9. 相關 K 編號
- K1067 TSMC A4f-EAV NULL
- K1067b UMC A4f-EAV θ₂>0 PASS
- K1067c MediaTek A4f-EAV REVERSE
- K1109 sector ANOVA FAIL
- K1113 firm covariate FAIL
