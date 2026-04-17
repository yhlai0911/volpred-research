# Paper 10 §1 Introduction — Gap Analysis vs §2–§9 Drafts (K1243)

**Paper**: Paper 10 — The Crypto Fear Channel
**Scope**: Assess whether `paper/crypto-fear-channel/body_v0_intro.tex` (§1 Introduction, v0 main-thread draft, 2026-04-17) remains coherent with §2–§9 subagent drafts (K1237–K1242), and propose specific extensions.
**Source files examined**:
- `paper/crypto-fear-channel/body_v0_intro.tex` (v0 intro, lines 30–46 = 4 substantive paragraphs)
- `paper/crypto-fear-channel/outline.md`
- `experiments/k1237/k1237_litrev_draft.md` (§2)
- `experiments/k1238/k1238_data_draft.md` (§3)
- `experiments/k1239/k1239_methodology_draft.md` (§4, GARCH-X-focused)
- `experiments/k1240/k1240_s5_s6_draft.md` (§5 Data / §6 GARCH-X results skeleton)
- `experiments/k1242/k1242_s7_s8_s9_draft.md` (§7 Robustness / §8 Discussion / §9 Conclusion)

**Verdict (headline)**: **EXTENSION RECOMMENDED, not optional.** The v0 intro frames Paper 10 purely around the K1025 framework (asymmetric Granger + quantile regression + Diebold–Yilmaz spillover + OOS NULL). K1239–K1242 introduce a **second methodological block — the GARCH-X fear-channel regression with VIX$^2$ as the fear proxy** — that is invisible in the v0 intro. Without a one-paragraph extension, the §1 reader will encounter §4.1 (GARCH-X specification), §6.1 (primary fear-channel finding), and §9 (conclusion headline mentioning $\hat{\phi}$) without preparation, creating an expectation mismatch.

---

## 1. v0 Intro Current Content (body_v0_intro.tex §30–46)

The v0 intro is a 4-paragraph structure:

| ¶ | Heading | Content | Scope |
|---|---------|---------|-------|
| 1 | (opening) | Motivation: post-ETF era, correlation vs forecasting tension | Level-set |
| 2 | Asymmetry | Hatemi-J (2012) asymmetric Granger; BTC$^{-} \to$ VIX significant, BTC$^{+}$ not | K1025 / K746b |
| 3 | Tail concentration | Quantile regression; $2.61 \to 22.31$, $8.5\times$ | K1025 |
| 4 | Regime dependence | 5-subperiod breakdown; only 2020 significant | K1025 |
| 5 | The forecastability gap | OOS DM $t=-0.98$, $p=0.33$; Harvey $|t|>3$ threshold | K1025 |
| 6 | Three contributions (list) | Combined framework; crisis-time amplifier; honest-NULL methodology | Framing |
| 7 | Roadmap sentence | Sections 2–9 pointer | Structural |

**Total**: ~600 words covering 4 stylized facts + 3 contributions + a roadmap. All content is K1025-sourced (symmetric with K639, K746b).

**Critical observation**: the v0 intro uses the word "spillover" (correlation-based causal framework) exclusively. It does **not** mention:
- GARCH-X
- Conditional variance
- Fear regressor or VIX$^2$ regressor
- Harvey-corrected $t^{\text{HLN}}$
- Likelihood-ratio tests against a GJR baseline

Yet §4.1 of K1239 (methodology) opens with: *"We define the fear channel operationally as the one-lag transmission of a traditional-market fear proxy into the conditional variance of Bitcoin returns."* This is a materially different framing from §1.

---

## 2. Gap Categories

Three categories of gap emerge from the §1 vs §2–§9 comparison:

### (A) Methodological scope gap (HIGHEST PRIORITY)

**Gap**: §1 discusses four analytical lenses (asymmetric Granger, QR, D-Y, OOS forecasting), but §4 introduces a fifth (GARCH-X with VIX$^2$), and §6 makes it the *headline* in-sample finding. A reader who has read §1 alone will arrive at §6 and find Table 3 (Primary Finding: Fear-Channel Transmission) with $\hat{\phi}$ coefficients and Harvey $|t^{\text{HLN}}|>3$ decisions — material that was nowhere telegraphed in the intro.

**Evidence**:
- K1239 §4.1–4.4 devotes ~870 words to GARCH-X specification, base model selection, statistical tests, and IV identification. This is the *largest single methodological block* in §4.
- K1240 §6.1–6.4 devotes ~600 words to fear-channel results tables (Tables 3, 4, 5) of which 3 of 4 tables are GARCH-X specific and K1025-independent.
- K1242 §7.1–7.5 dedicates the entire robustness section to GARCH-X sensitivities (alternative fear proxies, sub-samples, cross-asset, E-GARCH/APARCH, IV).
- K1242 §9 opening sentence: *"This paper identifies a fear-channel transmission from the CBOE VIX to Bitcoin conditional variance under a GARCH-X specification..."* — this is *the* thesis statement, and the current §1 does not prepare for it.

**Recommended fix**: Add a new ¶ (after current ¶5 "The forecastability gap", before the 3-contribution paragraph) that introduces the variance-domain complement. Draft below.

### (B) Third contribution reframing (MEDIUM PRIORITY)

**Gap**: Current §1 contribution #3 reads: *"Third, the predictive-power null, reported transparently rather than hidden, contributes to a growing methodological awareness in the volatility forecasting literature that in-sample significance and out-of-sample usefulness can diverge substantially."*

This is correct for the K1025 framework but under-sells the combined package. With GARCH-X added, the contribution package is:
1. Cross-method framework (Granger + QR + D-Y) — existing
2. Regime-conditional amplifier interpretation — existing
3. Honest OOS null under Harvey threshold — existing
4. **(NEW)** Variance-domain $\hat{\phi}$ quantification that complements the correlation-domain spillover, bridging @engle2002 GARCH-X tradition with @diebold2012 FEVD spillover

**Recommended fix**: Either (a) expand to 4 contributions, or (b) rewrite contribution #3 to encompass both the OOS null and the variance-domain addition.

### (C) Companion-paper cross-reference (LOW PRIORITY)

**Gap**: K1242 §8.2 discusses at length the relation to K1214 (companion negative-result paper, *Why GAS-$t$ Fails on Bitcoin*). The v0 intro does not mention K1214 or the companion-paper structure.

**Evidence**:
- K1237 §2.4 concludes with a substantive paragraph on K1214: *"A companion paper in our own program (\citealp{lai2026btc}...) reports a null result..."*
- K1242 §8.2 (~170 words) articulates how Paper 10's positive result and K1214's negative result are complementary rather than conflicting.
- K1242 §9 ¶2 also invokes K1214: *"...complementary to the companion negative-result paper K1214 (@lai2026btc)..."*

**Recommended fix (optional)**: Add one footnote (not a paragraph — low priority) in the v0 intro's contribution block referencing K1214. A body of ~15 words: *"\footnote{A companion paper (Lai 2026a, K1214) reports a within-BTC negative result: GAS-$t$ does not improve on GJR-Normal. The two papers address orthogonal questions.}"*

### (D) Abstract reconciliation (already handled)

**Gap**: v0 abstract does not mention GARCH-X. **Handled separately in `k1243_abstract_draft.md`** (v1 abstract, 250 words, adds one GARCH-X hedge sentence).

---

## 3. Recommended §1 Extension (Draft)

To close gap (A) — the highest-priority one — insert the following paragraph between the current "The forecastability gap" paragraph and the three-contribution paragraph. Main thread transcribes into `body_v1.tex`.

### Draft paragraph (~220 words, for insertion as new ¶6)

\paragraph{Variance-domain complement: the GARCH-X fear-channel regression.} The four analytical lenses introduced above — asymmetric Granger causality, quantile regression, Diebold--Yilmaz spillover, and out-of-sample forecasting — all operate in the correlation or Granger-causal domain. They characterise the \emph{direction} and \emph{regime-dependence} of the spillover but do not quantify a \emph{variance-domain transmission coefficient}. To complement these tests with a parametric measure of fear transmission, we augment an MF-GJR(1,1,1) baseline with a lagged squared-VIX regressor,

$$\sigma_{t}^{\text{BTC},2} \;=\; \omega \;+\; \alpha \varepsilon_{t-1}^{2} \;+\; \gamma \varepsilon_{t-1}^{2} \mathbb{I}(\varepsilon_{t-1}{<}0) \;+\; \beta \sigma_{t-1}^{2} \;+\; \phi \, \text{VIX}_{t-1}^{2},$$

and estimate $\phi$ by quasi-maximum likelihood with Student-$t$ innovations. The GARCH-X extension is consistent with the Paper 9 (MF-GJR + VIX) precedent of \citet{engle2002} and the cross-market evidence in K949 that the VIX-elasticity of equity conditional variance is approximately $\theta_{1} \approx 2.1$. We evaluate $\hat{\phi}$ against the Harvey-corrected $|t^{\text{HLN}}| > 3$ decision threshold of \citet{harvey2016}, test $H_{0}: \phi = 0$ against the one-sided alternative motivated by the amplifier narrative, and subject it to a battery of robustness checks (alternative fear proxies, chronological sub-samples, pre/post-ETF split, alternative GARCH base specifications, and an instrumental-variable refinement using the orthogonalised AR-residual fear shock). The variance-domain evidence speaks to cross-market information transmission at conditional-second-moment level, and is reported alongside the correlation-domain evidence in Section~6.

### Rationale

- **Position**: between current ¶5 (forecastability gap) and ¶6 (three contributions). This lets the reader see the GARCH-X tool as a response to the limitations of the correlation-domain tools, not as a standalone exercise.
- **Length**: ~220 words adds approximately 1/3 of a page to the current ~3-page intro; target total §1 remains within ~3–3.5 pages.
- **Numbered equation**: introducing (∗) here pre-figures the §4.1 specification. Main thread may assign `\label{eq:garch-x-baseline}` and cross-reference from §4.1.
- **Citation harmonisation**: uses `\citet{engle2002}` and `\citet{harvey2016}` — both keys exist in the current v0 bibliography (body_v0_intro.tex \bibitem entries), so no new bibliography entries needed for this paragraph.

### Alternative (shorter, lower-commitment) paragraph

If main thread prefers a shorter hedge without committing to the full paragraph, the following 90-word insertion at the end of ¶5 (forecastability gap) is the minimum-commitment variant:

> *We complement this Granger-style analysis with a parametric GARCH-X regression that adds lagged VIX$^{2}$ to an MF-GJR baseline, quantifying the variance-domain fear-channel coefficient $\phi$ and testing it against the Harvey-corrected $|t^{\text{HLN}}| > 3$ threshold \citep{harvey2016}. The variance-domain evidence and its robustness to alternative fear proxies, sub-samples, and GARCH specifications are reported in Section~6.*

**Recommendation**: Use the full 220-word paragraph if main thread keeps §6 and §7 at current GARCH-X emphasis. Use the short 90-word hedge if main thread de-emphasises GARCH-X (e.g., moves it to a §6.5 supplementary subsection or an appendix).

---

## 4. Companion Paper Footnote (Low Priority, Optional)

If main thread wishes to close gap (C):

> ``\footnote{A companion paper, Lai (2026a, internal ID K1214), reports a within-BTC negative result: GAS-$t$ with heavy-tailed innovations does not improve on GJR-Normal in out-of-sample QLIKE loss. The two papers address complementary questions — cross-market information transmission here, within-asset distributional choice there — and jointly highlight that cross-asset information inclusion matters more than within-asset distributional complexity for BTC variance forecasting.}''

Insert after the closing sentence of the 3-contribution paragraph. ~60 words.

---

## 5. Gap Verdict Summary

| Gap | Priority | Fix Length | Fix Location |
|-----|----------|------------|--------------|
| (A) Methodological scope — GARCH-X missing | **HIGH** | +220 words (full) or +90 words (short) | New ¶ after current ¶5 |
| (B) Third contribution reframing | MEDIUM | Rewrite current contribution #3, optionally expand to 4 | Within current 3-contribution paragraph |
| (C) K1214 companion reference | LOW | +60 words as footnote | In 3-contribution paragraph |
| (D) Abstract reconciliation | Already handled | — | `k1243_abstract_draft.md` |

**Headline verdict**: **Gap (A) is mandatory; Gaps (B) and (C) are optional.** Without (A), §1 misrepresents the scope of the paper; adding (A) brings §1 into coherence with §4, §6, §7, and §9 as drafted by K1239–K1242.

---

## 6. Decision Trees for Main Thread

### Decision 1: Does main thread keep the GARCH-X / K1241 block in Paper 10 v1?

- **YES (keep)** → Apply gap (A) full 220-word extension. Apply gap (B) contribution expansion. Abstract = v1 (with K1241 hedge). → Proceed with K1241 completion and populate tables.
- **NO (drop GARCH-X to appendix or R&R)** → Apply gap (A) short 90-word hedge only. Abstract = v0 unchanged or minimal update. → K1239–K1242's §4.1, §6, §7 shrink; repurpose K1237/K1238 §2–§3 drafts unchanged.

### Decision 2: Single-paragraph extension vs contribution expansion?

- **Single paragraph only (¶6 extension)** → Fast; preserves current 3-contribution structure.
- **¶6 extension + 4th contribution** → More thorough; signals the paper's dual-domain innovation to reviewers. Recommended for JIFMIM submission; optional for FRL short-form.

---

## 7. Notes for Main-Thread Adoption

1. **No changes should be made to v0 body_v0_intro.tex in this worktree.** Per CLAUDE.md §"Subagent / Skill 使用準則" and paper-workflow rule, only main thread writes `.tex`. This gap analysis is purely advisory.

2. **Recommended operational sequence**:
   - Main thread reads this gap analysis.
   - Main thread decides YES/NO on GARCH-X scope (Decision 1).
   - Main thread drafts `body_v1.tex` from v0 + this gap analysis's ¶6 recommendation + K1237–K1242 §2–§9 drafts + K1243 v1 abstract.
   - Main thread runs `paper-review-cycle` on body_v1.tex to catch any residual inconsistencies.
   - Main thread runs `citation-verifier` for DOI cross-check.
   - Main thread runs `paper-update` CLI to sync to platform.

3. **Preservation of v0 numbers**: All five K1025 numbers in the current v0 intro (N=2,812; QR $2.61 \to 22.31$; $8.5\times$; $F=11.05$; DM $t=-0.98$) are verified as correct per K1025 JSON (consulted by K1238/K1240). Do NOT alter these.

4. **Honesty discipline**: The ¶6 extension's sentence *"We evaluate $\hat{\phi}$ against the Harvey-corrected $|t^{\text{HLN}}| > 3$ decision threshold"* commits only to the methodology, not to a positive finding. If K1241 returns insignificant $\hat{\phi}$, the §6 table reports the null and the §8 discussion explains it — ¶6 of the intro does not need to change, because it only promises the test, not the outcome.

5. **Seed 42**: GARCH-X estimation in K1241 must use `np.random.seed(42)` for any bootstrap SEs or Monte Carlo sanity checks, matching the seed convention of K1025.

---

*End of K1243 §1 gap analysis. Headline verdict: EXTENSION RECOMMENDED (¶6 insertion, 220 words; fallback 90-word hedge). Main-thread action: resolve Decision 1 + Decision 2 before committing body_v1.tex.*
