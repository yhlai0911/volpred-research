# Paper 9 (garch-x-vix) — Review History v6

**Date**: 2026-05-23
**Round**: v6 — Low-priority issue batch (C6/C8/C10/C12 + missing citations)

---

## What Was Fixed

### C12 — GLD DM t Inconsistency (RESOLVED)

**Status**: ✅ RESOLVED

**Problem**: Introduction (line 84) stated "GLD with GVZ: DM $t = 3.39$" but the correct value is $t = 3.17$ (consistent with abstract, Table 4, and Section 5.2 narrative). The value 3.39 belongs to the "VIX + GVZ (dual)" model.

**Fix**: Changed intro line 84 from "DM $t = 3.39$" → "DM $t = 3.17$" for GLD with GVZ.

---

### C6 — Harvey (2016) Citation Context (RESOLVED)

**Status**: ✅ RESOLVED

**Problem**: Line 298 cited only `harvey2016` for multiple-testing concerns, missing the cross-sectional vs. time-series context distinction. White (2000) provides the foundational data-snooping framework in a time-series setting.

**Fix**:
- Added `\citet{white2000}` alongside `\citet{harvey2016}` at line 298: "consistent with the multiple-testing concerns raised by \citet{white2000} and \citet{harvey2016}."
- Added White (2000) bibliography entry: "A reality check for data snooping." *Econometrica*, 68(5):1097–1126.

---

### C8 — Cross-asset Multiple Testing (RESOLVED)

**Status**: ✅ RESOLVED

**Problem**: Table 4 (cross-asset validation) reported "Harvey sig." without acknowledging that testing 6 additional assets beyond SPY requires further multiple-testing adjustment.

**Fix**: Added Bonferroni footnote to Table 4 `\tablenotes`:
> "With 6 cross-validation assets beyond the primary SPY result, a conservative Bonferroni-adjusted threshold of $|t| > 3.22$ leaves SPY ($t=4.03$), QQQ ($t=3.71$), STOXX50E ($t=3.64$), and FEZ ($t=3.45$) Harvey-significant; GLD with GVZ ($t=3.17$) falls marginally below this stricter criterion and should be interpreted with caution."

---

### C10 — Contemporaneous Terminology / Simultaneity (RESOLVED)

**Status**: ✅ RESOLVED

**Problem**: The term "contemporaneous normalization" ($u_{t-1} = r_{t-1}/\sqrt{\tau_t}$) could imply a simultaneity problem since $\tau_t$ and $r_t$ share the same time subscript.

**Fix**: Added clarifying sentence to line 184: "Despite the shared time subscript, there is no simultaneity: $\tau_t$ is a deterministic function of $\mathrm{VIX}_{t-1}$, which is observed before $r_t$."

---

### Missing Citation: corsi2009 (RESOLVED)

**Status**: ✅ RESOLVED

**Problem**: The HAR-RV section (line 797) cited `\citep{corsi2009}` but no corresponding `\bibitem{corsi2009}` existed in the bibliography, causing an undefined citation warning.

**Fix**: Added Corsi (2009) bibliography entry: "A simple approximate long-memory model of realized volatility." *Journal of Financial Econometrics*, 7(2):174–196.

---

## Pre-existing Issues Already Resolved (not in v5 tracking table)

| Issue | Status |
|-------|--------|
| C15: xeCJK/PingFang TC | ✅ Already commented out in main.tex (lines 13–15) |
| C16: Acerbi (2014) Risk → (2019) MS | ✅ Already Management Science (2019) at bibitem line 974 |
| C13: Proposition 3 formal status | ✅ Already converted to `\begin{remark}` with explicit "empirical rather than derived analytically" |

---

## Compilation Status

- XeLaTeX 3 passes: **CLEAN** (43 pages, zero fatal errors)
- Resolved warnings: `white2000` and `corsi2009` undefined citations (now resolved)
- Remaining pre-existing warnings: `hyperref` Unicode token warnings in URL strings (cosmetic only)

---

## Remaining Open Issues from v5 (not addressed in v6)

| Issue | Status |
|-------|--------|
| C7: VRP tautology quantification | OPEN — requires new computation K_NEW_E |
| C9: Refit sensitivity COVID interaction | OPEN — requires new computation |
| C11: A4f vs A4 fragility (block bootstrap) | OPEN — requires new computation |
| C17: Proposition 1 algebraic identity label | OPEN — has mitigating note; could rename to "Observation" |

---

## Stage Assessment

**Current stage**: `revision_required` (improved — low-priority batch resolved)
**Next priority**: C7 (VRP tautology quantification) or C11 (block bootstrap CI for A4f vs A4)
