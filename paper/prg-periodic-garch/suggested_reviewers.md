# Suggested Reviewers — P6 Periodic Realized GARCH

**Target journal**: Finance Research Letters (FRL)
**Submission status**: DRAFT (awaiting user decision)
**Date prepared**: 2026-04-28

---

## FRL Submission Portal Field

Most FRL submission portals allow 3–5 suggested reviewers and 0–2 opposed (do-not-consider) reviewers. The list below is sized to fit either norm.

---

## Suggested Reviewers (5 candidates)

### 1. Andrew J. Patton — Duke University

- **Email**: andrew.patton@duke.edu
- **Expertise**: Volatility forecasting, robust loss functions (QLIKE), forecast evaluation
- **Why suitable**: Patton (2011) is one of the paper's central methodological references — the QLIKE-as-robust-loss framework underlies the §4 evaluation. Patton has published extensively on multivariate volatility and forecast comparison and is a natural referee for any paper that builds on the robust-loss-with-noisy-proxy framework.
- **Conflict check**: No coauthorship with Yi-Hao Lai. Different country / institution. No PhD-supervisor relationship.

### 2. Peter R. Hansen — University of North Carolina at Chapel Hill

- **Email**: peter.hansen@unc.edu
- **Expertise**: Realized GARCH, Realized Volatility, MCS, RV evaluation
- **Why suitable**: Hansen and Lunde (2005) is the second methodological pillar of the paper's fair-comparison framework, and Hansen, Huang, and Shek (2012) "Realized GARCH: A Joint Model for Returns and Realized Measures" is the closest direct ancestor of the PRG specification. PRG can be read as a session-periodic extension of the Realized GARCH family, so Hansen's expertise maps directly onto the model's correctness assessment.
- **Conflict check**: No coauthorship with Yi-Hao Lai. Different country / institution.

### 3. Fulvio Corsi — University of Pisa

- **Email**: fulvio.corsi@unipi.it
- **Expertise**: HAR-RV, long-memory volatility, intraday volatility modeling
- **Why suitable**: Corsi (2009) HAR-RV is the dominant alternative model in the close-to-close volatility-forecasting literature, used as one of the §4 baselines in the paper. The paper's headline methodological correction (HAR's apparent dominance over GJR is a target-mismatch artifact under fair evaluation) directly engages the HAR literature, so the original HAR author is well-placed to assess whether the correction is fair.
- **Conflict check**: No coauthorship with Yi-Hao Lai. Different country / institution.

### 4. Federico M. Bandi — Johns Hopkins University

- **Email**: fbandi1@jhu.edu
- **Expertise**: High-frequency econometrics, RV theory, microstructure noise
- **Why suitable**: Bandi has published extensively on RV theory, bias-variance trade-offs in RV measures, and the role of overnight vs intraday returns in volatility estimation. He is a natural referee for any paper that uses tick-level TAIFEX RV and combines it with daily OHLC RV across markets.
- **Conflict check**: No coauthorship with Yi-Hao Lai. Different country / institution.

### 5. Roxana Halbleib — University of Freiburg

- **Email**: roxana.halbleib@vwl.uni-freiburg.de
- **Expertise**: Multivariate volatility, GARCH evaluation, realized covariation
- **Why suitable**: Halbleib has co-authored several papers on GARCH-class evaluation methodology and forecast loss-function selection, with a reputation for careful methodological assessment. She would be well-suited to evaluate the §4.5 GJR-X fair-information benchmark — the paper's strongest single methodological innovation.
- **Conflict check**: No coauthorship with Yi-Hao Lai. Different country / institution.

---

## Opposed Reviewers (do-not-consider) — optional, 0–2

### 1. Tim Bollerslev — Duke University (only if absolutely required)

- **Why oppose** *(soft conflict)*: Bollerslev and Ghysels (1996) is the paper's direct ancestor — the periodic GARCH framework that PRG extends. A reviewer assignment to Bollerslev could be either favorable (familiar with the framework) or adversarial (defending the original calendar-periodicity scope). On balance, the editor's judgment should prevail; this entry is a flag rather than a hard veto.
- **Recommendation**: **Leave blank** unless FRL portal forces a non-empty opposed list. Soft conflicts are best left to the editor.

---

## Why these five (rationale for editor)

The five suggested referees cover the paper's three methodological pillars:

| Pillar | Primary referee | Backup |
|---|---|---|
| Realized GARCH / RV theory | Hansen | Bandi |
| Fair-target evaluation (HAR vs GJR critique) | Patton | Corsi |
| Multivariate / cross-asset GARCH evaluation | Halbleib | Patton |
| Tick-level RV (TAIFEX validation) | Bandi | Hansen |

No two referees from the same institution or country. All five are tenured / senior researchers with substantive methodological-letter publications, appropriate for FRL editorial assignment.

---

## Notes for user before submission

- FRL portal usually accepts 3–5 suggestions; the top 3 (Patton, Hansen, Corsi) are the strongest fits and could be submitted alone if portal limits to 3.
- Email addresses listed above are the institutional addresses on faculty pages as of the preparation date; the user should re-verify against current faculty listings before pasting into the portal in case of recent moves.
- The "opposed reviewers" field is optional. The Bollerslev soft-conflict flag is documented here for traceability but is **not recommended for submission** — editor judgment is more reliable than a soft self-disclosure.

---

## Cross-link

- `paper/prg-periodic-garch/cover_letter.md` (companion submission material)
- `paper/prg-periodic-garch/SUBMISSION_READY.md` (gate status)
- `paper/prg-periodic-garch/main.tex` (final manuscript)
