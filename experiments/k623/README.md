# k623 — MF2-GARCH（修正版）vs GJR vs EWMA，SPY

- Experiment ID: `k623`
- Status: cautiously positive（**未達 Harvey 門檻，且有 2 個未解 HIGH bug** — 見〈保留條款〉）
- Created At: 2026-04-16
- 最近一次重跑: 2026-07-11（K1655 DM HAC class sweep，只換 DM 推論，模型與樣本未動）

## 問題描述

Conrad & Engle (2025, JAE 40(4), 438–454) 的 MF2-GARCH 把條件變異數拆成短期分量 g_t（unit-mean GJR，吃 r²/τ）與長期乘法分量 τ_t。K621 首次實作被 Codex 抓到 3 個 HIGH bug（短期分量寫成獨立變異數過程、V_t 分母錯、BIC 跨 m 用不同樣本量），結果不可信。K623 是修正這 3 個 bug 後的重做，問 SPY 上 MF2-GARCH 是否真的贏得過 GJR。

## 方法

| 項目 | 設定 |
| --- | --- |
| 資產 / 資料源 | SPY / yfinance |
| 全樣本 | 2006-01-01 ~ 2026-03-27（窗口釘死） |
| OOS | 2023-01-01 ~ 2024-12-31（502 obs） |
| 估計窗 | rolling w=2000，每 21 日 refit |
| 波動率代理 | 平方報酬 r² |
| MF2 參數 | 6 個：α, γ, β, λ₁, λ₂, λ₃（無 ω — unit-mean 約束） |
| 最適 m | 66（BIC，全 m 統一 burn-in 252） |
| 對照組 | GJR-GARCH、EWMA |

已修正的 K621 三個 bug 記在 `k623_results.json:bugs_fixed`。

## 結果

OOS 損失（502 obs）：

| 模型 | QLIKE | MSE |
| --- | --- | --- |
| **MF2 (m=66)** | **1.5030** | 1.1329 |
| GJR | 1.5303 | 1.1522 |
| EWMA | 1.5623 | **1.1213** |

Diebold-Mariano（**2026-07-11 起用 canonical `volpred.stats.model_evaluation.dm_test`**）：

| 配對 | QLIKE t | p | MSE t | p |
| --- | --- | --- | --- | --- |
| MF2 vs GJR | **-2.30** | **0.0218** | -2.19 | 0.0288 |
| MF2 vs EWMA | -2.41 | 0.0161 | +0.29 | 0.7725 |
| GJR vs EWMA | -1.43 | 0.1546 | +0.79 | 0.4317 |

負 t = 前者較優。MF2 在 QLIKE 上顯著優於 GJR 與 EWMA；但在 MSE 上最佳模型其實是 EWMA，且 MF2 贏不過它（p=0.77）。**MF2 的優勢是 QLIKE-specific，不是全損失函數通用。**

### 2026-07-11 DM 推論更正（K1655 class sweep）

原始 K623 的 DM 用實驗內自寫的 local helper，其 Newey-West 頻寬是 `range(1, h)` —— **h=1 時等於完全不做 HAC**。改用 canonical `dm_test`（頻寬 floor 為 1）後：

| 宣稱 | 舊（退化 DM，無 HAC） | 新（canonical HAC） |
| --- | --- | --- |
| MF2 vs GJR, QLIKE | t=-2.03, p=0.042 | **t=-2.30, p=0.0218** |

**點估計完全沒動**（QLIKE 1.5030 vs 1.5303，樣本窗口釘死於 END=2026-03-27），所以新舊差異可**純歸因於 HAC 修正**，不像 k507 混雜了樣本延長。

方向與 k621 同族一致：MF2/GJR 的 QLIKE loss differential 自相關為**負**（acf(1..5) = -0.049, -0.037, -0.041, -0.030, +0.011），負自協方差**縮小** HAC 標準誤 → |t| 反而**變大**、p 值變小。這再次證實 class-sweep 的核心教訓：**遺漏 HAC 是雙向誤設，不是單向灌水**（k621 的 MSE t 是 2.26 → 3.64）。

**結論方向未被推翻，反而略微增強** —— 但這不解除下列保留條款，宣稱強度不得升級。

## 保留條款（未解，結論強度不可超過證據）

1. **未達 Harvey 門檻**：t=-2.30 < 3.0。本專案對 forecast 比較採 Harvey (2016) 的 t>3 標準，故這仍是 *cautiously positive*，不是 confirmed。
2. **收斂率僅 25%**（6/24 refits）。四分之三的 refit 沒收斂，參數估計可信度存疑。
3. **unit-mean 未真正實現**：g 的跨 refit 平均 = **1.367**（理論應為 1.0），τ 平均 = 0.995。這是 K621 Codex 二審指出的 τ 約束數學錯誤（λ₂+λ₃<1 是錯的條件，正確為 E[τ]=(λ₁+λ₂)/(1-λ₃)）的殘留症狀，尚未修。
4. MF2 與 GJR 的預測相關性高達 **0.986** —— 兩者預測幾乎同向，QLIKE 1.8% 的差距經濟意義有限。

以上 2/3 項需要 K625 第三次修正才能解除；DM 推論更正**不改變**這些 caveat。

## 檔案

- `k623_mf2_garch_corrected.py` — 實驗腳本（2026-07-11 改用 canonical `dm_test`；輸出路徑改為 script-dir 相對）
- `k623_results.json` — 結果（2026-07-11 重跑）
- `data/`, `references/`

## 參考

- Conrad, C. & Engle, R. F. (2025). Modelling volatility cycles: the MF2-GARCH model. *Journal of Applied Econometrics*, 40(4), 438–454.
- Harvey, C. R. (2016). Editorial: The Scientific Outlook in Financial Economics. *Journal of Finance*.
- Class sweep 脈絡：`docs/governance/2026-07/dm_hac_lag_class_sweep.md`
