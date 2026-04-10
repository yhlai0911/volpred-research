# K1018: Robust VT Design (K743 Corrected)

## Problem & Motivation
K743 designed a "Robust VT" with floor/cap/EWMA/weekly rebalance to protect against investor behavioral biases. Codex identified potential bugs in the floor/cap boundary implementation. K859 was a clean redo but used different EWMA parameters (span-based, not lambda-based). This experiment reimplements the Robust VT with the specific design: EWMA(lambda=0.94), floor=30%, cap=90%, weekly rebalance, and evaluates against all 14 existing strategies.

## Method
- **Baseline**: 12/VIX with cap=1.5, monthly rebalance (K687 standard)
- **Robust VT**: 12 / EWMA_VIX(lambda=0.94), clipped to [0.30, 0.90], weekly rebalance
- **EWMA**: lambda=0.94 equivalent to span ~32.3 days (vs K859's span=5/10/22)
- **Two modes**: SPY-only (VT = w*SPY + (1-w)*cash) and SPY/GLD (VT = w*SPY + (1-w)*GLD)
- **Data**: yfinance SPY/GLD/VIX, 2005-01-01 to 2026-04-10 (~5350 trading days)
- **TX cost**: 5 bps per leg per weight change
- **All signals use `.shift(1)`** for proper lag

## Key Results

### Full Sample (2006-2026)
| Strategy | Mode | Sharpe | CAGR | MDD | Calmar | Win% |
|----------|------|--------|------|-----|--------|------|
| Baseline 12/VIX monthly | SPY/GLD | 0.575 | 6.2% | -34.1% | 0.182 | 66.3% |
| **Robust VT weekly** | **SPY/GLD** | **0.594** | **6.3%** | **-35.5%** | **0.176** | **67.1%** |
| BH 50/50 | SPY/GLD | 0.597 | 6.3% | -36.8% | 0.172 | 61.3% |
| Baseline 12/VIX monthly | SPY-only | 0.324 | 4.6% | -28.3% | 0.163 | 65.4% |
| Robust VT weekly | SPY-only | 0.304 | 4.5% | -31.2% | 0.145 | 65.4% |

### COMMON_START Period (2023-01-04 ~ present)
| Metric | SPY-only | SPY/GLD |
|--------|----------|---------|
| Sharpe (with RF=4%) | 0.873 | 1.409 |
| Sharpe (no RF) | 1.260 | 1.711 |
| MDD | -12.9% | -12.1% |
| CAGR | 11.3% | 17.8% |

### 5 Listing Criteria
| # | Criterion | Result |
|---|-----------|--------|
| 1 | Same-period Sharpe >= median | FAIL (1.71 < median ~2.3) |
| 2 | Cross-OOS >= 3/5 wins vs BH | PASS (3/5 on 2y periods) |
| 3 | Codex review | Pending |
| 4 | Sensitivity +/-20% | PASS |
| 5 | MDD < -20% (COMMON_START) | PASS (-12.1%) |

### Statistical Tests
- DM test (Robust vs Baseline): t=-1.47, p=0.14 (**not Harvey-significant**)
- Bootstrap Sharpe diff: 0.019 [-0.053, 0.091] (contains zero)

### Sensitivity Analysis
All parameter variations keep Sharpe within 30% of baseline:
- floor: 0.24/0.30/0.36 -> Sharpe 0.596/0.594/0.594
- cap: 0.81/0.90/0.99 -> Sharpe 0.598/0.594/0.582
- lambda: 0.92/0.94/0.96 -> Sharpe 0.598/0.594/0.588

## Conclusions

1. **Marginal improvement over standard 12/VIX**: Robust VT Sharpe 0.594 vs baseline 0.575 (+3.3%), but not statistically significant (DM t=-1.47 << 3.0)
2. **Not competitive with existing strategy roster**: On COMMON_START, Sharpe 1.71 (no RF) is below the median of existing strategies (~2.3). Does NOT pass listing criterion #1
3. **Does pass most other criteria**: Cross-OOS (3/5), sensitivity (PASS), MDD (-12.1% PASS)
4. **Confirms K687/K697 conclusion**: VT is drawdown insurance, not alpha generator. Floor/cap/EWMA add robustness but not alpha
5. **EWMA(lambda=0.94) = similar to K859's EWMA(span=10)**: Both produce comparable results (K859 combo best Sharpe=0.579 vs K1018 0.594)

**Verdict**: Robust VT is a valid defensive variant of 12/VIX but does NOT warrant listing as a new strategy. It does not add enough value over the existing `simple_12vix` strategy already on the platform.

## Files
- `k1018.py` — Experiment script
- `k1018_results.json` — Full results with all metrics, DM tests, cross-OOS, sensitivity

## References
- K687: Post-Correction Strategy Ranking
- K743: Investor Behavior Under VT (original Robust VT)
- K846: 50/50 Triple Moat
- K859: Robust VT Clean Redo
- Moreira & Muir (2017), Volatility-Managed Portfolios, JF
- Harvey et al. (2016), t>3.0 threshold
