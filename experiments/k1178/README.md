# K1178: Paper 3 Table 5 — 13-Market International Replication (CANONICAL)

## 動機

Paper 3 reproducibility audit (commit 0fa27397) 的 BLOCKER D5：  
- K901 用了錯誤的 13 市場組合（含 EWH, EWY；缺 EWC, VGK, INDA, MCHI）
- Paper Table 5 宣稱 avg ΔMDD=28.7pp, t=15.70, r=−0.770 (VIX sens vs ΔMDD), ρ=0.830 (GJR γ vs ΔSharpe)
- 這些數字無法從 K901 重現
- K1178 使用 paper 精確的 13 markets，建立 canonical 復現實驗

## 13 Markets (Paper 精確清單)

| Region | Ticker | Name |
|---|---|---|
| Developed | EFA | MSCI EAFE |
| Developed | EWJ | MSCI Japan |
| Developed | EWG | MSCI Germany |
| Developed | EWU | MSCI UK |
| Developed | EWA | MSCI Australia |
| Developed | EWC | MSCI Canada |
| Developed | VGK | Vanguard Europe |
| Emerging | EEM | MSCI EM (Broad) |
| Emerging | FXI | China Large-Cap |
| Emerging | EWZ | MSCI Brazil |
| Emerging | INDA | iShares MSCI India |
| Emerging | EWT | MSCI Taiwan |
| Emerging | MCHI | MSCI China (Broad) |

## Strategy

- VT: w_t = min(12/VIX_{t-1}, 1.0) × Equity + (1-w) × SHY
- Signal: `signal.shift(1)` — NO lookahead, VIX from t-1 determines weight on t
- Sample: January 2007 – March 2026 (paper Table 5 specification)
- Data: yfinance, `auto_adjust=True` (total return / dividend-adjusted) for all equity ETFs
- VIX: unadjusted Close
- Seed: 42

## Key Findings

### 成功復現 (Matched)

| Metric | K1178 | Paper | Status |
|---|---|---|---|
| BH MDD (all 13) | <1% rtol vs paper | — | MATCHED (13/13) |
| VIX sensitivity (all 13) | <0.3% rtol | — | MATCHED (13/13) |
| 13/13 markets ΔMDD > 0 | YES | YES | MATCHED |
| Pearson r (VIX sens vs ΔMDD) | −0.806 (p=0.0009) | −0.770 (p=0.002) | MATCHED (rtol=4.7%) |
| DM avg ΔMDD | 30.7 pp | 32.0 pp | NEAR MATCH (rtol=4%) |

### 未完全復現 (Diverged)

| Metric | K1178 | Paper | rtol | Notes |
|---|---|---|---|---|
| avg ΔMDD | 24.90 pp | 28.7 pp | 13.2% | Driven by EM markets |
| t-stat | 10.25 | 15.70 | 34.7% | Still highly significant |
| Spearman ρ (VIX vs ΔMDD) | −0.835 | −0.720 | 16.0% | Actually stronger! |
| GJR γ vs ΔSharpe ρ | +0.187 (NS) | +0.830 | 77.5% | NOT reproducible |
| EM avg ΔMDD | 18.2 pp | 24.7 pp | 26.3% | EEM/FXI/EWZ material gap |

## Root Cause Analysis

1. **資料來源 (CRITICAL)**：Paper 使用 adjusted close (total return / dividend reinvested)。
   - 用 `auto_adjust=True` 後，BH MDD 13/13 完全吻合（rtol<1%），確認資料源
   - K901 及初版 K1178 使用 `auto_adjust=False`，造成 Sharpe 和 ΔMDD 系統性偏差

2. **RF rate**：Paper 的 VT Sharpe 數字暗示較低的 effective RF（~1-2%），而非我們用的 4%。
   - 此差異不影響 MDD 計算（MDD 是純報酬路徑，與 RF 無關）

3. **EM 市場 VT MDD 殘差差異**：EEM/FXI/EWZ/MCHI 的 VT MDD 仍有 28-56% rtol 差異。
   - 可能原因：daily VIX 訊號的 SHY 報酬在 2022 年利率上升期間 SHY 大跌，拖累 VT 績效
   - Paper 可能使用了不同的現金代理（零報酬現金），或 monthly rebalancing 的不同實作

4. **ρ=0.830 (GJR γ vs ΔSharpe) 無法復現**：
   - 此相關係數可能是用 Table 1 的 N=22 資產 γ 值與 Table 5 的 ΔSharpe 混搭計算
   - 或原始稿件的計算錯誤，需要論文作者澄清

## 建議 (b)/(c)

### 建議 (b): 修改論文數字

K1178 使用 paper 精確的 13 markets 和 auto_adjust=True 總報酬資料。核心主張（VIX sensitivity 預測 ΔMDD，13/13 改善）已確認且實際上更強（r=−0.806 > paper −0.770）。

建議更新：
- avg ΔMDD: 28.7pp → **24.9pp** (仍顯著且具經濟意義)
- t-stat: 15.70 → **10.25** (p<0.001，仍高度顯著)
- Pearson r: −0.770 → **−0.806** (更強，更新有利)
- ρ(VIX vs ΔMDD): −0.720 → **−0.835** (更強)
- **移除或澄清** ρ=0.830 (GJR γ vs ΔSharpe)——此數字無法復現

### 建議 (c): 標記 Errata Pending

若無法確定 paper 原始計算流程（如 monthly rebalancing 細節），建議在 paper revision 中：
- 標記 Table 5 的 avg ΔMDD, t-stat, ρ 為 "revised" 值
- 加注腳說明此更新

## 檔案清單

| 檔案 | 說明 |
|---|---|
| `k1178.py` | 主要實驗腳本（auto_adjust=True, signal.shift(1)） |
| `k1178_results.json` | 完整結果（13 markets × VT/BH + cross-section） |
| `k1178_vs_paper3_table5_diff.md` | 詳細差異分析報告 |
| `run.log` | 執行日誌 |

## 資料來源

- yfinance, auto_adjust=True，2007-01-01 to 2026-03-31
- INDA available from 2012-02-06; MCHI available from 2011-04-01
- VIX: ^VIX via yfinance (unadjusted)
- Cash proxy: SHY (iShares 1-3 Year Treasury Bond ETF)

## 實驗正直宣告

- 無 lookahead bias: `signal.shift(1)` 在所有市場一致執行
- 未手調 seed 或硬 coded 數字去 match paper
- 未修改 paper/vt-trend-following/main.tex 或 K901 結果 JSON
- Paper 數字差異如實報告，不掩蓋

## 相關 K 編號

- K901: 原始 13-market VT 實驗（錯誤 asset set）
- K898: SPY dual mechanism decomposition
- K1178: 本實驗（canonical 復現）
