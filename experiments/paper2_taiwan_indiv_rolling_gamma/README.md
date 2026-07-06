# paper2_taiwan_indiv_rolling_gamma

**Provenance re-estimation for Taiwan-VT Paper 2, Table `tab:gamma` rolling-window rows.**

## Motivation
`paper/taiwan-vt/reviews/audit_step1_2.md` flagged the individual-stock
rolling-window (w=2000) GJR-GARCH gamma rows in `body_v3.tex` (L152-154) and the
9-stock rolling average as **untraceable**: they trace only to knowledge entry
N121 (derived from a since-deleted K530 run), with no surviving source JSON.
The research-honesty rule (Table row → JSON source must be traceable) requires a
reproducible binding, or — if the legacy values cannot be reproduced — a
re-estimate under a documented spec (never fabricate a method to hit the legacy
number).

## Method (identical to K892) + calendar alignment
GJR-GARCH(1,1), Constant mean, Normal innovations, `arch`-package MLE on
returns×100; rolling window w=2000, reporting the **last (most recent)**
2000-obs window (matching K892's `rolling_w2000.last_window` convention);
robust t-values; persistence = α + 0.5·γ + β. Deterministic MLE (no seed).
No lookahead (in-sample descriptive γ, not a forecast/signal).

**Calendar alignment (2026-07-07, resolves Codex CONDITIONAL_PASS caveat):**
the first-pass recompute took each snapshot's *own* last-2000-obs window, so
window ends differed by security (2317/2454 → 2026-04-17, k1302 2383/2886 →
2025-01-22, k1302b five stocks → 2026-05-15). Codex required a common end date
before the numbers become canonical. Fix: pre-load all 10 series, set
`common_end = min(last-obs date across all 10)` = **2025-01-22**, truncate every
series to `≤ common_end`, then take the last 2000 obs. 2025-01-22 is the *latest*
common end achievable from the offline snapshots with **no network re-fetch** (it
is bound by the k1302 2383/2886 snapshots), so the "fully reproducible, no
network" guarantee is preserved. All 10 windows now share start 2016-11-04 /
end 2025-01-22 (same TWSE trading calendar).

## Data (all offline snapshots — fully reproducible, no network)
- 2317 / 2454 / 0056: `paper/taiwan-vt/data/..._2008-2026.csv` (adj_close)
- 2383 / 2886: `experiments/k1302/data/*.csv` (yfinance adj_close snapshots)
- 2412 / 2881 / 2882 / 2885 / 2891: `experiments/k1302b/data/*.csv` (Close)

Mixed adj/close is inherited from the canonical K1302/K1302b data package;
documented in the results JSON `data_source_note`.

## Result — legacy rolling values are NOT reproducible
Canonical column = **calendar-aligned** (all windows end 2025-01-22). The
first-pass non-aligned column is shown for transparency (superseded).

| Ticker | Name | Legacy (N121) γ/t | Non-aligned γ (superseded) | **Calendar-aligned γ/t (canonical)** | verdict |
|---|---|---|---|---|---|
| 2317 | Hon Hai | 0.052 / 1.14 | 0.032 | **0.015 / 0.45** | ✗ mismatch |
| 2454 | MediaTek | 0.044 / 0.96 | 0.045 | **0.027 / 1.22** | ✗ mismatch |
| 2886 | Mega Financial | 0.179 / 2.42 | 0.054 | **0.054 / 1.41** | ✗ 3× off |
| 0056 | Yuanta High-Div ETF | 0.112 / 1.87 | 0.310 | **0.202 / 2.89** | ✗ flips narrative |

Aggregates (rolling w=2000, calendar-aligned):
- **9-stock avg γ**: legacy 0.054 → **0.024** (non-aligned 0.037)
- **10-security avg γ** (incl 0056): legacy 0.060 → **0.042** (non-aligned 0.064)
- **9-stock amplification ratio** (TWII 0.272 / avg): legacy 5.0× → **11.3×**
- **10-security ratio**: legacy 4.5× → **6.5×**

Notes:
- The legacy N121 rolling numbers are non-reproducible under the documented
  arch-MLE rolling spec — robust across both non-aligned and calendar-aligned
  recomputes (the "not reproducible" conclusion does not depend on the window
  end date).
- **0056 calendar-aligned γ=0.202 (t=2.89) is the HIGHEST of the 10 individual
  securities** (9-stock avg 0.024, next-highest single stock 2885 = 0.063) **but
  is BELOW the TWII index rolling γ=0.272**. This is the key correction vs the
  non-aligned pass (which put 0056 at 0.310, *above* the index): under the
  correct calendar-aligned spec, the ordering is **index (0.272) > 0056 ETF
  (0.202) ≫ individual-stock average (0.024)**. Both the paper's OLD prose
  ("0056 second-highest γ=0.112") AND the non-aligned interim narrative ("0056
  highest, above the index") are wrong; the canonical statement is that a
  diversified ETF sits between the index and single stocks — consistent with,
  and *strengthening*, the diversification-amplification thesis (more
  aggregation → more leverage asymmetry), while the amplification ratio rises
  (5.0× → 11.3× for the 9-stock average).
- ⚠️ The TWII index rolling γ=0.272 used in the ratio is itself the untraceable
  N120 table value (provenance tracked separately, task step 4). The *direction*
  of amplification is robust; the exact ratio inherits N120's provenance risk.

## Scope decision (research-honesty × narrative state machine)
Because the reproducible values materially change narrative-adjacent claims
(0056 "second-highest" → highest individual but below index, rolling
amplification 5.0×→11.3×, Mega 0.179→0.054), the rendered `body_v3.tex`
table/prose is **NOT** rewritten in this run. Per CLAUDE.md paper narrative state
machine, such a rewrite goes through the main-thread paper revision flow. This
run delivers **step 1 (calendar-aligned recompute)** of the parent task:
1. the **traceable, calendar-aligned source JSON** (all 10 securities) — the
   canonical binding target, resolving the Codex CONDITIONAL_PASS caveat;
2. this README documenting the aligned numbers + the corrected 0056 ordering
   (index > ETF > single stocks).

Remaining steps 2–5 (integrate rows + footnote into `body_v3.tex`, rewrite the
0056-inclusion sensitivity paragraph around the **corrected** ordering, resolve
TWII/0050 provenance, recompile + reproduce.py rebind + paper-update + online
verify) are a coupled but distinct paper-body edit filed as a follow-up. The
taiwan-vt paper stays gated (do-not-advance) until that integration lands.

The paper's **primary** amplification claim (4.3×, canonical full-sample
BW-robust γ̄=0.027, sourced to K1302+K1302b, VERIFIED) is **unaffected** — the
rolling block is explicitly a secondary sensitivity display.

## Files
- `paper2_taiwan_indiv_rolling_gamma.py` — re-estimation script
- `paper2_taiwan_indiv_rolling_gamma_results.json` — per-security + aggregates
