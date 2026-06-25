# Codex Source Review - K1552

Verdict: `CONDITIONAL_PASS` for source integrity; empirical verdict remains `NULL_AMPLIFICATION_WITH_OPPOSITE_RALLY_DECOMPRESSION`.

Checks performed on 2026-06-25:

- Required artifacts exist: `README.md`, `k1552.py`, `k1552_results.json`, figures, and data audit outputs.
- Lookahead guard is explicit: `loss_memory_raw` / `rally_memory_raw` are converted to predictive variables via `.shift(1)`.
- The episode library for date `d` ends at `d-22`, so the current 21-day cue is not compared against overlapping current-window episodes.
- A first-pass source review caught and fixed a forward-target leakage risk: `log_fwd5_rv` no longer uses `log_fwd5_rv.shift(1)` as a control; it uses `log_past5_rv_lag1`, which is built only from returns through `t-1`.
- Random procedures use `SEED = 42`; bootstrap uses 1000 moving-block reps.
- The script does not edit `storage/memory/knowledge.json`, Supabase, Mirror, or feed files.

Residual limitations:

- The signal is a public-market proxy, not investor recall or account-level transaction data.
- The experiment cannot identify the psychological mechanism; it only tests whether a similarity-based public cue has predictive content in sector ETF OHLCV.
- The significant aggregate results are opposite-direction rally effects, so no article or knowledge entry should present K1552 as support for volatility amplification.
- Per-ticker tests are secondary diagnostics and should not be cited without a follow-up multiplicity-controlled design.

Promotion guidance: knowledge entry may record the null/opposite proxy result after the canonical writer/gate, but it should not be used as a positive behavioral-volatility claim.
