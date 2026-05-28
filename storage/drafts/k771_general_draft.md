---
title: "類股分散度看起來比 VIX 更細，但 K771 告訴你它未必更有用"
audience: general
status: draft
tags:
  - SPY
  - VIX
  - dispersion
  - sector rotation
  - 策略研究
experiment_refs:
  - K771
---

# 類股分散度看起來比 VIX 更細，但 K771 告訴你它未必更有用

很多策略研究都有一個很自然的直覺：

如果市場內部開始分化，代表不同類股對景氣、利率、風險的反應正在拉開。這種「分散度」也許能比單看 `SPY` 或 `VIX` 更早告訴你，接下來該押大盤，還是該改抱一籃子類股。

`K771` 測的就是這個想法。

做法不複雜：

- 用 `11` 個美股 sector ETF 的日報酬，計算 `20` 天 rolling dispersion
- dispersion 很高時，持有等權 sector basket
- dispersion 很低時，持有 `SPY`
- 中間區間，持有 `50/50`
- 每月調整一次，訊號明確 `shift(1)`，避免 lookahead

這個想法很合理，但結果很克制：

**dispersion timing 並沒有打敗更簡單的基準，尤其沒有打敗 `12/VIX`。**

## Full sample 先看結論：沒有明顯升級

![K771 full sample comparison](experiments/k771/k771_general_fullsample_comparison.png)

`2010-02-03` 到 `2026-03-30` 的 full sample 裡，含交易成本的 dispersion timing：

- Sharpe = `0.812`
- MDD = `-36.6%`

單看這兩個數字不差，但放進基準一起看就沒有優勢了：

- `SPY B&H` Sharpe = `0.822`
- `50/50 SPY/GLD` Sharpe = `0.973`
- `12/VIX` Sharpe = `1.054`

更重要的是，drawdown 也沒有更漂亮。dispersion timing 的最大回撤比 `SPY` 更深，和 `12/VIX` 更不是同一個等級。

這代表它不是那種「報酬更高、風險更低」的乾淨升級，而比較像一個聽起來合理、做出來卻只是普通的替代方案。

## 外樣本更誠實：只在少數窗口贏過基準

![K771 cross OOS sharpe](experiments/k771/k771_general_cross_oos_sharpe.png)

把樣本切成 `7` 個兩年窗口後，故事更清楚：

- dispersion timing 只在 `2/7` 個窗口贏過 `SPY`
- 只在 `3/7` 個窗口贏過 `50/50 SPY/GLD`

它不是完全沒用。像 `2015-2016`、`2021-2022` 這種環境，它確實有相對好看的表現。

但真正能拿來當長期規則的策略，不是偶爾贏一次兩次，而是要跨 regime 仍然有穩定優勢。`K771` 在這點上沒有交出足夠強的證據。

## 為什麼會這樣

`K771` 有一個很有意思的描述統計：

**dispersion 與 `VIX` 的相關係數是 `0.658`。**

這不表示兩者完全一樣，但至少表示它們講的是高度重疊的風險故事。當一個更複雜的訊號，和現有訊號本來就大幅重疊時，它要提供穩定增量，本來就很難。

研究裡的 DM test 也支持這個判斷。相對於基準比較，統計量是 `-4.361`，方向上不利於 dispersion timing，說明這不是「差不多」而已，而是沒有證據支持它比基準更好。

## 這篇真正有價值的地方

`K771` 的價值，不是在證明 dispersion 沒資訊，而是在幫研究畫界線。

市場內部分化這個概念本身沒有錯，甚至很可能對風險監控有用。但當你把它變成一條可執行的資產配置規則，增量並沒有自然出現。至少在這份測試裡，它沒有轉成更高的 Sharpe，也沒有轉成更淺的回撤，更沒有穩定打敗已經很強的 `12/VIX`。

對投資人來說，這是一個很實用的提醒：

**訊號比別人精細，不代表策略就會比別人好。**

## K771 的一句話結論

類股分散度確實捕捉到市場內部結構變化，但把它做成 monthly timing 規則後，並沒有形成穩定可複製的投資優勢。`K771` 最終是一個乾淨的 `NULL RESULT`。

## 資料來源

- 實驗編號：`K771`
- 腳本：`experiments/k771/k771_dispersion_timing.py`
- 結果：`experiments/k771/k771_dispersion_timing_results.json`
- 資料來源：`yfinance`
- 樣本期間：`2010-02-03` 至 `2026-03-30`
