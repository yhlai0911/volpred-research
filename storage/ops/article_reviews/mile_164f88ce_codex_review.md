# Article Codex 24h Review — mile_164f88ce

- Article: K1529 FOMC 前後的信用債 ETF stress 沒有成為 SPY 波動率前哨
- Source experiment: `experiments/k1529_credit_spread_fomc_vol/`
- Article published: 2026-06-28 (24h-rule task created 20:10 UTC)
- Reviewer: hourly-04 main thread (fact-check vs results.json) + prior Codex review on experiment code 2026-06-17
- Review date: 2026-06-29 04:13 台灣時間

## Verdict

**PASS** — article numbers fully match `k1529_credit_spread_fomc_vol_results.json`; verdict and language are appropriately constrained.

## Number-by-number fact-check

| Article claim | results.json ground truth | Match |
|---|---|---|
| 可評估 event windows = 97 | `tests.credit_stress_event_vs_same_month_baseline.n_events: 97` | ✅ |
| event stress mean 0.000115 | 0.000115 | ✅ |
| baseline mean -0.000342 | -0.000342 | ✅ |
| diff mean 0.000457 | 0.000457 | ✅ |
| paired t = 0.3361 | 0.3361 | ✅ |
| paired t p = 0.737525 | 0.737525 | ✅ |
| Wilcoxon p = 0.340171 | 0.340171 | ✅ |
| Block-bootstrap p = 0.376623 | 0.376623 | ✅ |
| abs_orth_surprise t = 1.922914 | 1.922914262887904 | ✅ |
| credit_hyg_lqd_pre_m5_m1 t = -3.004182 | -3.004182309256302 | ✅ |
| sticky/flexible credit t = -2.074332 p = 0.038049 | -2.0743316 / 0.038048522 | ✅ |
| OOS pre-FOMC credit → SPY RV t0-t5 QLIKE -13.849% | -13.849167779524644 | ✅ |
| OOS post-response credit → SPY RV t6-t26 QLIKE +5.9212%, DM t = -1.294 | +5.921226 / DM t = -1.2939944 | ✅ |
| Bonferroni alpha = 0.0100 | 0.01 | ✅ |
| Verdict NULL_ETF_PROXY | NULL_ETF_PROXY | ✅ |

## Claim-strength gate

- ✅ 「結果是 NULL_ETF_PROXY」— matches verdict.
- ✅ 「DM t=-1.294，距離 Harvey-strength 門檻很遠」— honest framing (Harvey threshold |t|>3).
- ✅ 「Bonferroni alpha=0.0100 下不成立」— correct application.
- ✅ 「不適合直接推論到公司債微觀結構」— self-limiting boundary clearly stated.
- ✅ 「ETF return proxy，不是直接的 option-adjusted spread 或 single-name credit spread」— scope honesty.
- ✅ Caveats section discloses: surprise data ends 2023-12-13 while prices extend to 2026-06-17 (no cross-methodology mixing).

## Lookahead audit

Per pre-existing Codex review (2026-06-17, `experiments/k1529_credit_spread_fomc_vol/codex_review.md`): PASS on implementation hygiene + lookahead discipline. Article only restates these results — no new claims requiring fresh code audit.

## Anti-overclaim cross-check vs prior K

- K1529 sits in `credit_stress × event_study` cluster; no prior K claims credit ETF stress as SPY vol precursor → article correctly positions as a NULL pilot, not a contradicted prior claim.
- pre-FOMC credit negative coefficient (t=-3.004) honestly framed as mean-reversion / microstructure hint, not as tradable precursor.

## Caveats noted in article (verified appropriately disclosed)

1. ETF proxy not single-name credit / TRACE / CDS
2. SF Fed surprise CSV ends 2023-12-13
3. Daily ETF OHLC cannot test 2pm ET announcement window
4. Sector baskets too coarse for price-rigidity mechanism evidence
5. sticky-minus-flexible diagnostic not publishable after multiple-testing

## Final

- **PASS** — article does not overclaim. All numerical assertions reconcile with experiment results JSON to the printed precision. Verdict + caveat treatment is honest. No correction needed.
- No follow-up action required.
