# Paper 2: Earnings-Announcement Volatility Amplification — Universal-Magnitude Evidence from Taiwan and U.S. Equity Markets

**Working Title**: Earnings-Announcement Volatility Amplification: Universal-Magnitude Evidence from Taiwan and U.S. Equity Markets
**Target Journal**: Journal of Empirical Finance | Finance Research Letters (backup)
**Status**: scaffold (paper_decision confirmed 2026-04-17; kickoff 2026-05-17)
**Decision Record**: Option 4+ (K1149 Scenario A) — universal-magnitude is a true firm-event effect orthogonal to the market factor

---

## Core Claim

Earnings announcements produce a **universal, market-magnitude spike in conditional volatility** (θ_EAV = +6.36×10⁻⁵, cluster-bootstrap t = +5.24) that is:

1. **Consistent across markets** (TW IS + US OOS, both binary-indicator spec)
2. **Orthogonal to market-stress factor** (survives PCA factor absorption, K1149 Scenario A)
3. **Best captured by a binary indicator** — continuous |surprise| adds no predictive value OOS (K1148)
4. **Not firm-size driven** — firm-characteristic heterogeneity rejected (K1148_d3)

---

## Model Specification

**Multiplicative GARCH-EAV** (per-stock GJR × pooled shared τ):

```
σ²_{i,t} = g_{i,t}(ω_i, α_i, γ_i, β_i) × τ_t

τ_t = θ₀ + θ_VIX·VIX²_{t-1} + θ_EAV·EAV_{i,t-1}
```

where EAV_{i,t} = 1 if firm i announces earnings on day t, else 0.

**Estimation**: Pooled MLE with stock fixed effects (m_i); per-stock GJR parameters + shared τ parameters. Cluster bootstrap (n=150 stock-level) as primary SE.

---

## Key Empirical Results

| Experiment | Market | IS/OOS | Spec | θ_EAV | Inference |
|-----------|--------|--------|------|-------|-----------|
| K1145 | TW (N=31) | IS | Binary | +6.36e-5 | bootstrap t=+5.24; placebo +13.6σ |
| K1148 | TW (N=29) | IS | Continuous | sig (Hessian t=10.4) | OOS DM t=-1.16 NS; binary preferred |
| K1148_d1 | TW (N=29) | OOS | Binary | — | TW OOS noise (US cross-market validates) |
| K1148_d2 | US (N=30) | OOS | Binary | — | DM t=-5.58 PASS; Harvey \|t\|>3.0 ✓ |
| K1148_d2 | US (N=30) | OOS | Continuous | — | DM t=-5.25 PASS; binary marginally stronger |
| K1149 | TW+US | IS+OOS | Binary+PC1 | — | Scenario A: factor absorption PASS (both markets) |

---

## Paper Structure (working outline)

1. Introduction — EAV anomaly, universal-magnitude claim, contributions
2. Model — Multiplicative GARCH-EAV specification, pooled MLE, identification strategy
3. Data — TW TWSE bluechips (N=29-31, 2010-2025), US S&P500 large-caps (N=30, 2014-2025)
4. Taiwan In-Sample Evidence (K1145) — pooled θ_EAV, bootstrap, placebo tests
5. US Out-of-Sample Validation (K1148_d2) — cross-market OOS DM test (binary + continuous)
6. Factor Robustness — PCA absorption test, Scenario A narrative (K1149)
7. Robustness Battery — drop-5-stocks stability, 3-EAV-def monotonicity, binary-vs-continuous
8. Conclusion

---

## Supporting Experiments

| K | Role | Status |
|---|------|--------|
| K1145 | TW IS pooled panel (main result) | PASS; Codex reviewed ✓ |
| K1148 | TW continuous |surprise| | PASS_IS; OOS NS → binary preferred |
| K1148_d1 | TW binary OOS | OOS noise (US validates) |
| K1148_d2 | US binary+continuous OOS (main cross-market) | PASS Harvey ✓ |
| K1148_d3 | Firm-characteristic heterogeneity | REJECTED |
| K1149 | PCA factor absorption | Scenario A PASS ✓ |
| K1302 | Paper 2 Table 2 individual γ JSON rebuild | pending P3 |

---

## Pending Tasks

- [ ] K1302: Individual stock γ parameters for Table 2 (P3, pending experiment)
- [ ] K1148_d1: TW OOS binary verdict — need to confirm and cite appropriately
- [ ] Literature review: minimum 3 anchors (Patell & Wolfson 1979, Engle & Rangel 2008, Li et al. ?)
- [ ] Write body.tex (after ≥3 OOS-verified + Codex-reviewed experiments confirmed)
- [ ] Run paper-review-cycle before submission

---

## Replication Package Requirements

Per CLAUDE.md research honesty principle: self-contained replication package is a hard requirement for journal submission.

- `experiments/k1145/k1145.py` — TW IS pooled MLE (seed=42)
- `experiments/k1148_d2/k1148_d2.py` — US OOS panel DM
- `experiments/k1149/k1149.py` — PCA factor absorption test

---

## Data Sources

| Asset | Source | Period |
|-------|--------|--------|
| TW stock prices (N=31) | Yahoo Finance (yfinance) | 2010-01-01 – 2025-xx-xx |
| TW earnings dates | TWSE 財報公告日.txt (K1145 cache) | 2010-2025 |
| US stock prices (N=30 S&P500) | Yahoo Finance (yfinance, K1147 cache) | 2014-01-01 – 2025-xx-xx |
| US earnings dates | yfinance get_earnings_dates (K1148_d2 cache) | 2014-2025 |
| VIX | CBOE via yfinance | 2010-2025 |
