# Codex Review - K1598 Online Conformal via Universal-Portfolio-Style Mixing

verdict: CONDITIONAL_PASS

## Findings

| Severity | Location | Issue | Fix / Status |
|---|---|---|---|
| MED | `k1598.py` | `UP_AggACI_lite` is a discrete Cover-style mixture over ACI experts, not the exact Liu-Dobriban-Orabona UP-OCP update. | Scope is explicit in script, README, JSON limitations, and method naming. |
| MED | `k1598_results.json` | UP-lite has only one strict cell-level win and does not beat `FixedIS` or `AggACI_grid` on aggregate mean pinball loss. | Verdict is conservative: `COVERAGE_COMPETITIVE_NO_PANEL_EDGE`. |
| LOW | `k1598.py` | The experiment uses centered absolute-return intervals rather than one-sided production VaR/ES. | README limits the claim to conformal interval calibration and calls out VaR/ES as follow-up. |
| LOW | `k1598.py` | Binomial and Christoffersen p-values are diagnostic under online conformal rather than the primary guarantee. | Primary gate is pinball-loss DM/Holm plus realized miscoverage tracking. |

## Checks

- Data provenance: uses frozen local `experiments/k1552/data/prices.parquet`; no live download.
- Lookahead control: EWMA `sigma_t` uses return `t-1`; rolling quantile uses scores through `t-1`; online updates occur after scoring day `t`.
- Metric orientation: pinball loss is computed on the standardized score quantile with `tau = 1 - alpha`; lower is better.
- Inference: paired DM/HAC uses `h=1`; Holm correction covers all UP-vs-baseline asset/alpha pair tests; Harvey |t| > 3 is required for strict wins.
- Multiple testing: 96 UP-vs-baseline tests are Holm-adjusted.
- Artifact completeness: script, README, JSON, compressed OOS forecast CSV, figure, review, and knowledge handoff are present.

## Result Integrity

Core JSON checks:

- `verdict = COVERAGE_COMPETITIVE_NO_PANEL_EDGE`
- panel cells = 24
- `UP_AggACI_lite` mean miss rate = 0.07347
- `UP_AggACI_lite` mean abs miss gap = 0.00219
- `Rolling252` mean abs miss gap = 0.00417
- `AggACI_grid` mean abs miss gap = 0.00246
- strict UP wins = 1
- strict UP losses = 0
- strict winning cell: `XLB`, alpha 0.10, UP vs Rolling252, t = -3.542, Holm p = 0.0388

The conclusion is appropriately scoped: useful coverage-stability signal, no panel-level replacement claim.
