# K1507 Codex Self-Review

Verdict: PASS

## Checks

- Lookahead: PASS. Feature construction uses daily returns through month-end t, then target is `monthly_ret.shift(-1)` for month t+1 (`k1507.py:170`, `k1507.py:171`, `k1507.py:180`). No t+1 return enters `skew_proxy_z`.
- Partial current month: PASS. The current incomplete calendar month is dropped before monthly returns are formed (`k1507.py:132`, `k1507.py:167`, `k1507.py:169`).
- Proxy disclosure: PASS. Script and results explicitly state that no option IV surface or stock-borrow fee data are used, and that `skew_proxy_z` is only a returns-only proxy (`k1507.py:3`, `k1507.py:479`).
- Cross-sectional design: PASS. Sorting, Fama-MacBeth coefficients, and rank IC all use month-level cross sections with minimum asset count checks (`k1507.py:272`, `k1507.py:297`, `k1507.py:319`).
- Inference: PASS. Monthly series use HAC t-statistics and 5,000 moving-block bootstrap confidence intervals (`k1507.py:235`, `k1507.py:257`, `k1507.py:329`).
- Overclaim guard: PASS. Verdict logic requires both negative high-minus-low spread and negative controlled Fama-MacBeth coefficient at Harvey-style t < -3 before support is declared (`k1507.py:459`).
- Reproducibility: PASS. Seed, tickers, window lengths, bootstrap reps, timing rule, and literature references are serialized in results (`k1507.py:45`, `k1507.py:467`).

## Residual Risks

- This experiment cannot test the true option-skew / borrow-fee mechanism because it lacks options and lending data.
- The ETF universe likely attenuates the hard-to-borrow effect that matters in individual-stock studies.
- Reported basket spreads are before transaction costs and should not be treated as a launch-ready strategy.
