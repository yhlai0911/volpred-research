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

## Method (identical to K892)
GJR-GARCH(1,1), Constant mean, Normal innovations, `arch`-package MLE on
returns×100; rolling window w=2000, reporting the **last (most recent)**
2000-obs window (matching K892's `rolling_w2000.last_window` convention);
robust t-values; persistence = α + 0.5·γ + β. Deterministic MLE (no seed).
No lookahead (in-sample descriptive γ, not a forecast/signal).

## Data (all offline snapshots — fully reproducible, no network)
- 2317 / 2454 / 0056: `paper/taiwan-vt/data/..._2008-2026.csv` (adj_close)
- 2383 / 2886: `experiments/k1302/data/*.csv` (yfinance adj_close snapshots)
- 2412 / 2881 / 2882 / 2885 / 2891: `experiments/k1302b/data/*.csv` (Close)

Mixed adj/close is inherited from the canonical K1302/K1302b data package;
documented in the results JSON `data_source_note`.

## Result — legacy rolling values are NOT reproducible
| Ticker | Name | Legacy (N121) γ/t | Reproducible γ/t | verdict |
|---|---|---|---|---|
| 2317 | Hon Hai | 0.052 / 1.14 | **0.032 / 0.92** | ✗ mismatch |
| 2454 | MediaTek | 0.044 / 0.96 | **0.045 / 1.54** | ~ γ close, t off |
| 2886 | Mega Financial | 0.179 / 2.42 | **0.054 / 1.41** | ✗ 3× off |
| 0056 | Yuanta High-Div ETF | 0.112 / 1.87 | **0.310 / 3.92** | ✗ flips narrative |

Aggregates (rolling w=2000):
- **9-stock avg γ**: legacy 0.054 → reproducible **0.037**
- **10-security avg γ** (incl 0056): legacy 0.060 → reproducible **0.064**
- **9-stock amplification ratio** (TWII 0.272 / avg): legacy 5.0× → **7.4×**
- **10-security ratio**: legacy 4.5× → **4.3×**

Notes:
- Hon Hai reproducible γ=0.032 exactly equals the K1302 full-sample value —
  strong evidence the legacy N121 rolling numbers used a different (lost)
  method/window, not the documented arch-MLE rolling spec.
- **0056 reproducible γ=0.310 is the HIGHEST of all securities (above the index
  0.272)** — this CONTRADICTS the paper's prose claim that 0056 is
  "second-highest ... γ=0.112". Correcting this row therefore entangles a
  narrative rewrite (the 0056-inclusion sensitivity paragraph reasons about
  0.112 explicitly), not just a number swap.

## Scope decision (research-honesty × narrative state machine)
Because the reproducible values materially change narrative-adjacent claims
(0056 "second-highest", rolling amplification 5.0×→7.4×, Mega 0.179→0.054), the
rendered table/prose is **NOT** rewritten in this run. Per CLAUDE.md paper
narrative state machine, such a rewrite must go through the main-thread paper
revision flow with author sign-off. This run delivers:
1. the **traceable source JSON** (all 10 securities) — the binding target;
2. `% source:` + `% PROVENANCE` inline comments in `body_v3.tex` binding the
   rows and flagging the legacy values as non-reproducible;
3. a `paper_body` follow-up task with the reproducible values for holistic
   correction; the taiwan-vt paper is gated (do-not-advance) until integrated.

The paper's **primary** amplification claim (4.3×, canonical full-sample
BW-robust γ̄=0.027, sourced to K1302+K1302b, VERIFIED) is **unaffected** — the
rolling block is explicitly a secondary sensitivity display.

## Files
- `paper2_taiwan_indiv_rolling_gamma.py` — re-estimation script
- `paper2_taiwan_indiv_rolling_gamma_results.json` — per-security + aggregates
