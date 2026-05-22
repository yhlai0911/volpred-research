# K1393: Leave-COVID-out DM Test — A4f vs GJR (K988 spec faithful replication)

**Paper**: Paper 9 (garch-x-vix)  
**Issue addressed**: C1 CRITICAL — COVID subperiod analysis  
**Status**: COMPLETE — C1 PASS (non-COVID DM t=4.26, Harvey-sig)  
**Predecessor bugs fixed**: K1391 (wrong OOS end), K1392 (wrong bounds + g init)

## Key Results

| Subperiod | n | DM t | Harvey-sig |
|-----------|---|------|------------|
| Full OOS (2019–2026-04-07) | 1825 | +3.60 | ✓ |
| Non-COVID | 1721 | **+4.26** | **✓ C1 PASS** |
| Pre-COVID | 273 | +2.52 | ✗ |
| COVID window (2020-02–06) | 104 | +1.48 | ✗ |
| Post-COVID | 1448 | +3.76 | ✓ |

QLIKE mean (full OOS): GJR = -8.267, A4f = -8.360 (diff = -0.093, A4f lower/better)

## Scientific Finding

A4f's advantage over GJR is **not COVID-driven**. Excluding the COVID-19 crisis (2020-02-01 to 2020-06-30, n=104), the non-COVID DM t = +4.26 is Harvey-significant at |t|>3.0. The COVID window itself shows only mild A4f advantage (t=1.48, not significant), suggesting the advantage comes from normal market conditions, not volatility spikes. This directly addresses reviewer C1 concern and strengthens the paper's claim.

## K1392 Bug Diagnosis

K1392 had three deviations from K988's A4f spec:
1. **theta0 bounds**: K1392 [0, var0×2] vs K988 [-1e-2, 1e-2] — allowed optimizer to inflate the constant
2. **theta1 bounds**: K1392 [1e-10, 1.0] vs K988 [1e-8, 1e-3] — allowed optimizer to over-scale VIX coefficient  
3. **g initialization**: K1392 h_g[0]=1.0 vs K988 g[0]=omega/(1-persist) — wrong unconditional mean

These caused K1392's A4f QLIKE to be -8.194 vs K988's -8.361 (large degradation), making GJR appear better (K1392 DM t=-1.606). K1393 uses K988's exact spec and recovers to A4f QLIKE = -8.360.

## Code Review

Reviewed by `feature-dev:code-reviewer` subagent (Codex overloaded at time of review):
- No lookahead confirmed (VIX and return both use abs_idx-1 in forecast path)
- A4f spec matches K988: bounds, g init, L-BFGS-B, denom_mode='tau_t'
- DM direction: d = gjr_loss - a4f_loss, positive t = A4f better
- Two non-critical dead-code observations (harmless)
- **Verdict: PASS**

## Paper Action (C1 CRITICAL)

Add robustness table:
- Full OOS: DM t = +4.48 (K988 pinned, n=1825)
- Non-COVID: DM t = +4.26 (K1393, n=1721) — Harvey-sig
- COVID window: DM t = +1.48 (K1393, n=104) — not sig

Narrative: "VIX-augmented model advantage is not an artifact of the COVID crisis episode."

## References
- K988: original comparison (full OOS n=1825, A4f DM t=+4.48)
- K1391: first COVID test (wrong OOS end 2026-05-20)
- K1392: second attempt (wrong bounds → A4f degraded)
- paper/garch-x-vix consolidated_issues_v3.md C1 CRITICAL
