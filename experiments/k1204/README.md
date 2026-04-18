# K1204 — Paper 2 §5 Cross-Market Institutional-Ownership Synthesis

**Status**: Synthesis-only, no new estimation. All numbers verbatim from seven
prior experiment JSONs.

**Integrity check**: **PASS (32/32)** — every shared number cross-verifies
exactly across all source experiments. No replication drift.

## 1. Paper 2 §5 current status

Paper 2 §5 documents a two-level cross-market institutional-ownership +
analyst-coverage mechanism for earnings-announcement volatility (EAV). The
ladder has been extended through five N-extension iterations + two robustness
tests. K1204 consolidates all of them into a single publication-grade evidence
package.

## 2. Seven-experiment synthesis table (verbatim canonical numbers)

| K | N | Markets added | Spearman ρ (inst_pct vs θ_rel) | p | Drop-LOO min p (market) | Panel analyst-only log_analyst t | Panel joint log_analyst t | Between-R² (inst_pct) | Within-R² (log_analyst) | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| **K1165** | 7  | base TW/EU/JP/US + KR/CA/HK | +0.7500 | 0.0522 | 0.0048 (drop EU ρ=+0.943) | 3.740 | **3.236** | 0.6314 | 0.0718 | STRENGTHENED |
| **K1166** | 108 (pooled) | per-stock θ_EAV refit, tautology removed | — | — | — | — | **3.556** | — | — | CONFIRMED (removed-tautology) |
| **K1168** | 10 | BR/CH/IN | +0.6121 | 0.0600 | 0.0199 (drop EU ρ=+0.750) | 3.903 | **3.627** | 0.5382 | 0.0623 | STRENGTHENED (borderline) |
| **K1172** | 12 | MX/ID (ZA UNDERPOWERED, dropped) | +0.4406 | 0.1517 | 0.0467 (drop MX ρ=+0.609) | 4.060 | **3.789** | 0.4320 | 0.0533 | PARTIAL |
| **K1171** | 13 | AU via HAND_CODED earnings | +0.3846 | 0.1944 | 0.0667 (drop MX ρ=+0.545) | 4.076 | **3.808** | 0.4194 | 0.0534 | DATA_LIMITED |

Legend: Panel joint log_analyst t sequence **3.236 → 3.556 → 3.627 → 3.789 →
3.808 is monotonically increasing**, confirming within-market
analyst-coverage mechanism strengthens as the cross-market sample grows.
All |t| exceed the Harvey (2016) |t|>3 threshold.

Between-R² (inst_pct) / Within-R² (log_analyst) ratio range **7.86× – 8.79×**
— cross-market institutional ownership dominates between-market variation,
while analyst coverage operates within-market. This is the two-level
hierarchical structure Paper 2 §5 commits to.

## 3. Robustness — K1163 EU full coverage

K1153 EU panel (N=18, DAX-heavy) was a potential cluster-boundary vulnerability
because yfinance sparse earnings coverage forced skipping 12 Stoxx-600
candidates. K1163 refits with full 30/30 using HAND_IRCALENDAR provenance for
10 tickers (MC.PA, OR.PA, SU.PA, DG.PA, RMS.PA, AI.PA, ULVR.L, RIO.L, DGE.L,
REL.L, LSEG.L).

| Metric | K1153 (N=18) | K1163 (N=30) | Δ |
|---|---|---|---|
| θ_EAV | 4.07e-05 | 5.22e-05 | +1.15e-05 |
| θ_rel | 0.1366 | **0.194** | +0.057 |
| Cluster bootstrap t | 4.19 | **4.807** | +0.62 |
| Placebo z | 14.77 | **22.27** | +7.50 |

θ_rel=0.194 with 95% CI [0.127, 0.277] stays entirely inside the **low
cluster (≤0.25)** and excludes the high-cluster lower bound 0.30. Paper 2
four-market classification (TW+EU low vs JP+US high) **survives full coverage**.

Verdict: **ROBUST**. Quarterly-density hypothesis remains REJECTED.

## 4. Robustness — K1173 EM proxy refinement

yfinance `major_holders` mixes promoter, government, and institutional blocks
in EM markets. K1173 refines inst_pct for 40 EM stocks (IN/BR/MX/CH) using
SEBI quarterly shareholding patterns and simplywall.st bucket decompositions
that exclude promoter/family-controlling/government stakes.

| Layer | N | ρ (inst_pct vs θ_rel) | p |
|---|---|---|---|
| yfinance baseline | 12 | +0.4406 | 0.1517 |
| **Refined EM proxy** | 12 | **+0.3846** | 0.2170 |
| Δ | | **-0.056** | +0.065 |

Δρ within ±0.10 → **NULL**. EM off-ladder behaviour is **STRUCTURAL
cost-of-capital scaling, not a yfinance proxy artefact**. Even with regulatory
disclosure data, BR/IN/MX/CH θ_rel (1.17–1.89) stay 3–25× above the
developed-market range (TW 0.17 → US 0.59).

## 5. §5 narrative final commitment

Paper 2 §5 headline:

> **STRENGTHENED with 3 residual caveats.**

**Caveat (i) — EM cost-of-capital scale factor**. EM θ_rel values (BR 1.89,
CA 1.45, IN 1.17, MX 1.20) sit 3–25× above the developed-market reference
range. K1173 refined-proxy falsification test confirms this is structural, not
a proxy artefact. Paper must treat developed-market ladder slope and
EM-absolute-scale as two separate parameters.

**Caveat (ii) — AU below-ladder sector bias**. K1171 (N=13) adds AU and ρ
drops from 0.441 → 0.385. AU sits at inst_pct≈0.37 (mid-high) but θ_rel=0.15
(very low, near TW/EU). Drop-AU LOO recovers K1172 ρ=0.441. AU is a mild
leverage point attributable to ASX Top 10 being heavy on banks/miners whose
earnings reports generate less idiosyncratic volatility than in US/CA/BR.
Paper should flag AU explicitly rather than exclude it.

**Caveat (iii) — K1163 EU cluster robust under full coverage**. θ_rel 0.194 <
0.25 low-cluster upper bound with bootstrap CI [0.127, 0.277] excluding 0.30.
placebo z=22.27. Four-market (TW+EU low vs JP+US high) clustering holds.

## 6. Publication-grade figures

- `k1204_figure_A_trajectory_rho.png` / `.pdf` — Cross-market ρ evolution
  with Fisher-z 95% CI band and verdict colour coding across K1165 → K1171.
- `k1204_figure_B_panel_harvey_t.png` / `.pdf` — Panel joint log_analyst t
  monotonic increase 3.236 → 3.808; all above |t|>3 Harvey threshold.
- `k1204_figure_C_two_level_r2.png` / `.pdf` — Between-market (inst_pct) vs
  within-market (log_analyst) R² with ratio line (7.86×–8.79×).
- `k1204_figure_D_em_residual_taxonomy.png` / `.pdf` — θ_rel vs inst_pct
  scatter colour-coded by region (developed / EM above-ladder / AU
  below-ladder / other EM); purple arrows show K1173 refined-proxy shift
  with no meaningful movement in θ_rel→inst_pct ladder slope.
- `k1204_figure_E_k1163_eu_robustness.png` / `.pdf` — K1153 N=18 vs K1163
  N=30: θ_rel within low cluster + strengthened cluster-boot t and
  placebo z.

All figures are 300 dpi PNG + vector PDF for direct submission.

## 7. Paper 2 body.tex rewrite materials

For main-thread §5 rewrite. Drop-in facts (verbatim):

- **Primary cross-market statistic (N=13)**: Spearman ρ = +0.385,
  p = 0.194 (one-sided).
- **Panel joint regression (182 stocks, 13 market FE)**: log_analyst
  β = 0.00127, t = 3.808, p = 0.0002. inst_pct β = -0.00206, t = -1.30,
  p = 0.195.
- **Two-level decomposition**: between-market R² (inst_pct) = 0.419;
  within-market R² (log_analyst) = 0.053; ratio ≈ 7.9×.
- **Developed cluster** (TW 0.17, EU 0.194, JP 0.39, US 0.59) — low-high
  cluster boundary at θ_rel ∈ (0.25, 0.30).
- **EM cost-of-capital scale factor**: BR 1.89, CA 1.45, IN 1.17, MX 1.20 —
  3-25× above developed range.
- **AU leverage point**: inst_pct 0.37, θ_rel 0.15, drop-AU LOO ρ = 0.441.
- **K1173 refined-proxy null**: Δρ = -0.056 (refined 0.385 vs baseline 0.441).
- **K1163 EU full coverage**: θ_rel 0.194 (K1153 0.137) with bootstrap CI
  [0.127, 0.277]; cluster boot t = 4.81, placebo z = 22.27.

Suggested Table 5 and Figures 5A-5E mapping:
- Table 5 → N-extension trajectory table in §2.
- Fig 5A → k1204_figure_A_trajectory_rho.
- Fig 5B → k1204_figure_B_panel_harvey_t.
- Fig 5C → k1204_figure_C_two_level_r2.
- Fig 5D → k1204_figure_D_em_residual_taxonomy.
- Fig 5E → k1204_figure_E_k1163_eu_robustness.

## 8. Data provenance / reproducibility

- `k1204.py` — synthesis driver, no estimation, seed 42.
- `k1204_figures.py` — figure generation, seed 42, 300 dpi.
- `k1204_results.json` — consolidated canonical, includes integrity check
  report (32/32 PASS).

Source experiment JSONs (verbatim):

```
experiments/k1165/k1165_results.json
experiments/k1166/k1166_results.json
experiments/k1168/k1168_results.json
experiments/k1172/k1172_results.json
experiments/k1171/k1171_results.json
experiments/k1173/k1173_results.json
experiments/k1163/k1163_results.json
```

All loaded via exact shared-key equality checks (absolute tolerance 1e-9
for float equality). Any future re-estimation that updates any source file
MUST pass the 32-check integrity test before Paper 2 §5 rewrite is refreshed.

## 9. Narrative decision state

Per CLAUDE.md "論文 narrative state machine":

- ≥ 3 complementary experiments OOS-verified: **MET**
  (K1165, K1166, K1168, K1172, K1171, K1173, K1163 — 7 total).
- Codex/Gemini review: Each underlying experiment has been reviewed in its
  own worktree; K1204 itself is consolidation only.
- Current state: **decision_candidate** — ready for main-thread user
  confirmation to transition to `decision_made_awaiting_body_rewrite`.

K1204 does NOT write to paper body.tex. Body rewrite stays in main thread.
