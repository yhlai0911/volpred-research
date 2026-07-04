# K1621 — Self-review / methodology audit

**Verdict reviewed:** NULL. **Reviewer:** `feature-dev:code-reviewer` fresh-context
subagent (Codex CLI quota-exhausted until 2026-07-07 → sanctioned fallback per
`.claude/rules/experiments.md`). Overall: **PASS** (7/7 audited dimensions, high
confidence). Full audit summary below.

## Audit checklist

| # | Item | Result | Evidence (k1621.py) |
|---|---|---|---|
| 1 | **Lookahead** | PASS | `forward_rv` target = `mean(rv_d[i+1..i+H])` (L189-202); expanding refit `train_hi = i - H`, slice `X[:train_hi]` → largest admissible `j = i-H-1`, `j+H = i-1 < i` (L278-289). HAR + EMB-RV features are trailing `.rolling()` only (L175-186), no forward shift. `oos_start=2017-02-06` matches `min_train=500`+warm-up arithmetic. |
| 2 | **QLIKE direction** | PASS | imports `qlike_pointwise` from `volpred.stats.model_evaluation` (L69), canonical `actual/predicted − log(actual/predicted) − 1`; not reimplemented, not reversed. |
| 3 | **K1355 cluster-robust** | PASS | `_pool_by_date` groupby-date-mean → DM-HLN on date series (L315-323) = `primary_date_aggregated`; stacked asset-day only diagnostic, tagged `"NOT a primary claim (K1355)"` (L461-467); verdict reads primary only (L527-538). |
| 4 | **DM-HLN horizon** | PASS | `H=5` passed to every `dm_hln` call (per-asset/pooled/regime/OAS); HLN correction factor `sqrt((T+1-2h+h(h-1)/T)/T)` + `t(T-1)` ref (L213-239) matches HLN 1997. No h=1 mismatch. |
| 5 | **Seed** | PASS | `SEED=42; np.random.seed(42)` (L72-73). OLS via `lstsq` deterministic; no bootstrap/MC in Phase-1 scope. |
| 6 | **Variance positivity / bias corr** | PASS | `resid_var` from training residuals only (L286); `exp(yhat + 0.5·resid_var)` (L289) + `clip(lower=EPS)` (L292) → strictly positive, no test leakage. |
| 7 | **Other correctness** | PASS | CCF sign convention verified algebraically (L300-312); DM-HLN degenerate-variance → NaN guard (L231-233); headline numbers in README/results.json match code-produced values to displayed precision (n_dates/n_asset_days/regime splits self-consistent). |

## Non-blocking observations (disclosed in README Limitations §5-6)

1. **EMB tail data gap (~33 trading days)** → primary `oos_end=2026-05-15` not
   `2026-07-02`. Silently trimmed via `dropna` on `base ∩ aug`. Reduces OOS n, does
   not bias the null sign.
2. **OAS T+1 as-of dating** → possible minor look-ahead confined to the secondary,
   already-underpowered OAS test; already negative (−17.2%, NS), so a leak would
   only flatter it — cannot rescue the null.

## Bottom line

The NULL verdict is code-derived, lookahead-safe, and uses the canonical QLIKE +
K1355 date-aggregation conventions correctly — trustworthy to record in the
knowledge base. The two observations warrant the disclosed one-line notes but do
not change the conclusion.
