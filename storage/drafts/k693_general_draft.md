---
title: 我們抓到自己作弊：12 個策略的 Sharpe 在修正後平均掉了 0.62
tags: [研究誠實, lookahead-bias, paper-trading, 自我審計, 策略修正]
experiment_refs: [K693]
data_source: experiments/k693/k693_results.json
period: 2022-01-01 to 2026-03-27
---

2026 年 3 月 29 日，我們跑了一個內部 audit，發現過去 VolPred 所有歷史 paper trading 回測都帶著一個系統性錯誤：lookahead bias。修正後，12 個策略的 Sharpe ratio 平均掉了 0.62。排行榜前幾名跌最慘。

這篇文章記這件事的全貌：錯誤是什麼、修正了什麼、數字怎麼變、以及為什麼我們選擇公開。

---

## 錯誤出在哪

每天計算策略表現的邏輯是：某天決定好配置權重（`weight_T`），然後把這個配置拿去計算那天的報酬。

舊版的 bug 是：`weight_T` 去配的是 `return_{T-1 → T}`，也就是「今天的收盤價相對昨天的漲跌」。但今天的收盤價，在今天還沒收盤前是不知道的。換句話說，這個 weight 是在「偷看」當天的結果後才決定的。

用一個更直接的比喻：把昨天的 VIX、昨天的波動率拿來決定配置，然後卻去撈今天的漲跌幅來計算績效。這兩個時點根本沒有對齊。

修正方法：`weight_T` 改為賺 `return_{T → T+1}`，也就是用今天的配置去實現明天的收盤報酬。同步把 `trade_date` 推到下一個交易日，並加入 `actual_returns` 欄位。修正覆蓋了 9,935 個 entries（801 個交易日，2022-01-01 到 2026-03-27），數據源為 yfinance（SPY、GLD、0050.TW、^N225）。

---

## 數字怎麼變

下表是 12 個策略修正前後的 Sharpe 對照。

| 策略 | Sharpe（修正前） | Sharpe（修正後） | 變化 |
|---|---|---|---|
| piecewise_conservative | 3.16 | 1.56 | **-1.60** |
| adaptive_tier | 3.02 | 1.51 | **-1.51** |
| tz_tw_jp_5050 | 3.03 | 1.63 | **-1.40** |
| taiwan_hybrid_leverage | 2.50 | 1.60 | -0.90 |
| vix_cond_leverage | 2.64 | 1.76 | -0.88 |
| global_vt_tz | 2.37 | 1.68 | -0.69 |
| fear_dca | 1.20 | 0.96 | -0.24 |
| slow_vt | 1.27 | 1.19 | -0.07 |
| recommended_5050 | 2.05 | 1.97 | -0.08 |
| risk_parity | 2.23 | 2.18 | -0.05 |
| simple_12vix | 1.26 | 1.22 | -0.04 |
| vix_leading_guard | 0.85 | 0.89 | **+0.04** |

12 個策略，平均 Sharpe 下降 0.62。只有一個策略（`vix_leading_guard`）的修正後 Sharpe 反向上升，原因後面解釋。

![12 策略修正前後 Sharpe 對照](experiments/k693/figures/before_after_sharpe.png)

![Sharpe 變化幅度（按降幅排序）](experiments/k693/figures/sharpe_delta.png)

---

## 傷最深的是哪類策略

Sharpe 掉最多的三個（`piecewise_conservative`、`adaptive_tier`、`tz_tw_jp_5050`）有個共同點：它們都頻繁地在資產之間切換配置，或是根據波動率訊號動態調整槓桿。

問題正好出在「動態」這個特性。一個策略每天的 weight 改變越多，它就越依賴「今天到底是漲還是跌」的資訊來決定配置。舊版的 bug 讓這些策略實際上是在「看了結果才決定怎麼押」。修正後，這個事後諸葛的優勢消失，Sharpe 跌了 1.4 到 1.6。

至於幾乎沒有變化的策略（`risk_parity`、`slow_vt`、`recommended_5050`），它們有個共同點：配置很穩定，不太隨日 return 改變。因為 weight 本來就不頻繁調整，偷看當天結果帶來的優勢本來就小，修正後自然沒什麼差。`risk_parity` 的 Sharpe 只從 2.23 掉到 2.18；`recommended_5050` 從 2.05 掉到 1.97。

`vix_leading_guard` 是唯一修正後 Sharpe 反而略升（+0.04）的策略。這不代表它「受益於 lookahead」，而是 return 時序位移後，恰好碰到修正後那段時間的報酬比修正前略高。K693 結論裡也明確標注：「正的 delta 代表修正後那段時序恰好有更高的報酬，不是修正方向的問題，正確性才是關鍵。」

---

## 這對排行榜的意義

舊排行榜裡，`piecewise_conservative`、`adaptive_tier`、`tz_tw_jp_5050` 這三個 Sharpe 都在 3.0 以上，看起來遠超其他策略。修正後，三個都落到 1.51 到 1.63 的區間，和 `risk_parity`（2.18）、`recommended_5050`（1.97）拉開了新的距離。

原本「中規中矩」的幾個策略，修正後的相對位次反而上升。`risk_parity` 的 2.18 現在是所有策略裡最高的，而舊排行榜上它排在 `piecewise_conservative` 之後。

這個位移有一個明確的解讀：過去的排名低估了低換手策略，高估了高度動態策略。修正後，這個偏差消失了。

---

## 我們做了什麼

在執行修正前，我們先備份了完整的舊資料（`storage/paper_trading_backup_pre_k693.json`），確保修正是可回溯的。

接著對所有 10,073 筆舊格式 entries 重新計算報酬（修正 9,935 筆，3 筆因末日缺收盤價設為 null，135 筆因缺價格跳過），並把 `trade_date` 改成正確的下一交易日，加入 `actual_returns` 欄位。

修正的完整結果記錄在 `experiments/k693/k693_results.json`，每個策略修正前後的 Sharpe、CAGR、max drawdown 都有完整的對比。

---

## 為什麼要公開說這件事

過去這些 Sharpe 數字是公開展示的。修正後數字變了，排名變了，如果我們選擇悄悄更新不說，讀者看到的就是前後不一致的記錄，卻不知道為什麼。

VolPred 的立場是：研究的可信度建立在過程透明上，不是建立在只展示好結果。抓到自己的錯誤並公開修正，比永遠展示沒有問題的成績單更值得信任。

這次的修正也提醒一件事：每個策略的 Sharpe 數字，都只在方法論正確的前提下有意義。一個 Sharpe 3.0 但帶 lookahead bias 的策略，和一個 Sharpe 1.5 但時序正確的策略，兩者根本不在同一個量尺上比較。

後者才是我們想公開展示的東西。
