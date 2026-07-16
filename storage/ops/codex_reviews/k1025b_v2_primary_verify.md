# K1025b v2 Codex primary-path verification

Reviewed commit: `be34b196644d21843a716eac01f9635a4d8635b8`

## VERDICT: PASS

No blocking defects were found. The K1259 closure gate is satisfied for knowledge entry
`e3e4b1fa`.

## Six required checks

1. **Canonical KPPS implementation — PASS.** `k1025b_v2.py` imports and binds
   `cholesky_fevd`, `generalized_fevd`, and `connectedness` directly from
   `experiments/k1025/k1025_v3.py`; it does not maintain a second implementation.
   The imported KPPS formula uses the residual covariance, MA coefficients, diagonal
   shock scaling, and Diebold-Yilmaz row normalization consistently.
2. **Buggy path is a real rerun — PASS.** `buggy_k1025b_index()` consumes the fitted
   VAR's `res.fevd()` output and deliberately repeats `decomp[-1]`; the published
   values appear only as comparison labels and verdict metadata. A fresh full-sample
   execution reproduced shape `[10,3]`, TCI `90.0238433936%`, and NET_BTC
   `-88.6240748515pp` from the pinned snapshot. Stored rolling series contain 512
   separately computed windows and independently aggregate to the reported means.
3. **Lookahead — PASS.** This is a contemporaneous/in-sample connectedness audit, not
   an OOS forecast claim. Price returns and RV20 use current and earlier observations;
   rolling windows are backward slices. There is no forward label or future-indexed
   feature. The re-pinned union-calendar alignment explicitly drops missing values
   before `pct_change`, matching the original per-ticker construction.
4. **Circular-shift null and two-sided p-value — PASS.** Shifts are sampled from
   `1..n-1`, preserve each marginal path under cyclic rotation, and break cross-series
   alignment. Focal and all-series variants are distinct. The p-value is
   `(1 + count(|null| >= |observed|)) / (B + 1)`, and the receipt records 1000/1000
   usable draws for both variants. The stored `0.004995004995...` equals `5/1001`,
   consistent with four tail exceedances plus the finite-sample correction.
5. **NET formula equivalence assert — PASS.** The executable assert compares legacy
   column-minus-row against canonical `to_others - from_others`. Fresh execution gave
   absolute error `8.8817841970e-16pp`, matching the result artifact.
6. **Claim strength — PASS.** The verdict withdraws the strong receiver claim and does
   not replace it with a transmitter claim. It distinguishes full-sample `+2.70pp`
   from rolling mean `-0.11pp`, reports 331/512 (64.648%) negative windows, and calls
   the sign unstable despite the full-sample randomization result.

## Fresh verification

- Full-sample receipt: `N=2812`, AIC lag `5`, KPPS TCI `13.7169392611%`,
  KPPS NET_BTC `+2.7047629663pp`, permutation range `3.1974423109e-12pp`.
- `uv run python scripts/experiment_gates.py run --path experiments/k1025b` — PASS.
- `uv run python -m pytest scripts/tests/test_fevd_ordering_ratchet.py -q` — 2 passed.

## Non-blocking findings

1. The result artifact stores null summaries and usable-draw counts, but not the four
   tail exceedances or the null draws themselves. The deterministic seed and pinned
   snapshot make the p-value reproducible; adding `tail_exceedance_count` in a future
   rerun would make it auditable without repeating the 1000-draw computation.
2. The internal comment above step 2 still says "identical data" while the function
   docstring, result receipt, and audit correctly say the snapshot is not byte-identical
   to the original live downloads. This stale comment does not reach the claim surface.

## Reviewed bytes

- `k1025b_v2.py`: `c7d337b2d02cfda74e85f51415bf0161df0673de4c952d7c3a5637d3efce9bec`
- `k1025b_v2_results.json`: `58a322b37a7df2d8593984a191d8d7aaaead293eb030c303665f3ee0d59a01a8`
- pinned CSV: `f0735f95bf7bab3ca5ed901eb85806bd147056e08e8e4b8e50ffb40464c5e92a`
