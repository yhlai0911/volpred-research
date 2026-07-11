# k621 — MF2-GARCH (Conrad & Engle, JAE 2025) 一步日頻波動率預測

- Experiment ID: `k621`
- Status: **FLAWED（模型實作有誤，係數與結論不可引用）** — 由 K623 取代
- Created At: 2026-04-15
- 最後一次重跑: 2026-07-11（K1655 DM HAC class sweep，**只換 DM 檢定，未動模型**）

## 問題描述

MF2-GARCH 把條件變異數拆成「短期 unit-mean GJR 分量 × 長期 multiplicative 分量」。
本實驗問：在 SPY 日頻一步預測上，MF2-GARCH 能否贏過 GJR-GARCH 與 EWMA(λ=0.94)？

## 方法

- 資料：SPY，2006-01-04 至 2026-03-26（yfinance）；OOS 2023-01-03 至 2024-12-31（501 obs）
- 滾動視窗 2000 日，每 21 日 refit（24 次 refit，MF2 收斂率 91.7%）
- Proxy：squared returns（r²_t）；損失：QLIKE + MSE
- 以 pre-OOS 樣本在 m ∈ {22,44,66,126,252} 中選 m（選到 m=252）

## 結論

**⚠️ 模型實作是錯的，數值不可引用。** Codex 審查抓到 3 個 HIGH bug：
(1) 短期分量應是 unit-mean 無因次 GJR（r²/τ），實作卻寫成獨立的變異數過程；
(2) 長期分量 V_m 的輸入因 bug (1) 連帶錯誤；
(3) 以 BIC 選 m 時不同 m 用了不同樣本量，比較口徑不一致。

正確規格的重做在 **K623**（`experiments/k623/`）。保留本目錄的理由是錯誤實作的存證
＋方法論教訓：統計量看起來合理，不代表模型實作正確。

## 2026-07-11 附記：DM 檢定改用 canonical HAC bandwidth

本次重跑**只改檢定、沒改模型**（模型仍是錯的），目的是量測 K1655 發現的 bug class ——
local DM 只在 `h > 1` 才做 HAC 修正，於是在本腳本用的 h=1 等於**完全不做 HAC**。
樣本與模型輸出完全未動，故新舊統計量差異可**純歸因於 HAC 修正**。

| DM 對比 | 舊 t（無 HAC） | 舊 p | 新 t（canonical） | 新 p | acf(1) |
|---|---|---|---|---|---|
| MF2 vs GJR (QLIKE) | -0.4658 | 0.6414 | -0.4057 | 0.6851 | -0.0753 |
| EWMA vs GJR (QLIKE) | 1.2917 | 0.1965 | 1.4258 | 0.1546 | -0.0454 |
| MF2 vs EWMA (QLIKE) | -1.4109 | 0.1583 | -1.5570 | 0.1201 | -0.0831 |
| **MF2 vs GJR (MSE)** | **2.2619** | **0.0237** | **3.6401** | **0.0003** | **-0.1811** |

判讀：

1. 三個 QLIKE 對比原本不顯著、修正後仍不顯著 — 方向不變。
2. **MSE 那一格是整個 class sweep 最重要的反例**：loss differential 的自相關是**負的**
   （acf(1)=-0.18、acf(2)=-0.20）。負自協方差會**縮小** HAC 標準誤，於是 |t| 由 2.26 **升到** 3.64
   （p 0.0237 → 0.0003）。這推翻了一個直覺陷阱 ——「沒做 HAC 只會高估顯著性，所以 null 結果一定安全」
   是**錯的**。遺漏 HAC 是雙向誤設：正自相關灌水 |t|，負自相關則壓低 |t|。稽核必須兩個方向都看。
3. 統計量方向未變（DM_stat 為正 = MF2 的 MSE 較差，GJR 在 MSE 上顯著勝出），且本實驗模型已知有 bug、
   無論文或 feed 文章引用此數字，故**不觸發對外結論的回溯更正**。

站點已從 `storage/ops/dm_hac_lag_baseline.json` 的 sites 移入 retired。

## 參考

- Conrad, C., & Engle, R. F. (2025). Modelling volatility cycles: the MF2-GARCH model. *Journal of Applied Econometrics*.
- 後續：K623（修正規格重做）、K1655（DM HAC lag bug class 全量掃描）
