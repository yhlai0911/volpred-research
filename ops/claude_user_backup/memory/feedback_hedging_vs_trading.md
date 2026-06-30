---
name: feedback_hedging_vs_trading
description: 避險效果要用避險指標評估（HE, VaR/ES, Utility），不要拿去跟交易策略比 Sharpe/CAGR
type: feedback
---

避險研究必須用避險專有的評估指標，不能跟交易策略比 Sharpe/CAGR。

**Why:** 避險的目標是降低風險，不是最大化報酬。一個 95% variance reduction + CAGR 2.2% 的避險組合做的正是它該做的事。不同主題有不同的評估框架。

**How to apply:**
- 避險研究：用 Ederington HE、VaR/ES reduction、utility-based、DM test
- 交易策略：用 Sharpe、MDD、CAGR、Harvey threshold
- 可以「額外」做應用比較，但基本的學術評估必須先做
- 對每個研究主題，先查文獻了解該主題傳統上怎麼評估，不要用同一套指標硬套所有主題
- 其他主題也一樣：不要把每個發現都拿去跟 50/50+VT 比
