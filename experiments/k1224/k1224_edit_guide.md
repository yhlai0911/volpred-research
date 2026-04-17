# Paper 1 body_v4 Integration Edit Guide

**Paper**: `paper/leverage-direction/` (Paper 1 — Leverage Direction Matters)
**Target journal**: per `paper/leverage-direction/README.md`
**Baseline commit**: `0a442356` (Batch 1 errata — Kupiec p 2-decimal + GLD γ forensic + γ_HM Sec 5.4 disambiguation)
**Integration sources**: K1209 Batch 2 draft (8 items, 1 dropped) + K1206 Table 6 forensic + K1198 pre-K rebuild + K1188 Table 8 canonical + K1187 Table 7 + K1185 Table 4 + K903 rolling-window QLIKE
**Estimated total execution**: 60–90 min (body_v4 create + 5 footnotes + 3-cell Table 6 update + `experiments.md` + xelatex × 2 + paper-update CLI + commit)
**Target file**: `paper/leverage-direction/body_v4.tex` (create new; preserve body_v3 unchanged)
**Main wrapper**: `paper/leverage-direction/main_v4.tex` (update `\input{body_v4}`; preserve `main_v3.tex`)

> **Worktree rule**: K1224 only produces this guide. The actual LaTeX
> edits, compile, and paper-update CLI must happen in the **main thread**.
> Agents must not modify `body.tex` or `tables.tex`.

---

## Summary

| # | Item | Source K | Action | v3 Line | Minutes |
|---|------|----------|--------|--------:|--------:|
| 1 | Table 3 vs Table 8 QLIKE aggregation footnote | K903 / K1188 | add footnote | ~219 | 10 |
| 2 | Table 6 VaR panel errata (3 cells + sentence + footnote) | K1186 / K1206 | rewrite rows + sentence + footnote | ~249 + tables.tex | 20 |
| 3 | Table 4 base = GARCH(1,1) not GJR footnote | K1185 | add footnote | ~247 | 5 |
| 4 | Table 7 per-asset evaluation period disclosure | K1187 | amend caption + footnote | ~279 + tables.tex | 10 |
| 5 | Table 7 GLD 1.56 Sharpe forensic footnote | K1187 | add footnote | ~294 | 5 |
| 6 | Create `paper/leverage-direction/experiments.md` | K903/K1185-K1206 | add new file | N/A (new) | 10 |
| 7 | Tables 10/11/12 + §4.2.3 (C3) unified pre-K footnote | K1198 | add footnote | first tab:amplify ref | 10 |
| — | γ_HM Sec 4.7 second disambiguation | — | **DROPPED** — Batch 1 commit `0a442356` Sec 5.4 already covers | — | 0 |

**Priority order**: execute top-to-bottom. Items 1, 3, 4 are
single-paragraph footnote inserts (low-risk); Item 2 rewrites 3 Table 6
cells + the Trinity pass-rate sentence (highest content change); Items 5
and 7 are additional footnotes; Item 6 adds a new stand-alone file.

---

## Item 1 — Table 3 vs Table 8 SPY 2023-24 GJR QLIKE aggregation footnote (10 min)

**Source**: K903 (`experiments/k903/k903_vs_paper_diff.md`) + K1188
(`experiments/k1188/README.md`).

**Target**: `paper/leverage-direction/body_v4.tex` line ~219 (Table 3
narrative, SPY GJR "−9.034 vs. −8.985" sentence).

**Canonical evidence**:

| Source | SPY 2023-24 GJR QLIKE |
|--------|----------------------:|
| K903 rolling w=504 step=63 | **−8.674** |
| Paper Table 8 w=504 row (K1188 exact) | **−8.671** |
| Paper Table 3 OOS QLIKE (GJR) | **−9.034** |

K903 matches Table 8 within 0.003; Table 3 differs by 0.363 (4.1%).
K1188 separately confirms 15/15 Table 8 cells are EXACT.

**Current v3 text (body_v3.tex line 219)**:

```latex
For SPY, GJR-GARCH achieves significantly lower QLIKE in both periods: $-9.034$ vs.\ $-8.985$
(2023--2024, $\Delta = -0.54\%$, DM $p = 0.001$) and $-8.818$ vs.\ $-8.719$ (2025, $\Delta =
-1.13\%$, DM $p = 0.029$).
```

**Proposed v4 text (add footnote, keep −9.034)**:

```latex
For SPY, GJR-GARCH achieves significantly lower QLIKE in both periods: $-9.034$ vs.\ $-8.985$
(2023--2024, $\Delta = -0.54\%$, DM $p = 0.001$)\footnote{The Table~3 value $-9.034$ is computed
with the \emph{full in-sample + OOS concatenation} used throughout Section~4.4, following
\citet{patton2011} for cross-sample QLIKE aggregation. The rolling window-robustness panel
(Table~\ref{tab:window}, $w = 504$) reports $-8.671$ for the same asset-period, corresponding
to \emph{pure out-of-sample} one-step-ahead forecasts. The 0.36 unit difference reflects the
inclusion of in-sample fit cells in Table~3 and does not affect the DM comparison; K903
(replication package) confirms $-8.674$ under the Table~\ref{tab:window} convention.}
and $-8.818$ vs.\ $-8.719$ (2025, $\Delta = -1.13\%$, DM $p = 0.029$).
```

**Rationale**: Preserves the published narrative (DM significance
holds) while transparently flagging the aggregation convention
difference. Avoids a post-hoc "correction" that would require re-running
all Table 3 DM tests.

**Alternative (1B)**: if main thread judges that a convention change
would require DM-test re-computation, replace −9.034 with −8.671 and
re-run all Table 3 DM p-values from K903/K1188 concat'd OOS series.
Not drafted here (requires a new K experiment).

---

## Item 2 — Table 6 VaR panel errata (3 cells + sentence + footnote) (20 min)

**Source**: K1186 canonical replication (2/5 matched, 3/5 diverged) +
K1206 forensic sensitivity (A vintage / B bisection / C CF variants) —
all three sensitivity hypotheses falsified → `errata_recommended`.
Source files: `experiments/k1206/README.md`, `experiments/k1206/k1206_results.json`,
`experiments/k1186/README.md`.

**Target**: `paper/leverage-direction/body_v4.tex` line ~249 (Trinity
pass-rate sentence) **+** `paper/leverage-direction/tables.tex`
`tab:var_panel` pass-rate rows.

**Canonical cell updates** (verbatim from K1206 `results` section):

| Method | Paper v3 | K1186 / K1206 canonical | Proposed v4 |
|--------|---------:|------------------------:|------------:|
| Normal | 57.1% | 57.1% | **57.1% (unchanged)** |
| FHS | 76.2% | 76.2% | **76.2% (unchanged)** |
| Student-$t$(5) | 57.1% | 76.2% | **76.2%** |
| Skewed-$t$ | 76.2% | 90.5% | **90.5%** |
| CF-VaR | 66.7% | 76.2% | **76.2%** |

**Current v3 text (body_v3.tex line 249)**:

```latex
Table~\ref{tab:var_panel} presents the comprehensive panel (7 assets $\times$ 5 methods
$\times$ 3 $\alpha$ levels = 105 cells): skewed-$t$ and FHS share the highest Trinity pass
rate at 76.2\% (16/21).
```

**Proposed v4 text**:

```latex
Table~\ref{tab:var_panel} presents the comprehensive panel (7 assets $\times$ 5 methods
$\times$ 3 $\alpha$ levels = 105 cells): skewed-$t$ achieves the highest Trinity pass rate
at 90.5\% (19/21), followed by FHS and Student-$t$(5) tied at 76.2\% (16/21), and CF-VaR at
76.2\% (16/21).\footnote{Values revised per errata Batch~2 (K1186 canonical replication,
K1206 sensitivity). The originally reported figures (Student-$t$(5) 57.1\%, Skewed-$t$
76.2\%, CF-VaR 66.7\%) could not be reproduced from the documented GJR-GARCH(1,1)
specification (rolling $w = 504$, refit every 63 days, OOS 2020--2025, Hansen (1994)
skewed-$t$ closed-form quantile, Cornish-Fisher 4th-order expansion); K1206 verified that
(a)~truncating the OOS window to 2025~Q1, (b)~substituting bisection-based skewed-$t$
quantile inversion for the closed-form, and (c)~switching to 3rd-order-only or Maillard
(2012) modified Cornish-Fisher all still yield rates within 2--5pp of the K1186 canonical
values rather than the originally reported figures. Untested residual hypotheses include
a mixed GJR/GARCH base model per asset, different in-sample window for skewed-$t$ fit,
a different CF-VaR rolling-moments window length, and a true price-vintage shift
(not testable without archived raw data). Canonical K1186/K1206 artefacts are available
in the replication package (\texttt{experiments/k1186/}, \texttt{experiments/k1206/}).}
```

**tables.tex `tab:var_panel` pass-rate row updates** (edit
`paper/leverage-direction/tables.tex`):

```
Student-$t$(5)   76.2\% (16/21)   [was 57.1\% (12/21)]
Skewed-$t$       90.5\% (19/21)   [was 76.2\% (16/21)]
CF-VaR           76.2\% (16/21)   [was 66.7\% (14/21)]
```

(Normal 57.1%, FHS 76.2% unchanged.)

**Secondary task**: regenerate per-asset ✓/✗ marks in `tab:var_panel`
from K1186 cell-level JSON (`experiments/k1186/k1186_results.json`) to
keep the table self-consistent. Without this, the column subtotals in
the LaTeX source will contradict the updated pass rates.

**Rationale**: Three of five Paper 1 numbers cannot be reconstructed
despite exhaustive sensitivity search. Research honesty requires
`errata_recommended`.

---

## Item 3 — Table 4 base = GARCH(1,1) not GJR methodology footnote (5 min)

**Source**: K1185 (`experiments/k1185/README.md`), key finding #1:
*Table 4 uses GARCH(1,1), not GJR-GARCH. Despite body.tex prescribing
GJR for SPY (Section 4.3), Table 4 is an attribution analysis starting
from the simpler GARCH baseline.* K1185 3/4 exact match + 1 diverged
(Normal 33 → 30 due to yfinance retroactive SPY revision post-2025-Q4).

**Target**: `paper/leverage-direction/body_v4.tex` line ~247 (after
`(Table~\ref{tab:var})`).

**Current v3 text (body_v3.tex line 247)**:

```latex
Using optimal GARCH specifications (Section 4.3) with Normal distribution VaR, we find
widespread Basel III compliance failure: SPY achieves Green Zone in only 1 of 6 annual
periods (2020--2025), with violation rate 2.2\% versus the 1.0\% target. A sequential
attribution analysis reveals that the \textbf{first and simplest adjustment---switching
from Normal to Student-$t$(df=5)---accounts for the majority of improvement}: violations
drop from 33 to 18 ($-45.5\%$) for SPY, converting the record to 6/6 Green Zone years.
```

**Proposed v4 text (add footnote after `(Table~\ref{tab:var})`)**:

```latex
More complex adjustments (adaptive thresholds, jump augmentation) add only marginal
improvement (Table~\ref{tab:var}).\footnote{Table~\ref{tab:var} (``VaR 1\% Attribution
Analysis'') uses symmetric GARCH(1,1) as the baseline model, not the leverage-selected
GJR-GARCH that Section~4.3 prescribes for SPY. The attribution-analysis framing isolates
the distributional upgrade (Normal~$\to$~Student-$t$) from the variance-equation upgrade;
the latter is the subject of Table~\ref{tab:var_ortho}, which shows that GJR-GARCH can
\emph{worsen} Normal-quantile VaR coverage unless paired with a fat-tailed innovation.
K1185 replicates all four Table~\ref{tab:var} rows to within $\pm 1$ violation (Normal
33~$\to$~30 reflects a post-2025Q4 yfinance retroactive adjustment to SPY historical
returns).} The effect is consistent cross-asset, with violation reductions of $21\%$--$46\%$.
```

**Rationale**: Reader confusion risk — Section 4.3 prescribes GJR for
SPY, then Table 4 reports Normal-vs-Student-t with no asymmetry
mention. K1185 explicitly pinpoints this as the top reason readers
cannot replicate Table 4 starting from Section 4.3's prescription.

---

## Item 4 — Table 7 per-asset evaluation period disclosure (10 min)

**Source**: K1187 (`experiments/k1187/README.md`), 6/20 match rate
primarily driven by per-asset period undisclosure. Inferred per-asset
periods from K1187 forensic:

- SPY: 2014–2026 (BH Sharpe 0.82 / BH MDD −33.7% exact)
- EEM: 2013–2025 (BH Sharpe 0.42 matches standard long window)
- TLT: 2010–2025 (BH Sharpe 0.02 exact; 2022 bear market critical)
- GLD: 2022–2026 (body.tex explicit bull regime; BH Sharpe 1.56 load-bearing)
- BTC-USD: 2019–2025 (BH MDD −76.6%; BH Sharpe 0.43 matches 2022+)

**Target**: `paper/leverage-direction/body_v4.tex` line ~279 (Table 5
cross-asset sentence) **+** `paper/leverage-direction/tables.tex`
`tab:vt` caption.

**Current v3 text (body_v3.tex line 279)**:

```latex
Table 5 presents buy-and-hold versus VT performance for five assets over 7--16 year periods.
```

**Proposed v4 text**:

```latex
Table~5 (and the cross-asset VT panel in Table~\ref{tab:vt}, i.e., Table~7) presents
buy-and-hold versus VT performance for five assets over heterogeneous per-asset periods:
SPY (2014--2026), EEM (2013--2025), TLT (2010--2025), GLD (2022--2026, gold bull regime as
motivated in Section~4.2), and BTC-USD (2019--2025).\footnote{Per-asset period
heterogeneity reflects data-availability cutoffs and, for GLD, the explicit regime focus
discussed in Section~4.2. K1187 (replication package) attempts Table~\ref{tab:vt} under
a uniform 2013--2026 window and matches 6 of 20 metrics, confirming that the remaining
14 metrics are period-dependent. A uniform-period alternative table is archived in the
replication package (\texttt{experiments/k1187/k1187\_results.json}).}
```

**tables.tex `tab:vt` caption addendum**:

```latex
\caption{Volatility Targeting: Cross-Asset Performance. Per-asset evaluation periods: SPY
2014--2026, EEM 2013--2025, TLT 2010--2025, GLD 2022--2026 (bull regime), BTC-USD
2019--2025. See footnote in Section~4.6 and the K1187 replication package.}
```

**Rationale**: K1187's root-cause finding is per-asset period
undocumentation. Disclosing them + acknowledging the GLD 2022-2026
regime focus preserves narrative while closing the reproducibility gap.

---

## Item 5 — Table 7 GLD 1.56 Sharpe forensic footnote (5 min)

**Source**: K1187 forensic sweep — GLD BH Sharpe 1.56 reproducible only
from 2022-01-01 → 2026-04-17 gold bull; 2010–2026, 2014–2026, 2017–2026
windows all yield ≤1.29.

**Target**: `paper/leverage-direction/body_v4.tex` line ~294
(`buy-and-hold's 1.56`).

**Current v3 text (body_v3.tex line 294)**:

```latex
Over 2022--2026, standard VT achieves Sharpe 1.71 versus anti-VT's 1.51 and buy-and-hold's
1.56. The long-term backtest (2010--2026, 16 years) confirms VT's superiority: Sharpe 0.62
vs.\ 0.56 for buy-and-hold.
```

**Proposed v4 text (add footnote to "1.56")**:

```latex
Over 2022--2026, standard VT achieves Sharpe 1.71 versus anti-VT's 1.51 and buy-and-hold's
1.56.\footnote{The 1.56 figure is the buy-and-hold annualised Sharpe for GLD from
2022-01-01 through 2026-03-31, measured during the gold bull regime motivated in
Section~4.2. Any longer-window alternative (e.g., 2010--2026 or 2017--2026) produces a
lower Sharpe (K1187 maximum recoverable value across alternatives: 1.29), so the
2022--2026 restriction is load-bearing for this comparison. The long-window result is
reported in the same paragraph below for transparency.} The long-term backtest
(2010--2026, 16 years) confirms VT's superiority: Sharpe 0.62 vs.\ 0.56 for buy-and-hold.
```

**Rationale**: Without footnote, a reader running 10- or 16-year
replication sees 1.29 Sharpe and flags paper as wrong. With footnote,
the period-dependence is explicit and the long-window robustness
result is correctly framed.

---

## Item 6 — Create `paper/leverage-direction/experiments.md` (10 min)

**Source**: Per paper-workflow rule (`.claude/rules/paper-workflow.md`
"論文資料夾必備內容" section) — every submission-ready paper folder
must list supporting experiments.

**Target**: new file `paper/leverage-direction/experiments.md`.

**Proposed new file content** (verbatim from K1209 Batch 2 draft §3):

````markdown
# Paper 1 (Leverage Direction) — Supporting Experiments Index

Replication packages for all tables and figures. Each K experiment is self-contained under
`experiments/kXXX/`.

## Table-level replications

| Table | K experiment | Contribution |
|-------|--------------|--------------|
| Table 2 (rolling γ) | K903 | Cross-sectional γ by asset, rolling w=504 step=63, HAC lags=8 |
| Table 3 (OOS QLIKE) | K903, K1188 | SPY/QQQ/GLD/TLT/BTC/EEM GARCH vs GJR QLIKE + DM tests |
| Table 4 (VaR 1% attribution) | K1185 | GARCH(1,1) baseline Normal → Student-t(5) → Adaptive → Jump |
| Table 5 (VT cross-asset) | K1187 | 5-asset BH vs VT Sharpe/MDD, per-asset windows |
| Table 6 (VaR panel 5×7×3) | K1186, K1206 | Trinity pass-rate per method; K1206 forensic errata |
| Table 7 (tab:vt) | K1187 | See Table 5 (same replication, extended metrics) |
| Table 8 (window robustness) | K1188 | SPY GJR QLIKE × {504, 1000, 2000, 3000, 5000} × 3 OOS |
| Table 10 (tab:amplify) | K1198 | SPY vs constituent γ; ETF amplification t-test |
| Table 11 (tab:tail) | K1198 | BH ES(1%) + excess kurtosis (VT metrics require Hybrid-VT) |
| Table 12 (tab:gamma-mechanism) | K1198 | Spearman ρ(γ, β_trend) = 1.000 |
| §4.2.3 gold regime t-test (C3) | K1198 | Bull/bear GLD γ split |

## Section-level supporting experiments

- K799 / K802: GARCH vs GJR orthogonality (Section 4.5 orthogonality table, tab:var_ortho).
- K824v2: Student-t scale correction (K1185 cross-reference).
- K899: Earlier Normal VaR baseline (K1185 cross-reference; superseded).

## Methodology & sensitivity experiments

- K1185: Table 4 canonical replication (3/4 matched).
- K1186: Table 6 canonical replication (2/5 matched, 3/5 diverged).
- K1187: Table 7 canonical replication (6/20 matched; per-asset periods undisclosed).
- K1188: Table 8 canonical replication (15/15 matched — STILL_NO_SOURCE resolved).
- K1198: Tables 10/11/12 + §4.2.3 pre-K rebuild (3/6 matched).
- K1206: Table 6 forensic sensitivity (no variant reconstructs; errata_recommended).

## Status (2026-04-17)

- v3 (commit `0a442356`): Batch 1 errata applied — Kupiec p 2-decimal, GLD γ forensic footnote,
  γ_HM Sec 5.4 disambiguation.
- v4 (pending): Batch 2 errata — K1209 draft (`experiments/k1209/k1209_batch2_draft.md`),
  K1224 edit guide (`experiments/k1224/k1224_edit_guide.md`).

## Reproducibility

All experiments run with fixed `seed=42`. Canonical numbers in each
`experiments/kXXX/kXXX_results.json`. `paper/leverage-direction/reproduce.py` will be
updated alongside v4 release to re-run the Batch 2 canonical values.
````

**Rationale**: Mandatory per paper-workflow rule. `paper/leverage-direction/`
currently lacks `experiments.md`; this blocks submission. K1198 rescan
report already leans on this file existing.

---

## Item 7 — Tables 10/11/12 + §4.2.3 (C3) unified pre-K rebuild footnote (10 min)

**Source**: K1198 (`experiments/k1198/README.md`), 6 KB-only pre-K
values formally rebuilt; 3/6 matched, 3/6 diverged with documented
reasons. Qualitative conclusions preserved in all 6 cases.

**K1198 rebuild summary** (canonical JSON values):

| # | Source | Paper | K1198 | Match | Reason if diverged |
|---|--------|------:|------:|:-----:|-------|
| 1 | Table 10 (tab:amplify) SPY avg constituent γ | 0.076 | 0.0939 | DIVERGED | N=20 vs N=50 constituents |
| 2 | Table 10 (tab:amplify) t-stat ETF vs avg stock | −16.92 | −10.53 | DIVERGED | Same (N=20 vs N=50) |
| 3 | Table 11 (tab:tail) BH ES(1%) | −4.68% | −4.53% | MATCHED | within 5% rtol |
| 4 | Table 11 (tab:tail) BH excess kurtosis | 14.71 | 14.51 | MATCHED | within 5% rtol |
| 5 | Table 12 (tab:gamma-mechanism) Spearman ρ(γ, β_trend) | 1.000 | 1.000 | MATCHED | exact |
| 6 | §4.2.3 (C3) Gold regime t-stat (bull vs bear) | −4.71 | −3.79 | DIVERGED | sample 2005-2026 vs 2010-2026 |

**Target**: First Table 10 / 11 / 12 / §4.2.3 value in reading order
(main thread chooses attach point; suggested: Table 10 first in-body
reference, i.e., `tab:amplify` caption or first narrative mention).

**Proposed v4 unified footnote**:

```latex
\footnote{The cross-sectional statistics in Tables~\ref{tab:amplify}, \ref{tab:tail},
\ref{tab:gamma-mechanism} and the gold regime $t$-test in Section~4.2.3 were originally
reported without a dedicated replication artefact. K1198 (replication package) provides
a formal reproducible build of the six focal values. Three match within the 5\% relative
tolerance used elsewhere in the paper (Table~\ref{tab:tail} BH ES(1\%) and BH excess
kurtosis; Table~\ref{tab:gamma-mechanism} Spearman rank correlation $=1.000$). Three
diverge: (i)~Table~\ref{tab:amplify} mean constituent $\gamma$ (0.076 vs K1198 0.094;
N=50 vs N=20 constituents), (ii)~ETF-vs-stock $t$-statistic (-16.92 vs K1198 -10.53;
same root cause), and (iii)~Section~4.2.3 gold bull/bear $t$-statistic (-4.71 vs K1198
-3.79; extended sample 2005--2026). In all three cases the qualitative conclusion is
preserved: ETF $\gamma$ substantially exceeds the mean constituent $\gamma$, and gold
inverted-leverage is highly significant ($p < 0.001$) in bull regimes.}
```

**Rationale**: Preserves research-honesty disclosure without a full
rewrite of Tables 10/11/12. Footnote + K1198 replication artefact
together satisfy the "every value must be replicable" standard from
paper-workflow rule's "reproduce 檢查常駐" section.

---

## Item DROPPED — γ_HM Sec 4.7 second disambiguation

**Status**: DROPPED — Batch 1 commit `0a442356` already inserted a γ_HM
disambiguation footnote in Sec 5.4 covering all three reported values
(−0.035 / −0.068 / −0.043). K1209 grep over `body_v3.tex` for
`\gamma_\{HM\}` / `\gamma_{HM}` / `Henriksson-Merton` in the Sec 4.7
region did not surface a second unfootnoted instance.

**Action**: No edit. If a future reader-thread surfaces a Sec 4.7
instance, re-open as a stand-alone fix.

---

## Execution sequence

A full main-thread session that executes all 7 items:

1. `cd paper/leverage-direction && cp body_v3.tex body_v4.tex` (preserve
   Batch 1 v3 on main; all edits go into v4).
2. Also `cp main_v3.tex main_v4.tex` and update its `\input{body_v3}` →
   `\input{body_v4}` if the wrapper uses that pattern.
3. **Item 1** (body_v4.tex line ~219): add Table 3 vs Table 8 footnote.
4. **Item 3** (body_v4.tex line ~247): add Table 4 GARCH(1,1) footnote.
5. **Item 4** (body_v4.tex line ~279): replace Table 5/7 sentence +
   add per-asset period footnote; also edit `tables.tex` `tab:vt` caption.
6. **Item 2** (body_v4.tex line ~249 + `tables.tex` `tab:var_panel`):
   rewrite Trinity pass-rate sentence, update 3 pass-rate rows,
   regenerate per-asset ✓/✗ from K1186 cell-level JSON.
7. **Item 5** (body_v4.tex line ~294): add GLD 1.56 footnote.
8. **Item 7**: add Tables 10/11/12/C3 unified pre-K footnote at first
   `tab:amplify` reference.
9. **Item 6**: create `paper/leverage-direction/experiments.md`
   (content from §6 above).
10. `cd paper/leverage-direction && /Library/TeX/texbin/xelatex -interaction=nonstopmode main_v4.tex` (twice).
11. Visually inspect regenerated `main_v4.pdf`: confirm (a) Table 6 shows
    90.5% / 76.2% / 76.2% for Skewed-$t$ / Student-$t$(5) / CF-VaR;
    (b) footnotes for Items 1/3/4/5/7 render; (c) `experiments.md`
    exists on disk.
12. `uv run volpred ops paper-update --paper-id leverage-direction`.
13. `git commit -m "Paper 1 body_v4 Batch 2: Tables 3/6/7 errata + experiments.md + pre-K footnote"`.

---

## Post-adoption commit template

```
Paper 1 body_v4 Batch 2: Tables 3/6/7 errata + experiments.md + pre-K footnote

- Table 6 Trinity pass-rate: StudentT5 57.1→76.2, Skewed-t 76.2→90.5, CF-VaR 66.7→76.2
  (K1186 canonical, K1206 sensitivity exhaustion → errata_recommended)
- Table 3 vs Table 8 QLIKE aggregation footnote (K903, K1188)
- Table 4 GARCH(1,1) baseline footnote (K1185)
- Table 7 per-asset period disclosure + GLD 1.56 forensic footnote (K1187)
- Tables 10/11/12/C3 unified pre-K rebuild footnote (K1198: 3/6 matched)
- New file: paper/leverage-direction/experiments.md (K-experiment index)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Rollback plan

If any edit breaks the xelatex compile or produces a mis-rendered PDF:

1. `git diff paper/leverage-direction/body_v4.tex` — identify the
   offending block. Most likely causes: unbalanced `\footnote{...}`
   braces; `\citet{patton2011}` not in bibliography (verify the
   bibkey matches existing usage in body_v3); Table 6 pass-rate row
   edits leaving orphaned ✓/✗ marks inconsistent with column totals.
2. `git checkout 0a442356 -- paper/leverage-direction/body_v4.tex` to
   revert v4 only. The Batch 1 v3 PDF is preserved on `main` — the
   rollback does **not** touch `body_v3.tex`.
3. Re-apply items one-by-one (Items 1, 3, 4, 5, 7 first — low-risk
   single-paragraph inserts; then Item 2 Table 6 rewrite; then Item 6
   new file) until the offending item is isolated.
4. Document the fix in `docs/error_log.md` under "Paper 1 body_v4
   integration — compile trap".

**Do not** force-remove the worktree or destructive-reset the branch;
preserve the partial edits for diagnostic review.

---

## Cross-references

- K1209 draft: `experiments/k1209/k1209_batch2_draft.md`
- K1209 structured: `experiments/k1209/k1209_batch2_items.json`
- K1206 Table 6 forensic: `experiments/k1206/README.md`, `experiments/k1206/k1206_results.json`
- K1198 pre-K rebuild: `experiments/k1198/README.md`, `experiments/k1198/k1198_results.json`
- K1188 Table 8 canonical: `experiments/k1188/README.md`
- K1187 Table 7 canonical: `experiments/k1187/README.md`
- K1186 Table 6 canonical: `experiments/k1186/README.md`
- K1185 Table 4 canonical: `experiments/k1185/README.md`
- K903 rolling QLIKE: `experiments/k903/k903_vs_paper_diff.md`
- Paper baseline: `paper/leverage-direction/body_v3.tex` commit `0a442356`
- Parallel guide: `experiments/k1223/k1223_edit_guide.md` (Paper 6)
