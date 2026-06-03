# Codex 24h Review — mile_31b2b0bb (K1413)

- **Article**: AI 五層產業鏈，我們不講故事，看波動率怎麼說
- **Draft source**: `storage/reports/feed.json` (`mile_31b2b0bb`)
- **Task**: `paper_review_mile_31b2b0bb`
- **Reviewed**: 2026-06-03 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **FAIL**

## Summary

這篇前半段大方向接近 `K1413`：基礎設施層的全期間波動率最高、跨層相關性在 2023→2025 確實上升、lead-lag 沒看到穩定時間差，這些都和 source 對得上。

但有兩個不能放過的 source-level 問題。第一，文中把「截至 6 月初」的當前風險焦點說成仍然是晶片層，這和 `k1413_results.json` 不符；最新 rolling vol 最高其實還是基礎設施層。第二，文章反覆說「五層」，實作上卻只有四個 AI basket（`L4/L5` 被合併成一層），這會讓讀者對方法有錯誤理解。

## Numeric verification

下列主數字與 `experiments/k1413/k1413_results.json` 一致：

| Draft claim | Source | Match |
|---|---|---|
| 2023-01-04 至 2026-06-02，855 交易日 | `data.period`, `data.n_trading_days` | ✓ |
| 全期間 vol：L3 51.7 / L1 41.2 / L2 40.9 / L4L5 25.1 / SPY 15.1 | `full_period_annualized_vol` | ✓ |
| 平均跨層相關：0.49 → 0.53 → 0.65 | `avg_cross_layer_corr_by_period` | ✓ |
| 能源 vs 晶片：0.51 → 0.61 → 0.79 | `correlation_by_period` | ✓ |
| lead-lag 全部 best lag = 0 | `lead_lag_vs_chips` | ✓ |

## Findings

1. **Current-volatility conclusion is numerically wrong** — `storage/reports/feed.json` article paragraph starting `截至 6 月初...`, `experiments/k1413/k1413_results.json:68-85`
   文章寫：
   - `截至 6 月初，晶片層的滾動波動率回到 42.4%,能源電力 39.0%,模型應用 24.9%。`
   - `這條鏈的定價爭論，目前還是集中在晶片和它的算力供給上。`
   - `晶片層仍然是上游裡抖得最厲害的。`

   但 results JSON 顯示最新值是：
   - `L3 基礎設施 latest = 64.63%`
   - `L2 晶片 latest = 42.44%`
   - `L1 能源電力 latest = 39.01%`
   - `L4L5 模型應用 latest = 24.90%`

   也就是說，截至 2026-06-02，**最抖的仍然是基礎設施層，不是晶片層**。這不是語氣問題，是直接和 source 數字衝突。

2. **“五層” narrative does not match implemented basket construction** — `experiments/k1413/README.md:16-24`, `experiments/k1413/k1413.py:55-60`
   文章從標題到正文都在講「AI 五層產業鏈」，但實驗實作只有四個 AI basket：
   - `L1 能源電力`
   - `L2 晶片`
   - `L3 基礎設施`
   - `L4L5 模型應用`

   也就是說，模型與應用在資料上被合併成同一層，並沒有五個獨立 layer series。這不代表實驗無效，但文章至少應寫成「五層框架、四個可交易 basket」，否則讀者會以為每一層都單獨計算過。

3. **“四層同步在 2025-04-25 前後觸頂” is overstated** — article paragraph `那個共同的高點值得記住。`, `experiments/k1413/k1413_results.json:49-95`
   文中說「四層的滾動波動率都在 2025 年 4 月 25 日前後觸頂」。source 實際上是：
   - L1 max date = `2025-04-25`
   - L2 max date = `2025-04-25`
   - L3 max date = `2025-04-25`
   - L4L5 max date = `2025-05-16`

   所以比較精確的說法應是「上游三層在 2025-04-25 同步觸頂，模型應用層的高點較晚，落在 2025-05-16」。

4. **Lead-lag “no stable arbitrage window” is acceptable as a reader-facing paraphrase, but should stay tied to daily data** — article paragraph `順帶補一個...`, `experiments/k1413/README.md:59-64`
   source 支持「best lag 全為 0」與「日線資料看不到穩定領先/落後」。這篇沒有把它講成因果，還算克制。  
   但如果要保留「套利無空間」這句，建議補成「至少在日線資料下沒看到空間」，避免讀者誤解成更高頻率也已被否定。

5. **Method caveats are mostly honest and source-aligned** — article末段 `數據與方法`, `experiments/k1413/README.md:74-80`
   等權 basket、yfinance adjusted close、描述統計未做正式檢定、樣本只涵蓋 AI capex 上行期，這些限制都有交代，這點是加分的。問題主要不是隱藏 caveat，而是把後段 narrative 從數字拉過頭。

## Lookahead audit

- PASS — rolling vol uses a backward-looking 63-day window only,見 [k1413.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1413/k1413.py:99)。
- PASS — period correlations and lead-lag are descriptive transforms on observed daily returns, not predictive backtests,所以沒有 classic signal-return lookahead 問題。

## Recommended fixes

1. 把「截至 6 月初晶片層仍是上游最抖」改成符合 source 的版本：**基礎設施層最新波動率仍最高，晶片與能源電力已從 4 月高點回落，但仍高於模型應用層。**
2. 把「五層」方法描述改精確：**概念上用 AI 五層框架，但資料上是四個 AI basket（模型與應用合併）+ SPY 對照。**
3. 把「四層同步在 2025-04-25 前後觸頂」改成：**上游三層在 2025-04-25 同步觸頂，模型應用層高點較晚。**
4. 若保留套利句，補一句限定：**這是日線資料下的 null result，不代表更高頻資料也沒有時間差。**
