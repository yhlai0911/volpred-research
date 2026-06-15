# K1506 Source-Code Review

**Reviewer**: main-thread source-level audit (Codex CLI fallback — see notes).
**Date**: 2026-06-16
**Verdict**: **CONDITIONAL_PASS** (methodology clean; verdict itself is honest null/insufficient).

## Why fallback reviewer

Two `codex exec` invocations both stalled at "Reading additional input from stdin..." — the prompt was passed via `$PROMPT` heredoc variable as the positional argument and the wrapper attempted to read stdin instead, so neither call produced a verdict. Per `.claude/rules/experiments.md`, when Codex CLI is unavailable, fallback to an independent source-level audit and label `reviewer_source` accordingly. The audit below walks the same 5-point checklist intended for Codex.

## 1. Lookahead bias — PASS

| risk | location | mitigation |
| ---- | -------- | ---------- |
| z-score baseline contaminated by event row itself | `k1506.py:129` | `past = grp.iloc[:i]` is **strict** (rows j<i only). Verified by re-reading. |
| forward window includes auction day T | `k1506.py:234` | `next_idx = move_s.index.searchsorted(T + pd.Timedelta(days=1))` forces first post-window day strictly > T. `signal_lag=1` written to results.json. |
| rolling baseline window slop | `k1506.py:128, 130` | 12M*30+5 day lookback applied **before** `[:i]` slice; cutoff lower bound only restricts the start, never extends past T. |

## 2. Statistical tests — PASS

| element | check |
| ------- | ----- |
| Welch t-test | `scipy.stats.ttest_ind(weak, benign, equal_var=False)` — appropriate given unequal variances (0.0394 vs 0.0414). |
| Bootstrap RNG | `np.random.default_rng(seed)` with `seed=42` primary, `seed=43` for secondary spec — independent streams, both reproducible. |
| Bootstrap CI | `np.percentile(diffs, [2.5, 97.5])` — standard percentile method, B=5000 reps. |
| Cohen's d | pooled-stdev formula with `n-1` denominator; standard. |

## 3. Fair comparison — PASS

- `groupby("term")` in `build_signal()`: z-score baseline is per maturity bucket (10Y vs 10Y; 30Y vs 30Y) — no cross-maturity contamination.
- Weak and benign categories both pulled via the same `compute_cum_vol(move_s, T_plus_1, POST_DAYS=5)` call path — identical lag, identical window length, identical return-construction method.
- Per-maturity robustness stratification (`robustness_per_maturity` in results.json) confirms direction holds within each bucket.
- VIX-regime stratification uses VIX value AT T (`vix_s.index.searchsorted(T, side="right") - 1`) — no leakage of future VIX into regime label.

## 4. Numbers consistency — PASS (sanity)

| claim in README | results.json field | consistent? |
| --------------- | ------------------ | ----------- |
| N_weak = 26 | `n_events_weak`: 26 | yes |
| N_benign = 97 | `n_events_benign`: 97 | yes |
| Primary t = -0.468 p = 0.642 | `primary_descriptive_t`: -0.468 / `primary_descriptive_p`: 0.642 | yes |
| Secondary t = -0.773 p = 0.441 d = -0.14 | `secondary_spec_z_lt_neg1.t_stat`: -0.773 / p: 0.441 / d: -0.136 | yes |
| Bootstrap 95% CI [-0.0195, 0.0084] | `bootstrap_95ci_mean_diff`: [-0.01952, 0.00843] | yes |
| 10Y mean_weak 0.0866 mean_benign 0.0954 | `robustness_per_maturity["10-Year"]` | yes |
| Total auctions = 278 | `n_auctions_total`: 278 | yes |

## 5. Honest null reporting — PASS

- README labels the result `INSUFFICIENT_SAMPLE (primary) + FAIL (secondary)` upfront.
- Direction is explicitly noted as "**opposite** to the hypothesis"; effect size is correctly characterized as "trivial (|d| ≈ 0.10–0.14)" and "statistically indistinguishable from zero".
- No claim of MOVE leading-indicator status. No suggestion that the relationship holds in any subsample (10Y and 30Y both null).
- Alternative explanations (dealer pre-hedging per Lou-Yan-Zhang 2013) are floated as **possible**, not asserted.
- Reproducibility section gives a one-command rebuild from scratch with documented seeds.

## Minor caveats (do not block verdict)

- `compute_cum_vol` returns `sqrt(sum(log_ret²))` over a 5-day window. This is **cumulative absolute return**, a realised-vol *proxy* — not annualised RV. README correctly calls this out in the methodology table.
- Sample size: 26 weak events under z<-1.5 is below the preregistered 30-event threshold. Results are formally marked INSUFFICIENT_SAMPLE rather than FAIL on primary spec — descriptive direction is still reported for transparency.
- Per-VIX-regime split uses `min(252, max(20, len(df)//4))` rolling window for the VIX regime threshold — adaptive to sample size; sensible default for ~276 events.
- TreasuryDirect endpoint switched from `/announced` (in original task brief) to `/search` (with `dateFieldName=auctionDate`) — this is the working endpoint that returns historical fields including `bidToCoverRatio`. Verified live via curl on 2026-06-16.

## Final verdict

**CONDITIONAL_PASS for methodology**. The null finding stands.

Recommendation: do **NOT** write a PASS knowledge entry. Mark as honest null in research_program.md; the result is informative as a refutation of the simple "weak auction → dealer stress → MOVE vol" channel at daily frequency over 2015-2026.
