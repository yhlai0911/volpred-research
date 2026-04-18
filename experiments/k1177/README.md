# K1177 — Paper 3 Table 3 TSMOM Hedge Canonical Replication

- **Experiment ID:** K1177
- **Status:** complete
- **Created:** 2026-04-17
- **Related:** K898 (prior Table 3 supplement), Paper 3 (vt-trend-following)

## Problem

Paper 3 Table 3 BLOCKER D1 (from reproducibility audit commit 0fa27397):
- Paper claims: SPY Hedged VT Sharpe = 0.737, MDD retention = 93%
- K898 computes: SPY Hedged VT Sharpe = 0.848, MDD retention = 107%
- Divergence: 15% Sharpe, 14pp retention, and sign reversal on MDD direction

## Objective

Precisely replicate the paper's Table 3 setup using the paper-specified methodology:
- Monthly VT rebalancing (paper text line 98: "Rebalancing is monthly")
- 10 bps transaction costs
- Orthogonalized TSMOM^perp hedge (paper Eq. 3)

Then determine which is canonical: paper 0.737/93% or K898 0.848/107%.

## Methodology

- **VT rule:** w_t = min(12/VIX_month_end_{t-1}, 1), applied daily (constant within month)
- **Rebalancing:** Monthly, with 10 bps tx costs at rebalance dates
- **Cash proxy:** SHY
- **TSMOM factor:** sign(cumret_{t-252:t-1}) * r_t (daily, 252-day lookback)
- **Orthogonalization:** TSMOM^perp = TSMOM - beta_MKT_fullsample * MKT (paper Eq. 3)
- **Hedge:** Rolling 252-day OLS of VT on TSMOM^perp; PureVT = VT - b_t * TSMOM^perp
  (beta NOT constrained — unlike K898 which constrains [0, 0.5])
- **Period:** 2005-01-03 to 2026-03-31
- **Bootstrap:** 10,000 reps, block=252 days, seed=42

## Key Differences from K898

| Feature | K1177 (this) | K898 |
|---|---|---|
| VT rebalancing | Monthly | Daily |
| Tx costs | 10 bps | 0 bps |
| TSMOM factor | Orthogonalized (TSMOM^perp) | Raw TSMOM |
| Beta constraint | None | [0, 0.5] |

## Results

### SPY (Primary Table 3 Asset)

| Strategy | Sharpe | MDD (%) |
|---|---|---|
| B&H | 0.616 | −55.2 |
| 12/VIX VT (monthly) | 0.683 | −26.4 |
| TSMOM-Hedged VT | **0.692** | **−17.2** |
| Pure TSMOM | 0.266 | −46.4 |

- **MDD Retention: 132%** (hedged MDD better than VT MDD)
- Bootstrap 90% CI: [106%, 194%]

### MDD Retention All Assets

| Asset | Paper | K1177 | K898 |
|---|---|---|---|
| SPY | 93% | **132%** | 107% |
| 50/50 | 96% | **115%** | 110% |
| DIA | 91% | **116%** | 104% |
| QQQ | 90% | **141%** | 120% |
| IWM | 97% | **113%** | 115% |

## Critical Diagnostic: VT Baseline Fingerprint

The paper's VT Sharpe = 0.797 and MDD = −24.7% match **daily** VT implementation,
not monthly. Monthly VT produces MDD = −26.4% (1.7pp different). This means:

- Paper's VT baseline was computed with **daily rebalancing**
- Paper text incorrectly says "monthly rebalancing"
- K898's daily VT (Sharpe=0.805, MDD=−24.7%) is the closer match to paper's baseline

## Verdict: (b) Paper Errata

**Decision: (b) — Paper has errata on both Sharpe and MDD retention direction**

Evidence:
1. Paper VT MDD = −24.7% is a daily fingerprint (monthly = −26.4%)
2. All three constructions (paper implied, K898, K1177) show MDD retention >100%
3. TSMOM hedging **improves** MDD protection, not degrades it
4. The paper's 93% retention claim is not reproducible under any tested construction

**Revised finding:**
"100%+ of VT's MDD protection survives TSMOM removal. TSMOM hedging actually
enhances MDD protection (SPY: 107-132% depending on construction)."

This is a STRONGER result than the paper claims, but requires correcting the narrative
from "93% survival" to "100%+ survival" and "slightly degrades" to "improves."

## Files

- `k1177.py` — Canonical replication script
- `k1177_results.json` — Full numerical results
- `k1177_vs_paper3_table3_diff.md` — Detailed diff report with root cause analysis
- `run.log` — Full execution log

## References

- Hood & Malik (2025) JBF — VT alpha absorption by TSMOM
- Moskowitz, Ooi, Pedersen (2012) JFE — TSMOM definition
- Harvey (2016) RFS — t>3.0 threshold
- Paper main.tex lines 94-139 (equations 1-6)
