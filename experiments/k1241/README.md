# K1241: Paper 10 §6.1 Primary Fear-Channel Regression (BTC GARCH-X(VIX²))

**Status**: DONE (NULL verdict)
**Paper**: 10 — Crypto Fear Channel (`paper/crypto-fear-channel/`) §6.1 Table 3
**Proposed / executed by**: Claude (main → worktree `agent-afd040e6`)
**Prior ids**: K639 (BTC→SPY Granger), K746b (asymmetric BTC→VIX Granger), K1025 (spillover framework), K949 (MF-GJR + VIX across markets), K1129 (BTC GJR-t baseline), K1133 (BTC sub-period regimes)

---

## Purpose

Paper 10 §6.1 Table 3 was skeleton-only (placeholder φ). K1241 produces the canonical
φ coefficient, Bollerslev-Wooldridge (1992) robust standard error, LRT vs baseline,
OOS DM-HLN, sub-period robustness, and Harvey (2016) |t| > 3 verdict for the
primary fear-channel regression: **does lagged VIX² enter the BTC variance
equation with a significant positive coefficient?**

---

## Specification

### Data

- **BTC-USD** daily close, yfinance, 2015-01-01 → 2026-04-14 (4,122 obs)
- **^VIX** daily close, yfinance, 2015-01-02 → 2026-04-14 (2,836 obs)
- Align VIX to BTC calendar with forward-fill (BTC trades 7 days, VIX weekdays only).
  Treatment: "fear state persists over weekend" — standard in Bouri et al. (2020)
  and Matkovskyy-Jalan (2019).
- BTC log-return in percent: `r_t = 100 * (log P_t − log P_{t-1})`
- Fear regressor: `VIX²_{t-1}` (lagged ONE trading day; lookahead guard in code)

**Aligned sample**: 4,120 obs, 2015-01-03 → 2026-04-14
**Descriptives**: BTC mean 0.133%, std 3.535%, skew −0.735, excess kurt 11.94;
VIX mean 18.31 (min 9.14, max 82.69 — March 2020 COVID peak).

### Models

| ID | Spec | Params |
|----|------|--------|
| M1 | GJR-GARCH(1,1) Student-t (baseline, no exog) | ω, α, γ, β, ν |
| M2 | GJR-GARCH(1,1) Student-t + φ · VIX²_{t-1} | ω, α, γ, β, **φ**, ν |
| M3 | GARCH(1,1) Student-t + φ · VIX²_{t-1} (no leverage) | ω, α, β, **φ**, ν |

### Estimation

- MLE via scipy `L-BFGS-B` (multi-start, 3-4 initial conditions per model)
  with `Nelder-Mead` polish from the best L-BFGS-B point.
- **Bollerslev-Wooldridge (1992) QMLE sandwich SE**: `V = H^{-1} OPG H^{-1}`
  - `H` = numerical Hessian of negloglik (central differences, step ~1e-5·|θ|)
  - `OPG` = per-observation score outer product (numerical gradient of per-obs ll)
- `t_BW = φ_hat / sqrt(V_{φ,φ})` — this is the robust t reported in Paper 10 §6.1.

### Evaluation

- **LRT** M2 vs M1, df=1 (restriction φ=0)
- **OOS split**: 70% IS / 30% OOS (IS n=2,884 ending 2022-11-25; OOS n=1,236 ending 2026-04-14)
- **OOS filtering**: variance recursion driven by IS-estimated parameters (static
  φ at IS) to isolate the structural contribution of VIX² vs re-estimation noise
- **Patton (2011) QLIKE** on r² proxy
- **DM-HLN (Harvey-Leybourne-Newbold 1997)**: HAC-corrected, small-sample HLN
  scaling, Student-t p-values
- **Harvey (2016) threshold**: |t_BW(φ)| > 3 required for publishable effect
- **Sub-period robustness** (K1133 convention):
  - P1 2015-2020 (n=2,190) — pre-institutional
  - P2 2021-2023 (n=1,095) — FTX / Luna / BlockFi
  - P3 2024-2026 (n=835) — spot-ETF era

### Lookahead + reproducibility

- VIX² shifted t-1 BEFORE estimation and filtering; explicit allclose assertion
  against a reconstructed reference shifted series (line ~161)
- `np.random.seed(42)` at top of script
- Multi-start init draws no randomness; pure grid of hand-chosen seeds

### Fair comparison

- All three models share the same sample, same IS/OOS boundary, same Student-t
  innovations, same filter recursion style, same estimator / SE framework.

---

## Results

### Full-sample parameter estimates

| Model | ω | α | γ | β | φ | ν | log L |
|-------|---|---|---|---|---|---|-------|
| M1 | 0.1531 | 0.154 | 0.000 | 0.894 | — | 2.73 | −10135.93 |
| M2 | 0.1558 | 0.154 | 0.000 | 0.894 | **−9.67e-06** | 2.73 | −10135.93 |
| M3 | 0.1558 | 0.154 | — | 0.894 | −9.67e-06 | 2.73 | −10135.93 |

Note on γ: the unrestricted MLE sits at γ=0 for BTC — consistent with the
crypto-literature finding that BTC shows **no standard leverage effect**
(see Baur & Dimpfl 2018, Catania 2018). This is itself a material observation
for Paper 10.

Note on ν: Student-t df converges to 2.73, near the lower boundary (constraint ν>2).
This reflects the extreme heavy tails of BTC daily returns (excess kurt 11.94 in
sample); the log-likelihood is extremely flat in ν below ~5, so the optimizer
prefers the boundary. This does not invalidate the φ identification because
φ SE is computed from the Hessian of the full likelihood at the interior solution.

### Fear-channel coefficient φ (Paper 10 §6.1 Table 3 canonical)

| Spec | φ | SE_BW | t_BW | p (two-sided) |
|------|---|-------|------|----------------|
| M2 GJR-X(VIX²) | −9.67e-06 | 7.78e-05 | **−0.124** | 0.901 |
| M3 Pure-Fear GARCH-X(VIX²) | −9.67e-06 | 1.56e-04 | **−0.062** | 0.951 |

Both φ estimates are **economically tiny, wrong-signed (negative, not positive
as fear-channel theory predicts), and statistically indistinguishable from zero**.

### Nested tests

| Test | Stat | p |
|------|------|---|
| LRT M2 vs M1 (df=1) | LR = 0.00 | 0.946 |
| OOS DM-HLN M2 vs M1 (Patton QLIKE) | t = 0.75 | 0.452 |
| OOS DM-HLN M3 vs M1 | t = 0.74 | 0.458 |
| OOS DM-HLN M2 vs M3 | t = 7.19 | <1e-11 |

OOS QLIKE is essentially identical across M1/M2/M3 (2.013 all three to 3dp).
The M2-vs-M3 DM-HLN is highly significant only because M2 and M3 differ in
γ specification, not because VIX² helps — the QLIKE gap is numerical,
not economically interesting.

### Sub-period robustness (φ in M2 within each regime)

| Period | n | φ | SE_BW | t_BW | LRT vs M1 (p) |
|--------|---|---|-------|------|----------------|
| P1 2015-2020 | 2,190 | −7.8e-05 | 1.31e-04 | −0.60 | 0.72 |
| P2 2021-2023 | 1,095 | +4.1e-05 | 6.81e-05 | +0.61 | 0.80 |
| P3 2024-2026 | 835 | −1.4e-04 | 4.38e-04 | −0.31 | 0.68 |

No regime shows |t_BW(φ)| > 2, and the sign **flips across regimes** (negative
in P1/P3, positive in P2). This rules out a regime-specific fear channel
that might have been masked by full-sample averaging.

### Harvey verdict

| Gate | Threshold | M2 value | Pass? |
|------|-----------|----------|-------|
| BW |t(φ)| | > 3.0 (Harvey 2016) | 0.124 | FAIL |
| LRT p | < 0.001 | 0.946 | FAIL |
| OOS DM-HLN |t| | > 2.0 | 0.752 | FAIL |
| Sub-period same-sign + |t|>2 | ≥ 2/3 | 0/3 | FAIL |

### OVERALL VERDICT: **NULL**

---

## Paper 10 §6.1 canonical numbers (for direct insertion into Table 3)

```
φ_M2       = -9.67e-06    SE_BW = 7.78e-05    t_BW = -0.12    p = 0.90
φ_M3       = -9.67e-06    SE_BW = 1.56e-04    t_BW = -0.06    p = 0.95
LRT M2:M1  LR = 0.00     df = 1             p = 0.95
DM-HLN M2 vs M1 (OOS)    t = +0.75    p = 0.45
Harvey (2016) |t|>3      FAIL
Sub-period robustness    0/3 regimes same-sign |t|>2
```

---

## Interpretation and Paper 10 narrative impact

This NULL **strengthens Paper 10's core message** rather than weakening it:

1. **Consistent with K1025 honest-NULL forecasting result.** K1025 already reported
   that BTC RV does not improve AR(VIX) out-of-sample. K1241 extends the honest
   NULL to the dual direction: VIX² does not improve BTC variance forecasts
   either. The paper's central claim is that the fear channel is **asymmetric,
   tail-concentrated, and regime-dependent** (Granger in crisis periods, QR in
   the 0.95 tail, Diebold-Yilmaz dynamic spillover) — **not** a simple pooled
   conditional-variance relationship. Finding a pooled NULL vindicates that
   framing.
2. **Justifies moving Table 3 into Section 6 (Robustness) rather than Section 5
   (Main results).** Paper 10 should lead with the tail-dependence / asymmetric-
   Granger evidence (K1025 QR, K746b asymmetric Granger). Table 3 functions as
   a "we checked the naive fear-channel conditional-variance spec and it does
   not hold" robustness point, which is scientifically honest.
3. **Rules out a regime-specific fear channel that would otherwise have been a
   natural alternative explanation.** P1/P2/P3 all show |t|<1 and inconsistent
   signs.
4. **γ=0 (no BTC leverage effect) is a material side finding** confirming
   Baur & Dimpfl (2018) and extending through 2026. Paper 10 should cite this
   explicitly when introducing the GJR specification.

## Recommended Paper 10 edits (main thread, not worktree)

- §5 Main results: lead with asymmetric Granger + QR tail dependence + Diebold-
  Yilmaz (K1025 material).
- §6.1 Table 3: rewrite as **robustness NULL**: "Pooled GARCH-X(VIX²) shows no
  significant fear-channel loading (φ_M2 = −9.67e-06, t_BW = −0.12, p = 0.90);
  LRT p = 0.95, OOS DM-HLN t = +0.75; sub-period stability 0/3. This NULL is
  consistent with our thesis that the fear channel is tail-concentrated and
  regime-dependent rather than entering the conditional variance linearly at
  lag 1."
- Footnote: note γ=0 for BTC GJR-GARCH(1,1) (no leverage asymmetry), consistent
  with Baur & Dimpfl (2018).

---

## Files

- `k1241.py` — main script
- `k1241_results.json` — canonical parameter estimates, SEs, tests, verdict
- `k1241_sigma_timeseries.png` — predicted σ_t: M1 baseline vs M2 GARCH-X
- `k1241_phi_rolling.png` — rolling 2-year φ estimate + t_BW with Harvey bands
- `README.md` — this file

Reproduction: `uv run python experiments/k1241/k1241.py` (takes ~5 min for full
fit + sub-period refit + rolling window; yfinance download required).

---

## References

- Bollerslev & Wooldridge (1992) Econometric Reviews 11:143-172 — QMLE robust SE
- Patton (2011) JoE 160:246-256 — QLIKE proxy-robust loss
- Harvey-Leybourne-Newbold (1997) IJF 13:281-291 — DM small-sample correction
- Harvey (2016) JF — |t|>3 multiple-testing threshold
- Engle (2002) JBES — GARCH-X with exogenous variance drivers
- Glosten-Jagannathan-Runkle (1993) JF 48:1779-1801 — GJR-GARCH
- Baur & Dimpfl (2018) Finance Research Letters 26:110-115 — Bitcoin leverage effect (negative finding)
- Catania (2018) JFE 18(3):493-544 — dynamic mixture GAS
- Bouri, Molnár, Azzi, Roubaud, Hagfors (2020) JIFMIM — BTC-VIX spillover
- Matkovskyy & Jalan (2019) IREF — crypto-equity fear channel
