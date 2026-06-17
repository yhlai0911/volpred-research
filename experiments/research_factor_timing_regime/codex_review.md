# Codex Review — research_factor_timing_regime

- Date: 2026-06-18 Asia/Taipei
- Reviewer: Codex CLI
- Verdict: CONDITIONAL_PASS methodology; empirical result NULL

## Scope

Reviewed `research_factor_timing_regime.py`, `research_factor_timing_regime_results.json`, and `README.md` for:

1. Lookahead / target alignment
2. Fair comparison across EW, momentum, and ElasticNet regime timing
3. Transaction-cost and turnover accounting
4. DM / bootstrap implementation
5. Result-to-claim consistency

## Findings

### PASS — Lookahead guard

- Features at month `t` are computed from monthly data available at month-end `t`.
- Model training for forecast date `t` uses `panel[panel["date"] < dt]`, so the newest target return in training is `(t-1)->t`, observable at allocation time.
- Weights formed at month-end `t` are applied to `t+1` returns in `simulate_strategy`.
- Current partial month is dropped after `resample("ME")`, so 2026-06-17 data is not treated as a full June monthly return.

### PASS — Fair comparison

- All strategies share the same factor ETF monthly return matrix.
- EW, momentum, and ElasticNet differ only by weight formation rule.
- Cost rate is applied consistently through turnover.

### PASS — Statistical tests

- DM uses `volpred.stats.model_evaluation.strategy_dm_test` on net monthly returns.
- Bootstrap is stationary bootstrap with B=1000, mean block=6 months, deterministic seed.
- No Python `hash()` seed dependence.

### CONDITIONAL — Transaction-cost approximation

- Turnover uses target weights versus drifted prior end weights, which is materially better than target-to-target turnover.
- It still assumes a flat 10 bps one-way cost for all ETFs and ignores bid/ask spread time variation and tax friction. This is acceptable for a first-pass turnover/cost audit but not for product-level implementation.

### CONDITIONAL — Model specification

- ElasticNet alpha/l1_ratio are fixed rather than nested-walk-forward tuned. This avoids CV leakage but means the "high-dimensional" model is a conservative single-spec probe, not an optimized model class.
- Factor ETFs are investable proxies, not academic long-short factor portfolios. The result should be framed as ETF-level factor rotation, not a universal factor-premium theorem.

## Result Consistency

The README matches results JSON:

- EW net Sharpe 0.799.
- Momentum top-3 net Sharpe 0.867 but DM p=0.529 and bootstrap CI crosses zero.
- ElasticNet regime top-3 net Sharpe 0.643, turnover 0.706/month, annual cost drag 0.85%.

The stated empirical verdict `NULL` is supported: no timing strategy clears Harvey `|t|>3` or bootstrap CI > 0 versus EW after costs.

## Required Caveats

- Do not market this as a rejection of all factor timing. It rejects this ETF-level, monthly, free-data ElasticNet/regime timing specification.
- Do not claim momentum timing passes statistically; it is directionally positive only.
- Any publishable article should emphasize turnover/cost and the simple-baseline lesson.
