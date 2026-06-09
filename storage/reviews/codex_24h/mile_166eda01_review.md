# Codex 24h Review — `mile_166eda01`

## Verdict

**`CONDITIONAL_PASS`**

Source code (`experiments/k1442/k1442_move_vix_ratio_cpi.py`) 與 article 主數字整體對得上：

- `MOVE/VIX = 3.88`, full-history percentile `P26`
- CPI event sample `n=29`
- `MOVE T-5→T0 mean = -3.25%`, median `-5.70%`
- `VIX T0→T+5 mean = +5.35%`
- paired t-test p-values `0.287 / 0.211`

沒有發現 lookahead 或 fabricated number。主要問題在 **敘事力度** 與 **事件窗標示精確度**。

## Findings

### 1. `T-5→T0` 被寫成「公布前 5 日」，時間標示不精確，會讓讀者誤以為不含公告日

- Article: [storage/reports/mile_166eda01.json](/Users/yhlai0911/Desktop/volpred-research/storage/reports/mile_166eda01.json:5)
- Code: [experiments/k1442/k1442_move_vix_ratio_cpi.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1442/k1442_move_vix_ratio_cpi.py:84)

程式明確把 pre window 定義成 `T-5 → T0`，而 `T0` 是 **CPI 公布當日**：

- `win = df.iloc[pos - 5 : pos + 6]`
- `move_T0_pct_change_5d = MOVE[T0] / MOVE[T-5] - 1`

但文章文字寫成「公布前 5 日」「公布前一週市場已經把不確定性消化掉」，這在語意上像是 **只到公布前一日**。實際上這個數字已經**包含公告日收盤反應**，不能直接說成純 pre-release drift。建議改成：

- `T-5 到公告日收盤`
- 或 `公告日前 5 個交易日至公告日`

這樣才和 source 一致。

### 2. 「數據說相反 / 股市那邊不是 vol crush」的語氣偏強，超過統計證據

- Article: [storage/reports/mile_166eda01.json](/Users/yhlai0911/Desktop/volpred-research/storage/reports/mile_166eda01.json:3)
- Results: [experiments/k1442/k1442_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k1442/k1442_results.json:18)

文章標題與內文把方向寫成：

- 「23 年 MOVE/VIX 數據說相反」
- 「股市那邊不是 vol crush」
- 「CPI 出來後股市波動率反而傾向上升」

但 source 給的正式檢定是：

- MOVE pre vs post: `p = 0.287`
- VIX pre vs post: `p = 0.211`

也就是 **統計上不顯著**。這足以支持：

- `沒有顯著 vol crush 證據`
- `資料不支持穩健的公布後下殺敘事`

但還不足以把結論寫成「數據說相反」或「股市那邊不是 vol crush」這種近乎反證式口吻。更準確的寫法應是：

- `至少在 2024–2026 這 29 次 CPI 事件裡，看不到顯著 vol crush；VIX 公布後平均甚至略升，但未達統計顯著`

## Lookahead / Implementation

**PASS**

- 這是描述性 event study，不是交易訊號
- 事件日對齊為 `>= CPI date` 的第一個交易日；對 8:30 ET 公布的 CPI 來說，用當日收盤衡量 `T0` 反應是合理的
- 沒有用未來資料生成 signal，也沒有 `same-day signal * same-day return` 的交易 lookahead 問題

## Recommended Fix

1. 把所有「公布前 5 日」改成 `T-5 到公告日收盤` 或等價表述。
2. 把標題 / 內文的強語氣降成 `不支持穩健 vol crush`，避免把 non-significant opposite-direction hint 講成已被證實的反結論。

