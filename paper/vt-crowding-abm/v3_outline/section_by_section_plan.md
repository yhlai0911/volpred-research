# P5 (vt-crowding-abm) v3 Section-by-Section Rewrite Plan

**Date**: 2026-04-27
**Source manuscript**: `paper/vt-crowding-abm/main.tex` (v2; lines 1–384)
**Target journal**: Finance Research Letters (FRL) — short-form, ≤ 2,500 words main text after FRL trim
**Driver evidence**: K1261 Phase 1 (10,500 sims, H1+) + K1262 Phase 2 (16,800 sims, H1+ STRONGLY SUPPORTED) + K1262b OAT (16,000 sims, H1+ confirmed robust to λ/γ ±50%)
**Calibration anchor**: P5-style Sharpe-only detector → VT cell1 baseline = **70%** EXACT match to current Table 2 (lines 119–140) → no rebuild of headline VT numbers required

---

## Status legend

- **KEEP** — content stands; minor wording polish only (≤ 5 lines changed)
- **REWRITE** — substantive reframing while reusing structure; 30–80% line replacement
- **EXPAND** — keep current text, add new paragraph(s) or subsection(s)
- **NEW** — entirely new subsection that does not exist in v2

---

## Section-level plan

### Front matter (lines 1–32) — KEEP

| Item | Status | Notes |
|---|---|---|
| Preamble / packages (1–28) | KEEP | No change |
| Title (23) | REWRITE (subtitle only) | New subtitle: "Quantifying the Tipping Point in a Positive-Feedback Strategy Family". Drops "VT Crowds" framing. ≤ 2-line edit |
| Author / date (25–27) | KEEP | No change |

**Effort**: ≤ 5 min main-thread

---

### §1 Abstract (lines 34–45) — REWRITE

**Status**: REWRITE — single largest visible reframing surface.

**v3 framing notes**:
- Reposition VT from "the strategy that crowds" to "the empirically dominant case in a positive-feedback strategy family that all crowd"
- New 2-sentence opener: positive-feedback strategies (VT, trend-following, mean-reversion) share a procyclical mechanism; we test whether crowding is VT-specific or generic
- Mid-paragraph: K1262 + K1262b cross-strategy + cross-(λ,γ) results
- Closing: VT magnitude (70% threshold, Sharpe collapse 0.47 → 0.08) is preserved as the canonical numerical anchor; new sentence on TF/MR ≤ VT ordering
- Address v2 MED M2 (length) at the same time: trim to ≤ 220 words

**Evidence to integrate**:
- K1262: TF threshold ≤ VT in 12/12 scaling × window cells under softer detector (one sentence)
- K1262b: ±50% λ/γ perturbations preserve qualitative ordering 5/5 cells (one sentence)
- Calibration claim: P5-style detector reproduces 70% VT threshold EXACT in cell1 baseline (one half-sentence)

**Cross-link**: full v3 abstract draft is in `draft_sections.md` §1.

**Estimated effort**: 30 min main-thread (rewrite + word-count trim + bibtex citation reformat)

---

### §1 Introduction (lines 50–60) — REWRITE

**Status**: REWRITE — paragraph-level reframing of motivation and contribution structure.

**v3 framing notes**:
- **¶1 (line 54)**: KEEP — VT industry context (Moreira-Muir, Harvey 2018, USD 2 trillion AUM) is still load-bearing. Add one closing sentence: "VT is the largest individual strategy class within a wider family of positive-feedback strategies that share a procyclical risk-of-volatility-feedback structure."
- **¶2 (line 56)**: REWRITE — broaden the procyclical literature paragraph beyond VT-only. Add explicit positioning: trend-following (Moskowitz et al. 2012, Asness et al. 2013) and mean-reversion (Lehmann 1990, Lo-MacKinlay 1990) literatures document standalone-strategy alpha, but the systemic / crowding consequences of *parallel adoption* across strategies is uncharacterized. ECB (2020) and Baltas (2019) procyclicality concerns are framed as *strategy-class-agnostic*, not VT-specific.
- **¶3 (line 58)**: REWRITE — sharpen the gap statement. From "at what adoption level does VT crowding become destabilizing?" → "at what adoption level does *correlated positive-feedback trading* become destabilizing, and is the threshold strategy-specific or a generic property of the feedback class?"
- **¶4 (line 60) — Contribution paragraph**: REWRITE — restructure the three contributions:
  1. **Strategy-family threshold framework**: an ABM that supports VT, trend-following, and mean-reversion under matched microstructure, calibrated so VT cell1 reproduces the standalone P5 paper Table 2 70% threshold EXACTLY.
  2. **Cross-strategy threshold ordering**: TF and MR thresholds ≤ VT under three independent detectors (K1262), establishing positive-feedback crowding as a *family-level* phenomenon.
  3. **Joint robustness**: scaling × window (12 cells, K1262) AND λ/γ ±50% (5 cells, K1262b) preserve the qualitative ordering — directly addressing knife-edge / parameter-tuning critiques.
- The fixed-vs-scaled liquidity validation (originally contribution 2) demotes to a methodological subsection inside §5 because the family-level ordering is now the primary contribution.

**Evidence to integrate**:
- K1261/K1262/K1262b counts (10,500 + 16,800 + 16,000 = 43,300 total simulations across 3 phases)
- Cell1 calibration EXACT match to Table 2 70%

**Cross-link**: §1 ¶1–3 draft in `draft_sections.md` §2.

**Estimated effort**: 60–75 min main-thread (literature paragraph rewrite + new bibitems + cross-ref to new §3 / §5 subsections)

---

### §3 Model — partially KEEP / partially EXPAND

#### §3.0 Header / overview (lines 63–67) — EXPAND

**Status**: EXPAND — add a single sentence that the model now supports three strategy classes with shared microstructure.

**v3 framing notes**: After "1{,}000 heterogeneous agents...10 years", insert one sentence: "The agent-class composition is parameterized so that the crowding adoption variable can apply to any of three positive-feedback strategy classes (VT, TF, MR) under identical Kyle microstructure, with non-strategy agents always Buy-and-Hold or noise."

**Estimated effort**: ≤ 10 min main-thread

---

#### §3.1 Agent Types (lines 69–77) — REWRITE

**Status**: REWRITE — current 3-class enumeration must become 4 active strategy options + noise + BH.

**v3 framing notes**:
- Keep BH, VT, Noise verbatim (currently lines 74–76)
- **NEW**: add `\label{subsec:vt_rule}` to fix v2 MAJOR M1 (broken cross-ref at line 197) when defining the VT rule
- **EXPAND**: add two new bullet items for TF and MR with explicit weight-update rules:
  - **Trend-following (TF)**: $w_t^{\text{TF}} = \text{clip}(0.5 + s \cdot \tilde{r}_{t-1}^{(W)},\, 0,\, 1.5)$, where $\tilde{r}_{t-1}^{(W)}$ is the W-day return signal up to $t-1$ (lookahead-safe), $s$ is a scaling intensity, and clip enforces the same $[0, 1.5]$ rail as VT. Baseline $s = 10$, $W = 22$.
  - **Mean-reversion (MR)**: $w_t^{\text{MR}} = \text{clip}(0.5 - s \cdot \tilde{r}_{t-1}^{(W)},\, 0,\, 1.5)$. Same $s$, $W$ baseline; sign-flipped signal.
  - **NoiseControl** (already implicit as fully-noise scenario): $w^{\text{NC}} = 0.5$ deterministic constant. The "NoiseControl strategy" is the falsifiability anchor: zero positive-feedback by design.
- Reframe the experimental variable: $\phi$ now denotes the adoption fraction of *the active strategy treatment*, where the treatment is one of {VT, TF, MR, NoiseControl}. BH agents are replaced by treatment agents as $\phi$ rises; noise traders fixed at 200.

**Evidence to integrate**: TF/MR signal definitions verified in `experiments/k1261/k1261_non_vt_ablation.py` (TFAgent / MRAgent classes).

**Citations to add**:
- Moskowitz, Ooi, Pedersen (2012, JFE) — time-series momentum literature
- Asness, Moskowitz, Pedersen (2013, JF) — value-and-momentum-everywhere
- Lehmann (1990, QJE) — short-horizon mean reversion
- Lo and MacKinlay (1990, RFS) — mean-reversion contrarian profits

**Estimated effort**: 60 min main-thread (math typesetting + 4 new bibitems + paragraph)

---

#### §3.2 Market Microstructure (lines 81–93) — KEEP

**Status**: KEEP — Kyle (1985) price equation and VIX update equations unchanged.

**v3 framing notes**: Eqs. (1)–(2) and the parameter calibration (λ=0.005, γ=200, κ=0.03) hold identically across all four treatments (verified by K1261 sanity gate byte-exact match VT_baseline vs K827v3 stored 500-MC). One footnote can clarify: "These microstructure parameters are held fixed across all four strategy treatments, isolating the strategy class as the only experimental variable."

**Estimated effort**: ≤ 10 min main-thread (one footnote)

---

#### §3.3 Feedback Structure (lines 95–97) — REWRITE

**Status**: REWRITE — broaden the feedback discussion from VT-only to family-level mechanism.

**v3 framing notes**:
- Keep the Brunnermeier-Pedersen (2009) framing
- Reframe: the positive-feedback loop is `selling pressure → price decline → realized vol up → strategy-trigger up → more selling`. For VT the trigger is VIX-rebalancing; for TF the trigger is a downward-momentum signal that flips the position; for MR the trigger is positional saturation under volatility-induced signal compression. Different triggers, *same procyclical loop topology*.
- One sentence: "The feedback strength scales with $\phi$ for any strategy whose weight update is a non-trivial function of recent prices/volatility; the experimental question is whether the threshold magnitude differs across strategy classes."

**Evidence to integrate**: from K1261 verdict caveats — TF runaway vol = 242 at 50% (1500× baseline), MR price collapse to 1e-23 at 30% — these are the empirical manifestations of the same feedback loop with different triggers.

**Estimated effort**: 30 min main-thread

---

#### §3.4 Simulation Design (lines 99–101) — REWRITE

**Status**: REWRITE — must reflect 3-phase experimental design, not v2's single-phase.

**v3 framing notes**: New paragraph documenting the layered design:
- **Phase 1 (K1261)**: 4 treatments × 7 adoption × 500 MC = 10,500 sims; cross-treatment threshold under strict 3-criterion detector
- **Phase 2 (K1262)**: 2 treatments (TF, MR) × scaling {1,3,5,10} × window {10,22,60} × 7 adoption × 100 MC = 16,800 sims; strategy-spec robustness
- **Phase 2b (K1262b)**: 4 treatments × 5 OAT cells (cell1 baseline + λ/γ ±50%) × 4 adoption × 200 MC = 16,000 sims; market-microstructure robustness
- **Total**: 43,300 sims across the family-level study
- Bootstrap CIs reported for headline VT (500 MC); Phase 2/2b cells use mean across 100/200 MC respectively (acknowledged limitation in §6)

**Estimated effort**: 30 min main-thread (table or paragraph form depending on space)

---

### §4 Results — major restructure

#### §4.1 Strategy Performance Degradation — VT focus (lines 108–149)

**Status**: KEEP table + figure, REWRITE narrative paragraphs.

**v3 framing notes**:
- Table 1 (lines 112–140) and Figure 1 (lines 144–149) **stand**: VT cell1 numbers (Sharpe 0.47 → 0.34 → 0.08, kurt 0.06 → 1.41 → 61.4) match K1262b cell1 baseline — no rebuild needed
- Rewrite narrative ¶ (line 110) from "VT strategy performance exhibits..." to lead with the framing: "We first establish the standalone VT threshold under the canonical microstructure (cell1 baseline of K1262b), reproducing the conditions under which positive-feedback effects dominate." All numerical claims unchanged.
- ¶ (line 142) on nonlinearity also KEEP — the phase-transition framing supports the new reframing.
- Add one transitional sentence after Fig. 1: "The remaining sub-questions are whether this nonlinearity is VT-specific (§4.4) and whether it survives parameter perturbation (§4.5–4.6)."

**Effort**: 20 min main-thread (narrative tweak only; numbers stand)

---

#### §4.2 Market-Level Consequences (lines 151–189) — KEEP

**Status**: KEEP — Table 2 and Figure 2 unchanged; same cell1 baseline.

**v3 framing notes**: One sentence transition added at end of §4.2 to flag that the kurtosis spike pattern is VT-specific in *magnitude* (kurt 61 at 100% VT) but TF and MR produce qualitatively-similar destabilization at lower adoption (forward-ref §4.4).

**Effort**: ≤ 10 min main-thread

---

#### §4.3 Statistical Significance (lines 191–193) — KEEP

**Status**: KEEP — Welch-t Harvey-threshold tests on VT cell1 unchanged.

**Effort**: 0 min

---

#### §4.4 NEW — Cross-strategy threshold table

**Status**: NEW subsection.

**v3 framing notes**: This is the *primary* new evidence layer for the reframing. Three side-by-side detector tables answering "is the threshold ordering robust across detector specifications?":

| Detector | VT | TF | MR | NoiseControl |
|---|---|---|---|---|
| Strict (Sharpe-drop > 50% AND kurt > 10 AND vol amp > 50%) | 100% | 20% | 50% | null |
| Softer (Sharpe-drop > 50% AND kurt > 1 AND vol amp > 50%) | 100% | 20% | 50% | null |
| **P5-style** (Sharpe sign-flip OR drop > 70%) | **70%** | 20% | 20% | null |

(Source: K1261 Phase 1 + K1262 Part B; calibration anchor in `k1262_softer_detector_table.md`.)

Plus the K1262 Part C scaling × window matrix (under softer detector, summarised) showing ordering robustness across 12 strategy-spec cells.

Key claims:
- TF threshold strictly < VT under all three detectors and all 12/12 K1262 cells
- MR threshold ≤ VT in 12/12 K1262 cells
- NoiseControl never crosses (falsifiability anchor)
- **P5-style detector reproduces VT = 70% EXACT** = the original P5 paper headline figure

**Cross-link**: full draft table + 250-word narrative in `draft_sections.md` §3.

**Effort**: 60 min main-thread (build table + 250-word narrative + caption + bibtex anchor to K1261/K1262)

---

#### §4.5 NEW — λ/γ OAT robustness

**Status**: NEW subsection (replaces / consolidates v2 §3.6 Sensitivity Analysis lines 204–239).

**v3 framing notes**: Replace v2's VT-only OAT sensitivity table (Table 3, lines 208–237) with a 5×4 cross-treatment OAT table:

| OAT cell (λ, γ) | VT crit | TF crit | MR crit |
|---|---|---|---|
| cell1 baseline (0.005, 200) | 70% | 30% | 70% |
| cell2 λ=0.0025 (low) | 100% | 30% | 30% |
| cell3 λ=0.0075 (high) | 70% | 30% | null* |
| cell4 γ=100 (low) | 70% | 30% | 70% |
| cell5 γ=300 (high) | 70% | 30% | 70% |

(*MR null reflects saturation in deeply-negative regime — Sharpe stays < -5 across all adoption — principled interpretation per K1262b code review.)

Key claims:
- TF/MR ≤ VT ordering preserved 5/5 OAT cells (qualitative robustness)
- VT magnitude *shifts* — only λ_low extends VT to 100%, mechanism-consistent (lower price impact = longer survival)
- This is **NOT a knife-edge artifact**: 50% perturbation of either parameter preserves the family-level pattern
- Direct rebuttal of NotebookLM "knife-edge" critique (see §5)

**Cross-link**: full draft in `draft_sections.md` §4.

**Effort**: 60 min main-thread (table + 250-word narrative + caption)

---

#### §4.6 Design Validation: Fixed vs. Scaled Liquidity (lines 241–246) — KEEP, demote

**Status**: KEEP content, demote from "second contribution" status to "supplementary methodological check".

**v3 framing notes**: The fixed-vs-scaled liquidity comparison (52% of degradation due to liquidity evaporation rather than crowding) is still important methodologically but is **not** the headline contribution any more. Move the sub-section deeper into §4 (after the new cross-strategy / OAT subsections) and trim the prose by ~30% to make space for §4.4–4.5.

**Effort**: 15 min main-thread

---

### §5 Discussion (lines 249–277) — partial REWRITE

#### §5.1 Policy Implications (lines 253–255) — REWRITE

**Status**: REWRITE — broaden from VT-only to family-level monitoring.

**v3 framing notes**: New first sentence: "Regulators should monitor the *combined adoption* of positive-feedback strategy classes (VT, TF, MR) as a systemic risk indicator, not just VT in isolation." The 50–70% threshold language stays as a benchmark for the dominant VT class; add one sentence noting that TF reaches a comparable threshold at 30% under the P5-style detector — implying the *combined* family threshold is potentially more conservative than VT-only monitoring.

**Effort**: 20 min main-thread

---

#### §5.2 Implications for Practitioners (lines 257–259) — KEEP

**Status**: KEEP

**Effort**: 0 min

---

#### §5.3 Limitations (lines 261–277) — EXPAND

**Status**: EXPAND — keep the six current limitations, add **two** new ones:

1. **(NEW) Strategy-spec calibration**: TF scaling = 10 and MR scaling = 10 are aggressive choices reflecting K1261 Phase 1 design. K1262 Phase 2 confirms ordering at scaling ∈ {1, 3, 5} but the threshold magnitude shifts (TF 70% at scaling = 1, 20–30% at scaling ≥ 5). The 5/5 K1262b cells use scaling = 10. Real-world TF managers' effective scaling is heterogeneous; the family-level ordering is the robust claim.
2. **(NEW) Three-class versus continuum**: VT, TF, and MR are distinct strategy classes in our taxonomy, but real positive-feedback strategies (e.g. risk-parity, trend-overlay leverage) sit on a continuum. Future work should test whether arbitrary mixtures of feedback signals share the same threshold structure.

**Effort**: 40 min main-thread (two new paragraphs + cross-refs)

---

#### §5.4 NEW — Reviewer-anticipated objection: "knife-edge" critique addressed

**Status**: NEW subsection. Direct response to NotebookLM critique surfaced in v2 review_history.

**v3 framing notes**: 3-paragraph framing per knowledge entry `81ebfe54`:
- ¶1 (the critique): Anticipated reviewer objection that the 70% threshold is a mathematical artifact of (λ, γ) tuning — a "knife-edge" result that does not generalize.
- ¶2 (qualitative ordering robustness): K1262b's 5 OAT cells × 4 treatments = 20 (cell, treatment) pairs preserve TF/MR ≤ VT in 5/5 cells. K1262's 12 scaling × window cells preserve TF threshold < VT in 12/12 under softer detector. The qualitative ordering is therefore *not* a knife-edge artifact under either strategy-spec or microstructure perturbations.
- ¶3 (directional magnitude): The VT threshold magnitude shifts from 70% to 100% at λ_low, 70% at λ_baseline / λ_high, 70% at γ_low / γ_high. The shift is monotonic and mechanism-consistent (lower Kyle impact → higher VT threshold), as predicted by Eq. (1) directly. This is a *directional* magnitude response, not a knife-edge.

**Cross-link**: full 3-paragraph draft in `draft_sections.md` §5.

**Citations to add (probable)**:
- Brunnermeier and Pedersen (2009, RFS) — already cited; load-bearing here
- Cont and Bouchaud (2000, Macroeconomic Dynamics) — herd behavior & crash; new bibitem suggested

**Effort**: 45 min main-thread

---

### §6 Conclusion (lines 280–286) — REWRITE

**Status**: REWRITE — Mission statement reframing.

**v3 framing notes**: New opener: "This paper presents preliminary agent-based evidence that *positive-feedback strategies as a class* exhibit a nonlinear crowding tipping point, with volatility targeting (VT) as the empirically dominant case in the family." Body keeps the 70% / Sharpe 0.08 / kurt 61 numerical anchors but adds: "Cross-strategy comparison (K1262 Phase 2) and λ/γ OAT robustness (K1262b) jointly establish that the threshold is a feature of the positive-feedback feedback class, not a VT-specific artifact." Closing future work: extend to risk-parity and target-volatility-overlay strategies; calibrate TF / MR scaling to real-world manager taxonomies.

**Effort**: 30 min main-thread

---

### Bibliography (lines 293–381) — EXPAND

**Status**: EXPAND — current 18 bibitems + need 6–9 more.

**Bibtex additions list** (priority-ordered):

1. **Moskowitz, T. J., Ooi, Y. H., Pedersen, L. H. (2012). Time series momentum.** *Journal of Financial Economics*, 104(2), 228–250. [DOI: 10.1016/j.jfineco.2011.11.003] — TF literature anchor for §3.1
2. **Asness, C. S., Moskowitz, T. J., Pedersen, L. H. (2013). Value and momentum everywhere.** *Journal of Finance*, 68(3), 929–985. [DOI: 10.1111/jofi.12021] — momentum cross-asset breadth for §3.1
3. **Lehmann, B. N. (1990). Fads, martingales, and market efficiency.** *Quarterly Journal of Economics*, 105(1), 1–28. [DOI: 10.2307/2937816] — MR literature anchor for §3.1
4. **Lo, A. W., MacKinlay, A. C. (1990). When are contrarian profits due to stock market overreaction?** *Review of Financial Studies*, 3(2), 175–205. [DOI: 10.1093/rfs/3.2.175] — MR alpha anchor for §3.1
5. **Cont, R., Bouchaud, J.-P. (2000). Herd behavior and aggregate fluctuations in financial markets.** *Macroeconomic Dynamics*, 4(2), 170–196. [DOI: 10.1017/S1365100500015029] — herd-behavior ABM benchmark for §5.4
6. **(v2 carry-over) Shleifer, A., Vishny, R. (1992). Liquidation values and debt capacity: A market equilibrium approach.** *Journal of Finance*, 47(4), 1343–1366. — fire-sale lit (v2 MED M5 carry)
7. **(v2 carry-over) Coval, J., Stafford, E. (2007). Asset fire sales (and purchases) in equity markets.** *Journal of Financial Economics*, 86(2), 479–512. — fire-sale lit (v2 MED M5 carry)
8. **(v2 carry M9) Add DOI 10.3905/jpm.2018.45.1.014 to existing harvey2018 bibitem** (carry from v2 MED)

**Effort**: 30 min main-thread (citation-verifier check on each new bibitem)

---

## Summary count

| Status | Count | Sections |
|---|---|---|
| KEEP | 5 | Front matter, §3.2 Microstructure, §4.2 Market-Level, §4.3 Stat Sig, §5.2 Practitioner |
| REWRITE | 8 | Title subtitle, Abstract, §1 Intro (¶2/3/4), §3.1 Agents, §3.3 Feedback, §3.4 Simulation Design, §4.1 narrative, §5.1 Policy, §6 Conclusion |
| EXPAND | 3 | §3.0 header, §5.3 Limitations, Bibliography |
| NEW | 3 | §4.4 Cross-strategy threshold, §4.5 λ/γ OAT, §5.4 Knife-edge rebuttal |

(Note: title subtitle counted under REWRITE; some sections combine status — e.g. §3.0 EXPAND + §3.1 REWRITE all live within §3 Model.)

**Net structure delta**: v2 has 5 sections (Intro / Model / Results / Discussion / Conclusion) and ~280-word abstract. v3 keeps the 5-section skeleton; §4 grows from 6 subsections → 8 (adds §4.4, §4.5; demotes §4.7 = old §4.6); §5 grows from 3 subsections → 4 (adds §5.4 knife-edge rebuttal).

---

## Total estimated main-thread effort

| Block | Hours |
|---|---|
| Front matter (title subtitle) | 0.1 |
| §1 Abstract REWRITE | 0.5 |
| §1 Intro REWRITE (¶2 / ¶3 / ¶4) | 1.25 |
| §3.0 / §3.1 / §3.3 / §3.4 (model expansions) | 2.0 |
| §3.2 footnote | 0.2 |
| §4.1 narrative tweak | 0.3 |
| §4.2 transition | 0.2 |
| §4.4 NEW — cross-strategy table + narrative | 1.0 |
| §4.5 NEW — λ/γ OAT table + narrative | 1.0 |
| §4.6 demote (current §4.7) — fixed-vs-scaled trim | 0.25 |
| §5.1 Policy REWRITE | 0.3 |
| §5.3 Limitations EXPAND (+2) | 0.7 |
| §5.4 NEW — knife-edge rebuttal | 0.75 |
| §6 Conclusion REWRITE | 0.5 |
| Bibliography EXPAND (+6 new bibitems, 1 DOI add, 1 reframe) | 0.5 |
| Compile + label-check + cross-ref pass + reproduce.py rerun | 0.75 |
| Total | **~10.0 hours** main-thread |

**Phasing recommendation**: split into 3 sessions × 3.5 hours each.
- Session 1: §1 (abstract + intro rewrite) + §3 (model expansions + label fix)
- Session 2: §4.4 + §4.5 (new evidence subsections — load-bearing for the reframing)
- Session 3: §5 + §6 + bib + compile + reproduce gate

---

## Pre-submission gate checklist (post-rewrite)

After main-thread converts this outline to .tex, the following must pass before tagging v3 ready:

1. **Reproduce gate**: `paper/vt-crowding-abm/reproduce.py` extended to cover K1261/K1262/K1262b results invoked in §4.4 / §4.5 — `match_rate ≥ 95%` GREEN. (Currently GREEN at 33/33 for v2 cell1 numbers.)
2. **Table-row → JSON binding**: every new Table 3 (cross-strategy) and Table 4 (OAT) row gets `% source: experiments/k126?/k126?_results.json#field` inline comment per `.claude/rules/paper-workflow.md` hard rule 3.
3. **Citation verifier sweep**: 7 new bibitems + 1 DOI add must pass citation-verifier round.
4. **latex-academic-reviewer round v3**: target rating ≥ 4.4★ on revised manuscript.
5. **Cross-paper meta-evaluation** (NotebookLM-backed): explicit response paragraph confirming that the «knife-edge / parameter-tuning» critique is rebutted by K1262 + K1262b. (Per v2 NotebookLM follow-up at `review_history/v2/README.md` lines 110–138.)
6. **Self-contained replication package check** (per CLAUDE.md investor SOP): `experiments.md` lists K827v3 + K1261 + K1262 + K1262b; `scripts/README.md` walks from clean clone to each main table; `data_sources.md` notes none-required (pure-simulation paper).
