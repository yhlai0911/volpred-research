# event_article_fomc_2026_06_17_t1_dotplot

**類型**: event_article / trending_repost  
**日期**: 2026-06-16 (FOMC T-1)  
**mile_id**: mile_53caca1a  
**狀態**: published

## 研究問題

Fed 6/17 FOMC 前一天，MOVE 指數落在全歷史第 34 百分位，低於過去六場 FOMC 前夕均值 72.1。點陣圖委員分散度今年最高，但利率選擇權定價偏低。這個結構性落差值得量化記錄。

## 核心發現

- **MOVE T-1 今日**: 69.38（全歷史 P34，低於 6 場 FOMC T-1 均值 72.1）
- **VIX**: 17.68（6/12）；**VIX9D**: 15.58（6/15）
- **TLT 30日 RV**: 9.5%（年化）；**IRX**: 3.618%
- 過去六場 FOMC T+5 SPY 均值: -0.96%，正報酬僅 2/6（33%）
- MOVE/VIX 背離：股市警覺性高於債市，結構不對稱

## 檔案

| 檔案 | 說明 |
|---|---|
| `fetch_data.py` | yfinance 數據抓取，結果存 results.json |
| `make_figure.py` | 兩張圖：1y MOVE+VIX 走勢 / 過去 6 FOMC T-1 對照 |
| `results.json` | 所有量化數字 |
| `body.md` | 發布文章 Markdown |
| `fb_draft.md` | Ivan Lai FB 貼文草稿（awaiting_interactive_session）|
| `figs/fig1_move_vix_1y.png` | MOVE+VIX 1年雙軸圖 |
| `figs/fig2_fomc_t1_comparison.png` | 過去 6 FOMC T-1 MOVE/VIX + SPY 5日報酬 |
| `raw_close.csv` | yfinance 原始收盤價，2003-2026 |

## 方法論

純描述性統計，無預測模型、無 signal、無 backtest。
資料來源：yfinance（^MOVE, ^VIX, ^VIX9D, TLT, SHV, ^IRX, SPY）。
FOMC 日期：Fed 官方公告日歷，2025-09 至 2026-04 六場。
