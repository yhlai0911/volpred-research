# Knowledge Handoff - K1598

Do not write this directly into `storage/memory/knowledge.json` without the main-thread K1259 writer gate.

## Proposed Entry

- id: `K1598`
- title: `Online conformal calibration via universal-portfolio-style mixing`
- status: `coverage_competitive_no_panel_edge`
- source_experiment: `experiments/k1598`
- data: 12 ETF adjusted closes from `experiments/k1552/data/prices.parquet`, train from 2005, OOS from 2016
- primary_result: UP_AggACI_lite improves coverage tracking versus rolling conformal and has one strict cell win, but no panel-level pinball-loss edge over ACI/AggACI.

## Evidence

- Panel cells: 12 assets x 2 alpha levels = 24.
- UP mean miss rate: 0.07347 across alpha 0.10 and 0.05 cells.
- UP mean abs miss gap: 0.00219, better than Rolling252 0.00417 and near AggACI_grid 0.00246.
- UP mean pinball loss: 0.126089, not better than FixedIS 0.125958 or AggACI_grid 0.126065.
- Strict wins: 1 (`XLB`, alpha 0.10, versus Rolling252; t=-3.542, Holm p=0.0388).
- Strict losses: 0.

## Safe Claim

UP-style expert mixing is promising as a parameter-free online conformal calibration device, but K1598 only supports a coverage-stability claim, not a robust panel-level forecasting or VaR replacement claim.

## Follow-Up

Revisit after implementing the exact UP-OCP update and converting the centered interval framework into one-sided VaR/ES backtests with A4f/GARCH/HAR scale forecasts.
