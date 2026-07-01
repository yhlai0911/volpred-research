# Duplicate Task Audit — 2026-07-02

Task closed: `research_t_bill_vol_genius_act_2025_eichengreen_fire_sale`

Audit verdict: **DUPLICATE_COVERED_BY_K1586**.

## Why No New Experiment Was Created

The claimed backlog task asks for:

- stablecoin reserve / supply changes as predictors of short-end T-bill realized volatility,
- DefiLlama / CoinGecko-style stablecoin supply data,
- `DGS1MO` / `DGS3MO` realized-vol targets,
- USDC-SVB depeg event windows on `SHY` / `BIL`,
- GENIUS Act 2025 context,
- Eichengreen stablecoin-run / fire-sale motivation.

`experiments/K1586/` already implements that full scope:

- README motivation and hypotheses cover GENIUS Act, Eichengreen fire-sale logic,
  DefiLlama stablecoin supply, `DGS1MO` / `DGS3MO`, and USDC-SVB event windows
  (`experiments/K1586/README.md:10`, `experiments/K1586/README.md:15`,
  `experiments/K1586/README.md:17`, `experiments/K1586/README.md:19`).
- Data sources cover DefiLlama, FRED `DGS1MO` / `DGS3MO`, and yfinance `SHY` /
  `BIL` (`experiments/K1586/README.md:38`).
- The executable script pins sample dates, the GENIUS Act event date, USDC-SVB
  event date, and the DefiLlama/FRED endpoints (`experiments/K1586/K1586.py:52`,
  `experiments/K1586/K1586.py:57`, `experiments/K1586/K1586.py:62`).
- H1 enforces stablecoin predictor lags with `.shift(k)` for `k>=1`
  (`experiments/K1586/K1586.py:254`).
- H2 runs the USDC-SVB SHY/BIL event study with Welch and block-bootstrap gates
  (`experiments/K1586/K1586.py:296`).
- Results JSON reports `verdict=NULL_PARTIAL`, H1 null, H2 SHY pass, BIL null,
  and H3 GENIUS Act diagnostic only (`experiments/K1586/K1586_results.json:271`,
  `experiments/K1586/K1586_results.json:212`,
  `experiments/K1586/K1586_results.json:250`).

## External Spot Check

- White House fact sheet and SEC statement confirm the GENIUS Act signing date
  used by K1586: 2025-07-18.
- DefiLlama stablecoin pages/API documentation match the free stablecoin supply
  source family used by K1586.
- Eichengreen / Viswanath-Natraj stablecoin-run literature is the same
  motivation class already cited in the README.

## Closure

No code or results were regenerated. The correct action is to close the stale
backlog task as covered by K1586 and leave the separate `paper_review_mile_*`
task for the actual paper/article review lane.
