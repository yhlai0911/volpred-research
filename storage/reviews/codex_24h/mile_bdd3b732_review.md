# Codex 24h Review — mile_bdd3b732

- **Article**: `每日精選導讀｜尾部風控不是預言明天：低波動、厚尾與風險模型的煞車距離`
- **Task**: `paper_review_mile_bdd3b732`
- **Reviewed**: 2026-06-25 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **FAIL -> CONDITIONAL_PASS_AFTER_FIX**

## Summary

首版每日導讀有一個 publication blocker：它沿用了 `mile_cbf8ba62` / K802 的舊 Basel 綠燈與 Trinity PASS framing，但 K802 已在 2026-06-17 的 Codex source review 被判定 `FAIL`。失敗點不是數字抄錯，而是 Basel 交通燈口徑與 Student-t / Skewed-t VaR 標準化問題。

我已用 `scripts/publish_draft.py --update mile_bdd3b732` 走正式更新路徑，把 K802 段落改成 caveat 版本：K802 只能作為「分配假設會影響違反次數」的警示案例，不能作為 Student-t / Skewed-t 已正式通過 Basel Trinity 的證據。更正後本篇可維持 published，但 K802 本身仍需 K802-v2 重跑後才可恢復正式引用。

## Numeric Verification

| Digest claim | Source check | Status |
|---|---|---|
| `mile_566da6fe`: 低波動區間 1% VaR violation rate `4.2%` | Source article feed entry reports low-vol `(7-11%) = 4.2%` | PASS to cited article |
| `mile_b02a5722`: Normal fixed-z `33 / 2.2%`, Student-t adaptive `19 / 1.3%` | Source article feed entry reports the same table | PASS to cited article |
| K802 / `mile_cbf8ba62`: GJR Normal `9`, Student-t / Skewed-t `6` violations | K802 JSON/source article report those counts, but 2026-06-17 Codex review rejects Basel green / Trinity PASS methodology | FIXED IN DIGEST |
| K824 / `mile_328ced24`: Normal `10`, Student-t `8`, QuantReg `4`, HistSim `4` over `502` OOS days | `experiments/k824/README.md` and `k824_quantile_forecasting_results.json` match | PASS |
| K1026 / `mile_dcf3a192`: pass rates `58%, 58%, 83%, 92%, 92%` | `experiments/k1026/README.md` and the 2026-06-19 Codex review match | PASS with existing source caveats |
| K941 / `mile_daed240a`: 90% coverage CAViaR-SAV `91.2%`, Quantile RF `90.0%`, GARCH Param `88.7%`, QR-GARCH `84.6%` | `experiments/k941/README.md` and `k941_results.json` match | PASS |

## Source / Timing Notes

- K802 lookahead was not the blocker; its OOS loop uses past returns only. The blocker is regulatory/methodological: custom rate-based Basel coloring over `n=502` and unstandardized Student-t / Skewed-t quantiles.
- K824 declares `signal.shift(1)` timing and its README notes HistSim's daily update advantage versus 63-day refit for other methods; the digest keeps this as a caveat rather than claiming an absolute method ranking.
- K1026 already has a Codex `PASS with source caveats` review. The digest's broad reader-facing claim about fewer fixed distribution assumptions improving scorecard pass rate stays within that prior review.
- K941 fixed seed and article/result numbers align; the digest only cites coverage percentages, not a new strategy or trading result.

## Applied Correction

Updated artifacts:

- `storage/drafts/codex_fix_mile_bdd3b732.md`
- `storage/reports/mile_bdd3b732.json`
- `storage/reports/feed.json` entry `mile_bdd3b732`

The update:

1. Rewrote the K802 paragraph to say the distribution assumption changes the violation count, but Basel green / Trinity PASS cannot be cited pending K802-v2.
2. Rewrote the curated bullet for `mile_cbf8ba62` with the same limitation.
3. Added an errata update action `codex_review_k802_caveat`.

## Sync Verification

- Dry run passed: `uv run python scripts/publish_draft.py storage/drafts/codex_fix_mile_bdd3b732.md --update mile_bdd3b732 ... --dry-run`
- Local update wrote `storage/reports/feed.json` and `storage/reports/mile_bdd3b732.json`.
- Full `feed-sync --apply` hung after the local write, so I interrupted it and used single-article sync instead.
- Single-article Supabase upsert passed via `scripts.supabase_sync.sync_article(item, storage_dir="storage")`.
- Supabase read-back found one `articles` row with `status=published`; content contains both K802 caveat strings.

## Verdict

`FAIL -> CONDITIONAL_PASS_AFTER_FIX`.

The first published version over-inherited a known failed K802 conclusion. The corrected version no longer cites K802 as Basel/Trinity evidence and can remain published. Do not treat this review as rehabilitating K802; it only clears the daily digest after disclosure and downgrade.
