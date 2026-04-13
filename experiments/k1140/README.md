# K1140: HAC Newey-West rolling θ_EAV trend re-test (K1114 follow-up)

[提出: Claude 承接 K1114 preamble self-doubt, 執行: Claude]

## 1. 計劃與問題描述

K1114 以 window=500, step=21 的 rolling design 估計 τ_t=max(θ₀+θ₁VIX²+θ₂EAV,ε) 三檔台積電/聯電/聯發科的時變 θ₂，並在 9 個 tests (3 tests × 3 stocks) 中 BH-FDR PASS 了 3 個：

- UMC structural trend (t=3.06, BH-adj p=0.012)
- MediaTek structural trend (t=4.67, BH-adj p=7.1e-5)
- TSMC regime KS split (p=0.009, BH-adj p=0.028)

但 K1114 README 的自我質疑段明確標記 caveat：相鄰 rolling θ 共享 479/500 ≈ 96% observations → **OLS-SE 嚴重低估，t-stat 嚴重高估**。有效獨立樣本數 ≈ T/(window/step) = T/24 ≈ 5-6，而非 124-132。

**研究問題**：K1114 的 3 個 PASS 在合理的 HAC-robust SE 下是否仍存？

## 2. 動機

Paper 2 在 cross-sectional firm-attribute 路線已經完全 NULL（K1109 sector ANOVA FAIL、K1113 firm covariate FAIL）。K1114 給 Paper 2 留了「temporal heterogeneity 新 angle」的可能退路，但這條退路的可信度完全取決於 HAC 後 signal 是否仍存。

- HAC PASS 仍在 → Paper 2 narrative 可以 pivot 到「θ_EAV 結構性時變」
- HAC 全部 collapse → Paper 2 cross-sectional + temporal 都 NULL，只能承認真正 exhausted

## 3. 方法

完全 reuse K1114 的 `per_stock_results[*]['theta2_series']`（128/132/124 個 rolling θ₂），不重跑 GARCH fitting（省成本、無 lookahead 風險）。

### 三層檢定設計

**Layer 1：Newey-West HAC SE for OLS trend**，三個 lag 設定：

| L | 依據 |
|---|------|
| 5 | Naive Newey-West 經驗式 `floor(4·(T/100)^(2/9))` ≈ 5。**這裡太小**，只為對照 |
| **24** | **Conservative：覆蓋 1 個 window 的 overlap週期 (500/21 ≈ 23.8)** |
| 48 | Very conservative：覆蓋 2 個 overlap 週期 |

**Layer 2：Block-permutation Spearman ρ (block=24, n_perm=5000)**，取代 standard Spearman asymptotic p。

**Layer 3：KS regime split with effective-n deflation**。KS 統計量本身是 distribution-level，相對 robust，但 p-value 原本假設 n 個獨立觀察值。我們把 effective n 除以 24 重新計算 Kolmogorov 分配的 p 值。

### 額外：Block-bootstrap trend slope

Newey-West HAC 假設 Bartlett-kernel 幾何衰減。如果 θ 序列有結構性曲度（不只是 AR(1) noise），HAC 會**仍然低估 SE**。因此加做 block-bootstrap：把 θ 分成 block_size=24 的 blocks，shuffle blocks 後重新 regress，直接由 null distribution 得到 p-value。這是最嚴格的 layer。

### 統計門檻

- Harvey (2016) |t| > 3.0 for t-based tests
- BH-FDR 對 9 p-values 做 multiplicity correction
- 通過 = BH-adj p < 0.05

### Lookahead 紀律

- 全部用 K1114 已產出 θ 序列（retrospective analysis，純 in-sample 描述，沒有策略回測、無 lookahead 風險）
- Seed 42

## 4. 結果

### θ 序列 lag-1 自相關 (confirms K1114 caveat)

| Stock | lag1 ACF | 推論 |
|-------|----------|------|
| TSMC | 0.308 | 中度自相關 |
| UMC | 0.366 | 中度自相關 |
| MediaTek | 0.469 | 高自相關 → HAC 校正最必要 |

Positive ACF 確認 OLS-SE 低估是真實問題，不是臆測。

### Layer 1：HAC Newey-West 三個 L 的 trend t-stat

| Stock | OLS t (K1114) | HAC L=5 | HAC **L=24** | HAC L=48 | 結論 |
|-------|---------------|---------|--------------|----------|------|
| TSMC | 1.75 (p=0.083) | 0.84 (p=0.40) | **0.76 (p=0.45)** | 0.88 (p=0.38) | NS 在所有 L |
| UMC | 3.06 (p=0.003) | 2.17 (p=0.030) | **2.45 (p=0.014)** | 3.32 (p=9e-4) | 不穩定：L=24 降到 t=2.45，L=48 回升 |
| MediaTek | 4.51 (p=2e-5) | 3.85 (p=1e-4) | **4.33 (p=2e-5)** | 5.39 (p=7e-8) | 最頑強：t 永遠 > 3.8 |

Note: K1114 README 的 MediaTek OLS t=4.67 來自不同的 slope convention；我們重跑得 4.51 一致。

### Layer 2+3 + BH-FDR @ L=24（核心判決）

9 個 p-values：HAC L=24 trend × 3 + block-perm Spearman × 3 + KS effective-n × 3。

| Test × Stock | raw p | BH-adj p | Verdict |
|--------------|-------|----------|---------|
| TSMC:trend (HAC L=24) | 0.450 | 0.877 | NS |
| TSMC:spearman_block | 0.487 | 0.877 | NS |
| TSMC:regime_effn | 0.999 | 1.000 | NS |
| UMC:trend (HAC L=24) | 0.014 | 0.065 | NS (marginal) |
| UMC:spearman_block | 0.243 | 0.729 | NS |
| UMC:regime_effn | 1.000 | 1.000 | NS |
| **MediaTek:trend (HAC L=24)** | **1.5e-5** | **1.4e-4** | **PASS** |
| MediaTek:spearman_block | 0.855 | 1.000 | NS |
| MediaTek:regime_effn | 1.000 | 1.000 | NS |

**1/9 BH-PASS survives HAC L=24 (MediaTek trend)**。K1114 的 3 個 PASS 中：

- TSMC regime KS (原 K1114 p=0.009) → effective-n 校正後 **p≈1.0**，完全由重疊觀察膨脹而來
- UMC trend → HAC L=24 BH-adj p=0.065，**卡在 BH 門檻外**
- MediaTek trend → 仍 **PASS**

### Layer strictest：Block-bootstrap trend (Preamble Rule #5 自我質疑)

MediaTek HAC t=4.33 仍 > 4，preamble 要求自我質疑。HAC 之所以不夠嚴格的原因：Newey-West Bartlett kernel 在 lag L 處截斷，但 θ 的結構性曲度會讓 SE 被持續低估。

改用 block-bootstrap 直接模擬 null：

| Stock | OLS t | HAC L=24 t | **Block-boot t** | Block-boot p | BH-adj p |
|-------|-------|------------|------------------|--------------|----------|
| TSMC | 1.75 | 0.76 | 0.80 | 0.488 | 0.878 |
| UMC | 3.06 | 2.45 | 1.91 | 0.021 | 0.191 |
| MediaTek | 4.51 | 4.33 | **1.75** | 0.061 | 0.273 |

**MediaTek 的 t-stat 從 4.33 崩潰到 1.75**——因為 block-bootstrap 保留 θ 序列整體的幅度與自相關結構，trend slope 的 null distribution 變寬了近 2.5 倍。這證實 Newey-West L=24 對 MediaTek 仍不夠嚴格：MediaTek 的 θ 序列有結構性曲度（lag1 ACF=0.47，最高），HAC geometric-decay 假設被違背。

**最終 0/9 BH-FDR PASS**。K1114 的 3 個 PASS 在嚴格 HAC 下 **全部 collapse**。

## 5. 結論

### K1114 結論校正

K1114 的 3/9 BH-PASS 是 **96% overlap + Newey-West 未校正的聯合 artifact**。

- **TSMC regime KS**：distribution-level 差異被獨立樣本假設膨脹 ~24 倍，effective-n 後 p 從 0.009 → 1.0
- **UMC trend**：從 t=3.06 → HAC L=24 t=2.45 → block-boot t=1.91，**系統性衰退**
- **MediaTek trend**：從 t=4.51 → HAC L=24 t=4.33 → block-boot t=1.75，**需要最嚴格的 layer 才看得出來**

K1114 三檔公司 θ₂ **mean pattern** 本身（TSMC ≈ 0, UMC > 0, MediaTek < 0）仍真實（因為是 point estimate，不涉及 SE），但「時間趨勢」、「VIX regime 切換」、「Spearman 相關」**都沒有**統計顯著性。

### 對 Paper 2 的意義

**Paper 2 narrative：真正的 cross-sectional + temporal 雙 NULL**。

Claude 建議的 pivot 路徑（K1114 自我質疑段預留的「θ 結構性收斂」angle）**不可用**。Paper 2 必須承認：

1. **Cross-sectional NULL**（K1109/K1113）：firm attributes 無法預測 θ_EAV 方向
2. **Temporal NULL**（K1114/K1140）：θ_EAV 在 same stock 內也沒有 robust 時間趨勢或 regime 切換
3. **K1067 三檔 pattern 是 sampling/window artifact**：mean θ₂ 由不同時期的估計 aggregation 造成，不是 stable trait 也不是 structural drift

這是乾淨的 negative result。Paper 2 的 contribution 可以定位為：

> "A4f-EAV model's heterogeneity claim (K1067 pattern) is a within-sample window artifact. After rigorous cross-sectional (N=31 sector ANOVA, 5 firm covariates) and temporal (rolling window HAC, block-bootstrap) controls, no systematic source of θ_EAV heterogeneity survives multiple-testing correction. Earnings-announcement variance effects are either (1) genuinely universal in magnitude across semiconductor stocks, or (2) too noisy at the stock level to be cross-sectionally or temporally detectable."

### Preamble Rule #5 自我質疑 (post-hoc)

MediaTek 的 HAC t=4.33 在 L=24 仍然 > 4，我按 preamble 要求自我質疑 → block-bootstrap 才揭示真實 SE 被 HAC 低估。這提醒一個通用教訓：**在高 overlap 場景，Newey-West HAC 是改善 OLS 的第一步，但不是充分條件；block-bootstrap 才是 gold standard**。

可能的其他解釋：
- MediaTek 真的有結構性 drift，但在 effectively n≈6 下無法被嚴格檢定拒絕 H0。**這等同於 NULL**——即使訊號可能真實存在，數據不足以排除 noise 解釋。
- θ 序列端點 sensitivity：start 2014-02、end 2025-12。若把 window 往後移或換資料切分，MediaTek trend 可能消失。未在本實驗驗證。

### 衍生 next_tasks (K1141+)

| K ID | 主題 | 優先度 |
|------|------|--------|
| K1141 | **Paper 2 正式改寫為雙 NULL narrative**（依 K1140 結論更新 manuscript） | 最優先 |
| K1142 | （保留）N=10 台股擴展 block-bootstrap trend — 如果還要做為 robustness，用 K1141 最終論文 revision 時的補充材料 | 低，視 reviewer 要求 |
| K1143 | A4f-EAV 改為 **pooled panel estimation**（不分股）— 若能在 pooled 上找到 θ_EAV ≠ 0，可作為 Paper 2 的 positive side-finding | 中等 |

**K1142 (N=10 擴展) 在 K1140 結論下已無必要**——K1114 的三檔 PASS 全部崩潰，擴展到 10 檔只會放大 null pattern，不會改變結論。除非有 reviewer 明確要求擴展 robustness，否則優先投入 K1141 論文改寫。

## 6. 檔案

- `k1140.py` — 實驗腳本
- `k1140_results.json` — 完整結果（HAC 三個 L × 3 stocks + block-bootstrap trend + block-perm Spearman + KS effective-n + 4 個 BH-FDR tables）
- `k1140_hac_vs_ols_tstat.png` — OLS / HAC L=5/24/48 t-stat 比較
- `k1140_L_sensitivity.png` — HAC SE、t-stat vs lag L ∈ [1, 60] 的敏感度曲線
- `k1140_theta_series_diagnostic.png` — 三檔 θ 時間序列視覺診斷 + OLS trend line
- `run.log` — 執行 log

## 7. 參考文獻

- Newey, W. K., & West, K. D. (1987). A Simple, Positive Semi-definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix. *Econometrica*, 55(3), 703-708.
- Politis, D. N., & Romano, J. P. (1994). The Stationary Bootstrap. *JASA*, 89(428), 1303-1313.
- Benjamini, Y., & Hochberg, Y. (1995). Controlling the False Discovery Rate. *JRSS B*, 57(1), 289-300.
- Harvey, C. R., Liu, Y., & Zhu, H. (2016). … and the Cross-Section of Expected Returns. *RFS*, 29(1), 5-68.
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *J. Econometrics*, 160(1), 246-256.

## 8. 相關 K 編號

- K1067 / K1067b / K1067c — TSMC/UMC/MediaTek A4f-EAV single-window results
- K1109 — Sector ANOVA pre-registered FAIL
- K1113 — Firm covariate FAIL
- K1114 — Rolling θ_EAV time-varying heterogeneity (本實驗直接承接)
