# Paper 10 `body_v1.tex` Integration Guide — Main-Thread Execution Plan (K1243)

**Paper**: Paper 10 — The Crypto Fear Channel
**Scope**: Single-shot main-thread integration guide for consolidating K1237–K1242 Markdown drafts (plus K1243 abstract + §1 extension) into `paper/crypto-fear-channel/body_v1.tex`. Estimated effort 3–4 hours main-thread time, excluding any wait for K1241 results.
**Status**: Integration recipe; not yet executed (CLAUDE.md rule: worktree agent does not write `.tex`).

---

## 1. Source Map (§ by §)

| § | Title | Primary source file | Format | Status | Notes |
|---|-------|---------------------|--------|--------|-------|
| — | Preamble (docclass / packages / title / authors) | `paper/crypto-fear-channel/body_v0_intro.tex` lines 1–22 | LaTeX (verbatim) | Ready | Copy lines 1–22 unchanged |
| — | Abstract | `experiments/k1243/k1243_abstract_draft.md` §"Abstract (v1 draft, 250 words)" | Markdown → LaTeX | Ready | 250-word v1; replaces v0 292-word abstract |
| 1 | Introduction | `paper/crypto-fear-channel/body_v0_intro.tex` lines 30–46 **+** `experiments/k1243/k1243_intro_gap_analysis.md` §3 "Recommended §1 extension" (¶6 insertion) | LaTeX (existing) + Markdown (new ¶6) | Ready | Preserve v0 ¶¶1–5, 7 as-is; insert ¶6 GARCH-X extension between ¶5 and current contributions ¶ |
| 2 | Literature Review | `experiments/k1237/k1237_litrev_draft.md` §2.1–§2.4 | Markdown → LaTeX | Ready | ~1,006 words, 22 citations |
| 3 | Data and Preliminaries | `experiments/k1238/k1238_data_draft.md` §3.1–§3.3 | Markdown → LaTeX | Ready | ~600 words + Table 1 (descriptive stats) |
| 4 | Methodology | `experiments/k1239/k1239_methodology_draft.md` §4.1–§4.4 | Markdown → LaTeX | Ready | ~870 words; GARCH-X block; main-thread decides §4.1 or §4.6 ordering |
| 5 | Data Description (expanded) | `experiments/k1240/k1240_s5_s6_draft.md` §5.1–§5.3 | Markdown → LaTeX | Ready | ~400 words + Table 2 (extended descriptives) |
| 6 | Main Results | `experiments/k1240/k1240_s5_s6_draft.md` §6.1–§6.4 | Markdown → LaTeX | **Tables pending K1241** | ~600 words skeleton; Tables 3/4/5 cells `TBD` until K1241; Figure 1 can be generated from K1025 JSON immediately |
| 7 | Robustness | `experiments/k1242/k1242_s7_s8_s9_draft.md` §7.1–§7.5 | Markdown → LaTeX | **Tables pending K1241** | ~820 words; alternative proxies / sub-samples / cross-asset / alt GARCH / IV |
| 8 | Discussion | `experiments/k1242/k1242_s7_s8_s9_draft.md` §8.1–§8.4 | Markdown → LaTeX | Ready | ~610 words; mechanism / K1214 companion / contribution / limitations |
| 9 | Conclusion | `experiments/k1242/k1242_s7_s8_s9_draft.md` §9 | Markdown → LaTeX | **$\hat{\phi}$ placeholder pending K1241** | ~320 words; 2 placeholders: `$\hat{\phi}$ verdict` and `[X\%]` annualised response |
| — | References / Bibliography | Consolidate from §2 (K1237 22 refs) + §4 (K1239 7 new refs) + §8 (K1242 3 new refs) + body_v0_intro.tex \bibitem (8 refs) | BibTeX `.bib` file | Ready | Total ~35 unique refs after deduplication |
| — | Tables | Table 1 (§3), Table 2 (§5), Tables 3/4/5 (§6), Tables A1+ (§7) | LaTeX `tabular` | Mixed | Table 1 + Table 2: K1025-ready; Tables 3–5 + §7 tables: pending K1241 |
| — | Figures | Figure 1 (§6.4 Granger flow), Figure 2 (§5 QR path from K1025), Figure 3 (§5 DCC regime bars), Figure 4 (§7 rolling DY from K1025), plus §6 pending K1241 σ-timeseries | PNG/PDF | Mixed | 4 from K1025; 1+ from K1241 pending |

---

## 2. Integration Steps (11 concrete steps)

### Step 1 — Verify all §2–§9 Markdown drafts are mutually consistent (~20 min)

**Objective**: Before transcribing any section, main thread cross-checks that terminology, symbols, citation keys, and numerical claims are uniform across §2–§9.

**Checklist**:
- [ ] Sample size `N = 2,812` consistent across §3, §5, §9
- [ ] Date range `2015-02-02 to 2026-04-08` consistent across §3, §5, §7, §9
- [ ] Seed `42` cited in §3 and §6 footnotes
- [ ] `signal.shift(1)` convention called out in §3.2 and re-referenced in §6/§7
- [ ] Harvey (2016) $|t^{\text{HLN}}|>3$ threshold consistent across §4.3, §6, §7, §9
- [ ] Hatemi-J (2012) cited consistently as `\citet{hatemi2012}` in §1, §2.4, §4.1
- [ ] Diebold–Yilmaz cited consistently as `\citet{diebold2012}` (note: outline.md line 108 mistakenly lists *Journal of Econometrics* 182(1) 119–134; correct is *International Journal of Forecasting* 28(1) 57–66 — verify in K1237 §2.3)
- [ ] QR coefficients `2.61 (τ=0.5)` and `22.31 (τ=0.95)` consistent across §1 abstract, §1 body ¶3, §5.2, §6 (if mentioned), §9
- [ ] F-stat `F=11.05` in 2020 sub-panel consistent across §1 ¶4, §5, §6.3, §9 (body_v0_intro.tex writes `F = 11.05, p < 10^{-6}`; K1237 §2 not explicitly numbered; K1025 actual is $7.9\times 10^{-7}$ — abstract draft already tightens this)
- [ ] DM test `t=-0.98`, `p=0.33` consistent across §1 ¶5, §7, §9
- [ ] Asymmetric-Granger F-stats at lag 5 consistent: BTC$^{-} \to$ VIX = 6.64; BTC$^{+} \to$ VIX = 0.28 (per K1240 §6.4)

**Output**: A short note to main thread if any inconsistency found; otherwise proceed.

### Step 2 — Create `paper/crypto-fear-channel/body_v1.tex` scaffold (~15 min)

**Objective**: Initialize the LaTeX skeleton with preamble, title, author, abstract placeholder, and 9 empty \section{} blocks.

**Commands**:
```bash
cd /Users/yhlai0911/Desktop/volpred-research/paper/crypto-fear-channel/
cp body_v0_intro.tex body_v1.tex
# Manually edit body_v1.tex:
#  - Replace abstract (lines 23-28) with v1 abstract from k1243_abstract_draft.md
#  - Preserve \section{Introduction} + 4 \paragraph{} blocks unchanged
#  - Insert new \paragraph{Variance-domain complement...} (from k1243_intro_gap_analysis.md §3)
#  - Replace \begin{thebibliography}...\end{thebibliography} with \bibliographystyle{apalike}\bibliography{references}
#  - Add \section{Literature Review}, \section{Data and Preliminaries}, ..., \section{Conclusion} as empty blocks
```

**Output**: `body_v1.tex` with preamble + expanded v1 intro + 8 empty section blocks ready for §2–§9 transcription.

### Step 3 — Transcribe §2 Literature Review (~30 min)

**Source**: `experiments/k1237/k1237_litrev_draft.md` §2.1–§2.4

**Conversion rules**:
- Markdown `### §2.1 X` → LaTeX `\subsection{X}`
- Markdown `\citet{key}` / `\citep{key}` → Keep as-is (already LaTeX)
- Markdown inline math `$...$` → Keep as-is
- Markdown paragraph breaks → LaTeX `\\par` or blank line

**Output**: §2 populated, ~1,006 words, 4 subsections, 22 citations.

**Bibliography side-task**: While transcribing, collect the 22 citation keys and prepare `references.bib` entries for §2 (deferred to Step 7).

### Step 4 — Transcribe §3 Data, §5 Data Description (~30 min combined)

**Sources**:
- §3: `experiments/k1238/k1238_data_draft.md` §3.1–§3.3 + Table 1
- §5: `experiments/k1240/k1240_s5_s6_draft.md` §5.1–§5.3 + Table 2

**Conversion rules**:
- Markdown table → LaTeX `\begin{table}[h]\centering\begin{tabular}{...}...\end{tabular}\end{table}`
- Markdown math blocks `$$...$$` → LaTeX `\begin{equation}...\end{equation}` with `\label{eq:...}`
- Equation $\text{RV}_{i,t}^{(20)} = \sqrt{252} \cdot \sqrt{(1/20)\sum...}$ (§3.2) should get label `\label{eq:rv20}`

**Note on §3 vs §5 redundancy**: Both sections discuss descriptive statistics. Main thread decides:
- **Option A (recommended)**: §3 keeps sample-construction + RV definitions (§3.1–§3.2); §5 keeps descriptive statistics + correlation + stationarity (§5.1–§5.3, originally §3.3 content). Merge §3.3 descriptive stats into §5.
- **Option B**: §3 keeps all three subsections per K1238; §5 is renamed "Extended Descriptive Analysis" and focuses on correlation patterns only.

Record the decision in the integration log for reproducibility.

### Step 5 — Transcribe §4 Methodology (~30 min)

**Source**: `experiments/k1239/k1239_methodology_draft.md` §4.1–§4.4

**Conversion rules**: Same as §2/§3/§5. Plus:
- GARCH-X equation (K1239 §4.1) → LaTeX `\begin{equation}\label{eq:garch-x-baseline}\sigma_t^2 = \omega + \alpha\varepsilon_{t-1}^2 + \gamma\varepsilon_{t-1}^2\mathbb{I}(\varepsilon_{t-1}<0) + \beta\sigma_{t-1}^2 + \phi \text{VIX}_{t-1}^2\end{equation}`
- QLIKE loss (K1239 §4.3) → LaTeX `\begin{equation}\label{eq:qlike}L^{\text{QLIKE}}(\hat\sigma^2, \hat\sigma^2_{\text{proxy}}) = \hat\sigma^2_{\text{proxy}}/\hat\sigma^2 - \ln(\hat\sigma^2_{\text{proxy}}/\hat\sigma^2) - 1\end{equation}`

**Subsection ordering decision (main-thread)**:
- K1239 flagged: does GARCH-X go to §4.1 (primary) or §4.6 (after Granger/QR/DY)?
- Recommended: **§4.1 primary** — this matches K1240 §6.1 treatment of GARCH-X as headline finding, and matches the K1243 §1 ¶6 extension which introduces GARCH-X ahead of the 3-contribution summary.
- If main thread flips to §4.6: adjust §6 table ordering correspondingly.

**Also add sub-subsections 4.1-4.5 from outline.md line 41-43** (Granger, QR, D-Y, EWMA/DCC, forecasting) — these are K1025-method descriptions not in K1239 draft. Main thread writes these brief (~100 words each) by summarising K1025 README.

**Output**: §4 populated; if main-thread chooses to write the missing §4.2–§4.5 K1025-method subsections, add another ~400 words beyond K1239's 870.

### Step 6 — Transcribe §6, §7, §8, §9 (~60 min combined; populate K1241-pending cells LATER)

**Sources**:
- §6: `experiments/k1240/k1240_s5_s6_draft.md` §6.1–§6.4
- §7: `experiments/k1242/k1242_s7_s8_s9_draft.md` §7.1–§7.5
- §8: `experiments/k1242/k1242_s7_s8_s9_draft.md` §8.1–§8.4
- §9: `experiments/k1242/k1242_s7_s8_s9_draft.md` §9

**Conversion rules**: Same as prior sections. Plus:
- Table 3 (§6.1): insert `TBD` for all K1241-pending cells; add LaTeX comment `% K1241-pending: populate $\hat\phi$, SE, $t^{\text{HLN}}$, LRT $p$, QLIKE after K1241 completes.`
- Tables 4, 5: same TBD pattern
- §6.4 Figure 1 Granger-flow diagram: main thread generates from K1025 JSON via a short Python script (or Graphviz); save as `figures/fig1_granger_flow.pdf`; insert `\includegraphics[width=0.8\textwidth]{figures/fig1_granger_flow.pdf}` in §6.4.
- §9 ¶1 `$\hat\phi$` placeholder: keep as `[placeholder for K1241 verdict]` LaTeX comment; DO NOT fabricate per research honesty principle 1.
- §9 ¶1 `[X\%]` annualised response placeholder: same handling.

**Output**: §6–§9 populated in draft form with explicit `% TBD K1241` markers at every pending number.

### Step 7 — Assemble `references.bib` from all sections (~30 min)

**Sources**:
- body_v0_intro.tex \bibitem block (lines 49–86): 8 entries — bouri2020, corbet2018, matkovskyy2019, hatemi2012, diebold2012, harvey2016, conrad2020, and the stubbed Harvey et al. 2016 entry
- K1237 §2 References (22 entries)
- K1239 §4 Citations introduced (7 entries: engle2002, glosten1993, diebold1995, harvey1997, harvey2016, patton2011, bollerslev1992)
- K1242 §7–§9 Citations introduced (3 new: nelson1991, ding1993, geanakoplos2010)

**Deduplication**: Many keys overlap (harvey2016 appears in v0, K1237, K1239). Main thread:
1. Collates all ~40 candidate entries.
2. Deduplicates by BibTeX key (keep one canonical entry per key).
3. Verifies each entry against Google Scholar / DOI (main thread may dispatch `citation-verifier` skill).
4. Writes `paper/crypto-fear-channel/references.bib` with ~35 verified entries.

**Output**: `references.bib` ready for `\bibliographystyle{apalike}` + `\bibliography{references}`.

### Step 8 — Create `experiments.md` (~15 min)

**File**: `paper/crypto-fear-channel/experiments.md`

**Content**:
```markdown
# Paper 10 — Supporting Experiments

| K | Role | One-sentence contribution |
|---|------|---------------------------|
| K639 | §5 Granger baseline | BTC → SPY RV Granger causality at lags 1–10, full sample. |
| K746b | §5/§6 asymmetric Granger | BTC downside volatility Granger-causes VIX; upside branch insignificant. |
| K1025 | §5/§6/§7 full spillover framework | Asymmetric Granger + QR + Diebold–Yilmaz + 5-regime breakdown + OOS DM null. |
| K1133b | §7.2 pre/post-ETF structural break | Documents post-2024 regime change used for ETF-era robustness. |
| K1214 | §8.2 companion negative paper | Within-BTC GAS-$t$ fails to improve on GJR-Normal (companion reference). |
| K1241 | §4/§6/§7 GARCH-X fear-channel | MF-GJR(1,1,1)-X estimation of $\hat\phi$ on BTC returns with VIX$^2$ regressor (PENDING as of 2026-04-17). |
| K1237 | §2 literature review draft | Subagent §2 draft (4 subsections, 22 citations). |
| K1238 | §3 data draft | Subagent §3 draft with Table 1 (K1025-sourced descriptives). |
| K1239 | §4 methodology draft | Subagent §4 draft including GARCH-X specification. |
| K1240 | §5/§6 results draft | Subagent §5 (complete) + §6 (skeleton, K1241-pending). |
| K1242 | §7/§8/§9 draft | Subagent §7 (K1241-pending) + §8 + §9 (K1241-placeholder). |
| K1243 | §1 abstract + gap + integration | Subagent §1 extension + v1 abstract + this integration guide. |
```

### Step 9 — Create `data_sources.md` (~10 min)

**File**: `paper/crypto-fear-channel/data_sources.md`

**Content**:
```markdown
# Paper 10 — Data Sources

| Series | Symbol | Source | Method | Period | N | License |
|--------|--------|--------|--------|--------|---|---------|
| SPDR S&P 500 ETF | SPY | Yahoo Finance | `yfinance` Python package | 2015-02-02 to 2026-04-08 | 2,812 | Free / no restriction |
| Bitcoin USD spot | BTC-USD | Yahoo Finance | `yfinance` | 2015-02-02 to 2026-04-08 | 2,812 | Free / no restriction |
| CBOE Volatility Index | ^VIX | Yahoo Finance | `yfinance` | 2015-02-02 to 2026-04-08 | 2,812 | Free / no restriction |
| Crypto Fear & Greed Index (robustness) | CFIX | Alternative.me API | HTTP GET `https://api.alternative.me/fng/?limit=0` | 2018-02-01 to 2026-04-08 | ~2,990 | Free / no restriction (attribution requested) |

**Retrieval scripts**: See `experiments/k1025/k1025.py` (primary data) and `experiments/k1241/k1241.py` (GARCH-X fear-channel estimation, pending).

**Alignment**: All four series are aligned on the NYSE / CBOE trading calendar intersection. Crypto weekend observations are dropped (no interpolation). Missing values in any of SPY, BTC-USD, VIX lead to dropping the full date row.

**Lookahead-bias discipline**: All forecast-use signals are strictly lagged — VIX on date $t$ uses only information available up to $t-1$, enforced in code by `signal.shift(1)`. Verified in §3.2 of body_v1.tex and in all estimation scripts.

**Seed**: Random seed 42 fixed for all bootstrap, sub-sample, Monte Carlo, and train/test split procedures throughout the paper.
```

### Step 10 — Compile with `xelatex` × 2 (~10 min)

**Commands**:
```bash
cd /Users/yhlai0911/Desktop/volpred-research/paper/crypto-fear-channel/
xelatex body_v1.tex
bibtex body_v1
xelatex body_v1.tex
xelatex body_v1.tex
```

**Expected issues**:
- Unresolved `\cite` warnings → add missing entries to `references.bib`.
- Overfull `\hbox` warnings → ignore for first pass; main thread addresses cosmetically post-draft.
- TBD placeholders in Tables 3/4/5 and §9 will compile fine as literal text `TBD`; flag in post-compile review.

**Output**: `body_v1.pdf` draft.

### Step 11 — Sync to platform via `paper-update` CLI (~15 min)

**Commands**:
```bash
cd /Users/yhlai0911/Desktop/volpred-research
uv run volpred ops paper-update --paper-id crypto-fear-channel --version v1
```

**This CLI handles**:
- PDF upload to Supabase / Mirror storage.
- Paper metadata update (status=`draft`, version=`v1`, last_updated=today).
- Platform feed sync (if applicable).

**Verification**:
```bash
curl -s https://volpred.zeabur.app/api/papers/crypto-fear-channel | jq '.version'
# Expect: "v1"
```

---

## 3. K1241 Dependency — Timing Decision

**Two viable execution strategies for main thread**:

### Strategy A — Wait for K1241 before body_v1 (RECOMMENDED)

**Rationale**: Produces a fully populated body_v1 with actual $\hat\phi$ values, avoiding a body_v2 revision round immediately after K1241 completes.

**Sequence**:
1. Wait for K1241 worktree agent to produce `experiments/k1241/k1241_results.json` (expected 1-day wall-clock from K1241 start).
2. Run Steps 1–11 above in a single 3–4 hour session, populating K1241-pending cells with actual values.
3. Main-thread narrative decision on §9 headline based on Harvey threshold pass/fail.

**Pros**: Single body_v1 commit; no v2 revision overhead; final $\hat\phi$ in abstract, §6, §9 from day 1.

**Cons**: ~1 day wait time.

### Strategy B — body_v1 with placeholders, body_v2 after K1241

**Rationale**: Establishes paper skeleton immediately; allows main thread to iterate on §2/§3/§4/§5/§8 polish while K1241 runs.

**Sequence**:
1. Run Steps 1–11 above immediately, with TBD cells for K1241-pending.
2. Commit body_v1.tex as scaffold.
3. When K1241 completes, run Step 6 revision only: populate Tables 3/4/5, populate §9 headline, update abstract hedge sentence.
4. Compile body_v2.tex; run paper-update with `--version v2`.

**Pros**: No wait; paper-review-cycle can start on §2/§3/§5/§8 polish immediately.

**Cons**: Two paper-update rounds; risk of reviewer seeing v1 with TBD cells if distribution happens prematurely.

**Recommendation**: Strategy A unless main-thread has urgent need to start reviewer cycle today.

---

## 4. Total Estimated Time

| Step | Min time | Max time | Dependencies |
|------|----------|----------|--------------|
| Step 1 — Cross-check | 20 min | 30 min | K1237–K1242 drafts read |
| Step 2 — Scaffold | 15 min | 20 min | body_v0_intro.tex read |
| Step 3 — §2 transcribe | 25 min | 40 min | — |
| Step 4 — §3+§5 transcribe | 25 min | 40 min | — |
| Step 5 — §4 transcribe | 25 min | 40 min | Methodology decisions |
| Step 6 — §6–§9 transcribe | 50 min | 80 min | K1241 (if Strategy A) |
| Step 7 — references.bib | 25 min | 45 min | Dedup + citation-verifier |
| Step 8 — experiments.md | 10 min | 15 min | — |
| Step 9 — data_sources.md | 8 min | 12 min | — |
| Step 10 — Compile | 10 min | 20 min | All above |
| Step 11 — Platform sync | 15 min | 20 min | Compile success |
| **Subtotal** | **228 min (~3.8 hr)** | **362 min (~6 hr)** | — |
| Add K1241 wall-clock (Strategy A) | 24 hr | 48 hr | K1241 agent |

**Main-thread attention time**: 3–4 hours if drafts are pre-verified (Step 1); up to 6 hours if issues surface during transcription.

---

## 5. Post-Body Quality Gates (Not Part of the 11 Steps)

After body_v1.pdf compiles successfully, main thread must run these gates before paper is ready for external review:

1. **`paper-review-cycle`** (latex-academic-reviewer + citation-verifier): catches symbol inconsistencies, equation misnumbering, citation gaps. Expected ~1 hour main-thread.
2. **`paper-stage-classifier`**: assigns stage (likely `draft` → `review` after §2-§9 complete with actual K1241 numbers). Expected 5 minutes.
3. **`reproduce.py`** (paper-workflow rule, three-way consistency): one-shot script reproducing Tables 1, 2, 3 (and 4, 5 if K1241 done). Output `reproduce_report.json` with `all_match: true`. Expected ~2 hours if scripts need writing (else ~30 min for a smoke test).
4. **Harvey (2016) multiple-testing disclosure**: §4.3 and §7 claim Harvey threshold; Codex-review the K1241 script to verify `|t^{HLN}| > 3` is the *pre-registered* decision threshold, not an ex-post cherry-pick.
5. **Lookahead-bias audit**: Codex-review K1241 and K1025 scripts to verify `signal.shift(1)` or equivalent lag. Per CLAUDE.md principle 11.

---

## 6. Integration Risk Register

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| K1241 returns insignificant $\hat\phi$ | Medium (30%) | Medium: §9 headline pivots to honest-NULL | Already prepared in K1242 §9: use the NULL-rewrite template in k1243_abstract_draft.md |
| §3/§5 redundancy unclear to main thread | Low | Low: Option A/B decision needed | Record decision in body_v1.tex comment block |
| Bibliography key conflicts across §2/§4/§8 | Medium (40%) | Low: dedup at Step 7 resolves | Use citation-verifier to cross-check |
| Compile fails due to special chars | Low | Low: fix in one xelatex iteration | Ensure UTF-8 encoding throughout |
| Paper-review-cycle uncovers substantive §1–§2 gap | Medium (25%) | Medium: may require small §1 rewrite | K1243 gap analysis should pre-empt most; residual gaps typical for first-round review |
| K1241 Codex review uncovers lookahead bias | Low (10%) | HIGH: per CLAUDE.md must recall paper | Pre-emptive Codex-review K1241 before Step 6 populates numbers |

---

## 7. Adoption Checklist for Main Thread

- [ ] Step 0 — Read all three K1243 outputs: abstract draft, intro gap analysis, this integration guide.
- [ ] Step 0a — Decide Strategy A (wait for K1241) vs Strategy B (body_v1 with TBD placeholders).
- [ ] Step 0b — Decide §3 vs §5 descriptive-stats division (Option A vs Option B).
- [ ] Step 0c — Decide §4.1 placement of GARCH-X (primary §4.1 vs §4.6).
- [ ] Step 0d — Decide §7.3 ETH/SOL inclusion (included with K1241 ETH/SOL cells, or cut to §8.4 limitations).
- [ ] Steps 1–11 as above.
- [ ] Post-body — Run paper-review-cycle → reproduce.py → paper-stage-classifier → citation-verifier.
- [ ] Commit `body_v1.tex`, `body_v1.pdf`, `references.bib`, `experiments.md`, `data_sources.md` in a single commit with message documenting Strategy choice and any K1241-pending status.

---

## 8. Summary

- **Source map**: 7 Markdown drafts (K1234 kickoff + K1237–K1242 + K1243 abstract + gap analysis) map cleanly to 9 LaTeX sections + abstract + bibliography + 2 support files.
- **11 concrete steps** from cross-check to platform sync; ~3–4 hours main-thread time excluding K1241 wait.
- **3 K1241-pending locations** in Tables 3/4/5 (§6), §7 robustness tables, and §9 headline placeholders. Main thread must not fabricate values.
- **4 main-thread decisions** required before body_v1 commit: Strategy (A/B); §3/§5 split (A/B); §4.1/§4.6 GARCH-X; §7.3 ETH/SOL.
- **Self-contained package** delivered after Steps 8/9: README.md + experiments.md + data_sources.md + scripts/README.md (see K1234 §5).

**Estimated calendar time**: 1 day (if Strategy B) to 3 days (if Strategy A with K1241 wait).

---

*End of K1243 integration guide. Main-thread adoption point: read → decide 4 questions → execute 11 steps → quality gates → commit body_v1.*
