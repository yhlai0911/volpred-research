# K1144: Paper 9 BLOCKER D1/D2 — FEZ + STOXX50E A4f Canonical Replication

## Status
Executed 2026-04-17. See `k1144_results.json` and `k1144_vs_paper9_diff.md` for verdict.

## Motivation
Paper 9 (garch-x-vix, submitted to J. Empirical Finance, commit 4e84d37f) cites:
- **FEZ DM t = 3.45** (Harvey significant) — Abstract + Table 6 + Conclusion
- **STOXX50E DM t = 3.64** (Harvey significant) — Abstract + Table 6 + Conclusion

Reproducibility audit (2026-04-17) classified these as:
- **D1**: STOXX50E t = 3.64 — closest source is K949 t = 3.84 but wrong spec/period
- **D2**: FEZ t = 3.45 — no source found at all

K1144 is the **dedicated authoritative experiment** to determine whether these numbers are:
- Correct but previously untracked (source gap only)
- Wrong (errata required)

## Spec (Exact Paper Replication)

| Parameter | Value | Source |
|-----------|-------|--------|
| Model | A4f: τ_t = θ₀ + θ₁ VIX²_{t-1}, free ω_g | main.tex Table 2 row A4f |
| Benchmark | GJR-GARCH(1,1) | main.tex Table 2 row B0 |
| OOS start | 2019-01-01 | main.tex Table 3 footnote |
| OOS end | 2026-03-31 | ~paper "2019-2026" |
| Window W | 2000 | main.tex Table 3 footnote |
| Refit | 63 days | main.tex Table 3 footnote |
| Loss | QLIKE on r² | Patton (2011) |
| DM test | Harvey HAC, Newey-West lag=floor(T^(1/3)) | Harvey (2016) |
| Harvey threshold | |t| > 3.0 | |
| VIX | ^VIX (US, not VSTOXX) | main.tex Table 6 footnote |
| Assets | FEZ (SPDR Euro STOXX 50 ETF), ^STOXX50E | main.tex Table 6 |
| Data source | yfinance | main.tex Section 3.1 |

### A4f vs K949 Differences
K949 uses:
- OOS 2016-2025 (not 2019-2026)
- log-exp spec: τ = exp(θ₀ + θ₁ log(VIX_{t-1})) — NOT A4f
- Refit every 21 days (not 63)
These differences explain why K949 FEZ t = 3.84 ≠ paper 3.45.

## Files
- `k1144.py` — main experiment script
- `k1144_results.json` — all numerical results
- `k1144_vs_paper9_diff.md` — comparison table with paper values
- `run.log` — execution log

## Key Results
See `k1144_results.json` → `summary.verdict` and `paper_comparison`.

## Decisioning Protocol
- **MATCHED** (rtol≤5%): audit D1/D2 resolved, no errata needed
- **PARTIAL_MATCH**: investigate OOS boundary or data vintage
- **NOT_MATCHED**: errata to J. Empirical Finance required (main decision for main thread)

## References
- Patton (2011). QLIKE loss. J Econometrics 160:246-256.
- Harvey et al. (2016). |t|>3.0 threshold.
- Diebold & Mariano (2002). Predictive accuracy comparison. JBES 20(1).
