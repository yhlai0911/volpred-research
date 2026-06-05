# Codex 24h-rule Review — mile_b62810dd

- **Article**: 模型分數明明贏了，為什麼我們還是不敢說它有效？
- **Published**: 2026-06-05T04:01:19+00:00
- **Reviewed**: 2026-06-05T14:15 台灣時間（published+10h，符合 24h rule）
- **Reviewer**: Codex CLI (`codex exec`, ChatGPT account, default `gpt-5.4` medium)
- **Task**: `paper_review_mile_b62810dd` (hourly-14 dispatch)
- **Linked K**: K1322 (n_test=17), K1324 (n_test=18, +1 OOS day vs K1322)

## 數字一致性 verify

| 文章宣稱 | 實測 | 對照 |
|---|---|---|
| K1322 HAR QLIKE 0.170 vs RW 0.443 | `K1322_results.json`: HAR=0.16981, RW=0.44291 | ✅ |
| K1324 仍比 RW 好但變弱 | HAR=0.35335 vs RW=0.53631；DM_HLN_t 從 1.817→0.993, p=0.088→0.335 | ✅ |
| Lookahead-free（特徵全 lag 1 天） | `k1324.py::build_har_features` 用 `rv.shift(1)` + lagged rolling 5/22；target=log(RV_t)，非 lagged | ✅（更精確說：predictors 全 lag，target 不 lag） |
| 樣本不足、待觀察 | K1322 n_test=17、K1324 n_test=18 — DM p=0.335 > 0.05 | ✅ 結論強度合宜，無 over-claim |

## Codex 5 項 verdict

1. **數字一致性** — PASS
2. **Lookahead-free 描述** — PASS
3. **結論強度（Harvey 2017 / DM）** — PASS（保守 hedge 合理）
4. **K1322 0.170 vs 0.443 可驗證** — PASS（檔案存在 `experiments/K1322/`，先前主線程因 case-sensitive ls 漏看，非 blocker）
5. **整體 24h-rule** — CONDITIONAL_PASS

**OVERALL: CONDITIONAL_PASS**

## Minor follow-up（不阻塞，下次同類文章建議）

- 敘事「多等 4 個交易日」容易讓讀者誤以為 OOS 從 17→21 天，實際 K1322→K1324 的 OOS 只多 1 天（17→18）；總樣本天數 76→80。下次同類「追加交易日」文章建議明寫「總樣本 +4 天、OOS 只多 1 天」以免誤讀。

## 不做改動

CONDITIONAL_PASS 且 minor 為 narrative clarity 而非數字錯誤；不撤下文章、不改 published content（改文章發布後文字會引發 mirror sync diff，且 minor 不到該成本）。記入此 review，未來同類選材時 reviewer 自查。

## 後續

- 結案 `paper_review_mile_b62810dd` status=succeeded，本 review file 作為 audit evidence
- 不寫 knowledge.json entry（task type = published article verify，非 K-experiment 結論；本 review 已是 audit trail）
