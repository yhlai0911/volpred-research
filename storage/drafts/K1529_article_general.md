---
title: "Fed 開會前，信用債真的會先示警嗎？這次答案偏否定"
audience: general
status: draft
phase: research
tags:
  - 一般讀者
  - FOMC
  - 信用債
  - 高收益債
  - ETF
  - 波動率
experiment_refs:
  - K1529
  - k1529_credit_spread_fomc_vol
image_url: https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1529_credit_spread_fomc_vol.png
description: "用 HYG/LQD 這類信用債 ETF proxy 測 Fed 會議前後的波動率前哨，結果沒有給出穩健支持。"
---

有一個很有吸引力的想法：Fed 開會時，真正脆弱的地方可能會先在信用債露出，股市晚一點才反應。

直覺上也說得通。高收益債比較怕融資條件收緊，投資級債比較穩。如果 `HYG` 開始明顯輸給 `LQD`，也許代表信用市場已經在替下一段股市波動拉警報。

這次研究把這個想法先降到一般投資人看得到的資料層級。沒有用逐筆公司債資料，也沒有用盤中 Fed 宣布那一小段時間；只用每日 ETF 價格和公開的 Fed 政策意外資料，做一個免費資料 pilot。

資料包含 102 場 FOMC 事件，從 2012-01-25 到 2023-12-13。價格資料來自 yfinance，標的包括 `HYG`、`LQD`、`VCIT`、`VCSH`、`SPY`、`^VIX` 和幾組產業 ETF；政策意外資料來自 SF Fed 的公開 CSV。

![FOMC 前後信用債 ETF proxy 三面板](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1529_credit_spread_fomc_vol.png)

## 信用債有反應，但不夠乾淨

這裡的信用壓力 proxy 很簡單：

`HYG` 表現比 `LQD` 更差時，就記成信用壓力上升。

如果這個指標真的是 Fed 會議波動率前哨，FOMC 後幾天應該明顯比平常更緊張。結果沒有那麼漂亮。

在可公平比較的 97 段事件視窗裡，FOMC 後 t0 到 t+5 的 `HYG-LQD` 壓力平均是 0.000115；同月非事件基準是 -0.000342；兩者差是 0.000457。

方向看起來是壓力多一點，但幅度太小。換成嚴格檢查後，這個差異離「穩定成立」還很遠。

![信用債 ETF proxy 摘要圖](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1529_general_summary.png)

## 當成股市波動前哨，也沒有過關

接著看更實用的問題：這個信用壓力能不能幫我們預測 `SPY` 接下來的已實現波動率？

先看會議前。用 FOMC 前 t-5 到 t-1 的信用壓力去預測會議後 t0 到 t+5 的 `SPY` 波動，模型反而變差，惡化幅度是 -13.85%。

再看會議後。等 FOMC 後 t0 到 t+5 的信用反應已經發生，再拿它去預測 t+6 到 t+26 的 `SPY` 波動，表面上改善 5.92%。這是整份研究裡最像訊號的一段。

但問題也在這裡：它出現得太晚，而且強度不夠。它比較像「事後看到信用市場也有些動靜」，還不像「可以提前使用的波動率警報」。

## 這不是說信用市場沒用

比較合理的解讀是：ETF proxy 太粗。

`HYG` 和 `LQD` 不只是信用風險，還混著利率存續期間、流動性、ETF 本身交易結構、基金持債品質。用它們去代表公司債信用利差，方便，但一定會失真。

產業 ETF 也一樣。研究裡用 `XLP`、`XLU`、`XLV` 代表價格比較僵固的產業，用 `XLE`、`XLB`、`XLK` 代表比較彈性的產業。這適合做第一輪檢查，不適合拿來宣稱真正的價格剛性機制已經被抓到。

另一個限制是資料時間。SF Fed 的政策意外 CSV 在這次可用資料裡停到 2023-12-13，價格資料雖然一路到 2026-06-17，但研究沒有把不同來源的驚訝度指標硬接在一起。

## 實務上怎麼用

如果你看 FOMC 前後的市場壓力，`HYG` 對 `LQD` 仍然可以放在儀表板上。它可以提醒信用市場有沒有同步緊張。

但這次結果不支持把它當成獨立的股市波動率前哨。至少在每日 ETF 資料裡，FOMC 信用壓力沒有穩定領先 `SPY` 波動。

真正值得記住的是這句話：高收益債有時會先皺眉，但這次資料沒有證明它會提前喊出股市接下來要更會晃。

要把這個題目重開，下一步需要更細的資料：逐筆或公司層級信用利差、真正的價格僵固指標，或 Fed 宣布前後的盤中資料。只靠 ETF proxy，證據還不夠。

*資料來源：VolPred 站內 FOMC 信用債 ETF proxy 實驗（experiment_ref: K1529；source artifact: experiments/k1529_credit_spread_fomc_vol/k1529_credit_spread_fomc_vol_results.json）。價格資料取自 yfinance daily OHLC，政策意外資料取自 SF Fed Monetary Policy Surprises 公開 CSV；事件期間 2012-01-25 至 2023-12-13，共 102 場 FOMC 事件；價格資料可得至 2026-06-17，但本次不混接其他政策意外序列。本文為研究導讀與風險教育，不構成投資建議。*
