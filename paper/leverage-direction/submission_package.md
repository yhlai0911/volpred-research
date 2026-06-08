# Submission Package — Leverage Direction (Paper 1)

**Status**: `READY_FOR_UPLOAD` (per decision_2026_06_05.md submit-first path; finalized 2026-06-08)
**Target Journal**: Journal of Banking and Finance (JBF)
**Managing Editor**: Christa H. S. Bouwman (Texas A&M, Mays Business School)

## Manuscript

- `main.tex` / `main.pdf` — main manuscript (~48 pages after v10 shortening)
- `supplementary.tex` / `supplementary.pdf` — appendix / robustness moved out (~9 pages)
- `body_v3.tex` — source body (compiled into `main.tex`)
- `tables_main.tex` / `tables_supplement.tex` — split per v10 shortening

## Portal Upload Bundle

| File | Use | Format |
|------|-----|--------|
| `main.pdf` | Main manuscript | PDF |
| `supplementary.pdf` | Supplementary material | PDF |
| `cover_letter.pdf` | Cover letter | PDF (2 pp, addressed to Prof. Bouwman, includes C3 K899 R&R acknowledgement) |
| `highlights.txt` | 5 highlights (portal text field) | plain text |
| `graphical_abstract.png` | Graphical abstract (raster) | PNG 1600px wide @ 300 dpi |
| `graphical_abstract.pdf` | Graphical abstract (vector) | PDF (35 KB) |
| `graphical_abstract.svg` | Source vector (fallback) | SVG |

## Cover Letter (`cover_letter.tex`)

- **Addressee**: Prof. Christa H. S. Bouwman, Managing Editor, *Journal of Banking and Finance* (Mays Business School, Texas A&M)
- **Three contributions** restated (leverage taxonomy → GARCH selection / VT alpha channel / time-zone momentum)
- **C3 acknowledgement**: Table 5 unified VaR (K899) reserved for revision round; current Table 5 internally consistent within each source experiment
- **Suggested reviewers** (3): Peter R. Hansen (UNC), Alan Moreira (Rochester), Dirk G. Baur (UWA)
- **Author**: Yi-Hao Lai, Department of Finance, Da-Yeh University

## Highlights (`highlights.txt`)

Five bullets, each ≤ 85 characters (verified):

1. Gold exhibits regime-dependent inverted leverage (t = -5.79, 93% negative)
2. GJR-GARCH beats GARCH only when gamma > 0.10; gamma sign guides selection
3. Gamma predicts VT alpha channel for equities (rho = 0.886, p = 0.019)
4. VT drawdown reduction is universal, driven by volatility level (rho = 0.944)
5. Time-zone momentum yields t > 3.0 in six Asia-Pacific markets after costs

## Graphical Abstract

- Source: `graphical_abstract.svg` (5.6 KB vector)
- Portal raster: `graphical_abstract.png` (1600 px wide @ 300 dpi, 312 KB)
- Portal vector: `graphical_abstract.pdf` (35 KB)
- Generated 2026-06-08 via `cairosvg` (`DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`)

## Anonymization Status

- JBF default workflow is **non-blinded** review for first submission. Author block in `main.tex` retained.
- If switching to double-blind for resubmission, strip author block + acknowledgements + self-citations.

## Data & Code Availability Statement

- `data_sources.md` lists all data sources (yfinance: SPY/QQQ/GLD/TLT/EEM/BTC-USD/IWM/SLV/^VIX; snapshot 2026-04-19)
- Local snapshot CSVs pinned in `data/`
- `reproduce.py` validates all numerical claims against `experiments/k*/results.json` (0 MISMATCH gate, last verified 2026-04-19 with 28 MATCH / 9 NOTE / 19 structural UNTRACEABLE)
- Replication entry: `uv run python paper/leverage-direction/reproduce.py`
- 7 figure regeneration scripts under `scripts/figures/`

## Conflict of Interest

- Single author, no funding from interested parties, no consulting relationships in scope.

## Known Open Items (R&R Round, Not Blocking First Submission)

- **C3 — Table 5 unified VaR (K899)**: Acknowledged in cover letter; current Table 5 internally consistent within each source experiment (K799 / K802 / K824v2)
- **C4 / C5 — Table 1 / Table 3 partial UNTRACEABLE rows**: 19 structural UNTRACEABLE entries in `reproduce_report.json` (data-limit, non-error)

## Pre-upload Checklist

- [x] Cover letter addressed to current Managing Editor (Bouwman, 2025–)
- [x] Cover letter includes C3 R&R acknowledgement
- [x] Cover letter compiles clean (xelatex, 2 pp)
- [x] Highlights 5 bullets ≤ 85 chars each
- [x] Graphical abstract PNG + PDF generated at portal-spec resolution
- [x] Manuscript ≤ 48 pp (per `Paper1_shorten_for_jbf` completion)
- [x] Reproduce gate 0 MISMATCH (last verified 2026-04-19)
- [x] Citation tier 0 MAJOR / 0 MEDIUM / 0 MINOR (per v10 review)
- [x] Data sources documented (`data_sources.md`)
- [x] Replication entry point exists (`reproduce.py`)

## Next Action

Bundle the seven portal files into a submission zip and upload to <https://www.editorialmanager.com/jbf/> at the corresponding author's convenience. No further code or paper edits required from the ops side.
