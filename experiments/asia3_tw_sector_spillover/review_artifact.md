# ASIA-3 code review artifact — asia3_tw_sector_spillover

**Reviewer**: `feature-dev:code-reviewer` subagent (Claude Opus, fresh context).
**Why fallback**: Codex primary path (`codex_exec_bounded.sh`, gpt-5.6-sol) completed its
line-by-line analysis but was killed by the 480s bound exactly at the verdict-synthesis
step (no printed verdict). Per `.claude/rules/experiments.md` §Codex fallback, the
`feature-dev:code-reviewer` subagent is the accepted independent fresh-context reviewer.
Reviewer source recorded honestly (K1259 discipline).

**Dates**: reviewed 2026-07-27 (Taiwan time). Two-pass: (1) full review on pre-fix
snapshot, (2) fix re-verification on final bytes.

## Round 1 — full review (pre-fix)

VERDICT: **CONDITIONAL_PASS**. All substantive econometrics correct; one figure-only
blocking defect.

Confirmed CORRECT, item by item:
1. **GFEVD math (Pesaran-Shin)** — `ma_coefficients()` VMA recursion
   `Psi_h = sum_{m=1}^{min(h,p)} A_m Psi_{h-m}` matches statsmodels `VARResults.coefs`
   (A_1..A_p); `generalized_fevd()` matches
   `theta_ij = sigma_jj^-1 sum_h (e_i'Psi_h Sigma e_j)^2 / sum_h (e_i'Psi_h Sigma Psi_h' e_i)`
   with row-normalization. No Cholesky — order-invariant.
2. **Axis orientation** in `connectedness()` correct (row=explained, col=source;
   from=row off-diag, to=col off-diag, net=to-from). `net_pairwise` satisfies
   `sum_j net_pairwise[i][j] = net[i]`.
3. **DY /N normalization** internally consistent; `net_pct` matches README to 2 dp.
4. **Lookahead discipline** in `oos_var_vs_ar_dm()` — `train=arr[:t]` ends t-1; manual
   VAR one-step forecast matches statsmodels `forecast()`; AR design matrix
   `train[lag-m:len(train)-m, j]` verified index-by-index (no off-by-one); AR/VAR share
   lag; loss aggregated by date before DM (K1355); canonical `dm_test` (Newey-West HAC).
5. **Garman-Klass invariance** claim correct (within-day ratios only).
6. **Overclaim check** — README numbers match JSON byte-for-byte; small net magnitudes,
   pooled bear-vs-calm reframed as window-length artifact, and OOS null are all honestly
   hedged. No overclaim.

BLOCKING #1: `plot_network()` drew pairwise arrows backwards (receiver→transmitter).
Numbers unaffected (figure-only). MINOR #1: OOS lag chosen with full-sample AIC then
reused (below reporting bar; comparison stays fair since VAR/AR share the lag).

## Fix applied

- `plot_network()` edge-direction branches swapped: `npw>0` now appends `(a,b)`
  (a transmits to b), comment corrected; `assets/spillover_network.png` regenerated.
- `lag_caveat` field added to `oos_var_vs_ar_dm()` return (documents MINOR #1).
- README limitation #7 added (same caveat).
No numbers changed.

## Round 2 — fix re-verification (final bytes)

VERDICT: **PASS**.

- Edge direction re-derived independently and confirmed: `net_pairwise[a][b] > 0` ⟹ a is
  net transmitter to b ⟹ branch appends `(a,b)` = arrow a→b (transmitter→receiver).
- Cross-checked JSON: `net_pairwise_pct["TSMC(Semi)"]["HonHai(EMS)"]=+0.2267` → arrow
  TSMC→HonHai (transmitter→receiver). Correct.
- Regenerated PNG visually re-opened: all arrows point from red (transmitter) into blue
  (receiver) nodes. Consistent with legend.
- `lag_caveat` + README #7 are non-functional documentation additions; no new risk.

**FINAL VERDICT: PASS** — GFEVD math, DY normalization, lookahead discipline, GK
invariance, README/JSON fidelity all correct; the one blocking defect fixed and
re-verified; no blocking issues remain.
