# Codex 24h Review — mile_082f0578 (K1559)

- **Article**: 交易量歸零那天，薄市場 ETF 後面 22 天更容易出事
- **Task**: `paper_review_mile_082f0578`
- **Reviewed**: 2026-06-29 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **PASS with caveats**

## Summary

這篇一般讀者版文章和 K1559 canonical source 對齊。文章把結論限制在薄市場 ETF 的零成交 / 價格停滯資料痕跡，並明確說這是風控 watchlist 與 liquidity-risk prior，不是買賣訊號或 universal ETF rule。樣本數、事件數、QAT/KSA/UAE concentration、missing row 只有 1 筆、以及資料來源都和 `k1559_results.json` / README 一致。

主要 caveat 是措辭層級：文章中「補跌、跳空或重新定價」是給一般讀者的風險描述，來源有 gap22 與 dd22 檢定支撐，但不能讀成方向性 alpha 或可交易預測。文章後段已明確否定買賣訊號，因此不需要更正。

## Numeric Verification

| Article claim | Source | Match |
|---|---|---|
| 28 檔 ETF | `README.md` / universe count | yes |
| Sample request 2014-01-01 to 2026-06-29 | `README.md` / `details.sample_period_requested` | yes |
| Estimation rows = 86,148 | `summary.primary_tests[0].n` / README | yes |
| Any data-quality events = 335 | `event_counts` / README key counts | yes |
| Zero-volume events = 306 | `event_counts` / README key counts | yes |
| Stale-price events = 322 | `event_counts` / README key counts | yes |
| Missing rows = 1 | `summary.missing_rows_total` | yes |
| QAT any DQ N = 172, 22d RV ratio = 1.47, gap = 19.8% vs 6.1% | README concentration audit | yes |
| KSA any DQ N = 87, 22d RV ratio = 1.35, gap = 26.4% vs 7.4% | README concentration audit | yes |
| UAE any DQ N = 72, 22d RV ratio = 0.74, gap = 2.8% vs 11.0% | README concentration audit | yes |
| Missing rows alone are not identified | `summary.missing_rows_total=1`; formal tests skipped for too few events | yes |

## Findings

No blocking or major findings.

1. **Lookahead framing is correct** — article timing paragraph; `experiments/k1559/k1559.py:150`
   Forward targets start from `returns[i + 1 : i + 1 + h]`, so same-day returns are not included in fwd RV, gap, or drawdown targets. The article's "signal uses data visible after day t; future risk starts next trading day" framing is accurate.

2. **Core conclusion stays conditional** — article opening, event-count paragraph, and final investment paragraph; `experiments/k1559/k1559_results.json:summary.verdict`
   Source verdict is `CONDITIONAL_PASS`, not broad PASS. The article says the result is narrow, concentrated in thin country ETFs, not missing-row evidence alone, and not a tradable alpha signal.

3. **Controlled-test description is source-aligned** — article control paragraph; `experiments/k1559/k1559.py:294`
   Source uses asset fixed effects plus lagged 22d RV, dollar volume, price, and SPY absolute return controls with HAC standard errors. The general-audience wording "經過流動性、近期波動與大盤同日波動等條件控制後" is accurate.

4. **Concentration caveat is prominent enough** — article QAT/KSA/UAE paragraph; `experiments/k1559/README.md`
   The strongest evidence is concentrated in QAT and KSA, while UAE goes the other direction. The article presents all three and explicitly says the rule is not universal.

5. **Minor caveat: downside wording should not be read as directional alpha** — article phrase "補跌、跳空或重新定價"; `formal_tests` includes `gap22_5pct` and `dd22_10pct`
   The phrase is acceptable because K1559 includes forward gap and drawdown risk tests, but the underlying strongest result is volatility/gap risk, not a signed return forecast. The article's final "不適合直接當買賣訊號" sentence prevents overclaim.

## Source-Code Audit

- PASS — event flags are same-day data-quality states, not future outcomes; see `experiments/k1559/k1559.py:221`.
- PASS — forward targets use t+1 windows only; see `experiments/k1559/k1559.py:150`.
- PASS — too-few-event guards prevent missing-row formal tests from being treated as identified; see `experiments/k1559/k1559.py:309`.
- PASS — Holm correction is applied to the event-target family; see `experiments/k1559/k1559.py:541`.
- PASS_WITH_CAVEATS — binary targets use linear probability models with HAC standard errors, matching the prior `experiments/k1559/codex_review.md` residual-risk note.
- N/A — The article does not make QLIKE, DM, Harvey, Sharpe, VaR, or strategy-performance claims.

## Verification Commands

```bash
uv run python -m py_compile experiments/k1559/k1559.py
```

Additional deterministic checks run during review:

- `audit_content_provenance(content, ["K1559"])` returned no tier-1 findings.
- `audit_image_urls(content)` returned `broken=[]` for both embedded Supabase image URLs.
- `_audit_general_content("general", tags, content)` returned no general-audience issues.
- `verify_article_live("mile_082f0578")` returned `True`.

The full K1559 experiment was not rerun during this article review because it fetches yfinance vendor data and would risk overwriting canonical artifacts. Existing canonical results, source code, review notes, figures, public image URLs, and the live article page were inspected.
