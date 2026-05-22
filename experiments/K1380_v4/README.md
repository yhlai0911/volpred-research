# K1380_v4 — Paper 9 White RC / Hansen SPA Test (3-Strike Refactor)

## Background

K1380 failed 3 times with `n_valid=0` due to joint mask logic. This is the mandated 3-strike
refactor with root-cause fixes.

**Three-Strike trigger**: K1380 v1/v2/v3 all produced `n_valid=0` because `np.all(..., axis=0)`
required ALL 17 models to have non-NaN forecasts at the same OOS step. When any MIDAS model
failed to converge at certain refit windows, the joint mask collapsed to empty.

## Root-Cause Fixes Applied in v4

| # | Fix | Root Cause |
|---|-----|-----------|
| 1 | Per-model valid_i masks (not joint valid_all) | Joint mask: any MIDAS NaN → zero valid obs |
| 2 | SPA/RC restricted to specs with coverage ≥ 95% | Ineligible models polluted joint mask |
| 3 | Per-model NaN/coverage diagnostic prints | Silent failure: only showed aggregate n_valid=0 |
| 4 | MIDAS B-series lag matrix via slicing (no np.roll) | np.roll wraps first K rows with tail data |

### Fix 4 Detail: np.roll lag matrix bug

**Old code** (K1380):
```python
lv_mat = np.column_stack(
    [np.roll(tr_lv, k+1)[(K+1):] for k in range(K)]
)
tr_ret_k = tr_ret[(K+1):]
```
`np.roll(tr_lv, k+1)` wraps around: first k+1 positions contain tail data.
Taking `[(K+1):]` removes only K+1 rows — lag K-1 (k=K-2, shift=K-1) still has 1 contaminated row at position 0. Off-by-one on row count too: gives `ntr-K-1` rows instead of `ntr-K`.

**Fixed code** (K1380_v4):
```python
lv_mat = np.column_stack([tr_lv[K-1-k:ntr-1-k] for k in range(K)])
tr_ret_k = tr_ret[K:]
```
Column k = lag k+1: `tr_lv[K-1-k : ntr-1-k]`. No wrapping, correct `ntr-K` rows.

## Method

- Same 17-spec horse race as K1380 (A1-A5, A2f/A4f/A3f/A2n/A4n, B1-B3, C1-C3, B0)
- OOS: 2019-01-01 onward, rolling W=2000, refit_every=63
- Per-model valid masks for QLIKE; SPA uses intersection of ≥95%-coverage specs
- Stationary bootstrap B=499, seed=42
- Harvey threshold |t| > 3.0

## Success Criteria

- `n_valid_spa > 1500`
- `≥ 12/17 models with coverage ≥ 95%`
- Script completes without `n_valid=0` error

## Output

- `k1380_v4_results.json` — SPA/RC test results + per-model coverage
- `k1380_v4_losses_all.npy` — (17, n_oos) QLIKE loss matrix

## Paper Linkage

**Paper 9** (`paper/garch-x-vix/`), Critical Issue C3:
> "17-specification ranking requires multiple testing correction (White RC / Hansen SPA)."

K1380_v4 resolves C3 by providing valid SPA + RC test results under corrected per-model masks.

## Related

- K1380 (original, 3× failed), K988 (GARCH-X horse race baseline)
- Triggered: `3-strike trigger 2026-05-22` per CLAUDE.md Three-Strike Rule
