# event_article_nfp_2026_07_03_t1

> **2026-07-19 更正**：本實驗原本用「當月第一個週五」proxy 推算 NFP 發佈日。對照官方行事曆，
> 13 個歷史樣本有 **7 個日期是錯的**，其中 `2025-10-03` 是**根本不存在的事件**（2025 年 10 月因
> 政府停擺沒有發布就業報告，9 月報告延到 2025-11-20）。事件日改由
> `volpred.data.event_dates.nfp_release_dates`（BLS/ALFRED 官方發布行事曆，release id 50）取得，
> fail closed 不回退 proxy。**所有歷史統計量都變了**（勝率 53.8% → 46.2%、兩個中位數都翻號）。
> 前後對照見 `nfp_official_dates_fix_report.md`；稽核來源 `experiments/k1442/related_event_date_audit.md`。

## 動機

**2026-07-02（週四）**是美國 6 月非農就業數據（NFP）發佈日 —— 不是 07-03。2026-07-04 國慶日
落在週六，聯邦假期觀察日往前挪到週五 07-03，BLS 因此把發布提前一天。這是 T-1（前一交易日）
事件驅動文章，提供讀者發佈前的波動率結構現況 + 歷史 NFP 反應統計，屬於 `event_article` 任務
類型，走 `feed-publisher` + `trending-repost` 共用的 event 發佈 SOP（立即 published + FB 雙發佈）。

（實驗 id 仍保留 `..._2026_07_03_t1` 這個原始命名，避免打斷既有引用；正確事件日以本文與
`_results.json.nfp_release_date` 為準。）

## 差異化 / 3-layer dedup

- `storage/reports/feed.json` 內既有非農相關文章（`mile_7012b52a`, `mile_d721672b`,
  `mile_630d0010`, `mile_44fb4b90`, `mile_414233df`, `mile_16abc5b1`, `mile_8f90ce78`,
  `mile_ee595d1b`, `mile_10f07ba2`, `mile_4ddbf3f0` 等）最新一篇 `published_at` 為
  2026-04-02，距今約 3 個月，且該批文章鎖定的是 2026-03/04 那次事件。NFP 為每月事件，
  本篇鎖定 2026-07-03 這次發佈，樣本窗口與時效性不同，非 narrative-arc dup。
- 本篇差異化角度：VIX9D/VIX 短端結構現況（term-structure inversion signal）+
  最近 13 次 NFP 事件視窗逐次拆開的 descriptive stats（非單純「歷史平均」敘事）。

## 資料來源

- **市場資料**：yfinance（`SPY`, `^VIX`, `^VIX9D` 日收盤）
- **事件日期**：`volpred.data.event_dates.nfp_release_dates` → BLS Employment Situation 官方
  發布行事曆（FRED/ALFRED release id 50）。取不到就 raise，**不回退任何 proxy** —— 錯的事件日
  比跑失敗更糟，因為它照樣產出看起來合理的數字。
- **期間**：
  - 歷史事件視窗：2025-05-02 至 2026-06-05（2026-07-02 之前最近 13 次官方發布）
  - 當前快照：截至 2026-07-01 收盤（發佈前一個交易日）
- **樣本數**：n=13 個歷史 NFP 事件（descriptive stats only，非統計檢定用途）

### 官方日期 vs 舊 proxy（7/13 錯誤）

| 月份 | 舊 proxy（第一個週五） | 官方發布日 | |
|---|---|---|---|
| 2025-07 | 2025-07-04 | **2025-07-03** | ❌ proxy 撞到休市的國慶日 |
| 2025-10 | 2025-10-03 | **（無發布）** | ❌ 幻影事件，政府停擺取消 |
| 2025-11 | 2025-11-07 | **2025-11-20** | ❌ 停擺後補發 9 月報告 |
| 2025-12 | 2025-12-05 | **2025-12-16** | ❌ |
| 2026-01 | 2026-01-02 | **2026-01-09** | ❌ |
| 2026-02 | 2026-02-06 | **2026-02-11** | ❌ |
| 2026-05 | 2026-05-01 | **2026-05-08** | ❌ |
| 2025-06 / 08 / 09、2026-03 / 04 / 06 | — | 與官方一致 | ✅ 6 筆正確 |

官方 trailing-13 另含 proxy 完全沒納入的 **2025-05-02**（因為 proxy 多塞了一個幻影的 2025-10 事件）。

### 一筆發布日無法交易（Good Friday）

13 筆裡有 **1 筆**的發布日不是交易日：**2026-04-03 是 Good Friday**（2026 復活節為 4/5），
BLS 照常發布就業報告，但美股休市。腳本因此把它的「當日報酬」記在下一個交易日
**2026-04-06（週一）**（`trading_day` 欄位與 `nfp_release_date` 不同的唯一一筆）。

**這筆的口徑和其他 12 筆不同**：它的 0.473% 是週一報酬，內含整個週末的資訊，不是乾淨的
「發布日當日反應」。這是誠實可得的最佳處理（發布日根本沒有 SPY 收盤價），但引用單筆數字時
必須知道這件事。此限制與日期修正無關 —— proxy 版本同樣把 2026-04-03 對到 2026-04-06。

## 資料缺口（已解除）

發稿當下 `yfinance` 的 `^VIX9D` 序列停在 **2026-06-26**，落後 `^VIX` 5 個交易日；當時的處理是
**不**把不同日期的 VIX 與 VIX9D 硬湊成比值，改用最後共同日期（2026-06-26）計算並逐字揭露落後
天數，沒有捏造任何值填補。

yfinance 事後已回補 2026-06-29 ~ 2026-07-01，因此比值現在是真正的同日 T-1 數字
（13.14 / 16.59 = **0.7920**，原為 0.9125）。**這是資料商 vintage 回補，不是本次日期修正造成的**
—— 2026-06-26 那筆仍是 16.80 完全沒變，這就是判定原因的依據；也不是 lookahead，13.14 是
2026-07-01 的真實收盤，仍嚴格早於 2026-07-02 發布。兩個 vintage 都保留在
`_results.json.vix9d_vintage_note`，發稿當時的宣稱維持可稽核。**線上文章從未引用 VIX9D 比值**
（已 grep 確認 0 命中），故不影響任何已發佈數字。

## Lookahead 檢查

本實驗**無預測模型、無 forward-label、無 train-test split**，純粹是描述性統計（descriptive
stats）：
- 歷史 NFP 事件視窗統計：所有數字皆為已發生（realized）歷史事件，`spy_ret_day0` 用
  release-day close-to-close return，`vix_chg_day0` 用 release-day VIX close 減前一交易日
  VIX close，`spy_ret_next_day` 用 release 隔一交易日 return —— 皆為 already-occurred 數字，
  無 lookahead 風險。
- 當前快照（VIX / VIX9D / SPY realized vol）：yfinance 下載窗口的 `end` 直接設在 **2026-07-02
  （exclusive）**，所以腳本裡的任何序列**根本不含發布日那一筆**。無 lookahead 是**結構性保證**，
  不是靠事後切片 —— 這是本次修正順帶補強的一點（原版下載到 07-03 再靠 `.loc[:AS_OF]` 切）。
- 無隨機程序（無 bootstrap / MC / train-test split），故無需 seed。

## 檔案

- `event_article_nfp_2026_07_03_t1.py` — 抓資料 + 計算 + 存 JSON + 存圖（fig1/fig2）
- `event_article_nfp_2026_07_03_t1_results.json` — 完整數字結果（canonical source）
- `nfp_historical_event_window.csv` — 歷史 13 次事件視窗明細表
- `render_lazypack.py` — 懶人包圖組 render script（讀取 `_results.json`，PIL 產生，非按張計費 API）
- `figures/fig1_vix_vix9d_term_structure.png` — VIX vs VIX9D 近 60 交易日走勢
- `figures/fig2_nfp_day_spy_return.png` — 近 13 次 NFP 發佈日 SPY 當日報酬長條圖
- `figures/nfp_lazypack_1_framework.png` / `_2_results.png` / `_3_takeaway.png` — 懶人包三張圖

## 主要數字（截至 2026-07-01，n=13 官方 NFP 事件）

「舊值」= 第一個週五 proxy 的結果，僅供對照，**不可再引用**。

| 指標 | 數值（官方日期） | 舊值（proxy） |
|---|---|---|
| VIX 最新收盤 | 16.59（2026-07-01） | 16.59（未變） |
| SPY 5 日已實現波動率（年化） | 14.41% | 14.41%（未變） |
| SPY 20 日已實現波動率（年化） | 18.28% | 18.28%（未變） |
| VIX9D 最後一筆 | 13.14（2026-07-01，無落後） | 16.80（2026-06-26，落後 5 日） |
| VIX9D/VIX 同日比值 | 0.7920（基準日 2026-07-01） | 0.9125（基準日 2026-06-26） |
| 近 13 次 NFP 日 SPY 上漲機率 | **46.2%** | 53.8% |
| 近 13 次 NFP 日 SPY 平均報酬 | -0.183%（中位數 **-0.023%**） | -0.185%（中位數 +0.098%） |
| 近 13 次 NFP 日 SPY 報酬標準差 | 1.236% | 1.168% |
| 近 13 次 NFP 日 VIX 平均變化 | +1.04 點（中位數 **-0.02** 點） | +0.99 點（中位數 +0.02 點） |
| 近 13 次 VIX 當日下降比例 | **53.8%** | 46.2% |
| 隔日 SPY 平均報酬 | **+0.032%** | +0.411% |
| 上次 NFP（2026-06-05）SPY 報酬 / VIX 變化 | -2.58% / +6.11 點（樣本內最大值） | 同（該日期本來就正確） |

VIX9D 兩欄的差異來自資料商回補，**與日期修正無關**（見上節）；其餘差異全部來自事件日期修正。

## 結論定位

Null-ish / 描述性結果，**修正後方向更弱而非更強**：13 次官方 NFP 發佈日的 SPY 勝率
46.2%（不到一半）、報酬中位數 -0.023%、VIX 變化中位數 -0.02 點 —— 三個數字都貼在零附近，
比 proxy 版本更接近純雜訊。平均值被單一離群事件主導（2026-06-05：SPY -2.58% / VIX +6.11 點，
同時是樣本內 SPY 最差與 VIX 最大跳動），所以平均 -0.183% 與中位數 -0.023% 差了近一個數量級，
引用時必須兩個一起講。

**修正前後最該注意的翻轉**：勝率從「多數上漲」(53.8%) 變成「多數下跌」(46.2%)，VIX 下降比例
從 46.2% 變成 53.8% —— 兩個敘事方向都反了。這正是 proxy 事件日的危險之處：它不會噴錯誤，
只會安靜地產出方向相反但一樣可信的結論。隔日平均報酬更是從 +0.411% 掉到 +0.032%（13 倍），
任何「NFP 隔天傾向反彈」的說法在官方日期下都不成立。

n=13 樣本數不足以做正式統計檢定，本實驗全程只作描述性用途。

## Codex Review

因本實驗屬**純描述性統計**（無模型、無推論檢定、無 lookahead 風險的模型組件），且為
event_article 產出（非 knowledge.json PASS/CONDITIONAL_PASS entry），不觸發 K1259 provenance
gate。仍建議 publish 前跑一次 anti_ai_gate.py + check_arc_dedup.py 作為內容層 gate（見下）。
