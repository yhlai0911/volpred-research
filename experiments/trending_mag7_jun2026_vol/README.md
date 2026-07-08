# 2026 年 6 月科技七巨頭回檔期間的波動率行為

Trending repost 的 evidence package（VolPred 角度：已實現波動率 + VIX + 橫斷面離散度）。

## 資料來源

- **yfinance** 日資料（`auto_adjust=True`，close-to-close）
- 期間：`2026-01-01` ~ `2026-07-09`（重點 5–7 月）
- 標的：QQQ + Mag7（AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA）+ `^VIX` + `^VVIX`
- 交易日數：見 `results.json` `meta.n_trading_days`
- 所有標的皆抓到（VVIX 亦成功，無 missing）

## 方法

- **已實現波動率（realized vol）**：每檔對自己序列 `dropna()` 後取日對數報酬，`rolling(20).std() × sqrt(252)`，換算成年化百分比。
  - 先 dropna 是為避免多 ticker union index 的 NaN gap 汙染 rolling window（NaN 落在 20 日窗內會讓整段 rolling std 變 NaN，早期版本因此讓 6 月 rv 全 NaN，已修）。
- **Peak-to-trough**：每檔在指定期間找高點，再找高點之後的最低點，算跌幅。逐檔各自算（單一名稱層級）。
- **Regime 三段切點**：以 Mag7 共識定義壓力段 —— peak `2026-06-01`、trough `2026-06-25`。理由：多數 Mag7 個股在 6 月初見高、6/25 見低；QQQ 指數本身較早在 6/10 見低（-7%）後陷入震盪，但個股回檔更深且集中 6/25 觸底。
  - `before_peak`：peak 前約 20 交易日
  - `during_selloff`：peak → trough
  - `after_trough`：trough → 今日

## 無 lookahead / 無隨機

- 純描述統計，無交易訊號、無回測，故無 `signal.shift(1)` 需求。
- Rolling RV 只用截至當日的過去報酬；peak-to-trough 只用實際歷史收盤價。
- 無任何隨機程序，故無 seed 需求。

## 主要結果（真實數字，見 results.json）

- **6 月個股 peak-to-trough**：MSFT -23.4%（最深）、AMZN -13.1%、META -13.4%、NVDA -14.2%、AAPL -12.7%、TSLA -11.5%、GOOGL -10.3%；**QQQ 指數僅 -7.0%**（06-02 → 06-10 觸底）。
- **三段年化 RV（QQQ）**：回檔前 16.0% → 壓力段 25.2% → 觸底後 33.1%。RV 在價格觸底「之後」才見高峰（20 日 rolling 的滯後特性）。
- **VIX**：回檔前約 16 → 6/10 見高 22.22 → 6/25（個股觸底日）已回落至 18.89 → 最新（07-08）16.9。YTD 區間 14.49–31.05。
- **VVIX**：回檔前約 91.6 → 壓力段高點 108.16 → 最新 91.38。
- **橫斷面離散度（壓力段 RV 排序）**：TSLA 47.0 > NVDA 44.8 > META 38.3 > MSFT 36.9 > AMZN 29.9 > GOOGL 29.6 > AAPL 22.6。最高最低價差 24.5 個百分點，跨名稱標準差 8.78。

## 產出檔案

- `trending_mag7_jun2026_vol.py`：分析腳本
- `trending_mag7_jun2026_vol_results.json`：全部數字
- `fig1_qqq_drawdown.png`：QQQ 2026 走勢與 6 月回檔標註
- `fig2_rv_vs_vix.png`：QQQ 已實現波動率 vs VIX（回檔區間灰底）
- `fig3_mag7_cross_section.png`：Mag7 壓力段 RV 排序 bar
