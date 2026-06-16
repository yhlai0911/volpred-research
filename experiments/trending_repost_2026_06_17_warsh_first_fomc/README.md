# trending_repost_2026_06_17_warsh_first_fomc

## Task Brief

**Task ID**: trending_repost_2026_06_17_聯準會首秀  
**Date**: 2026-06-17 (FOMC 開會日)  
**Type**: trending_repost  
**Status**: in_progress  

## 主題

Warsh 擔任新主席後首次 FOMC 會議 + 5 月 CPI 發佈後的跨資產波動率重新定價。

## 核心角度

- MOVE 指數（債市波動率）vs VIX（股市波動率）的跨資產關係
- SOFR / Fed Funds rate path 在 CPI 4.2% 後的 implied 走向
- 跨資產 vol 重新定價機制：債市波動率領先/落後股市的 episode
- 利率 vol 上升對股票風險溢酬的隱含意義

## 數據來源

- VIX / VIX9D: yfinance `^VIX`, `^VIX9D`
- MOVE: yfinance `^MOVE`
- FRED: `DFEDTARU` (Fed Funds upper), `T10Y2Y` (殖利率曲線斜率), `CPIAUCSL`
- 時間範圍：近 90 日（2026-03 起）

## 產出

- `fetch_data.py`: 抓數據
- `analyze.py`: 分析 + 圖表
- `results.json`: 量化結果
- `figs/*.png`: 真實圖表
- `article.md`: 文章草稿
- `fb_draft.md`: FB 草稿
