# K1598 - Online Conformal via Universal-Portfolio-Style Mixing

## Verdict

`COVERAGE_COMPETITIVE_NO_PANEL_EDGE`

UP_AggACI_lite improves coverage tracking versus a rolling 252-day conformal quantile and records one strict cell-level DM/Holm win (`XLB`, alpha 0.10, versus `Rolling252`). It does not produce a panel-level pinball-loss edge: aggregate mean pinball loss is slightly worse than `FixedIS` and `AggACI_grid`, and the implementation is a lite Cover-style mixture over ACI experts rather than the exact UP-OCP algorithm.

## Motivation

Liu, Dobriban, and Orabona (2026) connect online conformal prediction to universal portfolio algorithms. The local VolPred question is operational:

Can a parameter-free universal-portfolio-style online conformal calibrator improve volatility-scaled return intervals beyond rolling conformal and ACI baselines?

## Literature Checked

- Liu, Dobriban, and Orabona (2026), "Online Conformal Prediction via Universal Portfolio Algorithms." https://arxiv.org/abs/2602.03168
- Gibbs and Candès (2021/2024), adaptive conformal inference under distribution shift. https://www.jmlr.org/papers/v25/22-1218.html
- Cover (1991), "Universal Portfolios." https://isl.stanford.edu/~cover/papers/paper93.pdf
- Areces, Mohri, Hashimoto, and Duchi (2025), "Online Conformal Prediction via Online Optimization." https://proceedings.mlr.press/v267/areces25a.html

## Data

- Source: `experiments/k1552/data/prices.parquet`
- Assets: `SPY`, `QQQ`, `IWM`, `XLB`, `XLE`, `XLF`, `XLI`, `XLK`, `XLP`, `XLU`, `XLV`, `XLY`
- Train start: 2005-01-01
- OOS start: 2016-01-01
- Target: centered daily log-return interval
- Score: `|r_t| / EWMA_sigma_t`
- EWMA sigma: lambda 0.94, updated from returns through `t-1`

## Methods

- `FixedIS`: static in-sample score quantile before OOS
- `Rolling252`: rolling 252-day empirical score quantile using only scores through `t-1`
- `ACI_eta_0p01`: single ACI threshold update with eta 0.01
- `AggACI_grid`: exponential-loss aggregation over ACI learning-rate experts
- `UP_AggACI_lite`: Cover-style universal portfolio over ACI expert returns `exp(-pinball_loss)`

`UP_AggACI_lite` is intentionally labeled lite. It tests the portfolio-mixture idea, not the exact closed-form UP-OCP update from the 2026 paper.

## Primary Results

Panel: 12 assets x 2 alpha levels = 24 cells.

| Method | Mean miss rate | Mean abs miss gap | Mean pinball | Mean half-width | Binom pass cells |
|---|---:|---:|---:|---:|---:|
| FixedIS | 0.07124 | 0.00487 | 0.125958 | 0.022216 | 23/24 |
| Rolling252 | 0.07917 | 0.00417 | 0.127078 | 0.022114 | 24/24 |
| ACI_eta_0p01 | 0.07430 | 0.00167 | 0.126105 | 0.022066 | 24/24 |
| AggACI_grid | 0.07314 | 0.00246 | 0.126065 | 0.022142 | 24/24 |
| UP_AggACI_lite | 0.07347 | 0.00219 | 0.126089 | 0.022146 | 24/24 |

Strict UP wins after Harvey |t| > 3 and Holm 5pct:

- `XLB_a0.10_UP_AggACI_lite_vs_Rolling252`: t = -3.542, raw p = 0.000404, Holm p = 0.0388

Strict UP losses:

- none

Interpretation: UP-lite improves the unstable rolling quantile baseline, but it does not beat the stronger ACI/AggACI family at the panel level.

## Safe Claim

UP-style online mixing is a useful conformal calibration direction for VolPred because it improves coverage tracking versus rolling conformal without strict losses, but this K1598 lite implementation is not enough to replace ACI/AggACI or claim a robust forecasting contribution.

## Unsafe Claim

UP-OCP is proven superior for VolPred VaR.

That would overstate the evidence. K1598 uses centered absolute-return intervals, EWMA scale normalization, and a discrete universal-portfolio-style expert mixture rather than the exact UP-OCP algorithm or one-sided VaR/ES backtests.

## Artifacts

- `k1598.py`
- `k1598_results.json`
- `k1598_oos_forecasts.csv.gz`
- `k1598_coverage_size.png`
- `codex_review.md`
- `knowledge_handoff.md`
