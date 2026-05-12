# Paper 8 (volatility-absorption) — Errata Pending

**Status**: R1 review (5 SEVERE, major revision pending)
**Date identified**: 2026-04-19
**Scope**: K903/K904 snapshot divergences — some with Harvey-threshold crossings

---

## Severity classification

### CRITICAL — Harvey-threshold crossing (paper claim may not hold under current snapshot)

| Paper claim | Paper value | Snapshot rerun (K903 2026-04-19) | Issue |
|---|---|---|---|
| controlled $t = -3.14$ | -3.14 (Harvey pass) | **-1.17 (Harvey fail)** | Paper's "Harvey-significant controlled effect" claim does not replicate under current yfinance snapshot. The sign is preserved but magnitude weakens by 63%, crossing the Harvey threshold boundary. |

### HIGH — Sign flip (paper claim inverts)

| Paper claim | Paper value | Snapshot rerun | Issue |
|---|---|---|---|
| T10 2020-2026 $\beta$ | -0.00035 | **+0.000139** | Sign flips — paper's "absorption all periods" claim breaks for the 2020-2026 COVID/inflation era. The magnitude also collapses from -0.00035 to +0.000139. |

### MEDIUM — Magnitude drift (direction intact)

| Paper claim | Paper value | Snapshot rerun | Relative drift |
|---|---|---|---|
| T10 2006-2012 $\beta$ | -0.00035 | -0.000392 | +12% |
| T10 2013-2019 $\beta$ | -0.00018 | -0.000255 | +42% |
| T9 $\tau=1.0$ $\beta$ | -0.00015 | +9.8e-05 | sign flip (magnitude similar) |
| T9 $\tau=1.5$ $\beta$ | -0.00022 | -0.00014 | -36% |
| T9 $\tau=2.0$ $\beta$ | -0.00028 | -0.00026 | -7% |
| T9 $\tau=2.5$ $\beta$ | -0.00033 | -0.000266 | -19% |
| T9 $\tau=3.0$ $\beta$ | -0.00041 | -0.000307 | -25% |
| $\beta_{RV}$ (alt norm) | -0.0031 | -0.01234 | +298% (same sign, much stronger) |
| $t$ RV norm | -2.76 | -8.19 | +197% (same sign, much stronger) |
| $\beta$ controlled | -0.00025 | -0.000198 | -21% |

## Root cause

Same as P9: yfinance retroactive adjustments. K903/K904 snapshot rerun (Codex `task_4e75` 2026-04-19) with `auto_adjust=False` and pinned CSVs yields divergent results because:
1. **Paper values** frozen at K903/K904 drafting-time pulls (pre-2026-04-19)
2. **Current yfinance data** reflects retroactive dividend + corporate-action backfills
3. Regression $\beta$/$t$ sensitive to sample tail adjustments

## Action required

### **CRITICAL: T10 2020-2026 sign flip + controlled t Harvey boundary**
- Cannot defer to post-review. **Paper body must be revised before submission to next journal** (paper is in R1 state, not yet published).
- Two paths:
  - **(a) Re-run K903 with paper drafting-time snapshot if recoverable** (yfinance archive may not permit time-travel; check if K903 stored raw snapshot CSV or only computed results)
  - **(b) Update paper T10 2020-2026 row to reflect current snapshot sign** (+0.000139 instead of -0.00035), revise "absorption all periods" claim to "absorption in non-crisis periods, inverts 2020-2026 under current yfinance snapshot"
  - **(c) Add prominent errata section documenting the drift and acknowledging claim limitation**

### MEDIUM: Other T9/T10 drifts (magnitude only)
- Within expected yfinance drift range. Table footnote disclosing snapshot date is sufficient.

### Unlinked prior work (Text section 4 entries)
- "VT overlay Sharpe 0.53 vs 0.68", "DM t=-2.81", "Daily rebal Sharpe 1.42", "Monthly rebal Sharpe 0.82" — these have `source=null` (no experiment JSON). Already UNTRACEABLE not MISMATCH (reproduce.py classifies correctly).
- Recommendation: explicitly cite the K-experiment or prior work producing these numbers, or remove from paper body if not reproducible.

## Mitigation applied (this revision cycle)

1. Codex `task_4e75` snapshot pinning bundled in `paper/volatility-absorption/data/` for future reruns.
2. reproduce.py snapshot-first path integrated.
3. Sub6 Table 6 NFP section fixed with (a) 修論文 approach (p=0.037 → 0.061, etc.).

## Path B Implemented (2026-05-13)

**main_v3.tex created** with Path B changes:
- Line 67 (intro): Added footnote disclosing snapshot sensitivity of baseline t-stat (-3.42 → -1.77)
- Lines 538-563 (threshold table): Updated all τ rows to K903 snapshot values; τ=1.0 sign flip disclosed; text softened from "significant for all thresholds" to "directionally negative for τ≥1.5"
- Lines 567-588 (sub-period text + table): Complete rewrite disclosing 2020-2026 sign reversal and insignificance of 2013-2019; table updated to K903 values (316/182/270 N, new β/t)
- Line 597 (RV normalization): Updated to K903 values (β=-0.01249, t=-8.2) — stronger result
- Line 606 (controlled regression): Updated to K903 values (β=-0.000216, t=-1.26) with Harvey-boundary footnote
- Lines 618, 633 (conclusion/limitations): Softened sub-period stability claim; added snapshot caveat

**Outstanding (next session)**:
- Cross-asset table (lines 801-804): GLD/TLT/0050.TW snapshot rerun needed (K903 only covers SPY)
- paper-update sync: `uv run volpred ops paper-update --paper-id volatility-absorption`

## Cross-reference

- `paper/volatility-absorption/reproduce_report.json` — current snapshot_mode match_rate 61.3%
- `paper/volatility-absorption/review_history/gate_fix_v1/proposal.md` — earlier P8 diagnostic
- `.claude/rules/paper-workflow.md` — snapshot pinning rule
- `docs/error_log.md` — session-level drift context
