# Citation Check Report — leverage-direction v10

**Date**: 2026-06-05
**Reviewer**: codex-cli
**Files reviewed**: `main.tex`
**Scope**: Resolve the four deferred citation items carried into `decision_2026_06_05.md`

---

## Executive Summary

| Severity | Count | Description |
|----------|-------|-------------|
| MAJOR | 0 | None found |
| MEDIUM | 0 | `engle1982` normalized to stable JSTOR URL |
| MINOR | 0 | `moreira2017`, `cederburg2020`, `bayerdimitriadis2022` verified as already correct |

**Overall verdict**: PASS — the deferred v9 citation queue is fully closed.

---

## Item-by-item Resolution

### 1. `engle1982` — RESOLVED

**v9 issue**: `10.2307/1912773` was flagged as an unverified DOI.

**v10 action**: Replaced the resolver-style DOI string with the explicit JSTOR stable URL:

```text
https://www.jstor.org/stable/1912773
```

**Assessment**: This removes ambiguity over whether a Crossref DOI exists while preserving a stable, canonical identifier for this pre-digital `Econometrica` paper.

### 2. `moreira2017` — RESOLVED

**v9 carry-over label**: journal abbreviation consistency.

**v10 verification**: The bibliography already uses the full journal title:

```text
\textit{Journal of Finance}, 72(4), 1611--1644.
```

This matches the surrounding style in `main.tex`, which uses full journal titles rather than mixed abbreviations. No edit required.

### 3. `cederburg2020` — RESOLVED

**v9 carry-over label**: page range missing.

**v10 verification**: The entry already contains the published page range:

```text
\textit{Journal of Financial Economics}, 138(1), 95--117.
```

No edit required.

### 4. `bayerdimitriadis2022` — RESOLVED

**v9 carry-over label**: preprint vs published ambiguity.

**v10 verification**: The bibliography already cites the published journal version:

```text
\textit{Journal of Financial Econometrics}, 20(3), 437--471.
https://doi.org/10.1093/jjfinec/nbaa013
```

No preprint-only wording remains. No edit required.

---

## Final Verdict

The deferred citation backlog from v9 is now closed. `main.tex` is citation-clean for the current submission round.
