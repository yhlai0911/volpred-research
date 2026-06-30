---
name: Session Close Price Assumption
description: 沒有日內資料時，PRG 假設 session 收盤價可交易。論文必須明確寫出此假設，並用 TAIFEX tick 做 robustness check。
type: feedback
---

PRG/PRS 模型用 session 收盤價計算 return。沒有日內資料的市場（SPY/QQQ/GLD/EEM）只能假設收盤價 ≈ 收盤前可交易價格。

**Why:** 高流動性資產（SPY bid-ask < 1bp）此假設合理，但必須明確寫出，不能隱含。

**How to apply:**
- 論文 methodology 段落明確陳述假設
- 有 TAIFEX tick 的市場：用收盤前 n=1,5,10 分鐘價格做 robustness check 實證驗證
- 無 tick 的市場：用流動性論證（bid-ask spread 資料）支持假設
