# K1442 — MOVE/VIX 比值與 CPI 公布前後的隱含波動率定價

## 動機

reader_facing_refill 補池任務（trending_repost P1）— CPI 2026-06-11 T-1 timely 切角。
原議題：「強勁就業 + CPI 預期 → MOVE/VIX 是否過度定價」。
切角：MOVE/VIX 比值的歷史百分位 + CPI 前後 5 日事件研究。

## 資料

- yfinance `^MOVE`（ICE BofA MOVE Index）+ `^VIX`
- 2003-01-02 到 2026-06-09，5794 trading days
- CPI 事件樣本：2024-01 到 2026-05，29 次（BLS 通常每月第二週公布）

## 方法

1. 計算 `MOVE/VIX` daily ratio
2. 當前值（2026-06-09）相對全期 + trailing-1Y 的百分位
3. Event study：每次 CPI 公布日為 T0，計算 T-5→T0 與 T0→T+5 的 MOVE/VIX % 變化
4. Paired t-test：pre vs post 5d 變化是否顯著不同

無 signal generation / 無 lag concern（純描述性 + 歷史事件回顧）。

## 主要結果

### 當前快照（2026-06-09）

| 項目 | 數值 |
|---|---|
| MOVE | 77.03 |
| VIX | 19.87 |
| MOVE/VIX 比值 | 3.88 |
| 全期百分位 | **P26**（偏低，非偏高）|
| trailing-1Y 百分位 | P35 |
| 全期中位數比值 | 4.78 |

**反直覺發現**：市場常說「CPI 前 MOVE 過度定價」，但當前比值在 P26（歷史分布偏低端），不是高估。

### CPI 事件研究（29 次）

| 視窗 | MOVE 均值 % | VIX 均值 % |
|---|---|---|
| T-5 → T0 (pre) | **-3.25%**（中位 -5.70%）| -1.81% |
| T0 → T+5 (post) | -0.39% | **+5.35%** |
| 公布後下跌頻率 | 44.8% | **僅 48.3%**（VIX 反而 51.7% 上漲）|

**Paired t-test**：MOVE p=0.287、VIX p=0.211 — **vol crush 統計不顯著**。

### 解讀

1. 「過度定價」假說不成立：當前 MOVE/VIX 比值偏低端
2. 「Vol crush」pattern 弱：CPI 公布後 VIX 反而多數情況上升（51.7% 事件）
3. 真實模式：MOVE 在 CPI 前 5 日中位數已跌 5.7% — 市場 **提前** 消化，到公布日反應已減弱

## 限制

- CPI 事件樣本 29 次（2024-2026），覆蓋高利率/通膨期，可能不代表全 cycle
- MOVE 來源 yfinance `^MOVE`（ICE BofA index proxy），與 Bloomberg 原值可能有對齊差異
- 未控制其他同窗事件（FOMC / NFP 與 CPI 鄰近時可能干擾）
- VIX 5 日 +5.35% 部分可能由 cross-event noise 驅動，不是純 CPI 反應

## Provenance

- Author: hourly-05 ($(date '+%Y-%m-%d %H:%M'))
- Reviewer: 待 Codex（descriptive event study 非 novel-method、無 knowledge.json PASS claim）
- Files: `k1442_move_vix_ratio_cpi.py` / `k1442_results.json` / `k1442_cpi_events.csv` / `fig_a_ratio_timeseries.png` / `fig_b_cpi_event_study.png`
