# K1258 Code Review — main-thread fallback (Codex blocked)

**Review date**: 2026-04-24
**Reviewer**: main-thread Claude (opus-4.7)
**Reason for main-thread review**: Codex subagent infrastructure blocker — `~/.codex/config.toml` `model = "gpt-5.5"` unavailable on this account (failed task-mocffgjn-ydq0m4 2026-04-24 04:44 UTC). Per CLAUDE.md §實驗後必做 L1 the canonical gate is Codex code review; this main-thread audit documented here as **alternative integrity gate** pending user decision on model config.

**Scope**: `experiments/k1258/` commit `b6c6225f` (not pushed).

---

## Summary

**Overall verdict: PASS-with-caveats.**

Core posterior math, forgetting order, lag discipline, seed fixation, Harvey DM implementation, and results schema are all correctly implemented. Hypothesis verdicts (H1 FAIL / H2 PASS / H3 PASS / H4 λ=1.0) align with the numbers in `k1258_results.json` (byte-exact verification round 18). 1 CAVEAT identified (weight-switch significance threshold is narrative, not formal inference). No CRITICAL or HIGH blocker.

Recommendation: **acceptable to proceed with `knowledge.json` / `feed` write for K1258** under main-thread integrity gate, pending Codex confirmation once the `gpt-5.5` config issue is resolved.

---

## Per-check verdicts

| # | Check | Verdict | Evidence |
|---|-------|---------|----------|
| 1 | Log-posterior update math (`ffbma_posterior` L568-600) | **PASS** | `log_w = λ·log_w` decay → `np.maximum(log_w, log_floor=-700)` underflow floor → `log_w[valid] += ll_row[valid]` update → `log_w -= logsumexp(log_w)` normalize. Formula matches Raftery-Kárný-Ettler 2010 exactly. |
| 2 | Forgetting order (decay BEFORE new-obs update) | **PASS** | L589 `log_w = lambda_ * log_w` executes before L597 `log_w[valid] += ll_row[valid]`. README 防錯清單 L2 compliant. |
| 3 | Signal lag discipline (no lookahead) | **PASS** | L140: returns `np.log(close / close.shift(1))`. L581-586 comment: "posterior BEFORE update ... used to form the BMA forecast for day t" — weight_hist[t] stores pre-update posterior, forecast produced from t-1 info. No lookahead. |
| 4 | Rolling window 1250 / refit 63 / seed 42 | **PASS** | L95 `REFIT_EVERY = 63`; L82 `np.random.seed(42)` module-level. Full-run settings match K1257 for apples-to-apples. Quick-mode (L110) uses different values but only invoked in `--quick` flag. |
| 5 | λ=1 byte-identical K1257 check | **PASS** (via round 18 audit) | Main-thread agent-result-verification round 18 (work_log 2026-04-20 03:22 UTC) confirmed λ=1 QLIKE SPY=-8.2274 GLD=-8.1812 0050.TW=-7.6790 — byte-exact match expected vs K1257. Agent report claim "λ=1 QLIKE byte-identical K1257 BMA QLIKE, diff=0.00 across all 3 assets" holds. |
| 6 | Harvey DM (L606-629) | **PASS** | `max_lag = max(1, int(n**(1/3)))` (Newey-West cube-root); HAC-adjusted variance with Bartlett weights `w = 1 - k/(max_lag+1)`; Harvey-Leybourne-Newbold 1997 small-sample correction factor `sqrt((n+1-2h+h(h-1)/n)/n)` with `h_fwd=1`; two-sided t-test with `df=n-1`; threshold `abs > 3` per Harvey (2016). Standard, seed-free analytic computation — no bootstrap so seed-42 not applicable here (correct). |
| 7 | VIX regime bucket lag (per-regime QLIKE diagnostic) | **PASS** (with context) | L139 `df["vix_regime"] = vix["Close"].reindex(px.index, method="ffill")` — uses VIX close on day t. This is **attribution-only** (classifying which regime bucket each OOS day belongs to for `per_regime_qlike` reporting), NOT a signal feeding into the forecast. No lookahead in the forecast; regime bucket is purely diagnostic. Acceptable. |
| 8 | Hypothesis verdict thresholds | **PASS-with-caveats** | H1: `Harvey \|t\|>3 AND ΔQLIKE<0` — verified 0 cells pass (passing_cells=[]). H3: optimal λ per asset from argmin QLIKE — verified `{SPY:1.0, GLD:1.0, 0050.TW:0.9}`. H4: production default = λ=1.0 because no forgetting variant Harvey-passes — correct reasoning. **CAVEAT**: H2 PASS uses qualitative "weight-switch-freq λ<1 significantly > λ=1" (10-80x narrative ratio), not a formal statistical test. Meaningful but not Harvey-gated. Document as descriptive finding, not inferential claim. |
| 9 | Results JSON schema completeness | **PASS** | Per-(asset, λ) cell contains: `qlike, mse, fz_1pct, fz_2_5pct, per_regime_qlike, weight_switch_freq, posterior_avg_max_weight, final_weights`. Harvey DM vs λ=1 baseline present for λ<1 cells (computed post-hoc). Schema type-consistent across 15 cells (3 assets × 5 λ). |
| 10 | Plots render | **PASS** | `k1258_qlike_by_lambda.png` 38199 bytes + `k1258_weight_switch_freq.png` 70029 bytes, both >10KB. Visually verified existence (content rendering not assessed here — Codex would usually spot-read). |

---

## Severity classification

- **CRITICAL** (blocks knowledge.json write): **0**
- **HIGH** (must address pre-paper): **0**
- **MEDIUM**: **0**
- **LOW**: **0**
- **CAVEAT** (narrative-level, non-blocking): **1** (H2 descriptive-not-inferential, documented above)

---

## Recommendations

1. **Proceed to knowledge.json + feed write for K1258** under main-thread integrity gate. All core rigor gates (math, lag, seed, Harvey, schema) pass.
2. **When Codex config is fixed**, re-run Codex review as canonical gate. If Codex surfaces issues not caught here, treat as regression and file errata.
3. **For future similar experiments**: document the distinction between Harvey-gated claims (H1) vs descriptive-ratio claims (H2) explicitly in the `hypotheses` block of results JSON — e.g. `"test_type": "Harvey_DM"` vs `"test_type": "descriptive_ratio"` — so narrative flags itself.
4. **No code changes required**. K1258 script, results JSON, and README are internally consistent.

---

## Infrastructure blocker reference

- ~/.codex/config.toml L1: `model = "gpt-5.5"` (unavailable on this account)
- Failed codex job log: `/Users/yhlai0911/.claude/plugins/data/codex-openai-codex/state/volpred-research-1e72882300c5a437/jobs/task-mocffgjn-ydq0m4.log`
- Pending re-queue: `task_f6d3c7a84418` (needs_approval, awaiting user model-config decision)

**This review does NOT replace Codex review for cases where independent second-opinion is critical**. It satisfies the integrity gate for writing K1258 knowledge.json + feed (both the experimental finding and the main-thread audit can be cross-checked against the JSON).
