# K675 / mile_5ef55c52 — Post-Publish Source-Level Review

- **Article**: `mile_5ef55c52` "同樣從 5 萬美元出發，20 年後差到快 5 倍：問題常常不是你不夠會算"
- **Published**: 2026-06-12T13:01:38.458914+00:00
- **Review date**: 2026-06-13
- **Reviewer**: Codex desktop
- **Task**: `paper_review_mile_5ef55c52`
- **Linked K**: `K675`

## (A) 數字一致性 → PASS

Article claims cross-checked against [`experiments/k675/k675_results.json`](/Users/yhlai0911/Desktop/volpred-research/experiments/k675/k675_results.json):

| 文章宣稱 | Ground truth | Verdict |
|---|---|---|
| 最差一組 20 年後約 8.6 萬 | `uninformed.terminal_wealth = 85,838.30` | ✅ |
| 60/40 約 41.9 萬 | `basic.terminal_wealth = 418,927.52` | ✅ |
| VT-aware 約 22.1 萬 | `vt_aware.terminal_wealth = 221,082.73` | ✅ |
| 恐慌時慢慢加碼約 18.9 萬 | `optimal.terminal_wealth = 189,038.79` | ✅ |
| 最佳與最差差到快 5 倍 | `418,927.52 / 85,838.30 = 4.88x` | ✅ |
| 純持有 SPY 可到約 36.2 萬 | `pure_bh_spy_terminal = 361,766.19` | ✅ |
| 恐慌賣出後只剩約 8.6 萬 | `uninformed_with_panic_terminal = 85,838.30` | ✅ |
| 蒸發 27.6 萬 / 砍掉 76% | `panic_cost_dollars = 275,927.89`, `panic_cost_pct_of_potential = 76.27` | ✅ |
| 升級到基本配置可縮小約 37% 差距 | `gini_reduction_pct = 36.9` | ✅ |

## (B) Lookahead / 實作檢查 → PASS

Source-level verification of [`experiments/k675/k675_wealth_inequality.py`](/Users/yhlai0911/Desktop/volpred-research/experiments/k675/k675_wealth_inequality.py):

- `simulate_vt_aware()` uses `prev_vix = vix_series.shift(1)` and applies `prev_vix.iloc[i]` to day `i` returns. This respects `signal at t-1, return at t`.
- `simulate_optimal()` also uses lagged VIX via `shift(1)` before position sizing and reserve deployment.
- `simulate_uninformed()` triggers panic exit after the current drawdown is observed, then holds cash for subsequent days. This is path-dependent but not lookahead.
- No same-day `VIX_t × return_t` or equivalent lookahead pattern found.

## (C) 結論強度 / overclaim → PASS

- This article is primarily descriptive and does **not** claim DM / Harvey significance where none is computed.
- Narrative claims stay within what `k675_results.json` supports: behavioral cost is large, knowledge helps, and panic selling is the dominant wealth destroyer in this setup.
- The phrase "情緒紀律的權重，可能比大多數人以為的更大" is appropriately hedged and consistent with the simulated panic-cost decomposition.

## (D) Research hygiene finding → CONDITIONAL

The published article is numerically consistent, but the experiment package is not fully publication-grade:

- [`experiments/k675/README.md`](/Users/yhlai0911/Desktop/volpred-research/experiments/k675/README.md) is still a placeholder with `Status: planning` and missing motivation / method / conclusion details.
- This violates the project rule that each experiment must have a meaningful `README.md` alongside script and results for full auditability.

This is a **research-process issue**, not a published-content mismatch. It does not justify retracting or editing the article text, but it should be fixed before reusing K675 in paper-grade writing.

## Overall verdict

**CONDITIONAL PASS**

- Published numbers match the current canonical results artifact.
- No lookahead bug or unsupported significance claim found.
- Follow-up needed: complete `experiments/k675/README.md` so the experiment satisfies the three-piece audit standard.

## Recommended follow-up

1. Upgrade [`experiments/k675/README.md`](/Users/yhlai0911/Desktop/volpred-research/experiments/k675/README.md) from placeholder to a real experiment record.
2. Keep article `mile_5ef55c52` published as-is; no content correction is required from this review.
