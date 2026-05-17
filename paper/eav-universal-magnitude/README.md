# Paper 2: Earnings-Announcement Volatility Amplification — Cross-Market Regularity with Magnitude Ordering in Taiwan, U.S., and Japan Equity Markets

**Working Title**: Earnings-Announcement Volatility Amplification: A Cross-Market Regularity with Magnitude Ordering — Evidence from Taiwan, U.S., and Japan Equity Markets
**Target Journal**: Journal of Empirical Finance | International Review of Financial Analysis | Finance Research Letters (backup)
**Status**: scaffold v2 (paper_decision confirmed 2026-04-17; kickoff 2026-05-17; scaffold rewrite per `review_v1.md` 2026-05-17)
**Narrative state**: `decision_made_awaiting_body_rewrite` (per `research_program.md` K1146 DECISION_MADE)
**Decision Record**:
- K1146 (2026-05-17) — three-market regularity confirmed: TW (K1145) + US (K1147) + JP (K1150) all PASS pooled bootstrap + placebo
- K1149 Scenario **A+D** — factor absorption symmetric across markets; stress-interaction asymmetric (US amplified; TW null)
- K1141 belongs to **Paper 4** (`paper/vix-sufficiency/`), **NOT** Paper 2 — earlier scaffold cross-reference was mistaken; K1141 only enters Paper 2 narrative as a footnote acknowledging the channel framework

**Scope separation**: This paper is independent of `paper/taiwan-vt/` (VT-strategy + concentration-amplification) and `paper/leverage-direction/` (γ asymmetry direction). It focuses exclusively on earnings-event variance amplification under a multiplicative GARCH framework.

---

## Core Claim

Earnings announcements produce a **robust, cross-market positive amplification** of conditional volatility whose **sign and statistical pattern are preserved across three independent equity markets**, while the **magnitude is market-specific and structurally ordered (US > JP > TW)**:

1. **Cross-market regularity in sign and significance** — pooled binary EAV indicator yields θ̂_EAV > 0 with cluster-bootstrap |t| > 4.4 in all three markets (TW K1145, US K1147, JP K1150).
2. **Magnitude ordering** — US (1.91 × 10⁻⁴) > JP (1.41 × 10⁻⁴) > TW (6.36 × 10⁻⁵); the ordering is consistent with cross-market institutional features (analyst coverage density, earnings-call culture, institutional pre-announcement positioning), interpreted in §6.5.
3. **Within-market firm-attribute heterogeneity is null** — pre-registered sector ANOVA (K1109), 6-covariate panel (K1113), rolling temporal trend (K1114), and HAC re-test (K1140) all FAIL to identify a firm-attribute predictor of θ_EAV. This null evidence supports interpreting θ_EAV as a **market-level constant**, not a firm-level idiosyncratic effect.
4. **Orthogonal to market-stress factor** — survives PCA factor absorption in both TW and US (K1149 Scenario A); stress-interaction is asymmetric (US: +5.04 t-stat amplification; TW: −0.39 NS; combined verdict = Scenario A+D).
5. **Binary specification marginally preferred over continuous |surprise|** — both specifications are highly significant out-of-sample on US data (binary DM t = −5.58; continuous DM t = −5.25), with binary slightly stronger (ΔDM t ≈ 0.33). The earlier "continuous adds no value" framing is retracted as over-stated.

---

## Model Specification

**Multiplicative GARCH-EAV** (per-stock GJR × pooled shared τ):

```
σ²_{i,t} = g_{i,t}(ω_i, α_i, γ_i, β_i) × τ_t

τ_t = max(θ₀ + θ_VIX·VIX²_{t-1} + θ_EAV·EAV_{i,t-1}, ε)
```

where EAV_{i,t} = 1 if firm i announces earnings on day t, else 0.

**Estimation**: Pooled MLE with stock fixed effects (m_i); per-stock GJR parameters + shared τ parameters. Cluster bootstrap (n=150 stock-level) as primary SE.

**Convergence caveat**: K1145 / K1147 main fits report `scipy.minimize.converged = False` on the inner BFGS step. Outer-loop EM-style tolerance (Δθ < 1e-7) is achieved and loglik plateau is monotone. Per `research_program.md` K1213 lesson ("library-limitation ≠ model invalidity"), this reflects the BFGS gradient tolerance being too strict relative to the small absolute magnitude of θ_EAV (~10⁻⁴–10⁻⁵), not a genuine model-identification failure. K1150 (JP) main fit reports `converged = True`. The replication package will document this explicitly. **P1 follow-up**: manual gradient verification + analytic-gradient MLE re-fit on TW/US for paper appendix.

---

## Key Empirical Results

| Experiment | Market | N (stocks) | Period | Spec | θ̂_EAV | Cluster-boot t | 95% CI | Placebo (one-sided p) |
|-----------|--------|-----------|--------|------|--------|-----|--------|---------|
| **K1145** | TW (TWSE bluechips) | 31 | 2014–2025 | Binary | +6.36 × 10⁻⁵ | +5.24 | [+4.13e-5, +9.38e-5] | 0/60 (z=13.27σ vs placebo SE) |
| **K1147** | US (S&P 500 large-caps) | 30 | 2014–2025 | Binary | +1.909 × 10⁻⁴ | +4.50 | [+1.29e-4, +2.80e-4] | 0/60 (z=70.74σ vs placebo SE) |
| **K1150** | JP (TOPIX large-caps) | 30 | 2014–2025 | Binary | +1.413 × 10⁻⁴ | +11.99 | [+1.29e-4, +1.76e-4] | 0/60 (z=38.65σ vs placebo SE) |

**Magnitude ordering** (point estimates): US (1.91e-4) > JP (1.41e-4) > TW (6.36e-5).

**Bonferroni adjustment for 3-market joint test** (k=3): all three markets retain |t| > 2.39 even under the conservative correction.

### Supplementary OOS / robustness experiments

| Experiment | Role | Outcome |
|-----------|------|---------|
| K1148 | TW continuous \|surprise\| IS | PASS_IS (Hessian t=10.4); OOS DM t=−1.16 NS — binary preferred |
| K1148_d1 | TW binary OOS | OOS marginal (DM t = −1.46, p=0.076 NS) |
| K1148_d2 | US binary+continuous OOS (TW-fitted spec → US OOS panel DM) | Spec-consistency / OOS forecast superiority test: binary DM t = −5.58; continuous DM t = −5.25 (both Harvey ✓). **Note**: this is a *spec consistency / OOS forecast* test — TW-fitted spec applied to US OOS — **NOT** an independent US magnitude estimate. The US magnitude estimate is K1147 (pooled IS). |
| K1148_d3 | Firm-characteristic ex-post heterogeneity (TW) | All 16 feature tests + 6 sector tests NULL. **Caveat**: pass/fail split inherits from K1148_d1 (TW OOS marginal NS), so selection-bias risk is non-trivial; primary null evidence is the ex-ante K1109/K1113. |
| K1149 | PCA factor absorption + stress interaction | Scenario **A+D**: factor absorption PASS both markets (TW IS t=10.62, US IS t=23.81; TW OOS DM=−2.48, US OOS DM=−3.31); stress interaction asymmetric (US t_stress=+5.04 PASS; TW t_stress=−0.39 NS; LRT p=0.010). |

---

## Null Heterogeneity Evidence Chain (Paper 2 contribution support)

The cross-market magnitude ordering interpretation is internally consistent **only because** within-market firm-attribute heterogeneity has been thoroughly excluded:

| Experiment | Hypothesis | Verdict |
|-----------|-----------|---------|
| K1109 | TW pre-registered random sector ANOVA (7 sectors, N=31) | **FAIL** — joint F=1.31, p=0.297; no BH-FDR survivor (min adj p=0.854) |
| K1113 | TW 6 firm covariates (mktcap, beta, earnings freq, volume, vol, momentum) with leakage-free 5-fold CV | **FAIL** — CV R² = −0.661; max BH-FDR adj p = 0.854; **no Tier-A firm** under correctly-specified PI |
| K1114 | Rolling θ_EAV time-varying heterogeneity (3 TW stocks, w=500/step=21) | OLS-SE PASS for UMC / MediaTek / TSMC, but README flags 96% sample overlap → OLS-SE under-states |
| K1140 | HAC Newey-West re-test of K1114 | **All 3 K1114 PASSes COLLAPSE** under HAC: no time-varying heterogeneity survives |

**Synthesis** (per K1146): no observable firm-attribute predictor (sector, mktcap, beta, earnings frequency, trading volume, momentum, regime, time trend) of θ_EAV survives multiple-testing correction → θ_EAV behaves as a market-level constant → the cross-market difference is **market-level structural** (institutional features), not firm-level noise. This null chain is a **contribution**, not a weakness — it is the logical support for the magnitude-ordering interpretation.

---

## Paper Structure (working outline, post-rewrite)

1. **Introduction** — EAV anomaly, cross-market regularity claim with magnitude ordering, contributions (3-market evidence + null heterogeneity reconciliation + spec consistency OOS test)
2. **Model** — Multiplicative GARCH-EAV specification, pooled MLE, identification strategy, convergence-flag handling
3. **Data** — TW TWSE bluechips (N=31, 2014–2025), US S&P 500 large-caps (N=30, 2014–2025), JP TOPIX large-caps (N=30, 2014–2025); VIX as global stress control
4. **Taiwan In-Sample Evidence (K1145)** — pooled θ_EAV, cluster bootstrap, placebo permutation, 5-layer robustness
5. **Cross-Market Pooled IS Validation (K1147 US + K1150 JP)** — each market 5-layer robustness; joint Bonferroni adjustment
6. **Earnings Announcement Volatility: A Cross-Market Regularity** (per K1146_body plan)
   - 6.1 Magnitude comparison table
   - 6.2 Magnitude ordering & institutional interpretation (US analyst coverage / earnings-call culture / institutional positioning)
   - 6.3 Spec consistency / OOS forecast superiority (K1148_d2 TW-fitted → US OOS panel DM)
   - 6.4 Factor robustness (K1149 Scenario A+D, including TW stress-interaction asymmetry honest disclosure)
   - 6.5 Binary vs continuous spec (K1148 + K1148_d2 — binary marginally preferred, continuous also significant on US)
   - 6.6 **Reconciliation with null within-market heterogeneity (K1109/K1113/K1114/K1140)**
7. **Robustness Battery (3 markets × 5 layers)** — drop-stock stability, 3-EAV-def monotonicity, multi-window, BH-FDR multiplicity, placebo permutation
8. **Discussion & Self-Challenge** — Hessian Wald vs cluster bootstrap; multi-spec multiplicity (Harvey-Liu-Zhu 2016); selection-bias caveat for K1148_d3
9. **Conclusion** — cross-market regularity with magnitude ordering; market-level constant interpretation; future directions

---

## Supporting Experiments

| K | Role | Status |
|---|------|--------|
| **K1145** | TW IS pooled panel (main result) | PASS; Codex reviewed ✓ |
| **K1147** | US IS pooled panel (main cross-market) | PASS; bootstrap + placebo ✓ |
| **K1150** | JP IS pooled panel (main cross-market) | PASS; bootstrap + placebo ✓; converged=true |
| **K1146** | Three-market synthesis / decision record | DECISION_MADE 2026-05-17 |
| K1148 | TW continuous \|surprise\| | PASS_IS; OOS NS → binary preferred |
| K1148_d1 | TW binary OOS | OOS marginal NS (p=0.076) |
| K1148_d2 | US OOS panel DM (TW-fitted spec → US OOS) | Spec consistency PASS Harvey ✓ |
| K1148_d3 | Ex-post firm-characteristic heterogeneity (TW) | All NULL; selection-bias caveat noted |
| K1149 | PCA factor absorption + stress interaction | Scenario A+D PASS ✓ |
| **K1109** | TW pre-registered sector ANOVA null | FAIL (intended) — supports market-constant interpretation |
| **K1113** | TW 6 firm covariates null | FAIL (intended) — leakage-free CV R² < 0 |
| **K1114** | Rolling θ_EAV temporal heterogeneity | OLS PASS but flagged for HAC re-test |
| **K1140** | HAC Newey-West re-test of K1114 | All K1114 PASSes COLLAPSE under HAC |
| K1302 | Paper 2 Table 2 individual γ JSON rebuild | pending P3 |

**Cross-paper note**: K1141 was previously listed as Paper 2 evidence but its README explicitly identifies it as **Paper 4 §4 Channel-Specific**. K1141 enters this paper only as a footnote acknowledging the parallel channel framework, not as Paper 2 evidence.

---

## Pending Tasks

### Scaffold-level (post-rewrite)
- [ ] (P1) K1148_d2 §6.3 narrative: cleanly separate "spec consistency / OOS forecast superiority" from "cross-market magnitude estimation" (the latter is K1147)
- [ ] (P1) K1149 §6.4 narrative: write Scenario A+D honestly with TW stress-interaction NULL disclosure
- [ ] (P1) lit_review.md: add Patell (1976), Beaver (1968), Bollerslev (1986), Bollerslev-Patton-Quaedvlieg (2016), Harvey-Liu-Zhu (2016), Diebold (2015), Diebold-Mariano (1995)
- [ ] (P2) Convergence-flag appendix: re-fit TW/US pooled MLE with analytic gradient; document scipy `converged=False` vs outer-loop tolerance discrepancy
- [ ] (P2) Citation-verifier pass on Engle-Ghysels-Sohn 2013 journal name (suspected ReStat, not JBES)
- [ ] (P2) K1148_d3 selection-bias risk disclosure in §6 — primary null evidence is ex-ante K1109/K1113

### Body / reproduction
- [ ] K1302: Individual stock γ parameters for Table 2 (P3, pending experiment)
- [ ] Body.tex — **DO NOT START** until P0+P1 scaffold rewrite signed off by user
- [ ] `reproduce.py` — must be written **before** body.tex (paper-workflow.md hard rule 2)
- [ ] Data snapshot pinning (CSV cache for TW/US/JP yfinance + VIX; `auto_adjust=False`)
- [ ] Run paper-review-cycle (latex-academic-reviewer + citation-verifier) before submission

---

## Replication Package Requirements

Per CLAUDE.md research honesty principle: self-contained replication package is a hard requirement for journal submission.

- `experiments/k1145/k1145.py` — TW IS pooled MLE (seed=42)
- `experiments/k1147/k1147.py` — US IS pooled MLE (seed=42)
- `experiments/k1150/k1150.py` — JP IS pooled MLE (seed=42)
- `experiments/k1148_d2/k1148_d2.py` — US OOS panel DM (TW-fitted spec)
- `experiments/k1149/k1149.py` — PCA factor absorption + stress interaction
- `experiments/k1109/`, `k1113/`, `k1114/`, `k1140/` — within-market null heterogeneity chain

---

## Data Sources

| Asset | Source | Period | N |
|-------|--------|--------|---|
| TW stock prices | Yahoo Finance (yfinance, `auto_adjust=False` to pin) | 2014-01-01 – 2025-xx-xx | 31 |
| TW earnings dates | TWSE 財報公告日.txt (K1145 cache) | 2014–2025 | — |
| US stock prices (S&P 500 large-caps) | Yahoo Finance (yfinance, K1147 cache) | 2014-01-01 – 2025-xx-xx | 30 |
| US earnings dates | yfinance get_earnings_dates (K1148_d2 cache) | 2014–2025 | — |
| JP stock prices (TOPIX large-caps) | Yahoo Finance (yfinance, K1150 cache) | 2014-01-01 – 2025-xx-xx | 30 |
| JP earnings dates | yfinance get_earnings_dates (K1150 cache) | 2014–2025 | — |
| VIX | CBOE via yfinance | 2014–2025 | — |

**Snapshot pin date**: TBD at body kickoff per paper-workflow.md hard rule 1.

---

## Rewrite history

- **v1 (2026-05-17, agent-generated)** — background agent scaffold; archived as `*_v1_pre_rewrite_backup.md`. NEEDS_REWRITE per `review_v1.md` 5 P0 + 4 P1 + 5 P2/P3 findings.
- **v2 (2026-05-17, main-thread rewrite)** — current file. Addresses all 5 P0 findings; addresses P1 #1 + #3 (partial) + #4; flags remaining P1 / P2 / P3 in Pending Tasks.
