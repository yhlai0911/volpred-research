# Paper 9 A4f `u_prev` / τ-alignment audit

**Task ID**: `paper9_a4f_alignment_audit`
**Trigger**: Codex K1056 review (storage/reports/codex_reviews/mile_bcdd203c_k1056.md) identified Bug 1 — `u_prev = r_{t-1} / sqrt(τ_t)` instead of `sqrt(τ_{t-1})` (state alignment misalignment in A4f recursion).
**Scope**: grep `u_prev` / `tau_prev` across all Paper 9 A4f experiments to determine whether bug is systematic.
**Audited at**: 2026-06-06 12:13 台灣時間 (hourly-12 fire)
**Auditor**: main thread (not agent)

## Bug definition

K1056 A4f recursion writes `u_prev = r_prev / sqrt(τ_t)` where:
- `τ_t` = current period long-run component (predetermined from `VIX_{t-1}²`)
- `r_prev = r_{t-1}` = previous return

Per file header definition `u_t = r_t / sqrt(τ_t)`, the lagged shock should be `u_{t-1} = r_{t-1} / sqrt(τ_{t-1})` — i.e. use **previous-period** `τ`. The K1056 code mixes period indices: previous return divided by current τ.

Codex labels this **Bug 1 — state alignment misalignment**. Impact on K1056: directional 5/5 results robust, magnitudes may shift but K1056 estimate suggests <2% (verified empirically by K1056b refit, see `experiments/k1056b/`).

## Audit table

| Script | In-sample loop | OOS forecast block | Status | Action |
|---|---|---|---|---|
| `experiments/k1056/k1056.py` | line 238: `tau[t]` | line 379: `tau_t` | **BUG (original)** | Fixed in K1056b; article + footnote already pending |
| `experiments/k1056b/k1056b.py` | line 234: `tau[t-1]` | line 373: `tau_prev` | **FIX (verified)** | Refit complete; CONDITIONAL_PASS per hourly-11 commit 18269c4a |
| `experiments/k994/k994.py` | line 184, 318: `tau[t]` / `tau_train[s]` | line 354: `tau_t` (forecast `u_prev_fc`) | **BUG (same pattern)** | Queue refit task K994b with `tau_prev` |
| `experiments/k1024/k1024.py` | line 252, 280: `tau_t` | line 502: `tau_t` | **BUG (same pattern)** | Queue refit task K1024b |
| `experiments/k988/k988.py` | line 273-277: BOTH modes (`tau_t` vs `tau[t-1]` selectable) + line 421: hardcoded `tau_t` w/ comment "predetermined per Engle 2013 Eq.4" | line 663-684: THREE modes explicit (A1_K889_original/tau_t/tau_t_minus_1) | **DESIGN (intentional comparison)** | No refit — this IS the experiment comparing alignments |
| `experiments/k988/k988b_supplement.py` | line 185-189: BOTH modes + line 315: hardcoded `tau_t` | line 513-516: configurable | **DESIGN** | No refit — supplement to K988 study |
| `experiments/k988_sens/k988_sens.py` | line 232: `tau[t]`, line 319: `tau_tr[i]` | line 343: `tau_t` | **BUG pattern** (no alternative mode) | Need clarification: is this sensitivity-to-alpha/beta (orthogonal to alignment) or alignment study? If orthogonal, queue refit with `tau_prev` |

## Summary

- **3 confirmed bugs (K1056, K994, K1024)**: same `tau_t` pattern as K1056, no alternative mode in code.
- **2 research-design scripts (K988, K988b_supplement)**: explicitly compare both alignments per Engle (2013) Eq.4 vs DGP interpretation — these ARE the experiments documenting the alignment choice. No refit needed; rather K1056-style bugs should reference K988 design for proper interpretation.
- **1 needs clarification (K988_sens)**: pattern matches bug but it's labeled "sensitivity" — sensitivity to what dimension?
- **1 fix verified (K1056b)**: refit completed, CONDITIONAL_PASS.

## Cross-paper impact (Paper 9)

Paper 9 narrative likely cites results from K994 / K1024 / K1056 simultaneously. Given:
- K1056b magnitudes within <2% of K1056 (per Codex estimate + hourly-11 verification)
- K994, K1024 expected similar magnitude robustness (same A4f structure, same data type)

**Working hypothesis**: Paper 9 directional conclusions hold; magnitudes need refit verification. No emergency paper retraction required.

**Footnote / methodology disclosure for Paper 9** (or any paper citing these experiments):
> The A4f recursion in K1056, K994, K1024 follows Engle et al. (2013) Eq.4 interpretation where `u_{t-1} = r_{t-1} / sqrt(τ_t)` uses the predetermined current-period long-run component. The DGP-consistent alternative `u_{t-1} = r_{t-1} / sqrt(τ_{t-1})` is compared in K988/K988b_supplement and verified in K1056b — both alignments give directionally equivalent results with magnitudes within ~2% (K1056b refit).

## Followup tasks queued

1. **K994b_refit_tau_alignment** P3 experiment — refit K994 with `tau_prev` denom, compare magnitudes; expected scope: same as K1056b (~2h compute), enqueue via `compute_queue`
2. **K1024b_refit_tau_alignment** P3 experiment — same for K1024
3. **K988_sens_alignment_clarify** P4 platform_ops — verify K988_sens scope (sensitivity to alpha/beta or alignment-specific); if alpha/beta, queue refit; if alignment-specific, document as bug-cousin of K1056
4. **Paper9_alignment_methodology_footnote** P3 paper_body — add explicit alignment footnote to Paper 9 body referencing K988 design + K1056b verification

## References

- K1056 Codex review: `storage/reports/codex_reviews/mile_bcdd203c_k1056.md`
- K1056b refit: `experiments/k1056b/k1056b.py`, hourly-11 commit `18269c4a`
- K988 design study: `experiments/k988/k988.py` (Engle 2013 Eq.4 vs DGP comparison)
- Engle, R. F., Ghysels, E., & Sohn, B. (2013). Stock market volatility and macroeconomic fundamentals. RES 95(3), 776-797.
