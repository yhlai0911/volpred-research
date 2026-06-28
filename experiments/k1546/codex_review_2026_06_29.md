# K1546 Codex review — 2026-06-29

**Article**: `mile_410f7532` — VIX 期限結構 VRP slope 預測 SPY drawdown 全樣本 NULL
**Reviewer**: Codex CLI 0.141.0 (gpt-5.4 medium, ChatGPT auth) — primary path
**Triggered by**: paper_review_mile_410f7532 (Codex 24h-rule)
**Date**: 2026-06-29 07:08 台灣時間
**Overall verdict**: **CONDITIONAL_PASS**

Headline NULL 站得住腳，無 lookahead；但 benchmark numerics + 統計穩健性 + 揭露面有 4 處需 remediation。文章 publish 不需即時撤回，下一輪 fire 跑 remediation task 補正。

## 詳細 findings

### A. Lookahead
- A1 **PASS** — signal `.shift(1)` 全 lag（k1546.py:253-255）
- A2 **WARN** — `forward_max_drawdown` 允許尾端 `N//2`，與「嚴格 N 日」敘述不一致（k1546.py:123-132）
- A3 **WARN** — RV 用 `rolling(win).std()` 未先 `dropna()`，導致 VRP 最後可用日停在 2026-05-22 而非 2026-06-23（k1546.py:84-88）
- A4 **PASS** — yfinance Close 對 VIX 無 forward-bias

### B. Statistical tests
- B1 **WARN** — HAC lag=1..N 比 N-1 多一階合理，但 README 不應暗示是最保守 Hodrick `2N-1`（k1546.py:153-156）
- B2 **PASS** — Spearman block bootstrap 正確（block=N, B=1000, seed=42）
- B3 **FAIL** — AUC 一律 `score = -signal`，VIX_level benchmark 方向反了：JSON 報 0.284，正向 high-VIX = high-tail-risk 應約 0.716（k1546.py:215-233 + results.json:493-506）
- B4 **FAIL** — quintile top-vs-bottom Welch iid t-test 未處理 21 日 forward DD 重疊樣本相依；code comment 「HAC t-test」與實作不符（k1546.py:195-200）

### C. Multiple-testing
- C1 **WARN** — 約 5 signals × 3 horizons = 15+ hypotheses 未做 Bonferroni/Holm/FDR；只警告 subsample cherry-pick
- C2 **PASS** — `IV_slope_3M_1M` p=1.44e-8 即使 Bonferroni ×18 仍 sig

### D. Verdict honesty
- D1 **WARN** — full-sample NULL 數字支持充足，但「不能預測」「白工」語氣偏絕對；建議改為「primary full-sample / incremental specification 下不成立」
- D2 **PASS** — encompassing regression 與文章敘事一致

## Remediation list（排 follow-up task）

1. **修 AUC direction**：對 VIX_level / IV_slope（正向訊號）改 `score = +signal`；VRP_slope 維持 `-signal`
2. **Quintile 改 block bootstrap 或降 diagnostic-only**：21 日重疊樣本 Welch 直接 iid 不可信
3. **Multiple-testing 揭露**：results.json + README 補一段 Bonferroni / Holm 註解
4. **RV `dropna()`**：SPY trading-day-aligned，將 VRP 延伸到 2026-06-23 而非 2026-05-22
5. **Article 語氣縮減**：把「白工」改成「primary full-sample 下不成立，IV_slope_3M_1M benchmark 仍 sig」

## 對 publish 的影響

- Headline NULL **不需撤回**（VRP_slope_6M_1M t=-0.98 / AUC=0.447 / Spearman CI 跨 0 均支持 NULL）
- B3 AUC bug 不影響 VRP_slope 的 NULL 結論（它本就應是 -signal），但讓 VIX_level benchmark 的 0.284 / 0.716 倒置會混淆讀者
- Remediation task 排下輪 fire，patch 後同步 README + article correction note
