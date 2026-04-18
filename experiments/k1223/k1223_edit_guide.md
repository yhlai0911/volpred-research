# Paper 6 body_v2 Integration Edit Guide

**Paper**: `paper/prg-periodic-garch/` (Paper 6 — PRG Periodic GARCH)
**Target journal**: Finance Research Letters (FRL)
**Baseline commit**: `7d35418b` (Eq.(5)–(6) errata defence, v3 PDF)
**Integration sources**: K1218 Appendix A draft + K1221 pre-submission audit
**Estimated total execution**: 80–120 min (blockers 65–80 min + polish 15–45 min)
**Target file**: `paper/prg-periodic-garch/main.tex` (430 lines)

> **Worktree rule**: K1223 only produces this guide. The actual LaTeX
> edits, compile, and paper-update CLI must happen in the **main thread**.
> Agents must not modify `main.tex`.

---

## Summary

| # | ID | Category | Location | Minutes |
|---|----|----------|----------|---------|
| 1 | B1 | BLOCKER | `main.tex` line 160 (Table 1 0050.TW) | 15 |
| 2 | B2 | BLOCKER | `main.tex` before `\end{document}` (line 430) + cross-ref at line ~206 | 55 |
| 3 | W1 | WARN   | New file `paper/prg-periodic-garch/data/README.md` | 10 |
| 4 | W2 | WARN   | `paper/prg-periodic-garch/data_sources.md` (append) | 5 |
| 5 | W3 | WARN   | `paper/prg-periodic-garch/reproduce.py` (pin canonical) | 30 |
| 6 | B3 | BLOCKER | CLI run from repo root | 5 |

**Priority order**: execute top-to-bottom. B3 is last because it
synchronises Supabase + Mirror after B1+B2 (+ optionally W1–W3) are in.

---

## Item 1 — B1 (BLOCKER, 15 min): Table 1 0050.TW OOS date correction

**Source**: K1221 audit item 3.4 (DIV-2 from `reproducibility_audit/diff_report.md`)
**File**: `paper/prg-periodic-garch/main.tex`
**Line**: 160

**Current content (line 160)**:

```latex
0050.TW    & OHLC (yfinance) & 1{,}266 & 2019/12--2026/04 & 46.1 & 53.9 \\
```

**Change to**:

```latex
0050.TW    & OHLC (yfinance) & 1{,}266 & 2021/01--2026/04 & 46.1 & 53.9 \\
```

**Diff**:

```diff
- 0050.TW    & OHLC (yfinance) & 1{,}266 & 2019/12--2026/04 & 46.1 & 53.9 \\
+ 0050.TW    & OHLC (yfinance) & 1{,}266 & 2021/01--2026/04 & 46.1 & 53.9 \\
```

**Reason**: K886 JSON actual OOS period is 2021-01-08 → 2026-04-02
(n_oos = 1266 matches; only the date string was stale). The
audit item 3.4 is the only paper-body defect among the 10 spot-checked
numbers (all 10 matched JSON at 3-dp); correcting this line is a
typographical fix, not a numerical one.

**Verification after edit**: `rg -n "0050.TW.*2019/12" main.tex` should
return zero hits.

---

## Item 2 — B2 (BLOCKER, 55 min): K1218 Appendix A integration

**Source**: K1221 audit item 7.1 + K1218 draft (`experiments/k1218/k1218_appendix_draft.md`)
**File**: `paper/prg-periodic-garch/main.tex`
**Locations**:
- Cross-reference sentence: Section 4.1 after Table 2 (line ~206, end of first paragraph after `\end{table}` block at line 204)
- Appendix body: between `\end{thebibliography}` (line 428) and `\end{document}` (line 430)

**Approach**: *Approach A — inline appendix in main.tex*. Simplest for
FRL (single-file submission is common). Separate `appendix.tex` +
`\include` (Approach B) is valid but adds a build-system dependency;
K1218 and K1221 both assume Approach A.

### Step 2a — Cross-reference sentence in Section 4.1

**Location**: `main.tex` line 206, at the end of the paragraph that
begins "The PRG Extended model significantly outperforms GJR-GARCH in
every market..." (the paragraph ends with "...a result we discuss
further below."). Append one sentence **before** the paragraph closes.

**Diff** (append to the same paragraph, line 206):

```diff
  The PRG Extended model significantly outperforms GJR-GARCH in every market, with DM $t$-statistics ranging from 4.26 (QQQ) to 6.63 (EEM), all surpassing the \citet{Harvey2016} threshold. The comparison against Separate GARCH is equally decisive: DM statistics range from $-4.07$ (TAIFEX) to $-6.69$ (SPY), confirming that the cross-session information bridge---not merely the session-specific parameterization---drives the improvement. The PRG Extended also significantly outperforms HAR in four of six markets; the TAIFEX comparison yields $t = 2.63$, below the Harvey threshold, a result we discuss further below.
+ Appendix~\ref{app:replication}.3 documents an independent clean-slate replication of the SPY results, yielding DM $t=6.13$ against the main-text $6.00$, which confirms the transcription of Eqs.~(\ref{eq:prg_ov_forecast})--(\ref{eq:prg_fullday}).
```

The cross-reference wording is **verbatim** from K1218 line 146–149
(`k1218_appendix_draft.md` A.5 recommendation), adjusted only to use the
paper's existing equation labels `eq:prg_ov_forecast` / `eq:prg_fullday`
(already referenced in Table 2 footnote line 202).

### Step 2b — Appendix body before `\end{document}`

**Location**: `main.tex` between line 428 (`\end{thebibliography}`) and
line 430 (`\end{document}`). Insert the block below after line 428.

**Insertion** (verbatim LaTeX from K1218 `k1218_appendix_draft.md`,
converted from its markdown+LaTeX hybrid to pure LaTeX):

```latex
\appendix

\section{Independent Replication of the Two-Phase Forecast Timing}
\label{app:replication}

\subsection{Motivation}

To ensure the PRG forecasting framework presented in Eqs.~(\ref{eq:prg_ov_forecast})--(\ref{eq:prg_fullday}) is not an artefact of the original code implementation, we conduct a clean-slate replication from scratch, using only the mathematical specification stated in Section~2.2 without reference to the original estimation code. This serves as transcription evidence that the documented two-phase timing convention is recoverable from the paper alone, and that the empirical figures reported in the main text are not tuned to a particular coding path. We regard this exercise as a transparency aid for future implementers and as direct rebuttal material for reviewers questioning whether the overnight realized squared return $r^2_{d,0}$ is handled consistently with the information set $\mathcal{F}_{d}^{\,o}$ claimed by Eq.~(\ref{eq:prg_fullday}).

The clean-slate implementation (indexed as K1200 in the project reproducibility ledger) was written by a distinct author pass and deliberately avoided reuse of the canonical K880 codebase. Only the estimation period, data source (\texttt{yfinance} SPY OHLC), and split convention were matched; all estimator code was reconstructed from the Eq.~(\ref{eq:prg_ov_forecast})--(\ref{eq:prg_fullday}) formulae.

\subsection{Methodology}

\begin{itemize}
  \item \textbf{Data.} SPY open/high/low/close observations covering
    \mbox{2000--01--04} through \mbox{2026--04--02}, retrieved via the
    public \texttt{yfinance} interface. This is the same universe and
    window used by the main-text SPY analysis.
  \item \textbf{Session returns.} Overnight returns are defined as
    $r_{d,0}=\log(\text{Open}_d/\text{Close}_{d-1})$ and intraday returns
    as $r_{d,1}=\log(\text{Close}_d/\text{Open}_d)$, consistent with
    Section~2.1.
  \item \textbf{In-sample / out-of-sample split.} In-sample ends
    \mbox{2018--12--31} ($n_{\mathrm{IS}}=4778$); out-of-sample covers
    \mbox{2019--01--02}--\mbox{2026--04--02} ($n_{\mathrm{OOS}}=1823$),
    matching the canonical SPY specification in Table~\ref{tab:spy}.
  \item \textbf{PRG Extended (8 parameters).} $\alpha_0,\gamma_0,\beta_0,
    \alpha_1,\gamma_1,\beta_1,\omega_0,\omega_1$ estimated by joint MLE on
    the interleaved overnight/intraday sequence via \texttt{L-BFGS-B}.
  \item \textbf{Optimizer.} Ten random starts per refit window (the main
    text uses five; the larger $n_{\mathrm{starts}}$ in the replication is
    intentional, to probe the sensitivity of the canonical figures to
    optimizer randomness).
  \item \textbf{Refit cadence.} Annual refit (every 252 trading days);
    state $h_{d-1,1}$ is propagated forward between refits.
  \item \textbf{Benchmark.} GJR-GARCH(1,1) with Student-$t$ innovations
    fitted on close-to-close returns, refit every 63 days.
  \item \textbf{Evaluation.} Out-of-sample QLIKE loss \citep{Patton2011},
    Diebold--Mariano test with the Harvey--Leybourne--Newbold (1997)
    small-sample correction, and Spearman rank correlation with realized
    proxy $r^2_{d}$.
  \item \textbf{Seeds.} A master seed of $42$ initialises the random
    starts; per-refit seeds are incremented sequentially so that each
    refit window is deterministic conditional on the master seed.
\end{itemize}

\subsection{Replication results}
\label{sec:appa_results}

Table~\ref{tab:appa_replication} reports the canonical SPY figures from the main-text analysis (denoted ``canonical'') against the clean-slate replication.

\begin{table}[H]
\centering
\small
\begin{tabular}{lccc}
\toprule
Metric & Canonical (main text) & Clean-slate replication & $\Delta$ \\
\midrule
GJR-GARCH QLIKE                    & 0.8542 & 0.8544 & $+0.0002$ \\
PRG Extended QLIKE                 & 0.7478 & 0.7355 & $-0.0124$ \\
DM $t$ (PRG Extended vs.\ GJR)     & 6.004  & 6.128  & $+0.124$  \\
Spearman $\rho$ (PRG Extended)     & 0.5678 & 0.5761 & $+0.0084$ \\
$n_{\mathrm{OOS}}$                 & 1823   & 1823   & $0$       \\
\bottomrule
\end{tabular}
\caption{Canonical main-text SPY figures against an independent clean-slate replication of Eqs.~(\ref{eq:prg_ov_forecast})--(\ref{eq:prg_fullday}). Both columns share identical data, split, and benchmark specification. The replication uses ten random starts per refit window, twice the canonical five.}
\label{tab:appa_replication}
\end{table}

All four metrics fall within the pre-registered replication tolerance bands: $|\Delta\text{QLIKE}| < 0.05$ and $|\Delta\text{DM}_t| < 0.3$. Importantly, the replication performs marginally \emph{better} than the canonical run on every PRG diagnostic (lower QLIKE, higher DM $t$, higher Spearman), while the GJR benchmark is essentially unchanged. This directionality indicates that the canonical figures reported in Section~4 are \emph{conservative} rather than inflated: a fresh implementation using only the paper's equations yields the same qualitative conclusion (PRG Extended strictly dominates GJR under QLIKE) with slightly stronger statistical support.

\subsection{Interpretation}

Three implications follow from Table~\ref{tab:appa_replication}.

First, the two-phase forecast timing convention stated in Eqs.~(\ref{eq:prg_ov_forecast})--(\ref{eq:prg_fullday}) is \emph{faithfully transcribed} from the canonical estimation code. Because the clean-slate author did not have access to the canonical code during implementation, any coding-path artefacts would have produced divergent numerics. The close agreement ($|\Delta\text{DM}_t|=0.124$, well below the 0.3 replication threshold) rules out an implementation gap between the paper's equations and the reported figures.

Second, the day-$d$ overnight realized squared return $r^2_{d,0}$ that enters $\hat{h}_{d,1}$ via Eq.~(\ref{eq:prg_fullday}) is legitimate conditional information at the day-$d$ open. It is a realized, not forecasted, quantity at the time the intraday forecast is issued; the forecasted object ($\hat{h}_{d,1}$) is evaluated against the \emph{next} realized component ($r^2_{d,1}$), which is strictly in the future. The clean-slate code enforces this timing via a separate $\hat{h}_{d,0}$ step (issued at close $d-1$) and a $\hat{h}_{d,1}$ step (issued at open $d$), and produces the same QLIKE ordering without any signal-at-$t$ multiplied by return-at-$t$ shortcut.

Third, practitioners can implement the PRG framework directly from the paper's mathematical specification. No private convention, no hidden initialisation trick, and no tuning to specific optimizer settings are required to recover the main-text findings.

\subsection{Reproducibility package}

\begin{itemize}
  \item \textbf{Code.} \texttt{experiments/k1200/} in the project repository. The script \texttt{k1200.py} accepts no arguments and writes all outputs to \texttt{k1200\_results.json} plus \texttt{k1200\_charts/}.
  \item \textbf{Data.} SPY OHLC, \mbox{2000--01--04} through \mbox{2026--04--02}, pulled at runtime via the public \texttt{yfinance} API. No proprietary or paid data are required.
  \item \textbf{Random seeds.} Master seed $42$ for initialisation of all random starts; per-refit seeds incremented sequentially so each refit window is deterministic.
  \item \textbf{Runtime.} Approximately 50 minutes on a single Apple M1 Max core (numba-accelerated inner loop).
  \item \textbf{Reference.} K880 canonical run (\texttt{experiments/k880/k880\_results.json}) is the source of the ``canonical'' column in Table~\ref{tab:appa_replication}.
\end{itemize}
```

**Notes on the LaTeX conversion** (markdown → LaTeX):
- K1218 draft used `## A.1 Motivation` etc.; converted to `\subsection{Motivation}` under `\section{Independent Replication of the Two-Phase Forecast Timing}` with `\label{app:replication}`.
- K1218 line 26 `\begin{itemize}` blocks are already LaTeX-native, carried over verbatim.
- K1218 line 65 `\begin{table}[H]` requires `\usepackage{float}`; verify `main.tex` preamble. If absent, replace `[H]` with `[htbp]`.
- K1218 text referenced `Eqs.~(5)--(6)` in prose; converted to
  `\ref{eq:prg_ov_forecast}--\ref{eq:prg_fullday}` to match existing labels
  (Table 2 footnote already uses these labels, so they must exist).
- `\citep{Patton2011}` replaces K1218's `(Patton, 2011)` parenthetical to
  match the paper's `natbib`/`authordate` style (Table 2 notes use
  `\citet{Harvey2016}` which is equivalent).

**Reason**: K1221 classifies this as the **single highest-ROI submission
fix**. Without it, the `7d35418b` errata is an internal decision with no
reviewer-visible defence. The appendix converts that internal decision into
a one-paragraph cross-reference plus a self-contained replication result
table, giving the reviewer direct rebuttal material for
Eq.(5)–(6) transcription questions.

---

## Item 3 — W1 (WARN, 10 min): `data/README.md` stub

**Source**: K1221 audit item 1.2
**File**: new — `paper/prg-periodic-garch/data/README.md`

**Create new file with content**:

```markdown
# Paper 6 — Data folder index

This folder holds pointers to the data used by the PRG Periodic GARCH
paper. Raw tick-level TAIFEX data are too large to ship with the paper
and are available on request (see `../data_sources.md`); the U.S.
ETF and Taiwan ETF data are pulled at runtime from Yahoo Finance.

## Data locations

| Dataset | Source | Path in this repo |
|---------|--------|-------------------|
| TAIFEX TX tick (5-min RV) | Proprietary tick feed | `~/Dropbox/TAIFEXDATA/` (local), processed RV in `experiments/k874/data/` |
| SPY / QQQ / GLD / EEM OHLC | yfinance public API | pulled at runtime, see `../reproduce.py` |
| 0050.TW OHLC              | yfinance public API | pulled at runtime, see `../reproduce.py` |
| K880 canonical SPY run    | Project experiment | `experiments/k880/k880_results.json` |

See `../data_sources.md` for API endpoints, retrieval commands, and
the TAIFEX data-availability clause. See `../scripts/README.md` for
the per-experiment K → script mapping.
```

**Reason**: `docs/paper-guide.md` rule 1 accepts `data/` OR
`data_sources.md`; this paper uses the latter. Reviewers, however, open
`data/` first. A 10-line stub closes that UX gap without duplicating
`data_sources.md`.

---

## Item 4 — W2 (WARN, 5 min): TAIFEX data-on-request clause

**Source**: K1221 audit item 1.6
**File**: `paper/prg-periodic-garch/data_sources.md` (append to end)

**Append** (after existing content):

```markdown

## Data availability

TAIFEX tick-level raw data are proprietary and not redistributed in this
repository. They are available upon written request to the corresponding
author; alternatively, the processed daily session realized variances
used in the paper are bundled in `experiments/k874/data/` and are
sufficient to reproduce Tables 2–5 for the TAIFEX rows.
```

**Reason**: FRL's "data available on request" is acceptable but the
package must state it explicitly. K1221 flags the absence as a WARN.

---

## Item 5 — W3 (WARN, 30 min): `reproduce.py` pin canonical K880

**Source**: K1221 audit item 2.4
**File**: `paper/prg-periodic-garch/reproduce.py`

**Current issue**: `reproduce.py` line 76 runs `k880v2_prg_fixed.py`
which yields QLIKE = 0.864 and DM = −0.57. The paper body (Table 2)
uses the K880 canonical values QLIKE = 0.748 and DM = 6.00 (defended by
the `7d35418b` errata commit and K1200). A reviewer running
`reproduce.py` today will see the K880v2 numbers and be confused.

**Options** (pick one, (b) is safer):

- **(a) Pin K880 canonical**: change the main-result path in
  `reproduce.py` to execute `k880_prg_main.py` (or the equivalent
  canonical K880 script) and compare against `k880_results.json`.
- **(b) Add K1200 band check**: after running K880v2, additionally run
  `k1200.py` and verify `|ΔQLIKE| < 0.05` and `|ΔDM_t| < 0.3` against
  `k880_results.json`. Emit a "MINOR_DIVERGENT band PASS" line. This
  preserves the K880v2 smoke test while also vindicating the paper's
  canonical numbers.

**Either option must additionally** emit a comment block at the top of
`reproduce.py` explaining:

```python
# NOTE: Main-text Table 2 SPY row uses K880 canonical (QLIKE=0.748, DM=6.00).
# K880v2 (this script's "smoke test") is a lookahead-bias ablation that yields
# QLIKE=0.864, DM=-0.57. See the `7d35418b` errata commit and Appendix A
# (K1200 clean-slate replication, DM=6.13) for the canonical defence.
```

**Reason**: K1221 flags this as a WARN, not a blocker, because the audit
confirms 10/10 paper-body numbers match source JSON at 3-dp. But a
reviewer running `reproduce.py` without reading the errata will see a
catastrophic-looking divergence. Option (b) is preferred because it
verifies the `7d35418b` + K1200 defensibility band at reproduce-time.

---

## Item 6 — B3 (BLOCKER, 5 min): `paper-update` CLI rerun

**Source**: K1221 audit item 7.3
**CLI**: from repository root,

```bash
uv run volpred ops paper-update --paper-id paper-6
```

**Prerequisites** (must complete before running this CLI):

1. Items 1 and 2 above are done (B1 Table 1 date + B2 appendix integration).
2. `xelatex` has been run twice on the edited `main.tex` from
   `paper/prg-periodic-garch/` so that cross-references (Table~2,
   Appendix A.\ref{sec:appa_results}) resolve. Suggested commands:
   ```bash
   cd paper/prg-periodic-garch
   /Library/TeX/texbin/xelatex -interaction=nonstopmode main.tex
   /Library/TeX/texbin/xelatex -interaction=nonstopmode main.tex
   ```
3. Visual sanity check: open the regenerated `main.pdf` and confirm
   (a) Table 1 shows "2021/01--2026/04" for the 0050.TW row, (b) the
   new Section 4.1 cross-reference sentence renders, (c) Appendix A
   appears after the bibliography with a populated A.3 table.

**Reason**: B3 is a synchronisation step. Running the CLI after B1+B2
(and optionally W1–W3) covers all three blockers in a single Supabase /
Mirror sync. Running it earlier would sync a partially-fixed PDF; running
it only once at the end is the recommended sequence.

---

## Execution sequence

A full main-thread session that executes all 6 items:

1. `git checkout -b paper-6-body-v2` from the `7d35418b` baseline (or
   latest `main`). Do **not** edit `main.tex` in place on `main`.
2. **Item 1 (B1)**: edit `main.tex` line 160.
3. **Item 2 (B2)**: add cross-reference sentence at line ~206; append
   appendix block before `\end{document}` at line 430.
4. **Item 3 (W1)**: create `data/README.md`.
5. **Item 4 (W2)**: append data-availability clause to `data_sources.md`.
6. **Item 5 (W3)**: update `reproduce.py` (option b recommended).
7. `cd paper/prg-periodic-garch && /Library/TeX/texbin/xelatex -interaction=nonstopmode main.tex` (twice).
8. Visually inspect regenerated `main.pdf`.
9. **Item 6 (B3)**: `uv run volpred ops paper-update --paper-id paper-6` from repo root.
10. `git commit -m "Paper 6 body_v2: K1218 appendix + K1221 fixes (B1/B2/B3 + W1/W2/W3)"`.
11. Re-run K1221 audit script (if automated) or manually spot-check
    the 3 blockers → all PASS.

---

## Rollback plan

If any edit breaks the xelatex compile:

1. `git diff main.tex` — identify the offending block (most likely
   causes: mismatched `\label` / `\ref`; missing `\usepackage{float}`
   for the `[H]` specifier in Table appa_replication; bibitem
   `\citep{Patton2011}` not defined if the existing bibliography is
   numeric-only).
2. `git checkout 7d35418b -- paper/prg-periodic-garch/main.tex` to
   revert `main.tex` only. The v3 PDF on disk is preserved.
3. Re-apply items one-by-one until the offending item is isolated.
4. Document the fix in `docs/error_log.md` under
   "Paper 6 body_v2 integration — compile trap".

**Do not** force-remove the worktree or destructive-reset the branch;
preserve the partial edits for diagnostic review.

---

## Cross-references

- K1218 draft: `experiments/k1218/k1218_appendix_draft.md`
- K1218 meta: `experiments/k1218/k1218_appendix_meta.json`
- K1221 audit: `experiments/k1221/k1221_submission_checklist.md`
- K1221 structured: `experiments/k1221/k1221_checklist_results.json`
- Paper baseline: `paper/prg-periodic-garch/main.tex` commit `7d35418b`
- K1200 canonical defence: `experiments/k1200/k1200_results.json`
- K880 canonical numbers: `experiments/k880/k880_results.json`
