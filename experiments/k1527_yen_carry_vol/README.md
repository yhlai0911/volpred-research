# K1527: 日圓 Carry Trade 倉位擁擠度與 VIX 不對稱定價分析

**實驗類型**: trending_repost evidence package（非正式量化實驗）
**日期**: 2026-06-17
**作者**: trending_repost subagent hourly-12

## 研究問題

2026年6月 CFTC 日圓淨空倉達9年新高（-145,800 contracts），超過2024年8月 carry trade 大解倉前的水位。當前 VIX 只有18，與2024年7月的14接近。這個組合是否代表 VIX 低估了尾部風險？

## 數據來源

- USDJPY（JPY=X）：yfinance daily close 2024-01-01 to 2026-06-16
- VIX（^VIX）：yfinance daily close 2024-01-01 to 2026-06-16
- CFTC 倉位數據：Bloomberg 2026-06-14 / Japan Times 2026-06-15 報導
- 2024年 carry trade unwind 統計：J.P. Morgan、Wellington Management 事後報告

## 關鍵數字

| 時期 | VIX 均值 | USD/JPY 均值 | 備注 |
|------|----------|-------------|------|
| 2024年7月（unwind前） | 14.4 | 158.3 | 空倉高但 VIX 低 |
| 2024年8月5日（unwind peak） | 33.1（收盤）| 145.7 | JPY 週內升值 +7.1 |
| 2024年12月（恢復後） | 15.9 | 153.7 | 正常化 |
| 2026年6月（現在） | 18.0 | 160.1 | 空倉更極端，VIX 更低 |

## 圖表

- `vix_usdjpy_2024_2026.png`：2024-2026 VIX 與 USDJPY 走勢
- `unwind_event_window_2024.png`：2024年8月事件窗口放大

## 結論

數據顯示2026年6月的 carry trade 倉位擁擠度超過2024年8月前的水位，但 VIX 並未反映等量的尾部風險溢價。這是 trending_repost 文章的核心主張的 evidence base，非正式量化分析。

