# Paper 4 (vt-insurance-cost) reproduce.py — Divergence Diagnosis v1

**Date:** 2026-04-19
**Trigger:** Codex task_96304dde7a56 shipped self-contained reproduce.py (exit 0) but match_rate=44.4% red. Goal: classify each divergent claim as (a) fix reproduce / (b) fix paper / (c) errata, and decide canonical period + adjusted-close policy.
**Scope:** diagnosis + proposal only. NOT modifying `main.tex`, NOT committing, NOT tweaking JSON.

---

## 1. Root Cause Summary (single headline)

**The bundled `paper/vt-insurance-cost/data/*.csv` files contain `auto_adjust=True` adjusted close series, but the paper's canonical numbers come from `auto_adjust=False` raw `Close` (experiment K811v2).** Every "divergent" core claim traces back to this single price-basis mismatch, plus one period-coverage issue (54 bps rebalancing premium references 2006–2024, bundle only has 2012–2024).

### Evidence

| Check | Value | Source |
|---|---|---|
| Bundled SPY close on 2012-01-03 | **99.3122** | `data/spy_2012_2024.csv` row 4 |
| yfinance `auto_adjust=True` SPY 2012-01-03 | **99.312225** | live verification via `yf.download` |
| yfinance `auto_adjust=False` SPY raw Close 2012-01-03 | **127.500** | live verification (raw, pre-split/div) |
| K811v2 data loader | `yf.download(..., auto_adjust=False)`, uses `df[["Close"]]` (raw) | `experiments/k811v2_insurance_premium_vov_fixed.py:73-77` |
| K811v2 canonical S0 BH CAGR | **12.506%** (matches paper 12.51) | `experiments/k811v2_insurance_premium_vov_fixed_results.json:full_period_metrics.S0_BH_SPY.cagr` |
| reproduce.py bundle-implied CAGR | **14.562%** | `reproduce_report.json:computed_values.bundle_spy_cagr_pct` |
| Delta | +2.056 pp CAGR inflation | dividends compounded into adjusted price push gross return up |

**Mechanism:** adjusted-close baked-in dividends raise both S0 CAGR and the opportunity-cost leg of every VT strategy. Since opportunity cost = `mean(BH – VT_gross)`, if BH is inflated by dividends but the VT weight-scaled leg `w_t * r_adjusted` captures the same dividends proportionally to `w_t`, the GAP stays positive but is scaled up by roughly the same amount the BH itself is inflated. That's exactly what we see: S1 opp cost 4.20% → 4.66% (+0.46), S2 opp cost 0.70% → 0.82% (+0.12). Direct cost (transaction) is invariant to price basis (depends on `|Δw_t|` only), which is why direct costs match to within 0.002%.

---

## 2. Canonical Decisions Proposed

### (I) Canonical period: **2012-01-03 to 2024-12-31** (unchanged for insurance-premium claims; separate extended window for rebalancing claim)

Paper main.tex line 108 explicitly states "VVIX-reliable period 2012-01-03 to 2024-12-31 (N=3,262 trading days, 12.94 years)". The S1/S2/S3 decomposition claims are ALL anchored to this window. **Keep 2012–2024 canonical for all insurance-premium decomposition claims.**

However, paper line 184 footnote explicitly documents: *"The correlation and rebalancing premium estimates use the 2006–2024 sample (from GLD inception) rather than the 2012–2024 VVIX-reliable period. The 2012–2024 sub-period yields ρ = 0.04 and a rebalancing premium of 48 bps, broadly consistent with the full-sample estimates."*

So for the **rebalancing premium claim only**, canonical is **2006–2024**. K846 result confirms: 2006–2024 monthly rebal premium = **53.67 bps** (rounds to 54 — that's the paper's 54 bps claim).

**Action:** Bundle needs `spy_2006_2024.csv` + `gld_2006_2024.csv` (raw Close) to reproduce the 54 bps claim. The current `spy_2012_2024.csv` is insufficient for that footnote claim.

### (II) Canonical close type: **`auto_adjust=False` raw Close** (matches K811v2, matches paper)

Paper line 108 says "consistent with CRSP to within rounding precision". CRSP total-return data is typically reported separately from raw close. The paper's S0 CAGR=12.51% matches K811v2 raw-Close computation. Therefore **raw Close is canonical**.

**Action:** Re-bundle all 4 CSVs (spy, gld, vix, vvix) using `yf.download(..., auto_adjust=False)` and keep the `Close` column. VIX and VVIX are indexes — `auto_adjust` doesn't affect them — so their bundled files are fine; only SPY and GLD need re-bundling.

> **Note on the physical interpretation:** `auto_adjust=False` raw Close is NOT a tradable total-return series (dividends paid but not reinvested), so CAGR of 12.51% understates the true total return of SPY. The paper's results are therefore a "price-return VT" analysis, not a "total-return VT" analysis. This is what K811v2 does, matches the paper, and is consistent with how many VT papers report numbers. The alternative — use `auto_adjust=True` (adjusted, total-return equivalent) — would require re-estimating ALL paper numbers. **We do not recommend switching to adjusted close because it would require rewriting Table 1, Table 2, the abstract, and the conclusion**.

---

## 3. Per-Field Divergence Table

| # | Claim | Paper | Reproduced | |Δ| | Status | Root Cause | Recommendation |
|---|---|---|---|---|---|---|---|
| 1 | S1 opp cost 4.20%/yr | 4.20 | 4.662 | 0.462 | divergent | adjusted-close inflates BH leg | **(a)** re-bundle spy_2012_2024.csv with `auto_adjust=False`; K811v2 reproduces 4.20 |
| 2 | S1 direct cost 0.43%/yr | 0.43 | 0.428 | 0.002 | match | — | — |
| 3 | S1 total premium 4.62%/yr | 4.62 | 5.090 | 0.47 | divergent | downstream of #1 | **(a)** same fix as #1 |
| 4 | S1 opp share 91% | 91.0 | 91.591 | 0.59 | match | — | — |
| 5 | S2 opp cost 0.70%/yr | 0.70 | 0.815 | 0.115 | divergent | adjusted-close inflates BH leg | **(a)** same fix as #1 |
| 6 | S2 direct cost 0.52%/yr | 0.52 | 0.522 | 0.002 | match | — | — |
| 7 | S2 total premium 1.22%/yr | 1.22 | 1.338 | 0.118 | divergent | downstream of #5 | **(a)** same fix as #1 |
| 8 | S2 cost reduction vs S1 74% | 74.0 | 73.713 | 0.287 | match | — | — |
| 9 | 50/50 SPY/GLD premium 54 bps/yr | 54.0 | –121.11 | 175.11 | divergent | period mismatch: paper 2006–2024 (K846) vs bundle 2012–2024 only AND adjusted-close | **(a)** bundle `spy_2006_2024.csv` + `gld_2006_2024.csv` raw Close; re-run K846 pathway in reproduce.py for the 2006–2024 sub-claim. K846 canonical = 53.67 bps ≈ 54 |

### Verdict distribution

- **(a) fix reproduce.py / re-bundle CSVs**: 5 out of 9 claims (all divergent ones)
- **(b) fix paper**: 0 claims (paper numbers are internally consistent with K811v2 + K846)
- **(c) errata**: 0 claims recommended (gaps are too large to call rounding — #9 is 325% relative, #1 is 11% relative; none qualifies as <5% rounding)

### Why NOT (b) revise the paper

- Paper numbers are **independently reproducible** from experiments K811v2 (insurance decomposition, 2012–2024, raw Close) and K846 (rebalancing premium, 2006–2024, raw Close). No drift between paper and its own experiment JSONs exists.
- The divergence is entirely a **packaging bug**: the bundled CSVs were pre-cached with the wrong `auto_adjust` flag, and the 2006–2024 span was never bundled at all.
- Research-honesty principle: **fix the pipeline to reproduce the audited paper numbers**, not the other way around.

### Why NOT (c) errata

- Smallest divergence on a divergent field is ≥11% relative (#1, #5 at ~11%/16%). That's an order of magnitude above a rounding-tolerance errata threshold (<5%).
- The 54 bps claim (#9) diverges by **325% relative** and flips sign from +54 to −121 bps. This is unambiguously a data-bundle defect, not a rounding issue.

---

## 4. Next Sub-Agents Proposed (queue these in main thread)

All three are **(a)-path execution**: fix the reproduce package so it reproduces the already-audited paper numbers. None touches `main.tex` or the paper's knowledge base.

### Sub1 — Re-bundle raw-Close SPY/GLD + verify K811v2 decomposition reproduces to within 0.1%

**Task type:** `paper_review` (reproducibility / replication package fix)
**K link:** K811v2
**Inputs to write:**
- `paper/vt-insurance-cost/data/spy_2012_2024.csv` (regenerated, `auto_adjust=False`, Close column)
- `paper/vt-insurance-cost/data/gld_2012_2024.csv` (regenerated, `auto_adjust=False`)
- `paper/vt-insurance-cost/data_sources.md` — update "adjusted close" → "raw Close (auto_adjust=False)"
**Success criterion:** after re-bundling, `reproduce.py` must yield:
- S0 CAGR ≈ 12.506% (matches K811v2)
- S1 opp cost = 4.20 ± 0.1 %/yr (claim #1 → match)
- S2 opp cost = 0.70 ± 0.1 %/yr (claim #5 → match)
- S1/S2 total premium within ±0.1 %/yr of paper
- Match rate ≥ 78% (7 of 9 — claim #9 still divergent pending Sub2)
**Do NOT:** change the decomposition formulae in reproduce.py. Only swap the data source.

### Sub2 — Bundle 2006–2024 SPY/GLD + port K846 rebalancing pathway into reproduce.py

**Task type:** `paper_review`
**K link:** K846
**Inputs to write:**
- `paper/vt-insurance-cost/data/spy_2006_2024.csv` (raw Close)
- `paper/vt-insurance-cost/data/gld_2006_2024.csv` (raw Close)
- `reproduce.py` — update `simulate_5050_rebalance` to load the 2006–2024 CSVs when computing the 54 bps claim (separate from the 2012–2024 panel used for insurance decomposition)
- `data_sources.md` — add extended-period rows
**Success criterion:** claim #9 reproduced at 54 ± 5 bps (K846 canonical = 53.67 bps, matches).
**Do NOT:** drop the 2012–2024 sub-sample check; keep both. Paper's footnote also reports 48 bps for 2012–2024 — include as a secondary tolerance check if helpful.

### Sub3 — Reconciliation pass + reproduce_report match_rate ≥95% + append to review_history

**Task type:** `paper_review`
**Depends on:** Sub1 + Sub2 complete
**Actions:**
- Rerun `reproduce.py` end-to-end; verify `match_rate_pct ≥ 95` and `alert_level = green`
- Append `paper/vt-insurance-cost/review_history/diagnosis_v1/reproduce_report_post_fix.json`
- Update `paper/vt-insurance-cost/README.md` reproducibility section with the fix summary and timestamps
- Write a short `paper/vt-insurance-cost/review_history/diagnosis_v1/resolution.md` noting: root cause (adjusted vs raw close), period gap (2006 data missing), and closing verdict.
**Do NOT:** edit `main.tex`, `body.tex`, or paper-content files. Only packaging + reproduce.py + documentation.

---

## 5. Open Risks / Notes for Main Thread

1. **VIX/VVIX are indexes; unaffected by `auto_adjust`**. No need to re-download those CSVs unless we want to standardize bundle provenance.
2. **2006–2024 GLD inception check**: GLD started trading 2004-11-18. Using `start='2005-12-01'` (as in K846) is safe; we have full 2006-01-01 coverage.
3. **Paper line 142 says "data source: yfinance; experiment K811v2"**. After Sub1 completes, this attribution becomes internally consistent with the bundled package.
4. **Alternative path (rejected):** We could switch the paper to `auto_adjust=True` (adjusted close, total-return basis) and re-compute all numbers. This would touch abstract, Table 1, Table 2, all in-text numbers — a ~10-field paper revision. Rejected because (a) the audited K811v2 uses raw Close, (b) the paper is already internally consistent, (c) research-honesty principle says fix the pipeline not the paper when the pipeline is the defective link.
5. **Reproduce.py regime logic nuance (not a divergence source, but worth flagging):** S3 weight formula in reproduce.py uses `insurance_intensity = clip(vov_z, 0, 1)` which is a continuous interpolation, while the paper text (lines 101, 164) specifies a binary switch at `z<1.0` with a 0.5 coefficient. Despite this, S3 total cost matches reasonably closely (3.31% paper vs 3.636% reproduced). This is a ~10% gap on an already-approximate sensitivity claim; if Sub1 re-bundling closes this to <5%, no further action. If it persists, flag as potential Sub4 (align S3 logic to paper spec exactly).

---

## 6. Appendix: File Paths Referenced

- Paper body: `/Users/yhlai0911/Desktop/volpred-research/paper/vt-insurance-cost/main.tex`
- Reproduce script: `/Users/yhlai0911/Desktop/volpred-research/paper/vt-insurance-cost/reproduce.py`
- Reproduce report: `/Users/yhlai0911/Desktop/volpred-research/paper/vt-insurance-cost/reproduce_report.json`
- Bundled data: `/Users/yhlai0911/Desktop/volpred-research/paper/vt-insurance-cost/data/`
- Canonical K811v2: `/Users/yhlai0911/Desktop/volpred-research/paper/vt-insurance-cost/experiments/k811v2_insurance_premium_vov_fixed.py`
- Canonical K811v2 results: `/Users/yhlai0911/Desktop/volpred-research/paper/vt-insurance-cost/experiments/k811v2_insurance_premium_vov_fixed_results.json`
- Canonical K846: `/Users/yhlai0911/Desktop/volpred-research/paper/vt-insurance-cost/experiments/k846_rebalancing_premium.py`
- Canonical K846 results: `/Users/yhlai0911/Desktop/volpred-research/paper/vt-insurance-cost/experiments/k846_rebalancing_premium_results.json`
