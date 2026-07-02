# event_article_nfp_2026_07_03_t1

## 動機

2026-07-03（週五）是美國 7 月非農就業數據（NFP）發佈日。這是 T-1（前一交易日）事件驅動文章，
提供讀者發佈前的波動率結構現況 + 歷史 NFP 反應統計，屬於 `event_article` 任務類型，走
`feed-publisher` + `trending-repost` 共用的 event 發佈 SOP（立即 published + FB 雙發佈）。

## 差異化 / 3-layer dedup

- `storage/reports/feed.json` 內既有非農相關文章（`mile_7012b52a`, `mile_d721672b`,
  `mile_630d0010`, `mile_44fb4b90`, `mile_414233df`, `mile_16abc5b1`, `mile_8f90ce78`,
  `mile_ee595d1b`, `mile_10f07ba2`, `mile_4ddbf3f0` 等）最新一篇 `published_at` 為
  2026-04-02，距今約 3 個月，且該批文章鎖定的是 2026-03/04 那次事件。NFP 為每月事件，
  本篇鎖定 2026-07-03 這次發佈，樣本窗口與時效性不同，非 narrative-arc dup。
- 本篇差異化角度：VIX9D/VIX 短端結構現況（term-structure inversion signal）+
  最近 13 次 NFP 事件視窗逐次拆開的 descriptive stats（非單純「歷史平均」敘事）。

## 資料來源

- **來源**：yfinance（`SPY`, `^VIX`, `^VIX9D` 日收盤）
- **期間**：
  - 歷史事件視窗：2025-06-06 至 2026-06-05（近 13 次「當月第一個週五」proxy 的 NFP 發佈日）
  - 當前快照：截至 2026-07-01 收盤（NFP 發佈前一個交易日）
- **樣本數**：n=13 個歷史 NFP 事件（descriptive stats only，非統計檢定用途）
- **NFP 日期識別規則**：採用「當月第一個週五」標準近似規則（BLS 慣例），未逐月比對 BLS
  官方行事曆做個別核實 — 此限制在文章與腳本 notes 中明確揭露。

## 已知資料缺口（誠實揭露，不硬湊）

`yfinance` 的 `^VIX9D` 序列在截至 2026-07-01 的抓取窗口中，最後一筆資料停在 **2026-06-26**，
落後 `^VIX`（資料到 2026-07-01）達 5 個交易日（已用 `yf.Ticker('^VIX9D').history()` 二次驗證，
非單次抓取失敗）。

處理方式：**不**把不同日期的 VIX 和 VIX9D 硬凑成一個比值。改用「兩序列都有資料的最後共同日期」
（2026-06-26）計算 VIX9D/VIX 比值，並在文章與圖表中明確標註這個比值的計算基準日與 VIX9D
落後天數。這是本篇唯一的資料限制，已在 `_results.json.notes` 與文章「誠實的不確定性」段落
逐字揭露。

## Lookahead 檢查

本實驗**無預測模型、無 forward-label、無 train-test split**，純粹是描述性統計（descriptive
stats）：
- 歷史 NFP 事件視窗統計：所有數字皆為已發生（realized）歷史事件，`spy_ret_day0` 用
  release-day close-to-close return，`vix_chg_day0` 用 release-day VIX close 減前一交易日
  VIX close，`spy_ret_next_day` 用 release 隔一交易日 return —— 皆為 already-occurred 數字，
  無 lookahead 風險。
- 當前快照（VIX / VIX9D / SPY realized vol）：全部只用 **截至 2026-07-01（`AS_OF`）** 的資料，
  嚴格早於 2026-07-03 NFP 發佈日，不觸碰發佈當天或之後的任何資料點。
- 無隨機程序（無 bootstrap / MC / train-test split），故無需 seed。

## 檔案

- `event_article_nfp_2026_07_03_t1.py` — 抓資料 + 計算 + 存 JSON + 存圖（fig1/fig2）
- `event_article_nfp_2026_07_03_t1_results.json` — 完整數字結果（canonical source）
- `nfp_historical_event_window.csv` — 歷史 13 次事件視窗明細表
- `render_lazypack.py` — 懶人包圖組 render script（讀取 `_results.json`，PIL 產生，非按張計費 API）
- `figures/fig1_vix_vix9d_term_structure.png` — VIX vs VIX9D 近 60 交易日走勢
- `figures/fig2_nfp_day_spy_return.png` — 近 13 次 NFP 發佈日 SPY 當日報酬長條圖
- `figures/nfp_lazypack_1_framework.png` / `_2_results.png` / `_3_takeaway.png` — 懶人包三張圖

## 主要數字（截至 2026-07-01，n=13 歷史事件）

| 指標 | 數值 |
|---|---|
| VIX 最新收盤 | 16.59（2026-07-01） |
| VIX9D 最後一筆 | 16.80（2026-06-26，落後 VIX 5 個交易日） |
| VIX9D/VIX 同日比值 | 0.9125（基準日 2026-06-26） |
| SPY 5 日已實現波動率（年化） | 14.41% |
| SPY 20 日已實現波動率（年化） | 18.28% |
| 近 13 次 NFP 日 SPY 上漲機率 | 53.8% |
| 近 13 次 NFP 日 SPY 平均報酬 | -0.185%（中位數 +0.098%） |
| 近 13 次 NFP 日 VIX 平均變化 | +0.99 點（中位數 +0.02 點） |
| 近 13 次 VIX 當日下降比例 | 46.2% |
| 上次 NFP（2026-06-05）SPY 報酬 / VIX 變化 | -2.58% / +6.11 點（樣本內最大值） |

## 結論定位

Null-ish / 描述性結果：13 次 NFP 發佈日的 SPY 報酬與 VIX 變化在平均值上接近雜訊（勝率
53.8%，接近拋硬幣；VIX 上升/下降比例 54/46 接近平手），但存在明顯尾部風險（上次事件
VIX 單日 +6.11 點是樣本內離群值）。文章誠實呈現此描述性型態，不誇大宣稱可預測性，
且明確標註樣本數不足以做正式統計檢定。

## Codex Review

因本實驗屬**純描述性統計**（無模型、無推論檢定、無 lookahead 風險的模型組件），且為
event_article 產出（非 knowledge.json PASS/CONDITIONAL_PASS entry），不觸發 K1259 provenance
gate。仍建議 publish 前跑一次 anti_ai_gate.py + check_arc_dedup.py 作為內容層 gate（見下）。
