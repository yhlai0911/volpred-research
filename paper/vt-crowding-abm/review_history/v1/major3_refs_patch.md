# MAJOR-3 Refs Patch — Paper 5 (vt-crowding-abm)

**Source of finding**: `review_history/v1/latex_review.md` §MAJOR-3 (lines 80–93).

**Scope**: Add 3 post-2015 VT-skeptic citations to strengthen literature positioning. Patch-only; main thread applies to `main.tex`.

**Prepared by**: paper_review sub-agent, 2026-04-18.
**Style**: `plainnat` + `thebibliography{20}` — matches existing `main.tex` bibitem format (author-year with `\bibitem[Author(Year)]{key}` block).

---

## 1. DOI Verification Status

| # | Cite Key | Task-brief DOI | **Verified DOI** | Status |
|---|---|---|---|---|
| 1 | `barroso2021` | `10.1016/j.jfineco.2020.10.006` | `10.1016/j.jfineco.2021.02.009` | **CORRECTED** — task brief had wrong DOI suffix; verified via ScienceDirect (JFE 140(3):744-767, 2021) |
| 2 | `cederburg2020` | `10.1016/j.jfineco.2019.10.007` | `10.1016/j.jfineco.2020.04.015` | **CORRECTED** — task brief had wrong DOI suffix; verified via ScienceDirect (JFE 138(1):95-117, 2020) |
| 3 | `liu2019` | (no DOI in brief; RFS claim) | `10.3905/jpm.2019.1.107` | **VENUE CORRECTED** — task brief said *Review of Financial Studies*; actual venue is *Journal of Portfolio Management* 46(1):38-51 (Nov 2019). Author order verified: Liu, F., Tang, X., Zhou, G. |

**Verification evidence**:
- (1) Barroso & Detzel — ScienceDirect page `S0304405X21000775`, RePEc `v140y2021i3p744-767`
- (2) Cederburg, O'Doherty, Wang & Yan — ScienceDirect page `S0304405X2030132X`, RePEc `v138y2020i1p95-117`, PDF available via Yan faculty page (`lehigh.edu/~xuy219/research/COWY.pdf`)
- (3) Liu, Tang & Zhou — JPM `jpm.pm-research.com/content/early/2019/09/11/jpm.2019.1.106`, SSRN `3283395`, venue confirmed JPM 46(1) not RFS

All 3 DOIs resolve to correct paper titles and author lists. No UNVERIFIED entries.

---

## 2. Bibitem Drafts (paste-ready, style-matched)

Insert **alphabetically** into the existing `\begin{thebibliography}{20}` block in `main.tex`. Reviewer note: existing bibitems use `\newblock` paragraph breaks and italicize journal names with `\emph{}`. Drafts below replicate that convention.

### 2.1 Barroso & Detzel (2021) — insert between `baltas2019` and `bookstaber2014`

```latex
\bibitem[Barroso and Detzel(2021)]{barroso2021}
Barroso, P. and Detzel, A. (2021).
\newblock Do limits to arbitrage explain the benefits of volatility-managed portfolios?
\newblock \emph{Journal of Financial Economics}, 140(3), 744--767.
\newblock \url{https://doi.org/10.1016/j.jfineco.2021.02.009}
```

### 2.2 Cederburg, O'Doherty, Wang & Yan (2020) — insert between `brunnermeier2009` and `cole2017`

```latex
\bibitem[Cederburg et~al.(2020)]{cederburg2020}
Cederburg, S., O'Doherty, M.~S., Wang, F., and Yan, X.~S. (2020).
\newblock On the performance of volatility-managed portfolios.
\newblock \emph{Journal of Financial Economics}, 138(1), 95--117.
\newblock \url{https://doi.org/10.1016/j.jfineco.2020.04.015}
```

### 2.3 Liu, Tang & Zhou (2019) — insert between `lebaron2006` and `moreira2017`

```latex
\bibitem[Liu et~al.(2019)]{liu2019}
Liu, F., Tang, X., and Zhou, G. (2019).
\newblock Volatility-managed portfolio: Does it really work?
\newblock \emph{Journal of Portfolio Management}, 46(1), 38--51.
\newblock \url{https://doi.org/10.3905/jpm.2019.1.107}
```

**Style consistency notes**:
- All 3 use `\newblock` between author / title / venue / DOI (matches `baltas2019`, `harvey2018`, etc.).
- `et~al.` uses tied space (non-breaking) matching existing `bookstaber2014`, `harvey2016`, `harvey2018`, `perchet2016`.
- DOI as `\url{}` — existing bibitems currently **omit** DOIs entirely (see `citation_review.md` MEDIUM findings). Recommendation: add DOIs to the 3 new entries for immediate alignment with citation-verifier MED requests; optionally backfill existing refs in a follow-up round.

---

## 3. Suggested Inline Citation Placements

Reviewer rationale (from `latex_review.md` MAJOR-3): "Add 2-sentence treatment in Introduction (after line 56) discussing that the empirical VT literature is contested (cite Barroso & Detzel 2021, Cederburg et al. 2020), and that this paper's contribution is orthogonal — we study crowding given VT is used, not whether VT itself delivers alpha."

### Placement A — Introduction paragraph 1 (after `harvey2018` on line 54)

**Current text (line 54)**: "\citet{harvey2018} demonstrate that such strategies meaningfully reduce tail risk across asset classes, and the approach has been widely adopted by pension funds, insurance companies, and target-date funds."

**Suggested insertion (1 new sentence, immediately after above)**:

```latex
However, the empirical case for VT is contested: \citet{cederburg2020} show that
volatility-managed portfolio alphas largely vanish in real-time out-of-sample tests,
\citet{barroso2021} find that the apparent gains concentrate in hard-to-arbitrage
stocks and disappear net of transaction costs for factors beyond the market, and
\citet{liu2019} document that timing the market via volatility alone is dominated
by a static buy-and-hold once look-ahead bias is removed.
```

**Why here**: This is the earliest place where the paper introduces VT as a strategy and cites its proponents (Moreira-Muir, Harvey et al.). Adding the skeptic trio immediately after gives balanced framing before the crowding discussion starts.

### Placement B — Introduction paragraph 3 (around line 58, scope clarification)

**Current text (line 58)**: "A critical gap remains: \emph{at what adoption level does VT crowding become destabilizing?} Existing analyses are either qualitative \citep{ecb2020}, focused on other strategy types \citep{baltas2019}, or lack a quantitative threshold."

**Suggested insertion (1 new sentence, appended to that paragraph)**:

```latex
Our question is orthogonal to the VT-alpha debate \citep{cederburg2020, barroso2021, liu2019}:
we take VT as a given practitioner strategy and ask at what adoption level its
\emph{collective} use becomes destabilizing, regardless of whether individual VT
alpha survives out-of-sample scrutiny.
```

**Why here**: Directly implements the reviewer's "contribution is orthogonal" scoping instruction. Places all 3 new refs in a single parenthetical citation, allowing Placement A to cite them narratively one-by-one or to be collapsed to `\citep{cederburg2020, barroso2021, liu2019}` if the intro word budget is tight.

### Placement C (optional) — §4.3 Limitations, "constant $\lambda$" paragraph (around line 250)

**Current text (line 250)**: "…Our sensitivity analysis (Table~\ref{tab:sensitivity}) confirms that $\lambda$ is the most influential parameter, suggesting that endogenizing it is the highest-priority extension."

**Optional insertion (after this sentence)**:

```latex
Separately, whether VT delivers individual-level alpha in real time is itself
disputed \citep{cederburg2020, liu2019}; our results should be read as conditional
on practitioners continuing to deploy VT regardless of that debate.
```

**Why here**: Strengthens the limitations framing by explicitly bracketing the VT-alpha debate as outside the paper's scope. Optional because Placements A + B already cover the 3 refs.

---

## 4. Minimum-viable apply plan (for main thread)

If word budget is tight and only 1 placement is feasible:
1. **Must-have**: Placement B (single citation covers all 3 refs; directly implements reviewer scope instruction).
2. **Nice-to-have**: Placement A (narrative citation; signals awareness of each paper's distinct claim).
3. **Optional**: Placement C.

If applying all 3 placements: A + B + C add ~60 words to Introduction and ~25 to Limitations — well within FRL 15-page budget.

---

## 5. Scope guard

- **Not modified**: `main.tex`, `experiments.md`, `README.md`, `reproduce.py`.
- **Produced**: This patch file only.
- **No commit performed**.
- **No `work_log.json` append** beyond the sub-agent scope (main thread handles).

---

## 6. References used for verification

- [Barroso & Detzel (2021) — ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0304405X21000775)
- [Barroso & Detzel (2021) — RePEc/IDEAS](https://ideas.repec.org/a/eee/jfinec/v140y2021i3p744-767.html)
- [Barroso & Detzel (2021) — SSRN 3088828](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3088828)
- [Cederburg et al. (2020) — ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0304405X2030132X)
- [Cederburg et al. (2020) — RePEc/IDEAS](https://ideas.repec.org/a/eee/jfinec/v138y2020i1p95-117.html)
- [Cederburg et al. (2020) — Author PDF (Lehigh)](https://www.lehigh.edu/~xuy219/research/COWY.pdf)
- [Liu, Tang & Zhou (2019) — JPM](https://jpm.pm-research.com/content/early/2019/09/11/jpm.2019.1.106)
- [Liu, Tang & Zhou (2019) — SSRN 3283395](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3283395)
