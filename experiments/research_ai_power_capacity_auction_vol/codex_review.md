# Codex Review: research_ai_power_capacity_auction_vol

Verdict: CONDITIONAL_PASS for methodology; empirical verdict remains
`NULL_NO_ROBUST_CAPACITY_AUCTION_VOL_SPIKE`.

## Checks

- Lookahead: PASS. The script states same-day ratios are descriptive and the
  primary target is the next trading day (`research_ai_power_capacity_auction_vol.py:10`).
  Event dates are mapped to the first trading date on/after the announcement,
  then the primary target uses `trading_day_offset(..., 1)`
  (`research_ai_power_capacity_auction_vol.py:288`). Volatility baselines use
  `rv.shift(1)` and `abs_ret.shift(1)` before rolling medians
  (`research_ai_power_capacity_auction_vol.py:247`).
- Event-date hygiene: PASS with caveat. The event list uses official result
  release dates, not delivery years (`research_ai_power_capacity_auction_vol.py:61`).
  Some MISO/PJM source rows are medium-confidence or generic source-family URLs,
  so the README correctly limits the claim to a daily event-window diagnostic.
- Target consistency: PASS. Every asset group is scored against the same
  next-day squared-return ratio construction (`research_ai_power_capacity_auction_vol.py:303`)
  and then aggregated through the same group panel (`research_ai_power_capacity_auction_vol.py:353`).
- Bootstrap and seed: PASS. `SEED = 42` is fixed (`research_ai_power_capacity_auction_vol.py:44`)
  and used by `np.random.default_rng(SEED)` before matched bootstrap draws
  (`research_ai_power_capacity_auction_vol.py:477`).
- Statistical gate: PASS. The gate is pre-specified in code as mean next-day RV
  ratio `> 2.0`, one-sided matched-bootstrap `p_upper < 0.05`, and a market
  spread above `0.25` (`research_ai_power_capacity_auction_vol.py:509`). No
  group passed (`research_ai_power_capacity_auction_vol_results.json:6`,
  `research_ai_power_capacity_auction_vol_results.json:259`).
- Claim-evidence match: PASS. IPP has a large directional mean next-day RV
  ratio (`12.579`) but misses the gate with `p_upper=0.05239`
  (`research_ai_power_capacity_auction_vol_results.json:204`,
  `research_ai_power_capacity_auction_vol_results.json:212`). README reports it
  as a near miss, not a PASS.
- Reproducibility: PASS with data-source caveat. The script pins the yfinance
  end date to 2026-07-02 and writes `data/close_panel.csv`
  (`research_ai_power_capacity_auction_vol.py:45`,
  `research_ai_power_capacity_auction_vol.py:227`), but adjusted-close vendors
  can revise historical data.

## Residual Risks

- Daily close-to-close data cannot distinguish pre-close and post-close
  announcement reactions.
- The event count is only eight, so bootstrap p-values are screening evidence.
- The proxy baskets do not map companies to PJM/MISO load zones or capacity
  revenue exposure.
