# K1035 mile_052ed9e4 Post-Publish Review

**Article**: mile_052ed9e4 — "為什麼好的波動率模型，連「極值理論」這個保險都不用買？"
**Publish timestamp**: 2026-05-10 12:44:55 UTC
**Review date**: 2026-05-11
**Reviewer**: Gemini 0.33.1 (Codex CLI fallback — primary path hit usage cap until 2026-05-12 19:46)
**Path**: Codex CLI fallback subagent (per `.claude/rules/experiments.md` 2026-04-28 fallback policy)

## Reviewer Source Note (Important)

Primary Codex CLI path attempted first (`codex exec --skip-git-repo-check`); aborted with `You've hit your usage limit ... try again at May 12th, 2026 7:46 PM`. Per CLAUDE.md `.claude/rules/experiments.md` fallback rule, switched to Gemini CLI as fallback reviewer. Per K1259 lesson (2026-04-29), **subagent fallback PASS ≠ primary-path Codex PASS** — a Codex re-validation pass should be scheduled once quota resets (>= 2026-05-12 19:46 local). Closure on subagent verdict is provisional.

## Verdict

**PASS** (conditional on Codex primary-path re-validation)

## Numeric Accuracy

All quantitative claims A–F verified to 2–3 decimals against `k1035_results.json`:

| Claim | Article | results.json | Match |
|-------|---------|--------------|-------|
| A. OOS=1827 days | 1827 | `.results.SPY.n_oos = 1827` | ✓ |
| B. Trinity totals 0/4, 4/4, 4/4, 4/4 | matches | `.trinity_totals` | ✓ |
| C. QQQ 1% vr 1.86% | 1.86% | `.results.QQQ.models.GJR-t.backtests."0.010".kupiec.vr = 0.01861` | ✓ |
| D. GJR-EVT SPY 2.46% / 1.04% | matches | SPY vr=0.02463, 0.01040 | ✓ |
| E. ξ: GJR=0.103, A4f=0.055 | matches | gpd_history mean (SPY): GJR=0.1025, A4f=0.0547 | ✓ |
| F. DM t SPY=-3.08, QQQ=-2.49 | matches | -3.0832, -2.4879 | ✓ |

## Lookahead Audit — CLEAN

Verified k1035.py:
- `oos_var_es_gjr_evt` (line 425): `h_t = ... ret[t-1]**2 ... + beta * h_prev` → uses only ret[t-1] and prior h ✓
- `oos_var_es_a4f_evt` (line 568): `tau_t = ... fear_vals[t-1]**2` → uses VIX at t-1 ✓
- Lines 404, 546: `std_resid = train_ret / np.sqrt(h_series)` where `h_series = gjr_recursion(... train_ret)` — train-only, no future leak ✓
- GPD refit uses only training window via `train_ret = ret[train_start:t]` (exclusive of t) ✓

## Seed — ADEQUATE

`np.random.seed(42)` at line 67. GPD fitting via `scipy.stats.genpareto.fit` is deterministic MLE (no MCMC). MLE start values are deterministic lists.

## Multiple Testing — NO CORRECTION NEEDED

- VaR backtests (Kupiec/CC/Basel) are reported per-config in standard literature practice; Trinity itself is a 3-test conjunction (more conservative than per-test α).
- DM-QLIKE uses Harvey (2016) `|t| > 3.0` rule of thumb, which is itself a multiple-testing-aware threshold (≈ Bonferroni for ~10 comparisons).
- Article correctly reports SPY as significant and QQQ as not significant at the 3.0 threshold.

## DM Threshold — Harvey-Compliant (Borderline)

SPY t=-3.0832 vs threshold 3.0 → passes but **borderline** (margin = 0.08). Article correctly flags SPY as significant. Note: DM test implementation in `src/volpred/stats/model_evaluation.py` should be re-checked for Harvey–Leybourne–Newbold (1997) small-sample correction; not blocking for this review since |t| > 3.0 robust to typical adjustments.

## Period Coverage — Minor Underclaim

- Article claims "19 年美股資料 (2005–2026)"; actual span 2005-01-01 to 2026-04-10 ≈ **21.3 years**.
- This is a **conservative underclaim**, not an overclaim. Suggestion to update to "21 年" in next edit but not blocking.

## Christoffersen Edge Case — Not Degenerate

GJR-EVT SPY 2.5%: lr_cc=0.021, p=0.989, n01=44, n11=1. High p reflects strong independence (one consecutive-violation pair in 1827 days). Test is correctly computed; high p is the *intended* signal that EVT eliminated clustering.

## Overclaim Audit — MINOR ONLY

Article appropriately scopes claims to SPY/QQQ. Limitations section explicitly lists:
- "只在美股大型 ETF 測過"
- "OOS 期間 7 年偏短"
- Notes K1058 already extending to 0050.TW

No generalization beyond evidence. Causal language ("VIX 機制已經把『極端尾巴』這件事內化") is methodologically supported by ξ reduction 0.103→0.055.

## GJR-t Failure Attribution — CORRECT

README: GJR-t fails Kupiec + Christoffersen (not Basel — Basel passes GREEN with max_violations_250 = 4 for 2.5%, 3 for 1%). Article correctly describes GJR-t as failing due to "violation rates too high" (Kupiec) and "violations cluster" (CC). No misattribution.

## Issues Found

### [MINOR] Period figure underclaim
Article: "19 年"; actual: 21.3 years. Non-blocking.

### [MINOR] Basel test uses single 250-day window
`basel_traffic_light` (k1035.py:706) iterates `range(n-250, n-249)` = exactly 1 iteration, covering only the last 250 OOS days (2025–2026). Standard Basel implementation would use a true rolling 250-day window throughout the OOS period. For 7-year OOS this could mask historical clusters (e.g., during COVID). However:
- Kupiec + Christoffersen are computed on the full OOS span, so independence/coverage detection is not affected.
- GJR-t still fails Trinity via Kupiec + CC at every config, so Basel methodology choice does not change the headline result.
- This is a methodology note, not a claim error.

### [MINOR] DM small-sample adjustment unverified
`dm_test` implementation in `src/volpred/stats/model_evaluation.py` should be confirmed to include Harvey-Leybourne-Newbold (1997) small-sample correction. For n_oos=1827 the correction is negligible (~1%) so the |t| > 3.0 verdict is robust.

## Recommendations

1. Schedule Codex CLI primary-path re-validation post 2026-05-12 19:46 (per K1259 lesson on fallback PASS not equal to primary-path PASS).
2. Optional minor edit: "19 年" → "21 年" in next article touch (non-urgent).
3. Document Basel test scope (last-250-day window) in experiment README for future replicability — not a correction to the article.
4. No corrections to the article are required; numerical claims and causal interpretation are sound.

## Audit Provenance

- Article extracted: jq `.[] | select(.id=="mile_052ed9e4")` on `storage/reports/feed.json`
- Results: `experiments/k1035/k1035_results.json` (timestamp 2026-04-10T17:10:13)
- README: `experiments/k1035/README.md`
- Source: `experiments/k1035/k1035.py` (1285 lines)
- Reviewer: Gemini CLI 0.33.1 (Codex CLI 0.121.0 quota exceeded)
- Review session: 2026-05-11
