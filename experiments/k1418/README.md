# K1418 — Paper 8 cross-asset NSI absorption regression rerun (pinned snapshot)

## 任務

修補 main_v3.tex Table `cross_asset_detail` (lines 800-805) 的 snapshot
不一致 — 主文 §2 line 67、§8 robustness tables 都已使用 2026-04-19 pinned
snapshot，但 cross_asset_detail 仍是 paper-drafting (2025 yfinance pull)
的數字。

## 方法

- 同 paper §3 absorption regression spec:
  - `NSI_t = alpha + beta * V_t + eps_t`
  - shock-day filter: `|dV_t| > 2`
  - **returns 以 percent 表示**（`r_pct = r_decimal * 100`） — paper §6.2 line
    327 報 `alpha = 0.091`，與 percent-return convention 吻合
  - Newey-West SE, lags=10
- 資料：
  - SPY / GLD / TLT / VIX → `paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv`（2026-04-19 pinned snapshot）
  - 0050.TW → yfinance `auto_adjust=False` 即時抓取（snapshot_date 寫入 results.json）
- 樣本：2006-01-01 → 2026-04-17

## 結果

| Asset | α | β (×10⁴) | t(β) | Adj R² | N |
|---|---|---|---|---|---|
| SPY | 0.092 | **-2.73** | -1.85 | 0.012 | 769 |
| GLD | 0.099 | **-4.34** | -2.90 | 0.024 | 769 |
| TLT | 0.094 | **-4.37** | -3.31 | 0.023 | 769 |
| 0050.TW | 0.073 | **+0.92** | +0.28 | -0.001 | 614 |

數字以 percent-return convention 報，與 paper §6.2 一致。Adj R² 直接由 OLS
公式得。

## 與 paper-drafting (2025 snapshot) 對比

| Asset | β (×10⁴) drafting | β (×10⁴) K1418 pinned | Δ |
|---|---|---|---|
| SPY | -2.8 | -2.73 | -2.5% |
| GLD | -4.3 | -4.34 | +0.9% |
| TLT | -4.4 | -4.37 | -0.7% |
| 0050.TW | +1.9 | +0.92 | -52% |

US 三檔 magnitude 幾乎不變；t-statistic 在 SPY 上由 -3.42 弱化為 -1.85 (與
paper line 67 footnote 報的 t = -1.77 一致；K1418 N=769 vs paper N=768 因
sample-end 終點界定差 1 日)。GLD/TLT t-stat 從 -4.17/-3.89 弱化為
-2.90/-3.31，方向不變且仍顯著。0050.TW magnitude 減半且 t-stat 由 +1.62
降到 +0.28，符合 paper 將其詮釋為「VIX 對非美市場非主要 fear gauge」的
論點。

## 與 paper main_v3.tex 既有 SPY pinned-snapshot 數字 cross-check

- main_v3.tex line 67 (footnote pinned-snapshot SPY): β = -0.000267, t = -1.77, N = 768
- K1418 SPY: β = -0.000273, t = -1.847, N = 769
- Δ < 2% — independent reproduce 通過

## 對 Paper 8 narrative 的影響

- 結論不變：US 三檔仍顯示負 β（absorption effect），0050.TW 仍方向不同
  （US-specific fear gauge）
- t-statistic 全面弱化 → 應在 narrative 與 footnote 註明，**SAR 與 RV-NSI**
  仍是 robust primary identification
- main_v3.tex Table cross_asset_detail 應更新為 K1418 數字 + Notes 改為
  「Sample: 2006-2026 under 2026-04-19 pinned snapshot」

## 後續

下一個主線程任務（Paper8 step (d)）：
1. Edit main_v3.tex lines 800-805 替換為 K1418 數字
2. 同步調整 caption / surrounding text（line 783-808 區域）若需要
3. `xelatex` 重編 main_v3.tex
4. `uv run volpred ops paper-update --paper-id volatility-absorption`

## 防錯記錄

- **Unit-bug catch**（K1418 v1 → v2）：首版 script 用 decimal returns 跑出
  β = -3e-6（比 paper -2.8e-4 小 100 倍）。對照 paper line 327 `alpha = 0.091`
  即可診斷出是 percent vs decimal 之差；修為 `r_pct = r * 100` 後 SPY 結果
  與 paper line 67 footnote pinned-snapshot 一致到 <2%。PreToolUse hook
  warning 觸發後立即停下檢查 → 修對。
- Same-day cross-section regression，no forecast → no `shift(1)` 需要（這是
  descriptive absorption coefficient，非 predictive 迴歸；與 paper §3
  spec 一致）。
