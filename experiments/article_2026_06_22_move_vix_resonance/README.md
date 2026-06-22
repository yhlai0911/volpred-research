# article_2026_06_22_move_vix_resonance

## 目的
為 trending_repost 文章「債市和股市同時在怕，但怕的不是同一件事」計算 evidence package。

## 資料來源
- Yahoo Finance ^MOVE（ICE BofA MOVE Index）
- Yahoo Finance ^VIX（CBOE Volatility Index）
- 樣本期間：2020-01-02 至 2026-06-18，共 1,613 個交易日

## 計算內容
1. 60日滾動相關係數（日對數漲跌幅 Pearson correlation）
2. MOVE/VIX 比值（regime indicator）
3. 共振指標：兩者 252 日 z-score 同時 > 1.0 的交易日比例
4. 各歷史分段統計（2020–2026 近 90 日）

## 關鍵結果
- 最新 60 日滾動相關：0.502（歷史第 78.5 百分位）
- 近 21 日均相關：0.572（接近歷史 90th pct = 0.575）
- 2026 近 90 日均相關：0.604（為樣本中最高分段）
- MOVE/VIX 比值 3.99（歷史第 38 百分位，低於中位數 4.62）
- 共振日（雙 z>1）近 90 日：5 天（5.6%），遠低於 2022 年（34.9%）

## 文章連結
trending_repost 發佈後更新 mile_id。
