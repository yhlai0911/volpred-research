# Citation Verification Report — vt-insurance-cost (v2, first full formal round)

**Manuscript**: `paper/vt-insurance-cost/main.tex` (mtime 2026-07-01 18:37, unchanged since v1)
**Date**: 2026-07-06
**Reviewer source**: main thread (Claude opus), building on the byte-identical-file v1 web-verified diagnostic (2026-07-05)
**Total citation keys**: 17 (all bibitems cited; no orphan / no undefined)

> **Round provenance (honest disclosure)**: `main.tex` is **unchanged** (mtime 2026-07-01) since the v1 citation diagnostic did full web-based verification on 2026-07-05 (`review_history/v1/citation_check_report.md`). Re-running the identical web searches would produce identical results at token cost with no new information. This v2 report therefore **re-affirms and consolidates** the v1 web-verified findings into the formal round, without re-fabricating searches. When main.tex is next revised (v3), citation verification must be re-run against the new text. Any claim below that could not be independently confirmed is marked **UNVERIFIED**, not asserted.

---

## Summary

| Severity | Count | Meaning |
|---|---:|---|
| MAJOR | 1 | Citation used to justify a core assumption but does not directly support it |
| MEDIUM | 8 | DOI/APA gaps, year/source mismatch, over-extended claims |
| minor | 2 | source-code key hygiene / wording |
| **Total issues** | **11** | across 17 keys |

**Overall verdict**: ⚠️ **Requires correction before submission.** No undefined/orphan references (clean 17↔17 machine match), but the bibliography is not APA-7/DOI-complete, and several in-text claims over-attribute to their cited sources. Fix MAJOR + MEDIUM before the submission version.

---

## Undefined / Orphan check (machine)

| Check | Result |
|---|---|
| Cited in text but not in bibliography | none |
| In bibliography but never cited | none |

Cited keys = bibitem keys = {barroso2015, bekaert2014, bollerslev2009, bongaerts2020, booth1992, cboe2014, cederburg2020, fleming2001, harvey2016, harvey2018, hasbrouck2009, hocquard2013, huang2015, liu2019, moreira2017, perchet2016, todorov2010}.

---

## Issues (consolidated from v1 web-verified findings)

### C-01. `hasbrouck2009` — MAJOR (content support gap)
- **Location**: main.tex line 108
- **Claim**: 5 bps TX cost "exceeds SPY's typical bid-ask spread of 1–2 bps" cited to Hasbrouck (2009).
- **Problem**: Hasbrouck (2009) is a general methodology paper estimating effective costs from daily CRSP U.S.-equity data; it does **not** establish a current, precise 1–2 bps spread for SPY specifically. This citation supports the paper's **core transaction-cost assumption**, so the mismatch is material.
- **Fix**: Compute SPY quoted/effective spread directly from TAQ/NBBO for the sample and cite that, or cite a direct SPY/ETF liquidity source; rephrase to "a conservative assumption relative to SPY's observed liquidity."

### C-02. All DOI-bearing journal articles — MEDIUM (APA-7 / DOI completeness)
- **Affected**: barroso2015, bollerslev2009, bekaert2014, bongaerts2020, todorov2010, booth1992, cederburg2020, fleming2001, harvey2016, hasbrouck2009, harvey2018, hocquard2013, huang2015, liu2019, moreira2017, perchet2016
- **Problem**: Reference list is hand-written journal style; DOIs and most issue numbers are missing. Not a compile error but fails submission-grade citation formatting.
- **Fix (verified DOIs from v1)**:

| Key | DOI |
|---|---|
| barroso2015 | 10.1016/j.jfineco.2014.11.010 |
| bollerslev2009 | 10.1093/rfs/hhp008 |
| bekaert2014 | 10.1016/j.jeconom.2014.05.008 |
| bongaerts2020 | 10.1080/0015198X.2020.1790853 |
| todorov2010 | 10.1093/rfs/hhp035 |
| booth1992 | 10.2469/faj.v48.n3.26 |
| cederburg2020 | 10.1016/j.jfineco.2020.04.015 |
| fleming2001 | 10.1111/0022-1082.00327 |
| harvey2016 | 10.1093/rfs/hhv059 |
| hasbrouck2009 | 10.1111/j.1540-6261.2009.01469.x |
| harvey2018 | 10.3905/jpm.2018.45.1.014 |
| hocquard2013 | 10.3905/jpm.2013.39.2.028 |
| huang2015 | 10.1017/S0022109018001436 |
| liu2019 | 10.3905/jpm.2019.1.107 |
| moreira2017 | 10.1111/jofi.12513 |
| perchet2016 | 10.3905/jai.2016.18.3.021 |

### C-03. `perchet2016` — MEDIUM (12/VIX rule over-attribution)
- **Location**: main.tex line 70
- **Problem**: The exact `w_t = min(12/VIX_{t-1}, 1)` rule is the manuscript's implementation of a 12% target using VIX, not a named rule verifiably from Perchet et al.
- **Fix**: "Following the target-volatility convention studied by Perchet et al. (2016), we implement a 12% annual target using lagged VIX as the forecast: ..."

### C-04. `perchet2016` — MEDIUM (visible year 2015 vs 2016)
- **Location**: main.tex lines 274–275
- **Problem**: Bibitem label shows "Perchet et al.(2015)" / year 2015, but the official JAI issue is 18(3), Winter 2016, DOI 10.3905/jai.2016.18.3.021. Internal key already says `perchet2016`.
- **Fix**: Change visible label + year to 2016.

### C-05. `cboe2014` — MEDIUM (unverifiable bibliographic entry)
- **Location**: main.tex lines 93, 241–242
- **Problem**: No official 2014 CBOE white paper with the exact title "CBOE VVIX Index: Measuring the volatility of volatility" could be verified. CBOE's verifiable document is the 2012 "Double the Fun with CBOE's VVIX Index." The *content* claim (VVIX = volatility-of-volatility index) is correct; the reference metadata is unreliable/misdated.
- **Fix**: Replace with the CBOE 2012 white paper + current VVIX dashboard URL.

### C-06. `harvey2018` — MEDIUM (turnover-drag claim too strong)
- **Location**: main.tex line 56
- **Problem**: Manuscript says Harvey et al. "prominently report turnover metrics as a key performance drag." The verified abstract emphasizes tail-risk / Sharpe effects; turnover-as-key-drag is not a headline Harvey claim.
- **Fix**: Cite Harvey et al. (2018) for tail-risk reduction only; attribute turnover/implementation-cost drag to a source that directly studies it (or Cederburg et al. 2020 for poor OOS).

### C-07. `harvey2016` — MEDIUM (DM-threshold scope)
- **Location**: main.tex lines 195–196
- **Problem**: Harvey-Liu-Zhu (2016) propose a multiple-testing hurdle for *new factors*; the manuscript applies |t|>3.0 to pairwise strategy DM tests. Conservative, but not that paper's setting nor a standard DM critical value. (Cross-references latex-review M-05.)
- **Fix**: "As a conservative multiple-testing heuristic inspired by Harvey et al. (2016), we report whether |t|>3.0; formal inference is the DM/HAC statistic."

### C-08. `liu2019` — MEDIUM ("destroys value" overstated)
- **Location**: main.tex line 207
- **Problem**: "destroys value in smooth sailing environments" is stronger than the source supports; Liu-Tang-Zhou (2019) question whether vol-managed portfolios work and find benefits concentrated in high-vol states.
- **Fix**: "...consistent with Liu et al. (2019), who find volatility management does not consistently improve performance outside the states where volatility timing is most valuable."

### C-09. `fleming2001` — MEDIUM (left-tail over-attribution)
- **Location**: main.tex line 54
- **Problem**: Fleming et al. (2001) is correctly the "economic value of volatility timing" paper, but is over-attributed here for left-tail compression (which Hocquard/Harvey support directly).
- **Fix**: "Fleming et al. (2001) establish the economic value of volatility timing, while Harvey et al. (2018) and Hocquard et al. (2013) document thinner tails."

### C-10. `moreira2017` — minor (priority wording)
- **Location**: main.tex line 54
- **Problem**: "formalized by Moreira and Muir" reads as a priority claim; volatility timing predates them (e.g., Fleming 2001).
- **Fix**: "in the influential formulation of Moreira and Muir (2017)".

### C-11. `huang2015` — minor (key hygiene)
- **Location**: main.tex lines 265–266
- **Problem**: Visible citation is correctly Huang et al. (2019), but the internal key is `huang2015`. No compile impact; source-code misleading.
- **Fix**: Rename key to `huang2019` in both `\cite` and `\bibitem`.

---

## Web-search verified key claims (carried from v1; source unchanged)

| Claim / reference | Result |
|---|---|
| Moreira & Muir (2017): scale exposure inversely to recent vol | Supported (soften "formalized") |
| Harvey et al. (2018): VT reduces tail/extreme returns | Supported |
| Harvey et al. (2018): turnover a key drag | **Not sufficiently supported** (C-06) |
| Cederburg et al. (2020): poor OOS across 103 strategies | Supported |
| Bongaerts et al. (2020): conditional VT on vol states | Supported |
| Perchet et al. (2016): exact 12/VIX rule | Partially supported; rephrase (C-03) |
| CBOE VVIX citation | Content supported; bibliographic entry to replace (C-05) |
| Hasbrouck (2009): SPY 1–2 bps spread | **Not sufficiently supported** (C-01) |
| Booth & Fama (1992): diversification/rebalancing return | Supported |
| Harvey et al. (2016): t>3.0 hurdle | Supported as factor-discovery heuristic, not DM critical value (C-07) |
| Liu et al. (2019): VT destroys value in calm | Overstated; soften (C-08) |
| Huang (2019), Bollerslev (2009), Todorov (2010), Bekaert-Hoerova (2014): VoV/VRP literature | Supported |

---

## Correction priority

1. C-01 (MAJOR): fix Hasbrouck SPY-spread support or compute spread directly.
2. C-02: add DOI + issue numbers to all references.
3. C-05: replace cboe2014 with verifiable CBOE 2012 / dashboard metadata.
4. C-04, C-03: perchet year → 2016; soften 12/VIX attribution.
5. C-06/C-07/C-08/C-09: revise over-strong cited claims.
6. C-10/C-11: minor wording + key hygiene.
