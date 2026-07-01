# Codex Review - research_quantum_reservoir_computing_for_realized_volatil

**Verdict**: PASS as a scoped reproducibility gate.  
**Claim strength**: limited to a classical echo-state reservoir proxy on daily
close-to-close public data. Do not cite this as evidence against the original
quantum reservoir computing paper.

## Checks Performed

- `uv run python -m py_compile experiments/research_quantum_reservoir_computing_for_realized_volatil/research_quantum_reservoir_computing_for_realized_volatil.py`
- `uv run python experiments/research_quantum_reservoir_computing_for_realized_volatil/research_quantum_reservoir_computing_for_realized_volatil.py`
- `jq` inspection of verdict, primary baseline, panel QLIKE means, bootstrap
  intervals, seed sensitivity, and per-asset QLIKE.
- PNG non-empty and dimensions checked with `file`.

## Review Notes

1. **Lookahead protection is explicit**: feature construction uses
   `signal.shift(1)` and `rolling(...).mean().shift(1)`. Training and scalar
   calibration use only rows before 2019-01-02.
2. **Target/model scope is honest**: the script labels the target as daily
   `r_t^2`, not high-frequency realized volatility.
3. **Primary baseline is conservative**: the gate compares the reservoir proxy
   against the best calibrated traditional benchmark among naive HAR22, linear
   HAR, and linear HARX. In this run, that baseline is `linear_har`.
4. **Calibration is train-only**: every model gets the same scalar QLIKE
   calibration estimated on the training window, avoiding a false null from
   log-variance back-transform scale bias.
5. **Randomness is pinned**: global seed is 42, reservoir seeds are fixed, and
   the target-level bootstrap uses B=1000 with seed=42.
6. **Null result is reported correctly**: reservoir seed median has mean QLIKE
   diff +0.032306 vs linear HAR and wins only 2/8 assets.

## Residual Risk

- The reservoir is an ESN-style classical proxy, not a quantum Ising Hamiltonian
  simulation.
- QLIKE on daily `r_t^2` can be noisy; a five-minute realized-volatility panel
  could change the ranking.
- Hyperparameters are fixed rather than tuned by nested validation.
- Pairwise DM tests are reported at the asset level; the primary conclusion
  relies on asset-level bootstrap and panel QLIKE, not a full model confidence
  set.
