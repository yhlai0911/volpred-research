VERDICT: FAIL

1. CRITICAL — same-day lookahead in every main backtest.
   Evidence: strategy weights are computed from same-day `VIX`/`VIX3M`/`sv_ratio` (`experiments/k503/k503_vix_meanrevert_strategy.py:183-275`) and then applied directly to same-day `SPY_ret` / `GLD_ret` (`experiments/k503/k503_vix_meanrevert_strategy.py:298-321`, `334-354`, `616-619`). There is no `shift(1)` or equivalent lag before multiplying weights by returns.

2. HIGH — article’s lag-control statement is false.
   Evidence: article explicitly says all strategies use `t-1` signal × `t` return (`storage/reports/feed.json:45` under “Lookahead 防護”), but the code uses contemporaneous signals and contemporaneous returns. This invalidates the article’s central anti-lookahead assurance and taints all reported performance numbers, including `12/VIX` Sharpe 1.60 and hybrid DM comparisons.

3. MEDIUM — long-horizon return claims rely on raw ETF Close, not adjusted total return.
   Evidence: data download uses `auto_adjust=False` and then backtests on `Close` for `SPY`/`GLD` (`experiments/k503/k503_vix_meanrevert_strategy.py:72-75`, `87-92`). Over 2006-2025 this understates dividend-bearing ETF returns and can distort the absolute comparison claims in the article (for example Buy & Hold SPY 8.39%, 12/VIX annual return 14.84%, and related Sharpe/MDD framing).
