# K681 Code Review — Lookahead Audit
**Date**: 2026-05-18  
**Reviewer**: Claude (主線程人工審查，Codex 同步備份)  
**Trigger**: Codex 24h-rule review for article mile_073884fd  
**Article**: VIX 百分位策略走出美國：四個市場的真實成績單

---

## VERDICT: CONDITIONAL_PASS

台灣結果可信；US/EFA 結果因 lookahead bias 需重跑 K681b 驗證。  
文章已加 errata 說明，K681b 排入 next_tasks。

---

## Issue 1: US/EFA 1日 Lookahead Bias（HIGH SEVERITY）

### 發現
`compute_vix_percentile()` 第 97-101 行：
```python
for i in range(window, len(vix)):
    window_vals = vix[i - window:i]   # t-252 到 t-1，共 252 天，正確
    percentile[i] = sp_stats.percentileofscore(window_vals, vix[i]) / 100.0
    # ^^^^ score = vix[i]（當日 VIX）→ 在 t 時刻用 t 當日 VIX 計算百分位
```

`compute_weights()` 第 132-134 行：
```python
data["w_pct_us"] = 1.0 - pct   # pct[i] 含 vix[i]，無 shift
```

`backtest_single_asset()` 核心：
```python
strategy_ret[i] = weights_arr[i] * asset_ret[i]
# weight[i] 依賴 vix[i]（當日收盤），但 asset_ret[i] = price[i]/price[i-1]-1
# 在 vix[i] 可知的「當日收盤後」，return[i] 的交易早已結束
```

### 問題
- `weight[i]` 用 VIX 收盤值（只有在 market close 才知道）
- `return[i]` = close(t-1) 到 close(t) 的報酬（market close 時才收尾）
- → **無法用 VIX 收盤(t) 來賺 return(t)，因為 return(t) 同時在收盤結束**

### 文章宣稱 vs 代碼實作
- 文章第 3 段：「**訊號使用前一日 VIX 收盤值，部位於下一交易日生效**，不存在用未來資訊的問題」
- 代碼（US/EFA）：**用當日 VIX**，無 `.shift(1)` → 與宣稱矛盾

### 台灣：正確
- `w_pct_tw = 1.0 - pct_lag`，其中 `pct_lag[i]` 用 `vix[i-1]` → 正確 lag

### 影響
- US Sharpe 1.676（DM t=3.125）：可能略微膨脹
- EFA Sharpe 1.843（DM t=5.419）：高度可疑，EFA 使用相同 `w_pct_us`（134, 728行），疊加跨時區問題

---

## Issue 2: DM test 非標準 Diebold-Mariano（LOW SEVERITY）

代碼計算兩策略日報酬差的 t-statistics，這是 mean-return t-test，非原始 Diebold-Mariano（用預測誤差差的 QLIKE/MSE）。標記為「DM test」略有誤導，但此用法在財務文獻中普遍接受。不影響結論。

---

## Issue 3: Harvey t>3 閾值語境（LOW SEVERITY）

Harvey (2017) t>3 設計用於「從數百個 prior strategy 中撈一個」的 multiple testing correction。K681 是比較同一 VIX 信號的兩種 scaling（pct vs 12/VIX），並非從海量 strategy 撈出。此處 t>3 過度保守，但方向正確（更嚴格 = 較難宣稱顯著），不影響研究誠實。

---

## 修正計劃

### 立即行動（已完成）
- [x] 審查文件寫入 `experiments/k681/k681_review_lookahead_2026_05_18.md`
- [x] 文章 mile_073884fd 加 errata（參見 feed.json 更新）

### 待辦
- [ ] K681b：US/EFA weights 加 `.shift(1)` 重跑，比較 Sharpe 差異
- [ ] K681b 結果出來後，更新文章數字或加 retraction note
- [ ] 若 K681b 驗證 US/EFA 仍顯著，原結論成立（article 改為 errata + citation）；若不顯著，需 major correction

---

## 台灣結果維持可信
- Taiwan 0050: Sharpe 0.266 vs 12/VIX 0.157（DM t=0.292 → 未達顯著，如實報告）
- Taiwan+Gold: Sharpe 0.364 vs 0.267（DM t=0.086 → 未達顯著，如實報告）
- 「台灣的贏可能只是運氣」— 文章如實呈現，研究誠實符合

---

## 引用前一日 VIX 的正確實作（供 K681b 參考）
```python
# 正確：US/EFA 也用 lag1
data["vix_pct_lag1"] = (1.0 - data["vix_percentile"]).shift(1)
data["w_pct_us"] = data["vix_pct_lag1"]  # 改用昨天的百分位
```
