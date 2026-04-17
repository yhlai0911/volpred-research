# BTC GAS-t Negative Paper Repo Initialization Guide

> **GATE**: User go/no-go decision required before execution. K1214 draft (4829 words) ready; K1228 is the implementation plan for main-thread to spin up `paper/btc-gas-negative/` as a self-contained paper folder per `docs/paper-guide.md` hard requirement.

**Experiment ID**: K1228
**Source draft**: `experiments/k1214/k1214_paper_draft.md` (4829 words, commit `91e5ab1d`)
**Supporting experiments**: K1129 (full-sample reversal), K1133 (sub-period decomposition), K1133b (5-model + MS-GAS-t)
**Knowledge**: `storage/memory/knowledge.json` entries K1129 (`ab4b18be`), K1133 (`47a41ba8`), K1133b
**Seed**: 42 (fixed for all reproductions)

---

## 1. Paper Metadata

| Field | Value |
|---|---|
| **Working title** | *Why GAS-t Fails on Bitcoin: Student-t Innovation Is the Culprit, Regime-Switching Cannot Rescue* |
| **Primary journal** | Journal of Empirical Finance (Elsevier, IF 2.1) |
| **Secondary journal** | Journal of Financial Econometrics (OUP) — direct home of Catania (2018) |
| **Tertiary journal** | Journal of Risk (Incisive Media) — if VaR/ES emphasis |
| **Initial status** | `draft` (upon `paper-upsert`) |
| **Supporting experiments** | K1129 + K1133 + K1133b |
| **Paper slug** | `btc-gas-negative` |

**Core claim**: The documented BTC underperformance of GAS-Student-t vs GJR-Normal (K1129 DM t=-4.58) is (i) concentrated in 2015-2020 pre-institutional period, (ii) ~75% attributable to Student-t innovation and only ~25% to score-driven GAS dynamics, and (iii) cannot be rescued by a 2-state Markov-switching extension beyond GJR-Normal — falsifying the Catania (2018) regime-switching remedy for Bitcoin.

---

## 2. Self-Contained Repo Structure (per `docs/paper-guide.md` 5-item rule)

```
paper/btc-gas-negative/
├── README.md                   # paper metadata + experiment index + status [REQUIRED item 5]
├── main.tex                    # LaTeX wrapper with \input{body_v1}
├── body_v1.tex                 # paper body (cherry-pick from K1214 draft)
├── references.bib              # bibliography, 16 starter entries per K1214, expand to ~20-30
├── experiments.md              # K1129 + K1133 + K1133b 1-line contribution pointers [REQUIRED item 4]
├── data_sources.md             # yfinance BTC-USD 2015-01-02 → 2026-04-14 spec [REQUIRED item 1]
├── data/                       # (optional) cached BTC-USD OHLC CSV snapshot
├── scripts/                    # reproduction scripts [REQUIRED item 2]
│   ├── README.md               # per-table/figure entry-point index
│   └── reproduce_all.py        # wrapper invoking K1129/K1133/K1133b entry scripts
├── results/                    # CSV numerical outputs [REQUIRED item 3]
│   ├── table1_full_sample.csv           # from K1129
│   ├── table2_subperiod_dm.csv          # from K1133
│   ├── table3_5model_decomposition.csv  # from K1133b Part A
│   └── table4_ms_gas_rescue.csv         # from K1133b Part B
├── figures/                    # publication PDFs [REQUIRED item 3]
│   ├── fig1_qlike_by_period.pdf
│   ├── fig2_5model_bar.pdf
│   └── fig3_state_prob_timeseries.pdf
├── reproduce.py                # top-level one-shot reproduce entry
└── reproduce_report.json       # output sanity check vs paper body numbers
```

Five-item compliance mapping:
1. **Raw data / data listing** → `data_sources.md` (+ optional `data/` cache)
2. **Reproduction scripts** → `scripts/README.md` + `scripts/reproduce_all.py` + top-level `reproduce.py`
3. **Results** → `results/*.csv` + `figures/*.pdf`
4. **Experiment index** → `experiments.md`
5. **README** → `README.md`

---

## 3. Step-by-Step Execution Plan (5 Phases, 24 Steps)

### Phase 1 — Skeleton (est. 10 min)

**Goal**: Create folder hierarchy and 5 self-contained stub files so `docs/paper-guide.md` compliance is baseline-green from commit 1.

1. `mkdir -p paper/btc-gas-negative/{scripts,results,figures,data,review_history}`
2. Write `paper/btc-gas-negative/README.md` — title, target journal JoEF primary, status=`draft`, K-list (K1129, K1133, K1133b), 2-line data-source summary pointing to `data_sources.md`.
3. Write `paper/btc-gas-negative/experiments.md` — three bullet lines: K1129 full-sample reversal (n_OOS=1926, DM t=-4.58); K1133 sub-period P1/P2/P3 decomposition; K1133b 5-model attribution + MS-GAS-t.
4. Write `paper/btc-gas-negative/data_sources.md` — `yfinance` ticker `BTC-USD`, daily, 2015-01-02 → 2026-04-14, n=4121 obs, `pct_change * 100` percent units, seed 42, retrieval date stamp, license note (yfinance is scraped Yahoo Finance; document fallback to Binance/Kraken if yfinance breaks).
5. Write `paper/btc-gas-negative/main.tex` skeleton — xeCJK preamble matching `paper/leverage-direction/main.tex` pattern, `\input{body_v1}`, `\bibliography{references}`.
6. Write `paper/btc-gas-negative/body_v1.tex` skeleton — `\section{Introduction}` through `\section{Conclusion}` placeholder headers only (content in Phase 2).
7. Commit: `paper/btc-gas-negative/ repo skeleton initialized (K1228 guide phase 1)`.

### Phase 2 — LaTeX cherry-pick from K1214 draft (est. 60 min)

**Goal**: Populate `body_v1.tex` with full content from `experiments/k1214/k1214_paper_draft.md`, converting Markdown → LaTeX verbatim on numbers.

8. Open `experiments/k1214/k1214_paper_draft.md` in editor alongside `body_v1.tex`.
9. Section-by-section conversion:
   - `#`/`##` → `\section{}` / `\subsection{}`
   - Markdown tables → `booktabs` `\begin{tabular}` with `\toprule`/`\midrule`/`\bottomrule`
   - Inline math `$...$` passes through; display math `$$...$$` → `\[ ... \]` or `equation` environment
   - Bold/italic → `\textbf{}` / `\emph{}`
   - Markdown refs `[Author, YYYY]` → `\citep{author_yyyy}`
10. Populate `references.bib` with 16 entries from K1214 (Bollerslev 1986, GJR 1993, CKL 2013, Catania 2018, Klaassen 2002, Patton 2011, HLN 1997, Harvey 2016, Hansen-Lunde 2005, Hwang-Valls-Pereira 2006, Chu et al 2017, Hamilton 1989, Gray 1996, Nelson 1991, Harvey 2013, Blasques-Koopman-Lucas 2015, Diebold-Mariano 1995).
11. Main-thread expansion: consider adding Katsiampa (2017), Baur-Dimpfl (2018), Haas et al (2004), Bauwens et al (2014) for crypto and MS-GARCH coverage (K1214 limitations section flagged these).
12. Verify canonical numbers stay verbatim from K1214 JSON (per K1214 cross-check: t=-4.58, t=-4.67, t=+2.67, t=+5.97, t=+0.28).
13. Commit: `paper/btc-gas-negative/ body_v1.tex populated from K1214 draft (K1228 guide phase 2)`.

### Phase 3 — Reproducibility package (est. 30 min)

**Goal**: Build three-way consistency (script ↔ data ↔ paper numbers) per `docs/paper-guide.md` hard rule.

14. Write `scripts/reproduce_all.py` — sequential wrapper importing and invoking `experiments.K1129.k1129.main`, `experiments.k1133.k1133.main`, `experiments.k1133b.k1133b.main` (or subprocess calls); collect output JSON paths.
15. Write `scripts/README.md` — per-Table/Figure mapping: Table 1 ← `experiments/K1129/k1129_results.json` via `k1129.py`; Table 2 ← `experiments/k1133/k1133_results.json`; Tables 3-4 ← `experiments/k1133b/k1133b_results.json`; Figures 1-3 ← K1129/K1133/K1133b `.png` outputs converted to PDF.
16. Export `results/*.csv`:
    - `table1_full_sample.csv` (BTC full-sample M1/M2/M3 QLIKE + DM-HLN t, p, QLIKE_rel_pct)
    - `table2_subperiod_dm.csv` (P1/P2/P3 × M1/M2/M3 DM matrix; flag P2/P3 as PRELIMINARY)
    - `table3_5model_decomposition.csv` (P1 M1-M5 QLIKE + pairwise DM; 75%/25% attribution row)
    - `table4_ms_gas_rescue.csv` (P1 MS vs {M1, M2, M3, M4} DM-HLN t, p, QLIKE_rel_pct)
17. Convert K1129/K1133/K1133b PNG figures to PDF via `matplotlib.savefig(... .pdf)` and place into `figures/`. Alternative: soft-link PNG for review cycle; PDF only needed before submission.
18. Write top-level `reproduce.py` — runs `scripts/reproduce_all.py`, parses resulting JSONs, writes `reproduce_report.json` with `{table_id, paper_value, script_value, match_bool, tol}` rows.
19. Run `uv run python paper/btc-gas-negative/reproduce.py` → verify `reproduce_report.json` all `match_bool=true`. If any `false`, apply `docs/paper-guide.md` (a)/(b)/(c) rule before proceeding.
20. Commit: `paper/btc-gas-negative/ reproduction package complete (K1228 guide phase 3)`.

### Phase 4 — Compile + paper-upsert (est. 15 min)

**Goal**: First PDF build + paper registered in platform so `paper-review-cycle` skill can target it.

21. `cd paper/btc-gas-negative && xelatex main.tex && bibtex main && xelatex main.tex && xelatex main.tex` — confirm no undefined refs, no missing citations in log.
22. `cd /Users/yhlai0911/Desktop/volpred-research && uv run volpred ops paper-upsert --paper-id btc-gas-negative --title "Why GAS-t Fails on Bitcoin" --target-journal "Journal of Empirical Finance" --status draft` — register in platform metadata store.
23. `uv run volpred ops paper-upload-pdf --paper-id btc-gas-negative --pdf paper/btc-gas-negative/main.pdf` — push PDF to Supabase + Mirror per canonical paper slug rule.
24. Commit: `paper/btc-gas-negative/ initial compile + paper-upsert (K1228 guide phase 4)`.

### Phase 5 — Review cycle (long-term, 1-2 weeks)

**Goal**: Iterate body_v2, body_v3 via `paper-review-cycle` skill until ready_for_submission stage.

- Invoke `paper-review-cycle` skill — parallel `latex-academic-reviewer` + `citation-verifier`.
- Archive each round in `paper/btc-gas-negative/review_history/v1/`, `v2/`, ... with round-README per existing template.
- Re-compile + `paper-update` per `paper-update` skill after each body revision.
- Stage transitions per `paper-stage-classifier`: draft → review → ready_for_submission → submitted.

---

## 4. Estimated Total Effort

| Phase | Duration | Output |
|---|---|---|
| 1. Skeleton | ~10 min | 6 new files, compliance-baseline-green commit |
| 2. LaTeX cherry-pick | ~60 min | body_v1.tex populated, references.bib 16 entries |
| 3. Reproducibility | ~30 min | scripts/, results/, figures/, reproduce_report.json |
| 4. Compile + upsert | ~15 min | main.pdf + platform-registered paper |
| **Phase 1-4 total** | **~2 hours** | First-compile paper repo |
| 5. Review cycle | 1-2 weeks | Review-iterated body_v2/v3 |

---

## 5. Submission Prep Checklist (run before first external submission)

- [ ] All 5 self-contained items present (`data_sources.md`, `scripts/README.md`, `results/`, `experiments.md`, `README.md`).
- [ ] `reproduce_report.json` all-green match vs paper body numbers (rerun on clean env).
- [ ] `data_sources.md` lists full API endpoint, retrieval date, license/TOS note (yfinance is derivative; document fallback).
- [ ] References bib verified via `citation-verifier` skill (DOI match, author names, year).
- [ ] Target journal format checklist (JoEF: abstract ≤200 words, keywords 3-6, structured section labels, AMS/JEL subject class).
- [ ] Cover letter draft in `cover_letter.tex` addressing: novelty (decomposition methodology), fit (crypto + GARCH extensions + negative result), prior submission status (first submission).
- [ ] Orphan K references (experiments.md TODOs) all resolved or explicitly tagged `unused in final draft`.
- [ ] `paper-stage-classifier` returns `ready_for_submission`.
- [ ] Main-thread review of final v_n body_v.tex (no agent-written `.tex`).

---

## 6. Strict Rules Reminder

- **No `.tex` written by agents** (this K1228 only produces `.md` + `.json`).
- **Numbers verbatim from K1129/K1133/K1133b JSONs** — no recalculation, no divergence.
- **Fixed seed 42** for any re-run.
- **Self-contained hard requirement** per `docs/paper-guide.md` is investigator-enforced at Phase 1 commit, not deferred.
- **Three-way consistency** (script ↔ data ↔ paper numbers) mandated via `reproduce.py`.
- **Phase 5 review cycle is long-term** — do not rush to submission without ≥2 review rounds.

---

## 7. Risk Register

| Risk | Mitigation |
|---|---|
| yfinance API changes break reproduce.py | `data/` cache snapshot at Phase 1; document Binance/Kraken fallback in `data_sources.md`. |
| P2/P3 sub-period sample-starved (n=345, n=100) | Flag PRELIMINARY in Table 2; main text anchors only on P1 (n=1441). |
| Catania (2018) JFEC home journal conflict-of-interest | Default to JoEF (primary); JFEC is backup with explicit framing of "tests and falsifies a JFEC-published claim". |
| MS-GAS-t 2-state may be under-specified | Limitations section (5.6 in draft) acknowledges; flag as future work. |
| Negative-result papers face higher rejection rate | Target JoEF for stated receptivity to methodology papers; cover letter must emphasize decomposition methodology contribution as generalizable. |

---

## 8. Cross-References

- `docs/paper-guide.md` — 5-item self-contained rule, three-way consistency rule, submission prep checklist.
- `docs/error_log.md` — prior-art error patterns to avoid during Phases 1-4.
- `paper/leverage-direction/` — structural template (has main.tex, body_vN.tex, review_history/, reproduce.py, storage/).
- `paper/prg-periodic-garch/`, `paper/taiwan-vt/`, `paper/vt-trend-following/` — additional self-contained reference examples.
- `experiments/k1214/k1214_paper_draft.md` — source draft, cherry-pick input.
- `experiments/k1214/k1214_paper_outline.json` — structured outline + canonical-number cross-check table.
- `.claude/skills/paper-update/SKILL.md` — Phase 4 step 22-23 CLI details.
- `.claude/skills/paper-review-cycle/SKILL.md` — Phase 5 orchestration.
- `.claude/skills/paper-stage-classifier/SKILL.md` — stage transition rules.

---

## 9. Go / No-Go Gate Questions for User

Before Phase 1 execution, main-thread should confirm with user:

1. **Target journal final decision**: JoEF primary confirmed? Or pivot to JFEC as primary (given Catania 2018 venue)?
2. **Title wording**: "Why GAS-t Fails on Bitcoin: Student-t Innovation Is the Culprit, Regime-Switching Cannot Rescue" — keep as-is or soften "Fails"/"Culprit" for journal house style?
3. **Bibliography expansion scope**: 16 entries (K1214 default) or expand to 25-30 for submission? Timing: Phase 2 or Phase 5?
4. **Figure PDF generation**: generate fresh from K1129/K1133/K1133b in Phase 3, or soft-link PNG for review cycle and defer PDF to Phase 5?
5. **Orphan K resolution**: K1133 P2/P3 preliminary flags — keep in paper as caveat, or drop to keep narrative clean?

Once user answers the 5 gate questions, main-thread proceeds to Phase 1 step 1.
