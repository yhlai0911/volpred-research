# mile_48c8328b — Codex 24h-rule Review Verdict

**Date**: 2026-06-15 23:09 台灣時間
**Reviewer**: codex-cli 0.139.0 (gpt-5.4 medium reasoning)
**Article**: mile_48c8328b「跨資產注意力加權預測波動率：聽起來高科技，實測沒贏 GJR」(published)
**Source**: `experiments/k189/` (rerun 2026-06-11 lagged + ex-ante alpha)
**Verdict**: **FAIL** — 文章與當前 source/results 嚴重不一致，**核心結論方向反轉**

## 關鍵問題（CRITICAL）

### 1. GJR 比較結論方向反轉
- 文章：六個資產全部輸 GJR；GJR 全勝
- 實際 (results.json:qlike_table)：6/6 資產 `qlike_attn_selected < qlike_gjr`（attention QLIKE 更低，故 attention 勝 GJR）
- DM vs GJR 5/6 顯著（QQQ/GLD/TLT/EEM/IWM 全 Bonferroni-12 < 0.05，winner=Attention）；SPY 不顯著但方向也是 Attention
- 文章「黑名單級別」誤導

### 2. DM 符號解釋反向
- Code 用 `loss_model - loss_baseline` (`k189_attention_vol.py:74`)；lower QLIKE better → **正 DM = model worse**
- 文章 line 32：「DM 正號代表注意力模型相對贏，負號代表輸」**完全反向**
- 把表內負值（attention 勝 GJR）讀成負（attention 輸）

### 3. Stale 數字
- 文章 SPY DM vs GJR `-1.31`，JSON `-0.9284`
- 文章 QQQ DM vs GJR `-7.52`，JSON `-6.7304`
- 整張數字表都是舊版（pre-2026-06-11 rerun）

### 4. α 選擇描述失準
- Code 真實做法：rolling ex-ante 500 日 selection (`line 291, 302`)
- 文章：「各資產 OOS 最佳混合權重 best α=0.9」暗示 OOS hindsight selection
- 改：rolling ex-ante 選擇下 502 OOS 日有 modal α=0.9（per `alpha_selection_counts`）

## 中等問題

- 22-day rolling RV 為 proxy（非 r² 單日）未揭露；DM NW lag `n^(1/3)` 對 22-day overlap 可能 under-cover
- 文章未提 Bonferroni / BH（results.json 內有，但文章只顯示 raw t/p）

## Source code 評估
**CONDITIONAL_PASS**（2026-06-11 rerun 已修主要 lookahead + post-selection）：
- Lookahead 已 fix：EWMA/attention/GJR train slice 全 lag-1
- α 選擇已改 rolling ex-ante
- Codex 已驗 line refs：k189_attention_vol.py:126, 135, 152, 156, 247, 251, 291, 302

## 必須行動

1. **mile_48c8328b article 立即 erratum 或撤稿**：核心結論反轉 + 數字 stale + DM 符號解釋錯；研究誠實 § 6「推翻舊結論必回溯更正」強制
2. **依當前 results.json 重寫文章**：「跨資產注意力小贏 GJR 但輸給 single-asset EWMA」是新結論
3. **plot script `plot_qlike_comparison.py:30` 仍讀 `qlike_attn_0.9`**，當前 JSON 為 `qlike_attn_selected`，圖也 stale → 重生 K189 圖
4. **新文章必補揭露**：22-day RV proxy + overlap caveat + rolling ex-ante α
5. **knowledge.json 新增 K189 reviewer entry**：reviewer=codex-cli 2026-06-15, source_review=CONDITIONAL_PASS, article_review=FAIL

## Task pool 連動
- 本 review task: `paper_review_mile_48c8328b` → succeeded (verdict recorded)
- Followup: `article_rewrite_mile_48c8328b` (P1, type=daily_article 因為是 reader-facing article rewrite)
- Boss email: critical alert（已 published 文章核心結論方向反轉）
