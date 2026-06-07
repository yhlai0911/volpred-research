# BTC-GAS Paper — Review Round v1 (R0 → R1 transition)

**Date**: 2026-06-07 16:14 台灣時間
**Stage**: R0 first-round review (body_v1.md, ~12,167 words, 9 sections)
**Owner**: hourly-dispatch-16 (autonomous)
**Inputs**: `paper/btc-gas-negative/drafts/body_v1.md` + sectional drafts

## Reviewers

| Reviewer | Output | Verdict |
|---|---|---|
| latex-academic-reviewer (sonnet medium) | [latex_academic_review.md](latex_academic_review.md) | **MAJOR_REVISION** |
| citation-verifier (sonnet medium) | [citation_verification.md](citation_verification.md) | **PASS** (1 typo, 3 missing bib entries, routine cleanup) |

## 合成判定

**Overall**: **MAJOR_REVISION** — paper 核心方法論與數據完整可審，但**3 個 SEVERE issue 必修**才能推進 R1。

### SEVERE（R1 前必修）

1. **S1 — Period 3 OOS 日期完全錯**: 內文寫「2024-01-21 → 2024-04-30」，實際 JSON OOS window 是 **2026-01-05 → 2026-04-14**（sub-period 從 2024-01 起算但 750-day warm-up 後 OOS 才開始 ~2026 Q1）。「spot-ETF era performance」全段需重新 frame 為「2026 Q1 OOS within spot-ETF sub-period」。
2. **S2 — ν > 30 機制描述錯**: Section 6 寫 MS-GAS-t 高波動 state 被推至 ν > 30（≈ Normal），但 ms_fit_log 顯示**全 Period 1 windows max ν ≈ 15.5**，無 state 接近 30。Regime-switching 的 mechanistic explanation 需重寫。
3. **S3 — Threshold 內部矛盾**: Section 3.6 寫 Harvey-Liu-Zhu threshold |DM| > 3，Table 1 注寫 |t| > 2。兩處統一。

### MAJOR（R1 應修）

- **M2 — 70/30 attribution 算術錯**：正解 76%（innovation factor）/ 24%（dynamics factor），不是 70/30
- 其餘 4 項 MAJOR 詳見 latex_academic_review.md（M1, M3-M5）

### Citation 端

- **0 hallucinated**: 21 in-text + 16 bib seed 全 verifiable
- **1 typo 必修**：Table 1 footnote line 338 「Newbould」→「Newbold」(HLN 1997)
- **3 missing bib**: Hamilton (1989), Harvey (2017 JF Presidential), Blasques-Koopman-Lucas 系列 — R1 補
- **9 bib 缺 DOI** + **APA author order**（Welch/Goyal）+ **truncated journal**（Hansen 2003 全名）— routine cleanup

## 下一步（R1 任務建議）

1. 派 `BTC_GAS_R1_fix_severe` (paper_body, opus high) — 主線程處理 S1/S2/S3 + M2 數字校正 → body_v2.md
2. 派 `BTC_GAS_R1_bib_cleanup` (paper_review, sonnet low) — 補 3 missing bib + 9 DOI + APA 修正
3. R1 完成後再跑一輪 paper-review-cycle 確認 SEVERE 全 cleared

## 強項（reviewer 共識）

1. 13 個 headline statistics 全對 `experiments/k1133b/k1133b_results.json` 逐項驗證（皆 match to 2 d.p.）— 內部一致性高
2. 方法論 exemplary（lookahead 處理、multistart、cross-period robustness）
3. Negative result framing 接近 Harvey (2016) 嚴謹度
4. Citation 池小而 clean（無造假）

## Audit trail

- 兩 reviewer 並行 dispatch (2026-06-07 16:08 台灣時間)
- latex review: 97506 tokens, 266s
- citation verify: 92390 tokens, 280s
- Total review effort: ~190K tokens / ~9 min wall
