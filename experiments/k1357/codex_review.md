# K1357 Codex Review

Review date: 2026-06-21

Verdict: PASS for research-honesty controls; empirical verdict is `EVENT_ONLY_WEAK`.

## Checks

- Proxy honesty: PASS. The script states and records that Corwin-Schultz daily high-low spread is only a low-frequency proxy, not quote-level bid/ask or RL market-maker behavior.
- Rolling features: PASS. `rolling_z_past()` computes z-scores using `x.shift(1)` before rolling moments in `K1357.py:126-130`.
- Event lookahead: PASS. The event label is shock day `t`; response uses `spread_log.shift(-1) - spread_log` in `K1357.py:187`, so the event test is forward by design.
- Forecast target: PASS. `target_rv5` is explicitly `sum(rv.shift(-i) for i in range(1, 6))` in `K1357.py:195`, i.e. `t+1..t+5`.
- Forecast predictors: PASS. HAR, VIX, volume, spread, and asymmetry predictors are all shifted in `K1357.py:222-228`.
- OOS fitting: PASS. Expanding OLS trains only on `df.iloc[:i]` before forecasting row `i` in `K1357.py:257-262`.
- Multi-asset DM: PASS. Pooled loss differentials are averaged by date before DM in `K1357.py:330-332`, avoiding the K1355 asset-day independence bug.
- Bootstrap: PASS. Event CI uses fixed `SEED=42` and 2,000 bootstrap draws in `K1357.py:342-356`.

## Result Integrity

- Event asymmetry: PASS but weak. Date-level negative-minus-positive cost-shock response is `+0.0457`; bootstrap CI `[+0.0006, +0.0896]` barely clears zero.
- Forecast gate: FAIL. Pooled QLIKE loss differential is `+0.000631` with DM `t=+0.626`, `p=0.531`; positive t means the spread-asymmetry challenger loses on average. Only 3 of 10 assets improve.
- Knowledge promotion: NOT recommended. The evidence supports only a proxy event-study clue, not a robust predictive signal or direct RLMM footprint.

## Caveats

- Daily OHLCV cannot identify reinforcement-learning market makers.
- Corwin-Schultz can be noisy for highly liquid mega-caps and misses intraday quote-depth dynamics.
- The event split is based on SPY close-to-close sign and daily VIX/volume shocks, not microstructure cost shocks observed at quote time.
