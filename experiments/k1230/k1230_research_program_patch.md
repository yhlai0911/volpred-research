# research_program.md Comprehensive Update Patch (post-K1228 FINAL)

> **⚠️ Supersedes K1212** (`experiments/k1212/k1212_research_program_delta.md`, commit `1a23e22c`). K1212 was written pre-K1216c and carries the K1211 STRENGTHENED-ladder framing with ρ ≈ +0.441 canonical as primary. That interpretation is now outdated. This K1230 patch integrates all post-K1212 session findings through K1228: the K1216 → K1216b → K1216c multistart-audit chain (9/9 FRAGILE), the K1222b Paper 2 §5 REBOUND narrative (ρ = +0.379 panel-wide refined, NOT −0.071 COLLAPSE), the K1216b asymmetric-refinement artefact lesson, the K1223 / K1224 / K1225 / K1227 / K1228 edit-guide stack, and the K1226 master-index consolidation.
>
> Per CLAUDE.md paper-workflow + worktree rules, the worktree agent does **not** edit `research_program.md` directly. This document is a cherry-pick-ready patch draft. Main thread reviews → merges § by § → commits.
>
> All numerical claims are **verbatim** from upstream experiment JSONs / knowledge entries (K1216c, K1222b, K1207, K1208, K1203, K1205, K1200, K1214, K1218, K1221, K1226). No new estimation is performed in K1230.
>
> Seed 42 declared for compliance (no RNG used).

---

## Section A — Updated Findings Per Paper

### Paper 1 (leverage-direction, JBF target) — READY FOR IMMEDIATE EXECUTION

**Status transition**: PROVISIONAL → READY.

- **Batch 1** committed `0a442356` (early session): Kupiec p 2-decimal + GLD γ forensic + γ_HM Sec 5.4 disambiguation. K1181 Spearman 0.5914 (paper 0.595), K1182 Granger F = 58.9 (paper 58.8), K1183 TSMC VT Sharpe 1.1244 (paper 1.121), K1184 skew-t η = 4.97 (paper 5.2) λ = −0.059 (paper −0.05), K1188 Table 8 15/15 MATCH, K1195 JBF Robustness Suite 5/6 MATCHED, K1196 Structural Leverage Panel 3/4 MATCHED, K1197 GJR-vs-EWMA crisis MDD direction confirmed, K1198 T10–12/C3 3/6 MATCHED (T12 Spearman = 1.000 EXACT).
- **Batch 2 edit guide**: K1209 draft (3574 words) → **K1224** 7-item edit guide (60–90 min main-thread execution). Items: (1) Table 3 vs Table 8 SPY GJR QLIKE aggregation footnote (K903 / K1188 numeric trace: −8.674 rolling vs −8.671 Table 8 vs −9.034 Table 3 full-concat); (2) Table 6 VaR panel 3-cell errata (K1186 / K1206 forensic); (3) Table 4 base = GARCH(1,1) not GJR footnote (K1185); (4) Table 7 per-asset OOS period disclosure (K1187); (5) Table 7 GLD 1.56 Sharpe forensic footnote; (6) create `paper/leverage-direction/experiments.md`; (7) Tables 10/11/12 + §4.2.3 unified pre-K footnote (K1198). γ_HM Sec 4.7 dropped (Batch 1 already covers).
- **Table 6 errata confirmed** (K1206): 3 cells diverged from K1186 replication (2/5 matched); A vintage / B bisection / C CF sensitivity variants all falsified → `errata_recommended` verdict.
- **New**: `experiments.md` file required (currently absent per `docs/paper-guide.md` 5-item rule).
- **Gate**: no user decision; 2-min approval + ~80 min execution window.

### Paper 2 (taiwan-vt) — MAJOR UPDATE: ρ REBOUND + NEW methodology contribution

**Status transition**: STRENGTHENED (K1211, K1212-era) → **MODESTLY WEAKER but SURVIVING** + additional methodological contribution (K1222b FINAL).

- **K1216c ROOT_CAUSE_METHODOLOGY** (commit `3cf6bc84`, knowledge `f63b6e01`, runtime 147.5s): 4/4 DEV markets (US / EU / JP / TW) also FRAGILE under identical 100-multistart protocol. Per-market LR stats vs χ²(1) = 3.84: US LR = 2836.68 (739×), EU LR = 837.97 (218×), JP LR = 235.57 (61×), TW LR = 587.78 (153×). Combined with K1213 AU + K1216 BR/IN/MX + K1216b CH/ID, **9/9 markets multistart-FRAGILE**. Two-basin likelihood surface in the shared-MIDAS + stock-FE-GJR pooled-MLE (K1168 / K1172 spec) is a universal design issue, not an EM-specific anomaly.
- **K1216b ASYMMETRIC-REFINEMENT ARTEFACT** (commit `b40d669f`): mixing refined EM pools (5 markets) with canonical DEV pools (4 markets) broke the cross-market rank concordance → primary Spearman collapsed from canonical +0.441 (N=12) to −0.071 (N=13, p = 0.82, Harvey t = −0.24). K1222 guide (commit `75df1c8f`) framed this as "ladder WITHDRAWN / COLLAPSED" — now **SUPERSEDED**.
- **K1222b FINAL narrative** (2925 words, `experiments/k1222b/k1222b_revision_guide.md`): applying multistart symmetrically across 9 markets rebuilds the rank concordance. 9-market refined Spearman ρ = **+0.379, p = 0.201, Harvey t = +1.36, N=13**. Fisher-z test vs canonical +0.441 (N=12): z-stat = 0.16, two-sided p ≈ 0.87 → statistically **indistinguishable**. Ladder is MODESTLY WEAKER but SURVIVING at ≈86% of canonical magnitude; both moderately positive, both non-significant at 5%.
- **Sector-FE K1207 PROMOTED** (knowledge `5d2d2435`): incremental adjusted R² from sector FE = 0.148 vs incremental adjusted R² from inst-FE = 0.0046 → sector explains ≈ 32× more θ_rel variation than institutional ownership. Joint F = 689.5, p = 7.9 × 10⁻¹⁴. Cross-sector Spearman(sector-median θ_EAV, sector-median inst_pct) = −0.006, p = 0.987 (n = 10) → sector and institutional ownership **empirically independent at sector level**. Sector-adjusted residuals absorb above-ladder EM residuals: IN 95.4%, MX 78.2%, BR 38.6%. K1207 promoted to §5.2 primary cross-market driver.
- **NEW methodology contribution** (§5.4 in K1222b): 10-step multistart protocol (100 L-BFGS-B starts × NM polish × DE sensitivity check × K-means K=2 basin identification × LR test) becomes Paper 2's third §5 contribution alongside analyst attention (within-market) and sector FE (cross-market).
- **Foundry 6-layer NULL** (K1108 / K1108b / K1108c / K1108d / K1108e / K1108f): K1108b DECISIVE NULL committed `5bcd8143`; K1108c capex binary t = −1.34 NS (4-firm pool N=135); K1108d non-capex preliminary NULL (coverage 8.9%, max HAC |t| = 0.968); K1108e op-leverage firm-FE absorbs SMI channel; K1108f regime-split Wald χ² = 0.036 p = 0.849 cannot reject equality. Foundry capex mechanism **abandoned**; appendix or drop entirely.
- **Within-market Panel Harvey t invariant**: `log_analyst` sequence 3.236 → 3.556 → 3.627 → 3.789 → 3.808 across K1165 → K1171 (N = 172 stocks × 12 markets × mean 2955 trading days). All 5 iterations above Harvey (2016) |t| > 3; monotonically increasing; `institutions_pct` insignificant at |t| < 1, β ≈ −1.27 × 10⁻³ stable. Independent of pooled-MLE basin choice → **invariant across K1216 fragility audit**.
- **K1222 SUPERSEDED**: revert any "WITHDRAWN / COLLAPSED / numerical artefact" language if partially merged into body.tex.
- **Gate**: 15-min K1222b review then body_v(n+1) execution per K1222b §4 (13 cherry-pick items).

### Paper 3 (vt-trend-following) — BLOCKED on user A/B/C decision

**Status**: Gate met (K1128 4-branch NULL) + K1217 path-(b) draft + K1227 triple-path edit guide. BLOCKED on user path selection.

- **K1205 cross-experiment integrity synthesis** (7 checks, ALL PASS): K1128 discrete VIX tertile IS-fixed OOS 0/854/20060 coverage degenerate, DM t = +1.306; K1131 natural cubic spline NULL with IS-extrapolation explosion to COVID VIX = 82; K1142 vol-normalized `|OFI|/σ_t` PARTIAL (OOS t = +2.255, AUC 0.671, best of 4, Harvey |t| > 3 fail); K1199 expanding-window adaptive VIX quantile NULL (coverage 0/6816/14098 still degenerate, DM t = +1.14 fail). No branch clears Harvey |t| > 3. K1142 is sole |t| > 2 cross-er.
- **Structural root cause (K1199)**: IS 2017-2019 VIX range [9, 37] does not intersect COVID OOS range [12, 83]. Once expanding window ingests Feb-Mar 2020 spike, q33 permanently rises → OOS low-regime coverage zero. Regime-identification approach is structurally brittle.
- **K1217 CONDITIONAL draft** (4991 words, path-b body pre-draft): targets hybrid null + positive framing (K1205 recommended).
- **K1227 triple-path edit guide**:
  - **Path (a)**: Full K1142 vol-norm anchor paper. Target IRFA primary / FRL secondary / PBFJ tertiary. Working title: *Vol-Normalized Microstructure Signal: A Regime-Free OFI Forecast for TAIFEX 5-Minute Jumps*. HIGH risk: single positive cell (33 OOS jumps underpowered for Harvey |t| > 3). ~3 weeks fresh body.
  - **Path (b)** K1205-recommended: hybrid null-plus-positive narrative (adopt pooled microstructure signal + drop VIX-regime). K1217 body pre-drafted. Lowest risk, highest cross-cell robustness.
  - **Path (c)**: Abandon + repurpose findings as negative-result / feed articles.
- **Panel B K1193 STRENGTHENING** (split-sample r = 0.793 vs paper 0.487) still pending main-thread rewrite under any path.
- **K1190 Sector 11 SPDR**: gamma range MATCHED but cross-sectional r DIVERGES (K1190 r = 0.089 vs paper 0.163) — errata cell.
- **Gate**: user A / B / C decision (K1205 recommends B).

### Paper 4 (vix-sufficiency) — BLOCKED on CONFLICT-A4 framing

**Status**: 7/7 UNIVERSAL_NULL verified; K1208 body draft ready; CONFLICT-A4 pending user resolution via K1225 dual-framing guide.

- **K1203 7/7 UNIVERSAL_NULL panorama** (commit `477c504a`): 28-cell native-IV vs alt-data DM t matrix across 7 asset classes × 4 specs (base / epu / finstress / all). All 7 assets: native IV (or rv30 for BTC / EEM robust) wins baseline. Zero cells pass 5% Patton QLIKE economic gate. Chain K1116c (`64a9d569`) → K1116f (`885d7b0b`) → K1201 (`87059567`) → K1203 closes the panorama.
  - SPY (^VIX): DM t ∈ [−3.021, −2.537]
  - QQQ (^VXN): DM t ∈ [−2.439, −1.967]
  - GLD (^GVZ): DM t ∈ [−3.341, −2.069]
  - USO (^OVX): DM t ∈ [−5.596, −2.584] (strongest baseline win)
  - TLT (^MOVE): DM t = +3.743 finstress (sole >|3| alt-data-wins cell)
  - BTC-USD (rv30 self): DM t ∈ [−5.494, +1.370]
  - EEM (^VIX spillover): DM t ∈ [−3.539, −0.999]
- **TLT finstress +3.743 rejected under triple-gate**: (a) lag sensitivity — `pit_shift1` collapses DM t to +2.00 Harvey-insignificant; (b) QLIKE improvement +0.50% order of magnitude below 5% Patton gate; (c) all-alt spec DM t = −5.67 (kitchen-sink collapse sign flip, overfitting signature).
- **^VXEEM unavailability disclosure**: 2026-04-17 yfinance probe HTTP 404 on ^VXEEM / VXEEM / ^VXFXI / ^CIV → K1203 dual-baseline design (primary EEM + ^VIX spillover correlation ≈ 0.75; robustness EEM + rv30). NULL verdict invariant across baselines.
- **K1208 draft** (1762 words): §5 UNIVERSAL_NULL framing markdown draft pending body_v4.tex transformation.
- **K1225 dual-framing guide** (shared baseline, parallel Version A / B guides):
  - **Version A** — channel-specific pivot (user decision `7ecab636`, 2026-04-17): reframe 28-cell panorama as channel-specific (energy commodities + long-duration Treasuries carry weak alt-data signals; equity broad + tech + gold + EM close them). Adopt UNIVERSAL_NULL as baseline-to-beat; TLT / USO cells highlighted.
  - **Version B** — UNIVERSAL_NULL (K1203 session gate, K1208 draft): all 7 assets confirm native IV sufficiency under true publication-lag PIT; zero assets clear 5% QLIKE + Harvey + subperiod triple gate. Final headline: native IV is universally sufficient.
- **CONFLICT-A4**: both versions share 0.1–0.6 sections (data, design, appendix A); differ only on §5 rhetorical framing and headline.
- **Errata stack** (orthogonal to CONFLICT-A4): DIV1 41.8% direction CRITICAL, DIV3 Table 3 Sharpe ranking possibly flipped, DIV4 Table 6 era Harvey passes hidden, DIV2 CV 0.33 → 0.37 (6 typo loci).
- **Gate**: CONFLICT-A4 user resolution (5-min framing pick).

### Paper 6 (prg-periodic-garch, FRL target) — READY FOR IMMEDIATE EXECUTION

**Status transition**: K880 lookahead flagged → **defensibility CONFIRMED** via K1200 clean-slate replication. READY.

- **K1200 clean-slate SPY replication** (K880v2 canonical timing): independent code pass using only Eqs.(5)–(6) specification. Canonical (main-text K880) vs replication (K1200) on identical SPY 2000-01-04 → 2026-04-02, IS-2018/12/31, OOS 2019/01/02 → 2026/04/02, n_OOS = 1823:
  - GJR QLIKE 0.8542 → 0.8544 (Δ +0.0002)
  - PRG Extended QLIKE 0.7478 → 0.7355 (Δ −0.0124)
  - DM t (PRG Ext vs GJR) 6.004 → **6.128** (Δ +0.124, slightly stronger)
  - Spearman ρ 0.5678 → 0.5761 (Δ +0.0084)
- All four metrics within pre-registered replication tolerance bands (|ΔQLIKE| < 0.05, |ΔDM_t| < 0.3). Replication performs **marginally better** on every PRG diagnostic → canonical figures are **conservative**, not inflated.
- **K1218 Appendix A draft** (930 words, `experiments/k1218/k1218_appendix_draft.md`): LaTeX-ready appendix body documenting K1200 clean-slate replication as transcription evidence for Eq.(5)–(6).
- **K1221 pre-submission audit** (6 items): 3 BLOCKERS + 3 WARNINGS (zero fabrication). Spot-checked 10/10 paper-body numbers match source JSON at 3-dp.
- **K1223 integration guide** (6 items, 80–120 min): B1 BLOCKER Table 1 0050.TW OOS date 2019/12 → 2021/01 (K886 JSON canonical); B2 BLOCKER K1218 Appendix A inline integration (55 min); W1 data/README.md stub; W2 data_sources.md TAIFEX on-request clause; W3 reproduce.py K880v2 pin + canonical band check; B3 BLOCKER `uv run volpred ops paper-update --paper-id paper-6` synchronisation.
- **Gate**: no user decision; 2-min approval + ~80–120 min execution window.

### Paper 9 (garch-x-vix) — robustness retained (unchanged from K1212 delta)

- K1027 Paper 9 7-window sub-period A4f 7/7 wins CONFIRMED. Pooled t = 6.535 → 6.977 under K1027 update. Sub-period DM t stats all Harvey-significant. Status unchanged since K1212.
- K1144 Paper 9 FEZ/STOXX50E A4f OOS 2019-2026 canonical replication (ticker forensic pending; ^STOXX50E vs ^ESTX50 ≈ 30% QLIKE gap).
- K995b Table 11 residual diagnostic submission status confirmed; integration pending: K998 vrp_autocorr_lag1 JSON write, experiments.md add K1045 as Table 11 source.
- No change in this session's scope.

### NEW — BTC GAS negative paper — BLOCKED on user go/no-go

**Status**: Feasibility CONFIRMED (K1129 / K1133 / K1133b). Draft and repo init plan READY. BLOCKED on user slot decision.

- **K1129 full-sample reversal**: BTC-USD daily 2015-01-02 → 2026-04-14, n_OOS = 1926. GAS-Student-t vs GJR-Normal DM t = −4.58 Harvey-significant (GJR-Normal **beats** GAS-t).
- **K1133 regime-concentrated decomposition**: P1 pre-institutional 2017-2020 (n = 1441) DM t = −4.67 Harvey-significant; P2 FTX/Luna 2023 (n = 345 preliminary) t = −0.82 NS; P3 spot-ETF 2026 (n = 100 preliminary) t = −0.80 NS. Effect concentrated in pre-institutional era.
- **K1133b innovation decomposition**: GJR-t = −3.36, GAS-t = −4.67 (K1133 baseline), GAS-Normal = −1.90 NS, GJR-N control = −0.06. M4 vs M3 DM = +2.67 → GAS-Normal **significantly beats** GAS-t. **~75% of P1 reversal attributable to Student-t innovation**, ~25% to GAS score dynamics (NS).
- **MS-GAS-t cannot rescue**: 2-state Markov-switching GAS-t extension does not beat GJR-Normal (K1133b Part B) → falsifies Catania (2018) regime-switching remedy for Bitcoin.
- **K1214 full paper draft** (4829 words, commit `91e5ab1d`, `experiments/k1214/k1214_paper_draft.md`): complete negative-result paper body cherry-pick source.
- **K1228 repo init guide** (5 phases, 24 steps):
  - Phase 1 (10 min): skeleton directories + README + experiments.md + data_sources.md + main.tex stub
  - Phase 2 (60 min): K1214 cherry-pick body_v1.tex
  - Phase 3 (40 min): scripts/ + reproduce.py linked to K1129 / K1133 / K1133b
  - Phase 4 (30 min): results/figures/ generation + reproduce_report.json
  - Phase 5 (15 min): xelatex × 2 + paper-upsert + paper-upload-pdf + paper-migrate-storage
- **Title**: *Why GAS-t Fails on Bitcoin: Student-t Innovation Is the Culprit, Regime-Switching Cannot Rescue*.
- **Target journals**: Journal of Empirical Finance (Elsevier, IF 2.1, primary) / Journal of Financial Econometrics (OUP, secondary) / Journal of Risk (tertiary).
- **Gate**: user go/no-go (5-min approval).

---

## Section B — Methodology Upgrades (session level)

### B.1 CRITICAL NEW RULE — Multistart before pooled MLE (K1213 → K1216 → K1216b → K1216c)

All cross-market / cross-asset pooled MLE estimations (shared-MIDAS-style or stock-specific GJR pooling) must from now on include a **100-start L-BFGS-B multistart audit + NM polish + DE sensitivity check** before any canonical number is reported. The two-basin pathology is **invisible under default single-init L-BFGS-B** — the K1168 / K1172 canonical panel demonstrably all 9/9 land in the inferior basin-A.

**Protocol specification (K1213 / K1216 / K1216b / K1216c identical, 10-step)**:

1. 100 random L-BFGS-B multistarts per market; log-uniform on θ_EAV, θ_0 ∈ [10⁻⁶, 5 × 10⁻⁴].
2. Penalty-trap guard rejecting `res.fun > 1 × 10¹¹` or `−res.fun < 1000`.
3. K-means (K=2) basin identification on converged (θ_EAV, LL) pairs.
4. Best-LL across valid starts = L-BFGS-B global estimate.
5. Sensitivity polish: Nelder-Mead warm-start + differential_evolution cross-check.
6. Refined best-LL = max over valid optimizers (NM consistently beats L-BFGS-B best).
7. LR test vs canonical: LR = 2·(LL_refined − LL_canonical) vs χ²(1) = 3.84.
8. Standard errors: Hessian on θ_EAV + HAC-robust sandwich (stock-level scores).
9. Cross-market rebuild: refit every market's θ_rel = θ_EAV_pooled / σ²_sample_mean.
10. Seed discipline: base = 42; 100 start seeds 43..142; DE seed = 49; K-means seed = 42.

**Cost**: ≈ 5–15 min per market on M1 Max. **No reason to skip**.

**9-market LR record (verbatim K1222b §3)**:

| Market | Exp | Canon θ_rel | Refined θ_rel | LR stat | χ²(1)=3.84 × | Verdict |
|---|---|---|---|---|---|---|
| AU | K1213 | 0.150 | 1.476 (NM 1.070) | 198.9 (NM 511.9) | 51.8× (133×) | ABOVE_LADDER_OVERTURNED |
| BR | K1216 | 1.887 | 2.691 | 145.66 | 37.9× | FRAGILE |
| IN | K1216 | 1.170 | 3.077 | 410.76 | 107× | FRAGILE |
| MX | K1216 | 1.202 | 1.845 | 347.27 | 90× | FRAGILE |
| CH | K1216b | 0.304 | 1.469 | 597.94 | 156× | FRAGILE |
| ID | K1216b | 0.238 | 1.917 | 365.36 | 95× | FRAGILE |
| US | K1216c | 0.415 | 8.614 | 2836.68 | 739× | FRAGILE |
| EU | K1216c | 0.196 | 1.434 | 837.97 | 218× | FRAGILE |
| JP | K1216c | 1.668 | 4.706 | 235.57 | 61× | FRAGILE |
| TW | K1216c | 0.314 | 1.364 | 587.78 | 153× | FRAGILE |

All 10 reject canonical at p < 10⁻³⁰ under nested-LR.

### B.2 CRITICAL NEW RULE — Symmetric refinement across cross-market panels (K1216b artefact lesson)

The K1215 → K1222 Spearman swing from +0.418 to −0.071 was an **artefact** of mixing refined EM pools with canonical DEV pools. Once K1216c applies the multistart protocol symmetrically across all 9 audited markets, Spearman rebounds to +0.379 (Fisher-z indistinguishable from canonical +0.441, p ≈ 0.87).

**Rule**: any cross-market comparison (Spearman, OLS panel, Harvey-t cross-market aggregate) must use **all canonical** θ_rel OR **all refined** θ_rel. Mixing is prohibited — it spuriously inflates or deflates rank correlations.

**Disclosure rule**: if a subset of markets has not yet been audited (e.g., CA / HK / KR still carry K1172 canonical θ_rel in K1216c), the paper must state this explicitly in the methodology or footnote and bound the expected rebound direction. K1216d (CA / HK / KR multistart) is expected to shift final ρ to within [+0.30, +0.50] range, but K1222b adoption does not block on it.

### B.3 Agent Markdown Draft Pattern VALIDATED (~30,000 words, 6+ drafts, 1 session)

This session produced 30,000 + words of paper-body drafts and edit guides (K1208 / K1209 / K1211 / K1214 / K1215 / K1217 / K1218 / K1222 / K1222b / K1223 / K1224 / K1225 / K1226 / K1227 / K1228 / K1230) from worktree sub-agents without any `.tex` mutation. Main thread consumes pre-drafted `.md` + `.json` and cherry-picks into body files.

**Validated workflow**:
- Worktree agent produces `experiments/k<N>/k<N>_<purpose>.md` + `k<N>_<purpose>.json` + `README.md`.
- Numerical claims verbatim from upstream JSONs.
- No mutation of `paper/**`, `research_program.md`, `storage/memory/**`, or `storage/ops/**`.
- Main thread cherry-picks in main-thread context; runs `xelatex × 2` + `paper-update`.
- Supports CLAUDE.md paper-workflow rule (論文 `.tex` 寫作與方法論決策留在主線程).

**Token efficiency**: high. Decouples 30k-word drafts from main-thread context pollution. Per-paper review windows remain tractable.

### B.4 PIT alignment triple-gate (K1116-family, from K1212 delta, retained)

Triple-gate for "positive" alt-data cells:
- (a) QLIKE improvement ≥ 5% Patton economic gate;
- (b) Subperiod majority (≥ 2/3 years) Harvey-significant;
- (c) All-alt augment does not overfit (no sign flip to DM < 0 at `pit_shift0`).

Single-cell positives (e.g., TLT finstress +3.74 in K1116f) rejected if any gate fails → prevents publication-leak artefact false positives. Addition to "行為準則" recommended.

### B.5 Sector-FE decomposition standard (K1207, from K1212 delta, retained)

Any cross-market theta_EAV / theta_OFI experiment should include a sector-FE (GICS 10) variant as orthogonal control. K1207 verdict `SECTOR_ORTHOGONAL_CONFIRMED` (F = 689.5, p = 7.9 × 10⁻¹⁴) establishes this as the standard cross-market decomposition.

### B.6 Two-phase forecast timing (K1200 / K880v2, from K1212 delta, retained)

Same-day realized info (e.g., `r²_overnight[t]`) predicting `h_intraday_t` IS lookahead. Proper two-phase: phase-1 uses t−1 close info for opening forecast; phase-2 uses t-open info for intraday update. K1200 clean-slate replication (DM 6.13) confirms K880v2 as the defensible spec over K880 (DM 6.00 conservative).

---

## Section C — Narrative State Transitions

| Paper | Previous (K1212 / pre-K1216c) | Current (K1230 / post-K1228) | Gate |
|---|---|---|---|
| **Paper 1 leverage-direction** | PROVISIONAL (Batch 1 committed, Batch 2 draft) | **READY FOR IMMEDIATE EXECUTION** (K1224 7-item edit guide, 60–90 min) | None — 2-min approval |
| **Paper 2 taiwan-vt** | STRENGTHENED ladder (ρ ≈ +0.441 K1211) | **MODESTLY WEAKER but SURVIVING** (ρ = +0.379 refined, Fisher-z ≈ canonical, p ≈ 0.87) + **NEW methodology contribution** (§5.4 multistart protocol) | 15-min K1222b review |
| **Paper 3 vt-trend-following** | Gate met (4-branch NULL + K1205 recommend b) | Gate met + **triple-path edit guide** (K1227 a / b / c) | User A / B / C |
| **Paper 4 vix-sufficiency** | 7/7 UNIVERSAL_NULL declared + CONFLICT-A4 flagged | BLOCKED on **CONFLICT-A4** resolution via K1225 dual-framing (Version A channel-specific vs Version B UNIVERSAL_NULL) | User framing pick |
| **Paper 6 prg-periodic-garch** | K880 defensibility CONFIRMED (K1200) | **READY FOR IMMEDIATE EXECUTION** (K1223 6-item edit guide, 80–120 min; 3 BLOCKERS + 3 WARNINGS) | None — 2-min approval |
| **NEW BTC GAS negative paper** | Feasibility CONFIRMED + K1214 draft | BLOCKED on user go/no-go + **K1228 repo init guide** (5 phases, 24 steps) | User go/no-go |

**Rewrite unlocked** (body work may proceed after gate clears): Paper 1 body_v4 (K1224), Paper 6 body_v2 + Appendix A (K1223), Paper 2 §5 body_v(n+1) (K1222b 13 items post-review), Paper 4 body_v4 (post CONFLICT-A4), Paper 3 body per chosen path, BTC GAS body_v1 (post go).

---

## Section D — Backlog (completed + new + blocked)

### D.1 Completed this session (~40 experiments + 13 guides, verbatim from K1226 §6)

**Experiments completed**:

- Paper 1 reproducibility: K1175 / K1176 / K1177 / K1178 / K1179 / K1180 / K1181 / K1182 / K1183 / K1184 / K1185 / K1186 / K1187 / K1188 / K1190 / K1191 / K1192 / K1193 / K1194 / K1195 / K1196 / K1197 / K1198 / K1206
- Paper 2 cross-market: K1163 / K1165 / K1166 / K1167 / K1168 / K1170 / K1171 / K1172 / K1173 / K1207
- Paper 2 foundry NULL: K1108 / K1108b / K1108c / K1108d / K1108e / K1108f
- Paper 2 multistart audit: K1213 / K1216 / K1216b / **K1216c** (9/9 FRAGILE ROOT_CAUSE_METHODOLOGY)
- Paper 3 4-branch: K1128 / K1131 / K1142 / K1199
- Paper 3 microstructure: K1100 / K1100b / K1100c / K1100d / K1100e / K1100f / K1100g / K1100g_d1-d8
- Paper 4 PIT chain: K1116 / K1116b / K1116c / K1116f / K1117 / K1117b / K1118 / K1118b / K1121 / K1123 / K1201 / K1203
- Paper 6 defensibility: K1200
- BTC GAS: K1129 / K1133 / K1133b
- Integration: K1156 / K1200 / K1202

**Guides / drafts produced**:

- K1204 / K1205 (Paper 3 synthesis) / K1208 (Paper 4 draft 1762 w) / K1209 (Paper 1 Batch 2 draft 3574 w) / K1211 (Paper 2 §5 STRENGTHENED draft 2380 w, **SUPERSEDED by K1222b**) / K1212 (session delta ≈1900 w, **SUPERSEDED by this K1230**) / K1214 (BTC GAS draft 4829 w) / K1215 (Paper 2 §5 revised draft, **SUPERSEDED by K1222b**) / K1217 (Paper 3 path-b draft 4991 w) / K1218 (Paper 6 Appendix A draft 930 w) / K1219 (cherry-pick dashboard, **SUPERSEDED by K1226**) / K1220 (executive briefing, **SUPERSEDED by K1226**) / K1221 (Paper 6 pre-submission audit) / K1222 (Paper 2 §5 WITHDRAWN guide, **SUPERSEDED by K1222b**) / K1222b (Paper 2 §5 FINAL 2925 w, ACTIVE) / K1223 (Paper 6 edit guide 6 items) / K1224 (Paper 1 edit guide 7 items) / K1225 (Paper 4 dual-framing guide) / K1226 (master index ACTIVE FINAL) / K1227 (Paper 3 triple-path guide) / K1228 (BTC GAS repo init 5-phase 24-step guide) / **K1230 (this research_program.md patch)**

### D.2 New pending queue (post-K1212 discoveries, K1226 + K1230 additions)

- **Paper 1 Batch 2 execution**: K1224 7-item cherry-pick into `paper/leverage-direction/body_v4.tex` (60–90 min main thread)
- **Paper 2 §5 body_v(n+1) rewrite**: K1222b 13 cherry-pick items + revert K1222 "WITHDRAWN / COLLAPSED" language (post 15-min review)
- **Paper 2 §5.4 NEW methodology appendix**: 10-step multistart protocol + 10-market LR record + 10-market basin-bimodality panel Figure (figure planning pending)
- **Paper 4 body_v4 per chosen framing**: K1225 Version A (channel-specific) OR Version B (UNIVERSAL_NULL) + 4 errata fixes
- **Paper 3 body per chosen path**: K1217 path (b) pre-drafted OR K1227 path (a) ~3 weeks / path (c) feed articles
- **Paper 6 body_v2 + Appendix A**: K1223 6-item cherry-pick (80–120 min main thread)
- **BTC GAS paper/btc-gas-negative/ initialization**: K1228 5-phase 24-step execution (post go/no-go)
- **K1100g_d9 cadence verify**: N225 asymmetric-t sign flip disambiguation (pending)
- **K1202b primary-source hand-verify**: Paper 2 foundry submission credibility — Taiwan earnings dataset licensing trail
- **K1216 methodology appendix write-up**: standalone methodology note for inclusion in Paper 2 §5.4 or separate methodology paper
- **K1216d CA/HK/KR multistart** (optional, not blocking): expected to shift unaudited 3 markets upward; final Spearman likely [+0.30, +0.50]
- **K1173 aggregate ρ rebuild** against PANEL-WIDE K1216 / K1216b / K1216c refined inputs (if retained in Paper 2 §6 robustness)
- **Paper 2 Figure 5H** — 3-scenario Spearman trajectory annotation (canonical +0.441 / asymmetric −0.071 footnote / 9-market refined +0.379 FINAL)
- **Paper 1 Tables 4/6/7/8** 15 KB-only values: 6 footnotes + additional K experiments as needed
- **Paper 3 Panel B K1193 STRENGTHENING rewrite** (r = 0.793 vs 0.487) under any chosen path
- **Paper 3 D1 TSMOM direction errata** research integrity
- **Paper 3 D2 Table 5 K1178 update** + ρ = 0.830 removal
- **Paper 9 K1144 FEZ/STOXX50E ticker forensic** (^STOXX50E vs ^ESTX50 ≈ 30% QLIKE gap)

### D.3 Blocked persistent (external / data, unchanged from K1212)

- **K1100h**: TAIFEX TX tick 2017–2021 via `~/Dropbox/TAIFEXDATA/` (user-gated)
- **K1116d**: True ALFRED vintage blocked — needs `FRED_API_KEY` (user-gated)
- **K1161b**: IV crush retry blocked — needs paid options data (ThetaData / OptionMetrics), `blocked_on_user`
- **K1175 legacy**: Full 96-files-per-day GDELT scan OR GCP-authed BigQuery rerun (capacity-bound)
- **I4**: VIX futures roll yield — yfinance no VIX futures historical data

---

## Section E — Research Directions Forward

### E.1 Short-term (≤ 1 week, ~80–120 min execution windows + 4 user-decision windows)

1. **Immediate execution (no user decision)**:
   - Execute K1224 → Paper 1 body_v4 (60–90 min). `xelatex main_v4 × 2` + `uv run volpred ops paper-update --paper-id leverage-direction` + commit.
   - Execute K1223 → Paper 6 body_v2 + Appendix A (80–120 min). `xelatex main × 2` + `uv run volpred ops paper-update --paper-id paper-6` + commit.
   - Both can run in parallel main-thread windows (different paper folders, no shared state).

2. **After user 15-min review** (Paper 2 §5 K1222b adoption):
   - Execute K1222b 13 cherry-pick items into `paper/taiwan-vt/body_v(n+1).tex`. Revert any K1222 "WITHDRAWN" language.
   - Add §5.4 methodology block with 10-step protocol + 10-market LR record.
   - Update Figure 5 with 3-scenario Spearman trajectory + 10-market basin-bimodality panel.

3. **After user decisions** (3 remaining: A-4, Paper 3 path, BTC GAS slot):
   - Resolve CONFLICT-A4 (Version A channel-specific vs Version B UNIVERSAL_NULL) → Paper 4 body_v4.
   - Paper 3 pivot a/b/c → body per chosen path; path (b) K1217 pre-drafted lowest effort.
   - BTC GAS go/no-go → K1228 5-phase 24-step repo init (105 min total).

### E.2 Medium-term (1 month, major revision cycles)

4. **Paper 2 major revision + re-submission prep** (Pacific-Basin Finance Journal): K1222b adoption + §5.4 methodology + Figure 5 rewrite + Paper2_errata_Table3_full_rewrite + Data section + abstract + Table 4 doc errata + G20 T4 IS Sharpe 0.732 vs 0.413 errata + G12/G20 Section 6 formal experiments. Foundry chapter → appendix or drop.
5. **Paper 3 post-pivot cycle** (IRFA / FRL / PBFJ depending on path): new body draft execution + paper-review-cycle (latex-academic-reviewer + citation-verifier) + Codex adversarial review. K1220 cross-market replication (ES / NQ) recommended before submission.
6. **Paper 4 post-body_v4 cycle** (JFE / RFS): errata stack clearance + submission prep per chosen framing.
7. **BTC GAS new paper cycle** (JEF primary): K1214 cherry-pick + paper-review-cycle + Codex review + submission prep. P2/P3 sample expansion (n = 345 / n = 100 PRELIMINARY → longer post-2023 data) recommended before submission.

### E.3 Long-term (quarter, new multistart audits + post-submission review)

8. **Remaining papers require analogous K1229-style multistart audit** if using shared-MIDAS / joint pooled MLE: `vt-crowding-abm` / `vt-insurance-cost` / `volatility-absorption` / `garch-x-vix` / `crypto-fear-channel`. Any paper relying on K1168 / K1172-style joint pooled MLE fits is potentially affected; preemptive K1229-style audit before submission.
9. **Paper 1 / Paper 6 post-submission review cycle**: reviewer-response preparation; pre-empt the 3 dropped Batch 2 items for potential R1 response.
10. **Paper 2 §5.4 as standalone methodology paper candidate**: if JBF / PBFJ reviewer expresses concern about paper scope, the multistart protocol + 9-market case study can be spun off as a methodological contribution paper to Journal of Econometrics / Journal of Financial Econometrics.
11. **K1216c cross-paper replication**: any future cross-market earnings-announcement panel study must cite K1216c protocol and declare 100-multistart compliance.
12. **Continuous Codex / Gemini adversarial review** for new drafts: K1222b / K1217 / K1214 all drafted but Gemini/Codex review still pending; running before body execution reduces main-thread rework.

---

## Merge Checklist for Main Thread

- [ ] Verify Section A canonical K numbers against `storage/memory/knowledge.json` recent entries (2026-04-17 / 04-18, 90+ entries in K1100–K1228 range).
- [ ] Resolve **CONFLICT-A4** (Paper 4 Version A vs Version B).
- [ ] Decide **Paper 3 A / B / C** (K1205 recommends B).
- [ ] Decide **BTC GAS go/no-go** (K1228 ready on go).
- [ ] Merge Section A into `research_program.md` 面向 H (paper sections) per-paper entries.
- [ ] Merge Section B.1 / B.2 / B.3 into `research_program.md` 方法論約束 / 行為準則 sections.
- [ ] Merge Section C narrative state transitions into `research_program.md` narrative state machine section.
- [ ] Update `storage/next_tasks.json` legacy working list with Section D.2 new queued items + mark Section D.1 completed items.
- [ ] Error log update: `docs/error_log.md` should capture (a) K1216c ROOT_CAUSE_METHODOLOGY 9/9 FRAGILE lesson; (b) K1216b asymmetric-refinement artefact as "mixing refined + canonical subsets across cross-market panels is prohibited"; (c) K1200 / K880v2 two-phase forecast timing pattern; (d) K1203 triple-gate for alt-data positive cells.
- [ ] Post-merge: `git commit` logging K1212 supersession + K1216c / K1222b / K1223-K1228 integration.
- [ ] Mark K1212 delta as SUPERSEDED in `experiments/k1212/README.md` + point to K1230.

---

*End of K1230 comprehensive research_program.md update patch. Supersedes K1212 delta. Produced 2026-04-18 by worktree agent (seed 42 declared; no RNG used). Cherry-pick target for main thread.*
