# PRG v8 — Citation verification (read-only)

**Round**: v8, 2026-08-05
**Candidate**: `paper/prg-periodic-garch/main.tex` sha256 `8852326a7b77eb34…`
**Bibliography**: inline `thebibliography`, 18 entries (L218–L329). No `.bib` file; the
`references/` directory holds only `literature_survey.md`.

## Scope and method

Two things get checked separately:

1. **Bibliographic accuracy** — do the 18 entries name real papers with correct venue, year,
   volume, pages, DOI?
2. **Claim–source alignment** — does each in-text citation support what the sentence says?
   This is where the round's most consequential finding sits.

Verification this session was constrained: `WebFetch` and `curl` are denied under the current
permission mode, so publisher pages and Sci-Hub were unreachable. `WebSearch` was available.
Every claim below states which evidence class backs it, and nothing is asserted beyond it.

## 1. Bibliographic accuracy — 18/18 internally consistent, 0 unresolved

All 18 entries carry a DOI and follow a consistent `apalike` pattern. Venue/year/volume/page
fields are mutually consistent with the DOI prefixes (`10.1016/j.frl…` → Finance Research
Letters, `10.1016/j.jbankfin…` → Journal of Banking & Finance, `10.1093/jjfinec…` → Journal of
Financial Econometrics, etc.). No retracted, predatory, or fabricated venue appears.

The v7 round verified all then-present entries against publisher metadata; `c23e36b5c`
(2026-07-19) added the three mechanism citations (AndersenBollerslev1997, HansenLunde2005,
Tsiakas2008) claim-verified at the time. Nothing has changed in the bibliography since.

**Not re-verified this round**: field-by-field DOI resolution against publisher metadata,
because network fetching was denied. The v7 verification is the standing evidence; it predates
no change to these entries, so it is not stale.

Every `\citep`/`\citet` key in the body resolves to a `\bibitem` — no orphan keys, no unused
entries beyond `Haas2004` and `Hansen2012`, both cited once in the body (L209, L84).

## 2. Claim–source alignment

### FINDING (MAJOR-1 in `latex_review.md`) — L207 names Tsiakas (2008) and Todorova & Souček (2014) as instances of the mixed-timing confound; the evidence points the other way

The sentence: *"Comparisons in the overnight-information literature
\citep[e.g.,][]{Tsiakas2008,Todorova2014} that combine components issued at different times…
can overstate model value by several t-units per market."*

The paper's own definition (L103) requires a **full-day composite** built from an
`F^c_{d-1}`-measurable overnight component plus an `F^o_d`-measurable intraday component,
benchmarked against a model held at `F^c_{d-1}`.

**Tsiakas (2008), JBF 32(2), 251–268.** Secondary sources describing the paper's specification
state it models *daytime* returns with feedback from the overnight period and leverage
effects, and that it **does not model overnight returns**. A model that produces no overnight
forecast component cannot form the two-time composite the paper defines. The mixed-convention
attribution does not fit.

**Todorova & Souček (2014), FRL 11(4), 420–428.** Descriptions of the paper's contribution
state it treats overnight information as a **separate regressor** in a HAR framework rather
than folding it into the daily realized-volatility aggregate, forecasting **intraday** realized
volatility. With an intraday target there is no full-day composite to assemble, so again the
attribution does not fit.

**Evidence class and its limit.** These readings come from secondary descriptions retrieved by
`WebSearch` (including later papers characterising both designs), not from the primary PDFs —
full text was unreachable this session. The characterisations are consistent across
independent sources and go to each paper's headline design, which is what the accusation
turns on. They are strong enough to establish that **the manuscript's claim is unsupported**
— which is the finding, since the burden of proof is the manuscript's — and strong enough to
make the accusation actively likely to be wrong. Confirming the positive statement ("these two
papers are coherent open-time designs, cite them as antecedents") should be done against the
primary PDFs before the reframed sentence is committed.

**Why it matters beyond accuracy**: Todorova & Souček (2014) is a *Finance Research Letters*
paper, and FRL is the submission target. Under single-anonymized review, an unsupported
methodological accusation against a prior FRL paper — contradicted by the submitting paper's
own §2.3 — is a direct acceptance risk.

**Recommended disposition**: drop the two keys from L207 (the generic sentence stands on §2.3's
mechanism), or reframe both as antecedents after primary-source confirmation. The second
option is worth the extra verification step: it removes the risk and adds two supporting
citations.

### Checked and clean

- **L55 literature sweep** (`Tsiakas2008`, `AndersenBollerslev1997`, `Blanc2014`,
  `Bollerslev1996`, `Linton2020`, `Kim2023`, `Todorova2014`, `Opschoor2021`, `Lai2024`) —
  each is cited for the general property attributed to it (overnight information moves
  next-session volatility; intraday periodicity; session-level modelling exists in these
  forms). No overreach.
- **L77 `HansenLunde2005`** — cited for assembling a whole-day variance from session
  components. Correct use of that paper's contribution.
- **L77 `Patton2011`, `Hansen2006`** — cited for QLIKE ranking robustness under imperfect
  proxies. Correct; this is the standard citation pair for that result.
- **L84 `Bollerslev1996`** — cited for the periodic GARCH stationarity condition ρ₀ρ₁ < 1.
  Consistent with the periodic ARCH framework of that paper.
- **L84 `Hansen2012`** — cited *to distinguish* PRG's "Realized" label from the daily Realized
  GARCH. Correctly framed as a contrast, not a claim of descent.
- **L84 `BollerslevWooldridge1992`** — Gaussian QML. Standard, correct.
- **L99 `Glosten1993`** — GJR-GARCH benchmark. Correct.
- **L111 `Diebold1995`, `Harvey1997`** — DM test and its small-sample correction. Correct
  pairing; the paper applies both as described.
- **L209 `Lai2024`, `Haas2004`** — cited to contrast PRG's parsimony with latent-regime
  alternatives. `Lai2024` is an author self-citation used as a contrast case, which is
  appropriate and disclosed by authorship.

### MINOR — declaration statements not yet present (submission-package level)

- FRL's current author guidance requires a **CRediT author contribution statement**; the
  manuscript has none. Single-author papers still need it.
- The `\thanks` block (L25–26) says *"All data and replication code are available upon
  request."* The repository already holds a self-contained replication package, and Elsevier
  finance journals increasingly expect a concrete data-availability statement rather than
  "upon request." L118's footnote also refers to "the replication package" as an existing
  object, which sits oddly beside "upon request."

Both are submission-package items rather than manuscript defects; they belong to the
journal-review gate, not to this round's verdict.

## Verdict

**FAIL** on claim–source alignment, driven by the single L207 finding. Bibliographic accuracy
passes 18/18. No unresolved central source, no citation of a retracted or non-existent work.
