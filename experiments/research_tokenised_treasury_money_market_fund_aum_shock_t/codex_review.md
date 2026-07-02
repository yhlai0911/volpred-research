# Codex Source Review

Review date: 2026-07-02

Verdict: `PASS_AS_SCOPED_WEAK_NULL_DIAGNOSTIC`

## Findings

No blocking source-level issues found after the alignment fix.

## Checks

- Experiment three-piece exists: `README.md`, `research_tokenised_treasury_money_market_fund_aum_shock_t.py`, and `research_tokenised_treasury_money_market_fund_aum_shock_t_results.json`.
- Data sources are explicit and cached under `data/`: DefiLlama protocol TVL, yfinance OHLCV, and FRED SOFR/IORB/WRMFNS.
- Lookahead controls are present in code:
  - Tokenised TVL signals use `.shift(1)` in lines 388-391.
  - FRED retail MMF control uses `.shift(5)` in line 351.
  - Forward targets use t+1 through t+h via `forward_sum` / `forward_mean`.
  - Expanding OOS forecast excludes train rows whose forward labels would not be observable at the forecast origin (`train_end = pos - horizon`, lines 530-536).
- Calendar alignment issue was fixed before accepting results: short-end ETF returns are computed on the ETF trading calendar, not the crypto-union calendar, preventing weekend NaNs from destroying 22-day rolling windows.
- Random state is fixed with `SEED = 42`; no randomized bootstrap is used in this version.
- Statistical gate is conservative: positive coefficient, HAC `|t| >= 3`, Holm p < 0.05, and positive OOS MSE improvement with DM t >= 3.
- Result interpretation is bounded. The script and README report `WEAK_RAW_ONLY_NO_ROBUST_OOS_PASS`, not a publishable spillover finding.

## Result Sanity

Primary result is weak/null:

- 5-day range-vol has raw positive association, but only HAC t = 2.05 and Holm p = 0.201; OOS DM t = 0.56.
- 22-day range-vol is weaker, HAC t = 1.70 and Holm p = 0.354.
- Close-to-close RV cells are negative and OOS-worse.
- Amihud liquidity-vol cells are negative and OOS-worse.

This supports only a bounded statement: public tokenised Treasury / MMF-like TVL is not a robust standalone predictor of short-end Treasury ETF liquidity-vol in this daily public-proxy design.

## Residual Limitations

- DefiLlama protocol TVL is not a complete issuer collateral ledger.
- Daily ETF OHLCV cannot observe bid-ask spreads, bill-market depth, or ETF creation/redemption flow.
- The sample is short and dominated by 2024-2026 adoption growth.
- Transaction-level RWA studies may still find collateral-flow mechanisms that this public daily proxy cannot see.
