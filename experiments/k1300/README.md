# K1300: Forgetting-Factor BMA — K1257 H3 Follow-up

[提出: Claude (autonomous backlog from research_program.md), 執行: Claude main thread]

## Motivation

K1257 standard BMA tested whether posterior-weighted combination of 6 vol-spec
candidates beats equal-weight on OOS QLIKE across SPY/GLD/0050.TW (2020-2026):

- H1 (BMA > GJR-t single best): **PARTIAL** (only GLD: t = -2.69 still < |3|)
- H2 (BMA > equal-weight, Harvey |t|>3): **FAIL** (no asset crossed threshold)
- H3 (regime weight shift): **FAIL** (posterior concentrates on a single
  winner within ~500 days, no observable regime-conditional reweighting)

Root cause for H2/H3 failure: Bayesian posterior multiplies likelihoods
cumulatively, so weights collapse to the historical best model
exponentially fast. Once concentrated, the BMA forecast is effectively a
single-model forecast and any regime-induced relative-skill changes never
propagate into the weights.

**Theoretical fix**: introduce a **forgetting factor** λ ∈ (0, 1] that
discounts past evidence in the log-posterior update:

  log w_{i,t+1} = λ · log w_{i,t} + log p(y_{t+1} | M_i, F_t)
  (followed by log-sum-exp normalization)

This is the Raftery–Kárný–Ettler (2010) "dynamic model averaging" recipe.
λ = 1 reduces to standard BMA (= K1257 baseline); λ < 1 prevents
posterior collapse and lets the weights track regime-conditional skill.

## Hypothesis

**H_K1300**: At least one of SPY / GLD / 0050.TW exhibits a λ < 1 setting
where forgetting-BMA produces QLIKE strictly below equal-weight ensemble
**and** the DM-Harvey corrected |t-stat| exceeds 3 (Harvey 2016 threshold,
matching K1257 H2 criterion).

- **RECOVERED** iff condition holds for ≥1 asset at any λ ∈ {0.95, 0.97, 0.99}.
- **CONFIRMED_FAIL** otherwise → BMA limitation is structural (set of 6
  GARCH/HAR candidates is not diverse enough for regime tracking to help)
  not solvable by forgetting alone.

## Design

| Item | Setting |
| --- | --- |
| Model pool (6) | GARCH-N, GJR-N, GJR-t, EGARCH-N, HAR-ABS, A4f-IV² |
| Assets | SPY, GLD, 0050.TW (K1257 triplet) |
| λ grid | 0.95, 0.97, 0.99, 1.00 (K1257 baseline) |
| Data span | 2018-01-01 → 2026-04-18 (post-GFC, full COVID-cycle) |
| IS train (rolling) | 1250-day window (~5y), refit every 63 days |
| OOS | 2020-01-01 → 2026-04-18 |
| DM test | Harvey-corrected (n + 1 – 2h + h(h-1)/n)/n, h = 1 |
| Bootstrap | seed = 42, B = 1000 (block bootstrap for QLIKE-diff CI) |

### Deviation from task spec

Task brief lists "HAR-RV, HAR-RV-X, GAS, Realized GARCH" in the candidate
pool. K1257 already documented that **Realized-GARCH and HAR-RV proper
require 5-min intraday data** which is not available locally for
SPY / GLD / 0050.TW; the K1257 substitution (HAR on |r| proxy, plus
A4f-IV² as IV-conditioned multiplicative model) is the production-feasible
6-model pool. K1300 inherits the same pool to keep apples-to-apples with
K1257 baseline — the only changed dimension is λ. Adding HF-data-dependent
models would change two things at once and confound the forgetting-factor
attribution.

GAS (generalized autoregressive score) is also not in K1257 nor implemented
elsewhere in the repo; adding it from scratch alongside λ-sweep would
double the scope. Deferred to potential K1300b if H_K1300 fails.

## Lookahead discipline

- Posterior `log_weights` updated at time t use only `p(y_t | M_i, F_{t-1})`
  where the predictive variance `h_i(t)` is computed from parameters fit
  on returns `[s..t-1]` (refit window strictly before t) and the recursion
  `h_i(t) = f(r_{t-1}, h_i(t-1))` — `signal.shift(1)` discipline.
- Weights used for the forecast at t are the **pre-t** posterior (set
  `weight_history[t] = exp(log_weights)` BEFORE multiplying in `log p(y_t)`).
- Seed = 42 for all random init / bootstrap.

## Success criterion

Hard gate from task brief:

```
≥1 asset has λ < 1 with DM-Harvey |t-stat| > 3 vs equal-weight
  ⇒ H_K1300 RECOVERED
otherwise ⇒ H_K1300 CONFIRMED_FAIL
```

## Outputs

- `k1300_forgetting_bma.py` — single-script λ-sweep + DM-Harvey + bootstrap
- `k1300_results.json` — per-asset × per-λ QLIKE, DM-t, p, Harvey-pass, bootstrap CI; verdict
- `k1300_qlike_lambda.png` — QLIKE-vs-λ curves per asset + Harvey thresholds
- `k1300_weights_lambda.png` — weight evolution for the best-λ per asset (illustrate non-collapse)

## References

- Raftery, Kárný & Ettler (2010) *Technometrics* — Dynamic Model Averaging with forgetting factor
- Koop & Korobilis (2012) *IJF* — DMA for inflation forecasting
- Harvey, Leybourne, Newbold (1997) — DM small-sample correction
- K1257 (this repo) — baseline standard BMA, FAIL on H2/H3

## Codex review note

Codex CLI blocked until 2026-05-13 02:46 UTC (quota window). Per
`.claude/rules/experiments.md` fallback policy (K1259/K1261/K1262
precedent), if results land before Codex unblocks, run independent
review via `feature-dev:code-reviewer` subagent. Knowledge entry must
note `code-reviewer subagent fallback` vs `Codex review` source.
