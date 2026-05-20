---
title: "Lookahead 修正後，14 策略誰是真贏家？K694 揭露 Sharpe 通膨最高 +2.04"
audience: general
status: draft
tags:
  - 一般讀者
  - 研究誠實
  - lookahead
  - Sharpe
  - 策略審查
  - 回測陷阱
  - 平台修正
experiment_refs:
  - K694
---

## 你看到的 Sharpe 3.0，可能少打了一天時差

你在策略平台看到「Sharpe 3.7、年化 32%」，第一反應通常是兩種：覺得太神奇、或覺得回測有鬼。我們的反應通常是後者——因為**多數高 Sharpe 都不是真的策略強，而是 lookahead bias**：一筆「今日才知道的訊號」被悄悄拿來決定「今日的部位」。

K693 揭穿了我們自家系統的這個 bug：`paper_trading.json` 在 9,935 筆紀錄裡，把 `data_date` 跟 `trade_date` 對到同一天——也就是用收盤後才能算出的訊號，「回頭」拿去交易當天本身。修正方式很簡單：所有 portfolio_return 統統往後延一天，明天的部位用今天的訊號。

修完以後，問題來了：**之前看起來很猛的策略，到底有幾個是真贏家？**

K694 就是這個問題的答案：把 14 個 active / paper-traded 策略，用修正後的資料**重新跑一次審查**，跟修正前（K640）做正面對比。

## K694 怎麼設計：一次重審 14 個策略

設計上極度單純：

- **資料**：`storage/paper_trading.json`，K693 已修正，1.23 年（2025-01-02 到 2026-03-27），309 個交易日
- **方法**：把每個策略的 corrected portfolio_return 重算 Sharpe / Sortino / CAGR / MDD / Calmar / win rate，跟 K640 (lookahead 偏差版本) 並排
- **沒有任何 signal shift、沒有任何 model retrain**——純粹是「同一條日報酬序列，往後挪一天」之後再算績效

也就是說，**修正前後的差距完全來自 lookahead 偏差本身**。沒有換策略、沒有換資料來源、沒有換期間。差多少就是 lookahead 偷偷給了多少免費 alpha。

## 結果：14 策略、最高通膨 +2.04 Sharpe

![14 策略 Lookahead 通膨幅度](experiments/k694/k694_inflation_rank.png)

完整通膨幅度（Sharpe 修正前 − 修正後）：

| 策略 | K640 Sharpe | K694 Sharpe（修正後）| Delta |
|---|---:|---:|---:|
| adaptive_tier | 3.735 | 1.691 | **+2.04** |
| piecewise_conservative | 3.975 | 1.961 | **+2.01** |
| taiwan_hybrid_leverage | 3.762 | 2.018 | **+1.74** |
| tz_tw_jp_5050 | 5.410 | 3.961 | **+1.45** |
| taiwan_spy_momentum | 4.678 | 3.615 | +1.06 |
| vix_cond_leverage | 2.827 | 1.854 | +0.97 |
| global_vt_tz | 4.036 | 3.662 | +0.37 |
| risk_parity | 2.448 | 2.128 | +0.32 |
| taiwan_8.63vix | 2.484 | 2.258 | +0.23 |
| vix_leading_guard | 1.825 | 1.653 | +0.17 |
| recommended_5050 | 1.995 | 1.849 | +0.15 |
| fear_dca | 0.427 | 0.430 | -0.00 |
| slow_vt | 0.255 | 0.305 | -0.05 |
| simple_12vix | 0.232 | 0.393 | -0.16 |

幾個重點：

1. **平均通膨 0.736 Sharpe（全 14 策略）/ 0.538（10 個 active）**——這不是小數
2. **最嚴重 = adaptive_tier，+2.04（120.9%）**：Sharpe 從 3.74 跌到 1.69，CAGR 從 31.9% 砍到 15.5%
3. **時區套利 / 多市場混合策略受傷最重**：tz_tw_jp_5050、global_vt_tz、taiwan_hybrid_leverage 通膨都在 1+ Sharpe 等級
4. **核心 VT 策略幾乎沒事**：slow_vt、simple_12vix、fear_dca 的 delta 都在 ±0.16 以內，部分甚至**修正後反而稍升**（因為 lookahead 在那些策略身上是中性甚至略負作用）

## 為什麼時區套利特別嚴重？核心 VT 為什麼幾乎不受影響？

![Sharpe 修正前 vs 修正後](experiments/k694/k694_corrected_vs_original.png)

直觀解釋一下這張散佈圖：每一點是一個策略，**離 y=x 對角線越遠，lookahead 偏差越大**。

時區套利策略（tz_tw_jp_5050、global_vt_tz）依賴的是「**台股已經收盤、日股下午盤訊號**」這類序列關係——當交易紀錄少打一天時差，下午才該知道的訊號被拿來決定上午的部位，等於白拿了好幾小時的市場資訊。所以通膨大。

反過來，**slow_vt / simple_12vix 這類核心 VT 策略**用的是 `signal[t-N:t]` 的長期 EWMA / vol target——慢訊號**對 1 天延遲幾乎不敏感**。這是個 important finding：**VT 家族在設計上對 lookahead 是 robust 的**，這也是為什麼學術文獻多年來敢用它們做 baseline。

## 重點：通膨 ≠ 作弊

我必須講清楚一件事：上面這些 +1.0、+2.0 的 Sharpe 通膨 **不是策略作者作弊，也不是回測程式碼故意作假**。這是**平台層級的資料管線缺陷**——`daily_update.py` 把 `data_date` 跟 `trade_date` 對齊到同一天，這是個欄位設計 bug，所有用這份資料表的策略都會被同樣地「免費補一天時差」。

這也是為什麼 K694 的價值不只是「揪出哪幾個策略掉很多」，而是：

1. **平台誠實展示修正過程**：先在 mile_921184c5（〈我們犯了一個重大錯誤——然後修正了它〉）公告 bug，再用 K693 修資料，再用 K694 公開重審 14 策略
2. **核心策略仍然 robust**：修正後 7/10 active 策略仍贏 SPY 買進持有（Sharpe ≈ 0.85），平均 Sharpe = 1.485、平均 CAGR = 17%——平台價值並沒有被 bug 整個掏空
3. **這次 audit 是一條更長 chain 的一環**：K547 / K222 / K560 / K645 / K646 / K237 過去 18 個月的 lookahead audit family 已經改過數十處流程；K694 只是最新一次 systemic 抽查

![10 個 active 策略 vs SPY](experiments/k694/k694_beat_spy.png)

## 給讀者：你應該怎麼看高 Sharpe 數字

下次看到任何平台（包括我們自家）公告「Sharpe 3.0、年化 30%」，請套這三個檢查：

1. **訊號來源跟交易時點之間有沒有 explicit lag？** 沒寫 `signal.shift(1)` 或等價邏輯就不要信
2. **核心 vs 衍生策略**：簡單慢訊號（VT、moving average）通膨幅度通常很小；複雜時區 / 多市場 / 多訊號嫁接的策略通膨機率高
3. **平台願不願意公開 audit 結果**：如果一個平台從不撤回任何策略、從不公告 bug fix——它要嘛真的完美，要嘛你看不到問題

K694 就是我們的第二類：誠實貼出 14 個策略的「修正前 vs 修正後」，包括最丟臉的 +2.04 通膨。能上架的策略名單會根據 K694 corrected metrics 重新排序，**adaptive_tier、piecewise_conservative 這類高通膨策略的 weight 會被調降或暫退**。

下一步是 K547-family 的延伸：讓 daily_update / paper_trading 寫入端強制 `data_date < trade_date` 不變式（已於 2026-03-17 落地），加 unit test 防止這個 bug 再復發。

---

**資料來源**：`experiments/k694/k694_results.json`（K694: CORRECTED Live Performance Audit, post-K693 lookahead correction）

**相關研究**：K640（原始 audit，pre-correction）、K692（identifies 801 lookahead entries）、K693（fixes 9,935 entries）、K547 family（系統性 lookahead audit chain）

**期間**：2025-01-02 → 2026-03-27，1.23 年，309 trading days
