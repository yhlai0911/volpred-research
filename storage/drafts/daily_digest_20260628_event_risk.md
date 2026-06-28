# 事件日前別急著躲：NFP、CPI、FOMC 留下的共同線索

下週又輪到 NFP。這種日子最容易把投資人推向二元選擇：留在場內，或先躲到場外。

VolPred 過去幾個月追過 NFP、CPI、FOMC，也測過事件日減倉。把這些文章放在一起看，主線很清楚：事件日期表能提醒我們波動集中，不能自動變成賣出指令。

K820 是最直接的一刀。它把 2006-01-05 到 2025-12-30 的 5,028 個交易日攤開，標出 FOMC、NFP、CPI 共 637 個事件日。結果沒有支持「事件日前先砍倉」。

50/50 的 SPY+GLD baseline Sharpe 是 0.8814，事件日半倉只剩 0.6757。baseline 最大回撤是 -32.5%，半倉策略反而到 -38.3%。事件日平均報酬是 0.111%，非事件日是 0.038%。這組數字的意思很樸素：你想躲掉風險，常常也把正報酬一起躲掉。

這不代表事件日很安全。K820 裡，FOMC 的絕對報酬波動約是平常的 1.35 倍。事件真的會改變短期分布，只是「分布變寬」和「該離場」中間還差了一步。

NFP 的版本更細。K741 檢查 2010-01-01 到 2026-03-28 的 NFP 公布日，樣本有 195 次。NFP 日 SPY 平均絕對報酬是 0.816%，非 NFP 日是 0.713%。波動有放大，但不是每次都同一個方向。

更重要的是 VIX 體制。低 VIX 區間的 NFP 日平均絕對報酬是 0.498%；高 VIX 區間的平均絕對報酬升到 1.488%。同樣叫 NFP，市場所在的波動體制不同，風險輪廓就不是同一件事。

這也解釋了六月那幾篇事件文為什麼一再看短端結構。NFP 前夕看 VIX 是否過低，CPI 前夕看 VIX9D/VIX 是否倒掛，FOMC 前看事件溢價是否已收斂。它們共同追問一件事：市場是否已經把事件價格放進去。

所以今天的導讀可以收成一句話：事件日前要做的是調整風險預算，不是把日期表當成開關。

要調整，先看兩件事。第一，事件本身是否真的讓波動分布變寬。第二，市場在事件前是否已經付了保費。前者回答「明天可能比較大」，後者回答「這件事有沒有已經很貴」。

最差的做法，是看見 NFP、CPI、FOMC 就機械減倉。K820 已經給過懲罰：Sharpe 從 0.8814 掉到 0.6757，回撤還變深。這會把日曆誤當模型。

比較好的做法，是把事件日放進風控語境。低 VIX 的 NFP 可以提醒你別低估當日波動；高 VIX 的 NFP 則要問市場是否已經在高價買保護。FOMC 前短端結構收回來時，追買保護也可能太晚。

這期精選的六篇文章，串起來剛好是一條路：先認識 NFP，再看事件減倉為什麼失效，接著用 VIX、VIX9D/VIX 與 FOMC 短端結構，把「事件」從日期升級成定價問題。

## 懶人包圖組

![K741 NFP VIX regime chart](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/K741_vix_regime_nfp_chart.png)

![NFP event chart](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/event_jobs_20260605_chart.png)

## 本期精選

- [mile_4ddbf3f0](https://volpred.zeabur.app/v3/reports/mile_4ddbf3f0)：先用一般讀者語言建立 NFP 的事件背景。

- [mile_7012b52a](https://volpred.zeabur.app/v3/reports/mile_7012b52a)：K820 的事件減倉測試，主結論是否定機械式避險。

- [mile_8d8b8877](https://volpred.zeabur.app/v3/reports/mile_8d8b8877)：NFP 前夕的 VIX 水位與事件日波動觀察。

- [mile_0fa9c7f5](https://volpred.zeabur.app/v3/reports/mile_0fa9c7f5)：CPI 前夕從 VIX9D/VIX 看短端保護需求。

- [mile_a5e79b07](https://volpred.zeabur.app/v3/reports/mile_a5e79b07)：FOMC 前短端事件溢價從偏貴回到平常。

- [mile_eda69bfb](https://volpred.zeabur.app/v3/reports/mile_eda69bfb)：K741 把 NFP 放進 VIX 體制，說明同一事件在不同市場狀態下差很多。

資料來源：K820 `experiments/k820/k820_event_risk_budgeter_results.json`；K741 `experiments/k741/k741_nfp_event_study_results.json`；以及上述已發佈 archive 文章。
