# k865 — Volatility Spillover Network (Diebold-Yilmaz), 2026 Tariff Crisis Update

- Experiment ID: `k865`
- Created: 2026-04-16
- **Status: CORRECTED 2026-07-11 — 原版所有 FEVD 衍生結論皆為 artifact，已撤回。**
- Script: `k865_vol_spillover_network.py` | Results: `k865_results.json`
- 舊（錯誤）結果保留供稽核：`k865_results_SUPERSEDED_fevd_bug.json`

## ⚠️ 2026-07-11 更正紀錄（先讀這段）

原版 `fit_var_fevd()` 用 `fevd.decomp[-1]` 取溢出矩陣，程式註解誤寫 `decomp` 形狀為
`(horizon, n, n)`。**statsmodels 的實際形狀是 `(n, horizon, n)`**（axis 0 = 被分解的變數，
axis 1 = horizon 步，axis 2 = 衝擊來源；本次以 statsmodels 0.14.6 實測驗證，且
`decomp.sum(axis=2) ≡ 1`）。因此 `decomp[-1]` 取到的是**最後一個資產（BTC）的
`(horizon, n)` 表**，下游把前 n 列當成 n×n 矩陣讀 —— **horizon 步被當成資產**。

正解：`fevd.decomp[:, -1, :]`（最後一個 horizon 的 n×n 矩陣）。

**作廢的數字**：TSI、from/to/net spillover、top transmitters/receivers、`spillover_matrix`、
rolling TSI、`crisis_comparison`、`connectivity_change`、`traditional_asset_network`、
`spy_role_change` —— 舊 results 內這些欄位**全部不可引用**。

**未受影響**：Granger 因果檢定（不經 FEVD；新舊完全相同）、RV 描述統計、RV 相關係數矩陣、
`tariff_impact` 報酬與 RV 比值（純描述統計）。

機械 gate：`scripts/tests/test_fevd_shape.py`（唯一 enforcement owner）。
根因與教訓：`docs/error_log.md` 2026-07-11 entry。

## 問題描述

1. 波動率溢出網路在 2026 關稅危機期間是否變得更連動？
2. 2026 年誰是最大的波動傳送者、誰是接收者？
3. 網路結構能否預示關稅賣壓的嚴重程度？

## 方法

- Diebold & Yilmaz (2012, IJF 28(1)) 溢出框架
- 7 資產日資料（SPY, QQQ, GLD, TLT, EEM, CL=F, BTC-USD），yfinance，2020-01-24 ~ 2026-04-04，2,240 obs
- 22 日滾動已實現波動率 → 各資產 z-score 標準化（避免 BTC 波動水平主導 VAR）
- VAR(5) → 正交化（Cholesky）FEVD，h = 10 → 取 `decomp[:, -1, :]` 的 n×n 表，列標準化到 100
- TSI = off-diagonal / total × 100；rolling 63 日視窗（step=5）
- 配套：pairwise Granger causality（maxlag 5）、去掉 BTC 的 robustness、RV 相關矩陣
- 無隨機程序（VAR / FEVD / Granger 皆為決定性估計），故無 seed 需求

## 結果（2026-07-11 修正後）

### TSI（全 7 資產）— 新 vs 舊

| 視窗 | n_obs | TSI 舊（錯） | TSI 新（正確） | 最大傳染源 舊 → 新 |
|---|---|---|---|---|
| COVID 危機 2020-01~06 | 136 | 90.89 | **61.18** | BTC (+265.8) → **SPY (+107.4)** |
| 後 COVID 2020-07~2021-12 | 549 | 90.52 | **26.70** | BTC (+536.3) → **SPY (+124.5)** |
| 升息 2022-01~2023-06 | 546 | 89.90 | **33.11** | BTC (+502.8) → **SPY (+127.7)** |
| 平靜 2024-01~2026-02 | 790 | 90.55 | **32.77** | BTC (+519.5) → **SPY (+182.7)** |
| 關稅（廣窗）2025-10~2026-04 | 186 | 90.89 | **39.61** | BTC (+380.4) → **SPY (+103.8)** |

Granger 顯著對數（p<0.05，未受 bug 影響）：31 / 10 / 14 / 18 / 14（42 對中）。

### 結論翻轉

1. **「TSI 在所有 regime 都黏在 ~90%、連動性是結構性的」→ 撤回。** 修正後 TSI 落在 26.7%–61.2%，
   且**明顯隨 regime 變動**：COVID（61.2%）遠高於平靜期（32.8%），關稅期（39.6%）高於平靜期。
   舊版「90% 且不動」正是誤切的數學必然（對角線不再是自身變異，質量全落 off-diagonal）。
2. **「BTC 是所有期間最大的波動傳送者」→ 撤回。** BTC 修正後在 COVID（−21.3）、平靜（−16.4）、
   關稅（−44.9）期都是**淨接收者**。舊版 +536 的淨值本身就不可能（淨佔比不可能超過 ~100×n）。
3. **「SPY 平常是接收者、關稅時罕見翻成傳染源」→ 撤回（這是原文章的核心賣點）。**
   修正後 **SPY 在全部五個視窗都是淨傳染源**（+103.8 ~ +182.7），沒有任何角色翻轉。
4. **「整體連動性在關稅期沒有顯著上升」→ 維持（方向不變）。** rolling TSI 兩樣本檢定
   t = 0.302（舊 0.924）、p = 0.382，仍未達 Harvey |t| > 3.0；且 tariff_n = 7，本來就沒有檢定力。
5. **修正後結果與前作一致**：K7（SPY 為 hub）、K356（SPY/TLT 輸出波動）。舊版「BTC 主導」與前作
   矛盾 —— 這個矛盾當時被寫成新發現，而不是被當成 bug 訊號。

### 淨溢出（修正後，7 資產）

| 視窗 | 淨傳送者 | 淨接收者 |
|---|---|---|
| COVID | SPY +107.4, TLT +24.1, GLD +20.7 | QQQ −65.9, OIL −38.5, EEM −26.5, BTC −21.3 |
| 平靜 2024-25 | SPY +182.7, GLD +2.5 | QQQ −92.2, EEM −59.9, BTC −16.4, OIL −9.3, TLT −7.5 |
| 關稅（廣窗） | SPY +103.8, GLD +24.5, EEM +13.7 | QQQ −62.8, BTC −44.9, OIL −22.7, TLT −11.6 |

去掉 BTC 的 robustness 結論相同（SPY 為最大傳送者：+110.2 / +172.3 / +91.4）。

### 未受影響的發現（仍可引用）

- 關稅期不對稱衝擊：OIL RV 2.83×、EEM 2.05×、GLD 1.85×，SPY 僅 1.03×（相對 2024-25 平靜期）
- 關稅期報酬：OIL +66.4%、GLD −11.2%、EEM −9.6%、SPY −4.1%
- COVID 有 31/42 條 Granger 連結，關稅期只有 14/42 —— 關稅衝擊比 COVID 局部得多
- RV 平均 off-diagonal 相關：平靜 0.377 → 關稅廣窗 0.487

## 已知限制

- **Cholesky 正交化 FEVD 有排序相依性**（本次未改）。Diebold-Yilmaz (2012) 用的是 **generalized**
  FEVD（排序不變）。本實驗沿用 statsmodels 的正交化版本，資產排序 SPY→QQQ→GLD→TLT→EEM→OIL→BTC
  會影響溢出方向的歸屬。**這是 shape 修正之外、尚未處理的第二個方法論缺口** —— SPY 排第一，
  在 Cholesky 下天生較容易被估成傳送者。把「SPY 是 hub」寫成強宣稱之前，必須先改 GFEVD 重跑。
- rolling 63 日視窗仍套 VAR(5) × 7 變數（每方程 36 參數 / 63 obs）→ 嚴重過度參數化，rolling TSI
  水平（~74%）明顯高於全窗估計；**只能看相對變化，水平值不可引用**。
- 資料到 2026-04-04，未涵蓋 4/3 之後的行情。
- 單一事件觀察，非統計推論。

## 參考

- Diebold & Yilmaz (2012) "Better to Give than to Receive", IJF 28(1), 57-66
- K7（溢出 Granger 網路）、K356（波動因果有向圖）、K422（商品波動溢出）、K628b（溢出；取法正確）
