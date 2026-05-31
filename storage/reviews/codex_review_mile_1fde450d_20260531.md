# Codex Review — `mile_1fde450d`

日期：2026-05-31  
文章：`論文發出去之後，6 個數字裡有 3 個對不上：一場我們自己抓自己的核對`

## Verdict

CONDITIONAL_PASS

## Findings

1. 文章把 Table 10 的差異歸因為「公開 API 只抓到 20 檔」，這個說法沒有被實驗腳本支持。`K1198` 是直接用硬編碼的 `SPY_TOP20_CONSTITUENTS` 清單做重建，不是先嘗試 50 檔再因 API 限制退回 20 檔。[experiments/k1198/k1198.py:112](/Users/yhlai0911/Desktop/volpred-research/experiments/k1198/k1198.py:112) 只定義 20 檔，[README](/Users/yhlai0911/Desktop/volpred-research/experiments/k1198/README.md:34) 也只說「this experiment used 20 stocks」。因此文章目前把「設計選擇 / 可得資料範圍」講成「API 客觀抓不到」，屬於過度具體化的因果敘述。

2. 文章把 `VT 在尾端風險上贏 BH` 列為「一句不改」的主結論，驗證力度寫得比實驗實際支持的更強。`K1198` 的 Table 11 重建，直接可重現的是 **BH** 的 ES 與峰度；README 明確註記 paper 的 VT 數字使用的是 **Hybrid VT**，而本次實驗用的是 simpler GARCH VT 近似，因此 VT improvement 數字本身並未被這次重建正式對齊。[experiments/k1198/README.md:42](/Users/yhlai0911/Desktop/volpred-research/experiments/k1198/README.md:42) [experiments/k1198/k1198.py:366](/Users/yhlai0911/Desktop/volpred-research/experiments/k1198/k1198.py:366) 文章若要保留這句，應降級成「不推翻既有尾端風險方向性敘述，但 VT 具體數值仍待 Hybrid 規格正式對齊」。

## Summary

文章主幹 `3/6 matched, 3/6 diverged → MODIFY_PAPER` 與 `K1198` 結果一致，沒有看到 lookahead 或 DM/Harvey 類過度宣稱。需要修的是兩處語氣：一處把 20 檔限制講成 API 事實，一處把 VT tail-risk 結論講得像已被本次重建完整驗證。
