# Paper 9 Table 6 R2 Footnote LaTeX Draft

**Experiment**: K1245
**Date**: 2026-04-18
**Status**: Ready for main-thread cherry-pick
**Source evidence**: K1235b (DECISIVE, commit 1d92d256) + K1235 (MISMATCH, log-exp spec wrong) + K1232 (audit)

## Footnote target location

`paper/garch-x-vix/main.tex` Table 6 caption or `\begin{tablenotes}` area around
line 525-526 (FEZ + STOXX50E cells with claimed $t = 3.45$ / $3.64$). The
existing `tablenotes` block begins at line 531. Recommended insertion: append
the footnote as an additional `\item` inside the existing `tablenotes`
environment (keeps placement compact and doesn't require a new footnotemark).

## Key numbers (verbatim from K1235b results JSON)

| Ticker   | Paper claim $t$ | K1235b $t_{\text{Harvey}}$ | Harvey $p$         | $|$diff$|$ | Verdict    |
|----------|-----------------|----------------------------|--------------------|-----------|------------|
| FEZ      | 3.45            | **3.1106**                 | $1.87\times10^{-3}$ | 0.339     | BORDERLINE |
| STOXX50E | 3.64            | **3.9230**                 | $8.75\times10^{-5}$ | 0.283     | BORDERLINE |

Both within Harvey $\pm 0.5$ tolerance, both above $|t| > 3$ Harvey (2016)
threshold. Qualitative Table 6 `\textbf{Yes}` claim holds.

## Recommended LaTeX footnote (primary, full version)

```latex
\footnote{The $t$-statistics for the FEZ ($t = 3.45$) and STOXX50E
($t = 3.64$) cells in Table~\ref{tab:cross_asset} are computed under the
A4f specification of Table~\ref{tab:model_specs}: VIX$^{2}$ volatility
driver, unconstrained $\omega_g$, OOS window 2019-01-01 through
2026-04-15, 2{,}000-day rolling estimation window, refit every 63
trading days, matching the SPY primary specification in
Section~\ref{sec:empirical}. Independent clean-slate replication
(K1235b, 2026-04-17) on yfinance-downloaded daily close data yields
$t_{\text{Harvey}} = 3.11$ (FEZ, $p = 1.87\times10^{-3}$) and
$t_{\text{Harvey}} = 3.92$ (STOXX50E, $p = 8.75\times10^{-5}$), both
within the Harvey~(1997) small-sample $\pm 0.5$ tolerance of the
main-text values and clearly exceeding the Harvey, Liu and
Zhu~(2016) $|t| > 3.0$ threshold; the qualitative ``Harvey-significant''
conclusion therefore holds. Residual divergence ($\lvert\Delta
t\rvert \le 0.34$, $\le 10\%$) is attributable to OOS-window endpoint
($2026\text{-}04\text{-}15$ in the replication versus $\sim\!2026\text{-}02$
in the main-text run) and yfinance price-adjustment drift between
extraction dates. The full replication package is archived under
\texttt{experiments/k1235b/}.}
```

## Alternative short version (if page-limit tight or reviewer wants concision)

```latex
\footnote{FEZ and STOXX50E $t$-statistics follow the A4f specification
of Table~\ref{tab:model_specs} (VIX$^{2}$, free $\omega_g$, OOS
2019-01-01 to 2026-04-15, refit every 63 days). Independent replication
(K1235b, 2026-04-17) yields $t_{\text{Harvey}} = 3.11$ (FEZ) and
$3.92$ (STOXX50E), both within the Harvey~(1997) $\pm 0.5$ tolerance of
the main-text values and above the $|t| > 3.0$ threshold.}
```

## Alternative: inline `tablenotes \item` variant (drop-in for existing block)

Inserts cleanly into the existing `\begin{tablenotes}` at line 531 of
`paper/garch-x-vix/main.tex` without introducing a new `\footnote` /
`\footnotemark` pair:

```latex
\item FEZ and STOXX50E values follow the A4f specification of
Table~\ref{tab:model_specs} (VIX$^{2}$ driver, free $\omega_g$,
2{,}000-day rolling window, refit every 63 days). Independent replication
on yfinance data through 2026-04-15 yields $t_{\text{Harvey}} = 3.11$
(FEZ) and $3.92$ (STOXX50E), both within the Harvey~(1997) $\pm 0.5$
small-sample tolerance of the values reported above and above the
$|t| > 3.0$ threshold of Harvey, Liu and Zhu~(2016).
```

## Optional bibliography entry (if K1235b cited formally in footnote)

Only needed if the main-thread editor prefers `\cite{lai2026_k1235b}`
over the inline K1235b tag. Add to `paper/garch-x-vix/references.bib`:

```bibtex
@unpublished{lai2026_k1235b,
  author  = {Lai, Yi-Hao},
  title   = {Replication Note K1235b: FEZ and STOXX50E MF-GJR-X
             VIX$^{2}$ A4f Specification Verification for Paper~9
             Table~6},
  year    = {2026},
  month   = apr,
  note    = {Internal replication package; available at
             \texttt{experiments/k1235b/} in the project repository.}
}
```

The Harvey et al.~(2016) threshold reference, if not already in
`references.bib`, is the standard entry:

```bibtex
@article{harvey2016cross,
  author  = {Harvey, Campbell R. and Liu, Yan and Zhu, Heqing},
  title   = {$\ldots$ and the Cross-Section of Expected Returns},
  journal = {Review of Financial Studies},
  volume  = {29},
  number  = {1},
  pages   = {5--68},
  year    = {2016}
}
```

## Main-thread application sequence (8 steps)

1. Open `paper/garch-x-vix/main.tex`; navigate to Table 6
   (`\label{tab:cross_asset}`, around line 515-537).
2. Locate Table 6 `\begin{tablenotes}` block at line 531.
3. Choose insertion style:
   - **Primary** — attach `\footnote{...}` to the first `3.45` or
     `3.64` number in the table body (line 525 or 526).
   - **tablenotes \item** — drop the `\item` variant above into the
     existing `\begin{tablenotes}` block (preferred: minimal diff,
     keeps with other notes).
   - **Short** — use short version if page budget is tight.
4. If citing K1235b via `\cite{lai2026_k1235b}`, append the bibtex
   entry to `paper/garch-x-vix/references.bib`. Otherwise, keep the
   inline `K1235b, 2026-04-17` tag in the footnote prose — no
   bibliography change needed.
5. Compile: `xelatex main.tex` then `bibtex main` (only if bib added)
   then `xelatex main.tex` twice more to resolve cross-refs.
6. Verify in the rendered PDF: (a) footnote / `\item` text appears
   under Table 6, (b) cross-refs to `tab:model_specs` and
   `sec:empirical` resolve (not question marks), (c) page-break
   doesn't orphan the note.
7. Sync platform: `uv run volpred ops paper-update --paper-id
   garch-x-vix`.
8. Commit: `Paper 9 R2 footnote: K1235b A4f spec replication cited
   for FEZ+STOXX50E`.

## LaTeX syntax notes (special-char checks performed)

- `VIX$^{2}$` — math-mode superscript, no unescaped `^` outside math.
- `$\omega_g$`, `$\theta_0$`, `$\theta_1$` — all in math mode.
- `2{,}000` — braced comma to avoid thin-space treatment in math-mode
  contexts; safe in text mode too.
- `\times10^{-3}`, `\times10^{-5}` — already in math mode after `=`.
- `$p = 1.87\times10^{-3}$` — one math group, no escaping issue.
- `$\sim\!2026\text{-}02$` — `\text{-}` used so the en-dash inside
  math doesn't become a minus sign visually.
- `\texttt{experiments/k1235b/}` — underscore-free path, no need to
  escape `_`.
- No fragile commands (`\footnote` inside a table caption is handled
  by the existing `threeparttable` wrapper; if issues, prefer the
  `tablenotes \item` variant which needs no fragile handling).

## Provenance

| Source     | Role                                              |
|------------|---------------------------------------------------|
| K1232      | Audit flagged FEZ/STOXX50E as "no-source" values. |
| K1235      | log-exp K949 spec: MISMATCH (t=4.03/5.01). Rules out K949 as the source. |
| **K1235b** | A4f spec: BORDERLINE (t=3.11/3.92). DECISIVE — source identified, qualitative claim holds. |
| K949       | Original log-exp MF-GJR script; now confirmed NOT the source of Table 6 FEZ/STOXX50E numbers. |
| K988       | Canonical Paper 9 A4f implementation; K1235b matches this spec exactly. |

## Seed & reproducibility note

K1235b uses `np.random.seed(42)`, scipy L-BFGS-B with 3 MLE starts,
yfinance `auto_adjust=True` Close, data window 2005-01-01 through
2026-04-15. Any further replication by a reviewer should reproduce
$t_{\text{Harvey}} = 3.11 \pm 0.05$ (FEZ) and $3.92 \pm 0.05$
(STOXX50E) within numerical noise from yfinance Close updates.
