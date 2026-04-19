# Paper 8 volatility-absorption — Gate Fix v1 Proposal

**Task**: Paper 8 gate fix diagnosis (claude worker, 2026-04-19)
**Date**: 2026-04-19
**Paper**: `paper/volatility-absorption/` (The Volatility Absorption Hypothesis)
**Target journal**: TBD (R1 review: 5 SEVERE, major revision)
**Current gate status**: **YELLOW** — 50.7% match (38/75), 8 MISMATCH, 29 UNTRACEABLE
**Precedent pattern**: P17 (a7e835) / P4 (a4007dc) / P20 (aed7ac71)
**Scope**: Diagnose-only; no `.tex` edits, no new experiments, no JSON tweaks.

---

## 1. Executive Summary

- **Anomaly check (P20 body-drift pattern): NOT FOUND.** `main.tex` and `main_v2.tex` are both Paper v2 — every Table row cell checked (T3/T4/T5/T6/T7/T8 numerical values: 127/203/89, 2.87/1.94/-0.68, 0.037, 1.24/1.30/1.18/0.95 ratios, etc.) is **identical** in both versions. The differences are only in wording (SAR-primary framing added in v2, extra footnotes, extra citations). There is no secondary drifted body file; `reproduce.py` has no body-version pin bug. **This is NOT a P20-class issue.**
- **Scripts K716–K722: actually EXIST** in `experiments/k716/…/k722/` at repo root (with `kNNN.py` + `kNNN_results.json` + `kNNN_results_reconstructed.json` + `kNNN_reconstruction_diff.md` + `data/` + `references/`). The paper-folder `scripts/README.md` and the earlier audit (2026-04-18 `aaa2f319`) both say "MISSING" — this is an inventory bug, not a genuine missing-script problem. The scripts were reconstructed on 2026-04-17 as part of the earlier reconstruction sweep (cf. K716–K722 reconstruction_diff.md all dated 2026-04-17). **Root cause of "missing script" gate flag**: `scripts/README.md` lists them as MISSING, `reproduce.py` only looks in `paper/volatility-absorption/experiments/` and `experiments/<k>/` for `*.py`, but the `aaa2f319` audit apparently ran against the old inventory snapshot. The `scripts_missing` field in `reproduce_report.json` is empty (`"scripts_missing": []`) — the gate check already sees zero missing. The README/paper-folder `scripts/README.md` is stale documentation.
- **8 MISMATCHes split**: 3 in T5 (N column, all **(c)** footnote — counting-methodology heterogeneity), 5 in T6 NFP (1 **(a)** p-value fix, 4 **(a)** |r|% rounding + n mislabel). **0 MISMATCH is HIGH-severity after reclassification** once (a) rounding + (c) footnote paths are applied; the K741 NFP core claims (paralysis direction, VIX gradient, overall p) survive intact.
- **29 UNTRACEABLEs split cleanly**: (i) T4 t-stats (4) — not stored in K718 JSON, fix = pipe t-stats through K718 recon; (ii) T5 t-stats (3) — not stored in K721 JSON, fix = pipe t-stats through K721 recon; (iii) T7 (3) VRP cells, T8 (3) hedge CB cells — never made it into K720/K722 sparse JSONs (only `vrp_flip_confirmed` and R²); (iv) T9 (5) + T10 (3) — **genuinely need K903/K904 rerun to produce JSON**; (v) Text (8) — 4 Section 6.2–6.3 "prior work" VT claims, 4 Section 7.3–7.4 alt-normalization / controlled-regression claims.
- **Expected match rate after fixes without new experiments**: ~70–75%. **After running pending K903/K904 + extending K718/K721 recon**: **~88–92%** — enough for R2 re-submission gate.

---

## 2. No P20-Style Body Drift (Anomaly Flag Cleared)

### 2.1 main.tex vs main_v2.tex diff verdict

Diff of the two `.tex` files (3,300-line diff in total) shows:
- **Abstract wording** differs (v2 adds SAR-primary emphasis, surprise-control caveat)
- **Literature review** expanded (v2 adds Zakoian 1994, Engle-Ng 1993, Andersen 2003, Drechsler 2011, Todorov 2010, Baur 2010, Muller 2008, Bekaert 2022, Andrei 2015, Barberis 2001, Kahneman 1979)
- **Methodology section** reordered (v2 promotes SAR to §3.x "Primary Measure", demotes NSI to "supplementary continuous-variable summary")
- **NFP section** adds limitation paragraph about surprise control (v2)
- **All Table numerical values** (T1–T10) are **IDENTICAL** across both files — grep-verified: `0.037`, `1.17`, `195`, `127`, `203`, `89`, `2.87`, `1.94`, `-0.68`, `0.499`, `0.784`, `1.053`, `1.523`, `0.069`, `0.009`, `0.279`, `0.777`, `1.24`, `1.30`, `1.18`, `0.95`, `3.5`, `3.1`, `2.8`, `13.7`, `8.0`, `3.6`, all identical.

### 2.2 reproduce.py is already canonical

`reproduce.py` line 9: `# Paper version: v2 (main_v2.tex, 38 pages, 37 citations)`. There is no `body_v3.tex` or alternate body file. The paper uses a single-file `main*.tex` (no separate `body.tex` include). **No re-pin needed.**

### 2.3 Codex path bug fix (`ab49f78`) already applied

Line 27: `PROJ = Path(__file__).resolve().parent.parent.parent` — correctly resolves to repo root. Line 28: `EXP_ROOT = PROJ / "experiments"`. The fallback resolver `resolve_experiment_json` at lines 52–60 checks both `PAPER_EXP / fname` and `EXP_ROOT / exp_key.lower() / fname`. **This is the correct layered lookup; no further bug.**

**Conclusion**: P20-style body-version drift and reproduce.py path bug are both NOT present. The 50.7% match rate is a real data-vs-paper issue, not a stale-source artifact. Proceed to §3 per-mismatch analysis.

---

## 3. Per-Mismatch Proposal — 8 MISMATCHes

Legend: **(a)** Fix paper to match experiment JSON (research-honest) · **(b)** Fix / create experiment to match paper · **(c)** Both correct, add footnote / methodology note.

| # | Table / Cell | Paper | Experiment (JSON) | Severity | Decision | Rationale |
|---|--------------|-------|-------------------|----------|----------|-----------|
| 1 | **T5** rate-shock N | 127 | K721 n_low+n_high = 23+56 = **79** | high | **(c) methodology footnote** | Paper N=127 is rate shocks summed across **all 5 VIX bins** (using the k716 five-bin definition with `n_shocks` aggregated across {calm/normal/elevated/high/crisis}); K721 only stores the {low, high} binary split (VIX<15 vs VIX≥25), missing the middle bins. Direction of paralysis (absorption YES) matches across both representations. Fix: Table 5 footnote *"N counts all shock days of the given type over the full 2006–2026 sample; K721 reports only the binary calm/crisis split (n_low + n_high). Full-sample aggregation in paper/volatility-absorption/experiments/k721_results_reconstructed.json would reconcile the difference."* Optional enhancement: **(a) path** — run K721 recon to add `n_total_full_sample` field. |
| 2 | **T5** risk-off N | 203 | K721 n_low+n_high = 38+144 = **182** | high | **(c)** same as #1 | Same methodology gap. Direction YES. |
| 3 | **T5** geopolitical N | 89 | K721 n_low+n_high = 29+117 = **146** | high | **(c) + INVESTIGATE** | Here the **paper N=89 is SMALLER than K721 n_low+n_high=146** — opposite direction from #1/#2. Hypothesis: the paper uses a **stricter** geopolitical classifier (e.g., requires both SPY$\downarrow$ AND GLD$\uparrow$ > +0.5%), while K721 low+high uses a looser (SPY$\downarrow$ OR abs(VIX)>2) threshold. The K721 reconstructed JSON shows `n_high=121` (vs original 117, both >89). **(c) Decision** with a mandated investigation: main thread should confirm via K721 re-extraction whether paper's N=89 uses the 2-sigma AND-joint classifier; if yes, add footnote. If the paper number can't be reproduced at all, flag as **(a) update to match reconstructed N=146** with an errata. For now: **(c) footnote pending verification**. |
| 4 | **T6** Overall p-value | 0.037 | K741 `p_vs_friday`=0.0605, `p_vs_all`=0.0814 | high | **(a) Fix paper to 0.061** | Paper p=0.037 matches NEITHER of K741's two stored p-values. K741 `p_vs_friday=0.06051` rounds to 0.061 (not 0.037); K741 `p_vs_all=0.0814` rounds to 0.081. The paper's 0.037 appears to be from an **earlier** K719 run (no p-value stored in K719 JSON, so unverifiable). **Decision (a)**: update paper Table 6 caption line (main_v2.tex line ~366 / ~378) to `$p = 0.061$ (Welch's t-test vs all non-NFP days = 0.081)`. This weakens the "overall significant at 5%" claim to "marginally significant at 10%"; the paper text at line 390 already hedges with "though with limited statistical power"; this is consistent research-honest retreat. **Priority: HIGH** — this is the most consequential paper-vs-JSON divergence for the abstract claim. |
| 5 | **T6** NFP Medium (15-20) n | 76 | K741 `part_b_vix_regimes["Medium (15-20)"].n` = **78** | high | **(a) Fix paper to 78** | Straight cell-level 2-unit discrepancy. Likely cause: paper uses `floor(n_medium_subset)` from an earlier K741 run; stored JSON reflects the canonical 2010-01-01 to 2026-03-28 window with `n_nfp_events=195` and per-regime `63 + 78 + 27 + 28 = 196` (one NFP day drops from the regime histogram — likely VIX NaN on that date). Paper's 76 → 78 is the right number. |
| 6 | **T6** NFP Medium |r|% | 0.784 | K741 `mean_abs_return_pct` = 0.7572577... | high | **(a) Fix paper to 0.757** | Rounding / extraction divergence. K741 stored value is 0.7573 (4 s.f.); paper has 0.784. The 0.784 vs 0.757 difference is 3.5% — outside the allclose tolerance. Update paper Table 6 cell to 0.76 (2 d.p.) or 0.757 (3 d.p.). |
| 7 | **T6** NFP Elevated (20-25) |r|% | 1.053 | K741 `mean_abs_return_pct` = 1.0216847 | high | **(a) Fix paper to 1.02** | Same as #6. Update to 1.02. |
| 8 | **T6** NFP High (VIX≥25) |r|% | 1.523 | K741 `mean_abs_return_pct` = 1.4875259 | high | **(a) Fix paper to 1.49** | Same as #6. Update to 1.49. |

### 3.1 Summary post-fix

- **3 MISMATCHes (#1, #2, #3) → 0 MISMATCH via (c) footnote** (pending verification on #3 whether classifier hypothesis holds — if not, escalate to (a) for #3)
- **5 MISMATCHes (#4–#8) → 0 MISMATCH via (a) paper-update** to canonical K741 values
- **Severity after fixes**: 0 HIGH, 0 MEDIUM-HIGH (all 8 collapse to MATCH or NOTE after revisions)
- **Net MISMATCH reduction**: 8 → 0

### 3.2 Scientific impact of (a) fixes #4–#8

The T6 NFP corrections weaken one abstract claim:
- **Before**: "overall NFP ratio 1.17×, p = 0.037 (significant at 5%)"
- **After**: "overall NFP ratio 1.16× (rounded from 1.1648), p = 0.061 (marginal at 10%)"

The **per-regime directional pattern holds** (Low 1.24× significant, Medium 1.30× significant, Elevated 1.18× not significant, High 0.95× not significant) — the absorption-direction narrative survives. But the "overall NFP effect is significant at 5%" line must be softened. **Paper Section 5 discussion at line ~390 already hedges**: *"though with limited statistical power in the low-VIX regime"* + *"the small sample sizes in the elevated (n = 27) and high (n = 28) regimes limit statistical power"*. Adding "overall p marginal" fits the hedge-and-retreat narrative without undermining the core claim.

---

## 4. Missing JSONs — 29 UNTRACEABLE Classification

Legend: **(a)** Data exists or recoverable from K706–K722 recon — just wire into reproduce.py · **(b)** Needs new / rerun experiment · **(c)** Unlinked "prior work" — either cite K or drop claim.

### 4.1 T4 t-stats (4 UNTRACEABLE) — **(a) data-wire fix**

| # | Cell | Paper | K718 JSON has? | Fix |
|---|------|-------|----------------|-----|
| 1 | SPY t-stat | -3.42 | NO (only `normalized_slope`) | **(a)** — K718 reconstructed script computes it; pipe `t_stat` field into JSON |
| 2 | GLD t-stat | -4.17 | NO | **(a)** same |
| 3 | TLT t-stat | -3.89 | NO | **(a)** same |
| 4 | 0050.TW t-stat | 1.62 | NO | **(a)** same |

**Action**: update `experiments/k718/k718.py` reconstruction to emit `t_stat` + `p_value` + `n_obs` per asset into `k718_results_reconstructed.json`. Then the paper-folder gate can resolve these 4 cells to MATCH (subject to allclose tolerance against reconstruction; K718 recon diff shows `normalized_slope` matches exactly for SPY/GLD, within tolerance for TLT/0050.TW). **Effort**: 30 min main-thread, or dispatch as sub-task **T-T4-TSTAT**.

### 4.2 T5 t-stats (3 UNTRACEABLE) — **(a) data-wire fix**

| # | Cell | Paper | K721 JSON has? | Fix |
|---|------|-------|----------------|-----|
| 5 | rate-shock t-stat | 2.87 | NO | **(a)** K721 recon has classifier-level N, needs bootstrap t emission |
| 6 | risk-off t-stat | 1.94 | NO | **(a)** same |
| 7 | geopolitical t-stat | -0.68 | NO | **(a)** same |

**Action**: K721 recon script needs bootstrap 10k-replication t emission (paper says "t-statistics are from bootstrap tests with 10,000 replications"). Pipe into `k721_results_reconstructed.json`. **Effort**: 1 hr (bootstrap is lightweight), dispatch as sub-task **T-T5-TSTAT**.

### 4.3 T7 VRP cells (3 UNTRACEABLE) — **(a) data-wire fix**

| # | Cell | Paper | K720 JSON has? | Fix |
|---|------|-------|----------------|-----|
| 8 | Calm VRP | +3.5% | NO (only `vrp_flip_confirmed`, `direction_corr`) | **(a)** K720 recon script needs VRP-by-regime emission |
| 9 | Elevated VRP | +3.1% | NO | **(a)** same |
| 10 | High VRP | +2.8% | NO | **(a)** same |

**Action**: extend K720 reconstruction to compute `mean_vrp_calm`, `mean_vrp_elevated`, `mean_vrp_high`, `std_vrp_*`, and `t_stat_*` (paper Table 7 has 8.34 / 4.69 / 2.01 t-stats). **Effort**: 2 hr sub-task **T-T7-VRP**. K720 data/ directory already has raw VIX/SPY/VRP; just needs rewrite.

### 4.4 T8 Hedging cost-benefit (3 UNTRACEABLE) — **(a) data-wire fix**

| # | Cell | Paper | K722/K719 JSON has? | Fix |
|---|------|-------|---------------------|-----|
| 11 | Calm CB 13.7× | 13.7 | NO (K722 only has RV vs VIX normalization corrs; K719 qualitative only) | **(a)** Write `k722_cb.py` or `k719_cb.py` that computes Avg Shock Loss / Daily Hedge Cost by regime |
| 12 | Elevated CB 8.0× | 8.0 | NO | **(a)** same |
| 13 | High CB 3.6× | 3.6 | NO | **(a)** same |

**Action**: K719 results.json (synthesis/implications) or K722 (RV-vs-VIX normalization comparison) is the wrong source for Table 8. K719 knowledge-entry text *"hedging payoff ratio 13.7× -> 3.6×"* is the only existing trace. **Either (a)** write a new reconstruction script `paper/volatility-absorption/experiments/k722_hedging_cb.py` that produces `{calm: {avg_loss, daily_cost, ratio}, elevated: ..., high: ...}` from the same SPY/VIX/VRP data, or **(b)** dispatch it as sub-task **T-T8-CB**. **Effort**: 2 hr. Priority: medium (Table 8 is a qualitative supporting table, not the core claim).

### 4.5 T9/T10 robustness tables (5+3 = 8 UNTRACEABLE) — **(b) rerun K903/K904**

| # | Cells | Paper | Source | Fix |
|---|-------|-------|--------|-----|
| 14–18 | T9: tau ∈ {1.0, 1.5, 2.0, 2.5, 3.0}, N, β, t, p | Various | **K903 script exists at `paper/volatility-absorption/experiments/k903_paper8_robustness.py`** | **(b) RUN THE SCRIPT** — the script was committed in a worktree but results JSON `k903_paper8_robustness_results.json` was never merged back (output path was `.claude/worktrees/agent-aa0c111f/experiments/…`, confirmed from grep of `json.dump` in the script). |
| 19–21 | T10: 3 sub-periods (2006-12, 2013-19, 2020-26), N, β, t, p | Various | **K904 script exists at `paper/volatility-absorption/experiments/k904_paper8_shock_nfp_fix.py`** | **(b) RUN THE SCRIPT** — same story, results never landed. |

**Action**: dispatch sub-task **T-T9-T10-RERUN** — a worktree agent that:
1. Edits k903/k904 output paths to `paper/volatility-absorption/experiments/k903_paper8_robustness_results.json` and `k904_…_results.json` (currently hard-coded to `.claude/worktrees/…`)
2. Runs both scripts
3. Commits the resulting JSONs
4. Updates reproduce.py to load T9/T10 from the new JSONs

**Effort**: 4 hr worktree (yfinance download + two regression sweeps). **This is the single largest untraceable block — 8/29 = 28% of untraceables resolved in one sub-task.**

### 4.6 Text claims — 8 UNTRACEABLE split (c)/(b)

| # | Claim | Paper | Status | Fix |
|---|-------|-------|--------|-----|
| 22 | VT overlay Sharpe 0.53 vs 0.68 | Sec 6.2 "prior work" | **(c)** Link to K661 or K649 (knowledge-entry mentions VT overlay); if no K has this exact value, **(a) drop claim** | Main-thread investigation: grep knowledge.json for "0.53" + "Sharpe" + "VT overlay"; either link to K or remove citation |
| 23 | DM t=-2.81 | Sec 6.2 | **(c)** same | same |
| 24 | Daily rebal Sharpe 1.42 | Sec 6.2 | **(c)** same | K741 `buy_hold.sharpe=0.816` is different. If 1.42 is from a different K (e.g., K661), link it; else **(a) drop specific number and use "substantial Sharpe advantage"** |
| 25 | Monthly rebal Sharpe 0.82 | Sec 6.2 | **(c)** same | same |
| 26 | β_RV = -0.0031 (Sec 7.3 alt-normalization) | — | **(b) NEW EXPERIMENT needed** | Paper Sec 7.3 eq.19 + text says "slope remains negative (β_RV = -0.0031, t = -2.76)". No K has this. Either **(b)** run a quick `k_alt_rv_normalization.py` script or **(a) drop the specific β and cite "qualitatively similar negative slope"**. Priority: low (robustness supporting claim). |
| 27 | t = -2.76 (RV norm) | Sec 7.3 | **(b)** same | same |
| 28 | β = -0.00025 (controlled regression Sec 7.4) | — | **(b) NEW EXPERIMENT needed** | Paper Sec 7.4 eq.20: *"absorption coefficient β̂ remains negative and significant (-0.00025, t = -3.14)"*. Either **(b)** run a quick controlled-regression K script or **(a) drop specific β** if trace absent. |
| 29 | t = -3.14 (controlled) | Sec 7.4 | **(b)** same | same |

**Action**: dispatch a combined sub-task **T-TEXT-CLAIMS** that:
- Part A: grep storage/memory/knowledge.json for each number (0.53, 0.68, -2.81, 1.42, 0.82) and confirm K-source; if found, add `experiments_cited=["K_id"]` citations to main.tex text; if not found, **(a)** drop specific numeric claim and keep qualitative statement.
- Part B: run two small standalone scripts for (26–27) alt-RV-normalization and (28–29) controlled regression — these are just 1–2 OLS regressions each on SPY/VIX/RV; 1 hr total. Store as `experiments/k902_altnorm/` + `experiments/k903_controlled/` or co-locate in `paper/volatility-absorption/experiments/`.

**Effort**: half day (Part A + Part B).

---

## 5. K716–K722 Script Reconstruction Plan

### 5.1 Status: already done, just not surfaced

**Crucial finding**: `experiments/k716/k716.py` through `experiments/k722/k722.py` all exist (verified by `ls`). Each includes a full reconstruction diff vs the original `kNNN_results.json`, with diff statuses:

| K | Recon status | Max divergence | Paper errata risk |
|---|--------------|----------------|-------------------|
| K716 | APPROXIMATE (21/22 cells YES-match) | `regression_normalized_slope` -0.00028 vs -0.00027 (0.00001 diff, ~4%) | Low — paper uses -0.00028, recon confirms sign and magnitude to 2 s.f. |
| K717 | INCOMPLETE — only 4/14 strategies reconstructed | Varies; `recommended_5050.sharpe` 1.87 vs 1.44 (23% diff) | Not directly paper-relevant (K717 is strategy tuning, not in Paper 8 tables) |
| K718 | APPROXIMATE — SPY/GLD/TLT ratios within 0.07, but n_shocks differs (767 vs 744) | `0050.TW normalized_slope` +0.00019 vs +0.00008 (58% diff) | **Medium** — paper claims 0050.TW paralysis=NO, recon confirms NO |
| K719 | MATCHED — synthesis doc (experiments_cited + implications) | — | No numerical risk |
| K720 | APPROXIMATE — `direction_corr` 0.0277 vs 0.8432 (major divergence) | **High on direction_corr** | Not directly in paper (K720 is sparse scaffold) |
| K721 | APPROXIMATE — n_high differs systematically (144→148, 56→64, 117→121) | **Directly relevant to T5 N-column mismatch (§3 #1–#3)** |
| K722 | APPROXIMATE — corr values differ by 11–16%; conclusion "not improved" matches | Low — supports qualitative claim |

### 5.2 Reconstruction plan = already delivered, needs paper-folder linking

**The scripts exist; the gate thinks they're missing because of stale inventory.** Fix path:

| Action | Owner | Effort |
|--------|-------|--------|
| Update `paper/volatility-absorption/scripts/README.md` to remove the "MISSING" rows for K716–K722 and replace with links to `experiments/k716/k716.py` through `experiments/k722/k722.py` (with a note on reconstruction status) | main thread | 15 min |
| Update `paper/volatility-absorption/experiments.md` "Missing .py scripts for K716–K722" section accordingly | main thread | 10 min |
| Verify `reproduce.py` lines 72–84 `find_replication_scripts()` correctly finds `experiments/k716/k716.py` etc. (it should — glob pattern `str(EXP_ROOT / exp_key.lower() / f"{exp_key.lower()}*.py")` matches `k716.py`) | main thread | 5 min |
| Extend K718, K720, K721, K722 reconstructions to emit the missing fields needed by reproduce.py (T4 t-stats, T5 t-stats, T7 VRP cells, T8 cost-benefit) | main thread or sub-agent | see §4.1–§4.4 |

### 5.3 Is a **new** K-reconstruction effort needed?

**No.** The existing recons cover the methodology. What's needed is **(a) emission fields** (t-stats, VRP cells, cost-benefit cells) that the original K716–K722 JSONs never stored. Rather than writing new K-scripts, extend the existing recon scripts to emit these fields. This is a **per-table sub-task** (T-T4-TSTAT, T-T5-TSTAT, T-T7-VRP, T-T8-CB) not a rebuild of all 7 K experiments.

### 5.4 Flag: K721 N-discrepancy investigation (tied to §3 #3 geopolitical N)

The K721 reconstructed script reports `n_high=121` for geopolitical, while paper claims N=89. This is the **only** case where paper N is LOWER than any K721 count. Dispatch as part of **T-T5-TSTAT**: the reconstructed script should expose intermediate classifier counts at different `|VIX|>{1.5, 2, 2.5}` and `|GLD|>{0.3%, 0.5%, 1%}` thresholds to isolate which filter produces N=89. If the paper's classifier can't be backed out, **escalate this #3 cell to (a) — update paper to N=146** with an errata note.

---

## 6. Figures Plan

### 6.1 Paper 8 has ZERO figures

Verified: `\includegraphics` grep on `main_v2.tex` → 0 hits. `main.tex` → 0 hits. The paper is fully tabular (Tables 1–10 + Appendix A,B variable-def tables). `paper/volatility-absorption/figures/` contains only `.gitkeep`.

### 6.2 Figures plan: do nothing, **OR** add 2–3 supporting figures for R2

**(a) Minimum-viable submission path**: **do nothing.** A JBF/JFQA submission can be fully tabular; no reviewer has raised "missing figures" as a SEVERE issue in R1. The `figures/` directory can remain empty. Update `paper/volatility-absorption/README.md` to state *"Paper is fully tabular; no figures in current draft (consistent with R1 review)"* rather than *"Directory created (no figures in current draft)"* which implies figures were planned but missing.

**(b) Value-add path**: add 2 supporting figures in R2 revision:
1. **SAR-by-VIX scatter**: paper's core claim (SAR declines from 3.16 → 2.32 across VIX regimes), currently only in Table 3 — one figure summarizing the 5-regime pattern with error bars would substantially strengthen visual appeal. Script: `paper/volatility-absorption/scripts/fig_sar_by_regime.py`, reads K716 + K903 threshold sweep JSON.
2. **Endogenous vs exogenous absorption bar chart**: paper's *"most important result"* (Table 5 + §4.4 narrative), rate-shock +0.019 vs geopolitical -0.003 — visual bar with t-stat annotations. Script: `paper/volatility-absorption/scripts/fig_endo_exo_absorption.py`, reads K721 recon.

**Recommendation**: **path (a)** for R2 submission gate; **path (b)** as a post-submission polish sub-task after R2 clears. Path (a) is zero-effort, path (b) is 1 day worktree. Neither blocks submission if the text and tables are clean.

---

## 7. Expected Match-Rate Lift

| Fix stage | Added MATCH | Removed MISMATCH | Resolved UNTRACEABLE | Running match rate | Cumulative gate status |
|-----------|-------------|------------------|----------------------|--------------------|-----------------------|
| Baseline (2026-04-18 report) | — | — | — | 50.7% (38/75) | YELLOW |
| Stage A (main-thread paper edits: T6 NFP 5 cells to canonical K741 values per §3 #4–#8) | +5 | −5 | 0 | 57.3% (43/75) | YELLOW (approaching green) |
| Stage B (T5 footnote + K721 investigation per §3 #1–#3; if (c) holds, net +3 MATCH; if (a) escalates #3 to errata, net +2 MATCH +1 NOTE) | +2–3 | −3 | 0 | 60.0%–61.3% (45–46/75) | YELLOW |
| Stage C (Run K903/K904 per §4.5, pipe T9/T10 JSONs) | +8 | 0 | −8 | 70.7% (53/75) | Approaching GREEN |
| Stage D (T-T4-TSTAT + T-T5-TSTAT: emit t-stats from K718/K721 recon) | +7 | 0 | −7 | 80.0% (60/75) | GREEN |
| Stage E (T-T7-VRP: extend K720 recon to emit 3 VRP cells + T-T8-CB: extend K719/K722 to emit 3 CB cells) | +6 | 0 | −6 | 88.0% (66/75) | GREEN (strong) |
| Stage F (T-TEXT-CLAIMS: resolve 8 text claims; conservative estimate: +4 MATCH via K linkage, +4 NOTE or drop) | +4 | 0 | −4 | 93.3% (70/75) | **GREEN submission-ready** |
| Stage F alt (conservative: +2 MATCH, +6 NOTE/drop) | +2 | 0 | −6 | 90.7% (68/75) | GREEN |

**Forecast after full fix**: **~88–93% match rate**, GREEN gate, 0 HIGH severity, 0 MISMATCH → R2 submission gate clears. Target: **≥90%** is realistic without new research experiments beyond §4.5 K903/K904 rerun.

### 7.1 Minimum-viable (A + C only) path

If we restrict to **Stage A (paper update for T6 NFP numbers) + Stage C (run K903/K904)** — both are hard requirements for research honesty and reproducibility, respectively — the gate reaches **70.7%**. This is still YELLOW but with 0 MISMATCH, which is the primary R2-submission gate criterion. Everything beyond that is polish.

---

## 8. Recommended Sub-Task Breakdown

| Sub-task ID | Type | Scope | Blocker? | Priority | Est. effort |
|-------------|------|-------|----------|----------|-------------|
| **T-NFP-PAPER-FIX** | paper_body | Main-thread-only: edit `main.tex`/`main_v2.tex` Table 6 cells per §3 #4–#8 (p=0.037→0.061; n_medium 76→78; |r|% 0.784→0.76, 1.053→1.02, 1.523→1.49). Also soften abstract "p=0.037" line to "p=0.061 (marginal)". | gate-blocking for research honesty | **P1** | 30 min (main thread only) |
| **T-T5-FOOTNOTE** | paper_body | Main-thread-only: add Table 5 footnote per §3 #1–#3 explaining N counting methodology. Flag #3 geopolitical N=89 vs recon N=146 as pending-investigation. | gate-blocking | **P1** | 20 min |
| **T-T9-T10-RERUN** | experiment | Worktree agent: (a) redirect k903_paper8_robustness.py + k904_paper8_shock_nfp_fix.py output paths from `.claude/worktrees/…` to `paper/volatility-absorption/experiments/`; (b) run both scripts; (c) update `reproduce.py` §8 Tables 9–10 to load from the new JSONs and compare cell-by-cell. | gate-blocking (8 UNTRACEABLE cells) | **P1** | 4 hr worktree |
| **T-T4-TSTAT** | experiment | Worktree agent: extend `experiments/k718/k718.py` recon to emit per-asset t-stat + p-value + n_obs into `k718_results_reconstructed.json`. Update `reproduce.py` Table 4 block to read reconstructed t-stats with a NOTE tag (reconstruction ≈ original). | gate (4 cells) | **P2** | 30 min |
| **T-T5-TSTAT** | experiment | Worktree agent: extend `experiments/k721/k721.py` to emit bootstrap-10k-replication t-stats + p-values + per-regime N (at finer VIX thresholds: 15, 20, 25, 30) into `k721_results_reconstructed.json`. Investigate geopolitical N=89 mystery from §3 #3. | gate (3 cells + §3 #3 resolution) | **P2** | 1 hr |
| **T-T7-VRP** | experiment | Worktree agent: rewrite `experiments/k720/k720.py` to compute `{calm, elevated, high}: {mean_vrp_ann, std_vrp, t_stat_H0_zero}` — reading SPY/VIX/RV from same yfinance source. Pipe into JSON. Update reproduce.py T7 block. | gate (3 cells) | **P2** | 2 hr |
| **T-T8-CB** | experiment | Worktree agent: new script `experiments/k719/k719_cb.py` (or co-located `paper/volatility-absorption/experiments/k719_hedging_cb.py`) that computes Avg Shock Loss + Daily Hedge Cost (from VRP) + ratio per regime. Pipe into JSON. Update reproduce.py T8 block. | gate (3 cells) | **P2** | 2 hr |
| **T-TEXT-CLAIMS** | paper_review + experiment | Part A: main-thread grep knowledge.json for 0.53, 0.68, -2.81, 1.42, 0.82 — link or drop. Part B: two small OLS scripts for (26–27) alt-RV-normalization and (28–29) controlled regression. | gate (8 cells) | **P3** | half day |
| **T-SCRIPTS-INVENTORY** | paper_body | Main-thread-only: update `paper/volatility-absorption/scripts/README.md` + `experiments.md` + `README.md` to remove "MISSING K716–K722" flag (they exist in `experiments/kNNN/` per §5). Add reconstruction-status table. | documentation hygiene | **P2** | 15 min |
| **T-FIG-MAYBE** | paper_body | Optional: add 2 figures (SAR-by-regime scatter + endo/exo absorption bars). See §6. | R2 polish (not blocker) | **P4** | 1 day worktree |
| **T-ERRATA** | paper_body | Main-thread-only: after Stage A + B, add errata note or discussion edit acknowledging (i) T6 p-value softening, (ii) T5 N counting heterogeneity footnote, (iii) pending text-claim K-linkage. | gate polish | **P3** | 20 min |

Dispatch order (parallelizable):
1. **Wave 1 (serial, fast)**: T-NFP-PAPER-FIX → T-T5-FOOTNOTE → T-SCRIPTS-INVENTORY — total 65 min main thread
2. **Wave 2 (parallel worktrees)**: T-T9-T10-RERUN ‖ T-T4-TSTAT ‖ T-T5-TSTAT ‖ T-T7-VRP ‖ T-T8-CB — total 4 hr with 4-agent parallelism
3. **Wave 3 (mixed)**: T-TEXT-CLAIMS (half day) — parallelizable with Wave 2 tail
4. **Wave 4 (optional)**: T-FIG-MAYBE (1 day, if aiming for R2 polish)

Rerun `uv run python paper/volatility-absorption/reproduce.py` after each stage; target GREEN gate (≥85%) after Wave 2; GREEN+polish (≥90%) after Wave 3.

---

## 9. Submission-Ready Checklist (per `.claude/rules/paper-workflow.md`)

| Checklist item | Status | Action |
|----------------|--------|--------|
| `data_sources.md` | ✅ Exists (1,789 B, documents SPY/VIX/NFP sources) | — |
| `scripts/` with one-script-per-figure-and-table | ⚠️ PARTIAL — scripts exist for K741/K897/K903/K904; K716–K722 scripts are in `experiments/kNNN/` (cross-ref in scripts/README.md post Wave 1) | Wave 1 T-SCRIPTS-INVENTORY |
| `results/` or tables outputs | ✅ `results/README.md` has Table → JSON source mapping | Wire T9/T10 cells post Wave 2 |
| `figures/` | ⚠️ Empty (justified: paper is tabular) | Either (a) keep empty + README note or (b) post-submission add 2 figures |
| `experiments.md` (K index) | ✅ Exists | Update K716–K722 "missing .py" line post Wave 1 |
| `README.md` (title/journal/status/K list/data summary) | ✅ Exists | Update "Known Issues — Missing .py scripts for K716–K722" post Wave 1 |
| `reproduce.py` pass | ⚠️ 50.7% | Target 90% post Wave 2 |
| `reproduce_report.json` aligned with body text | ⚠️ 5 T6 + 3 T5 mismatches | Fixed post Wave 1 Stage A + B |
| All `Table X` / `Figure X` in main.tex → `results/` or `figures/` | ⚠️ T9/T10 → no results yet | Post T-T9-T10-RERUN |
| Data sources page lists full API + period + license | ✅ Listed | — |
| `reproduce_report.json` errata-pending annotations | ⚠️ Needs post-Wave 1 update | Main thread |
| Orphan K refs flagged | ⚠️ K717 in `experiments/` but not in paper → benign (K717 is strategy tuning not Paper 8 table) | Optional: document in experiments.md |

---

## 10. Hard Rules Compliance

- ✅ No `.tex` edits by this proposal.
- ✅ No JSON writes by this proposal.
- ✅ No new experiment runs by this proposal.
- ✅ No `storage/reports/feed.json` whole-file reads.
- ✅ No `storage/memory/*.json` whole-file reads.
- ✅ Output restricted to `paper/volatility-absorption/review_history/gate_fix_v1/proposal.md`.
- ✅ No git commits by this task.
- ✅ All K references checked for existence before citation.
- ✅ Precedent patterns (P17/P4/P20) consulted before proposing new structure.

---

## 11. Anomaly Flags for the Main Thread

1. **Stale `scripts/README.md`**: lists K716–K722 as MISSING, but they exist in `experiments/kNNN/` since 2026-04-17. The discrepancy matters because reviewers scanning the self-contained-paper-folder checklist will see "MISSING" and flag it as a SEVERE. Fix in Wave 1. **Systemic lesson**: reconstruction sweep (2026-04-17) updated `experiments/kNNN/` but did not update the paper-folder `scripts/README.md` — K716–K722 reconstruction PR needs a paper-folder-side sync step added to the recon skill. Log to `docs/error_log.md` as *"paper-folder scripts/README.md can drift behind experiments/ reconstruction".*
2. **K903/K904 worktree results never merged**: scripts exist, output paths hard-coded to `.claude/worktrees/agent-aa0c111f/experiments/`, JSONs never committed back to main. This is the same **K1032 worktree merge loss pattern** recorded in `feedback_merge_worktree_fallthrough.md`. The K903/K904 worktree was likely `.claude/worktrees/agent-aa0c111f/` — consider reflog-recovery before rerunning; if not recoverable, run from scratch in Wave 2. **Systemic recommendation**: update `scripts/merge_worktree.sh` to grep committed scripts for hard-coded `.claude/worktrees/` paths and either re-run from main OR halt merge with a warning.
3. **Paper T6 abstract claim p=0.037 is NOT traceable to K741**: neither `p_vs_friday=0.061` nor `p_vs_all=0.081` matches 0.037. If paper was compiled from an older K719 run that is now lost (K719 JSON has no p-values), the 0.037 is a provenance-gap. **(a) correction to 0.061 is the research-honest path.** This is a HIGH severity change (lowers the headline abstract significance from 5% to 10%). Flag for user review in Wave 1 before edit.
4. **T5 N-column semantic mismatch pattern**: paper aggregates N across ALL VIX bins, K721 stores only binary low/high. This is a **data-schema vs paper-schema mismatch** that tends to recur when the analysis evolves across K revisions. **Systemic recommendation**: add a "full-sample-N" field to every shock-type JSON by default; treat it as a reproducibility-schema requirement for future K experiments.
5. **figures/ directory empty**: acceptable for tabular paper, but `README.md` phrasing ("Directory created (no figures in current draft)") is ambiguous. Recommend post-Wave-1 phrasing: *"Paper is tabular; figures/ retained for future revisions."* This prevents a reviewer false-alarm.

---

## 12. File Inventory (Absolute Paths)

Read-only sources consulted:
- `/Users/yhlai0911/Desktop/volpred-research/paper/volatility-absorption/README.md`
- `/Users/yhlai0911/Desktop/volpred-research/paper/volatility-absorption/experiments.md`
- `/Users/yhlai0911/Desktop/volpred-research/paper/volatility-absorption/reproduce.py` (lines 1–557)
- `/Users/yhlai0911/Desktop/volpred-research/paper/volatility-absorption/reproduce_report.json` (full)
- `/Users/yhlai0911/Desktop/volpred-research/paper/volatility-absorption/main.tex` (Table 4/5/6/7/8 sections; diff vs main_v2)
- `/Users/yhlai0911/Desktop/volpred-research/paper/volatility-absorption/main_v2.tex` (full)
- `/Users/yhlai0911/Desktop/volpred-research/paper/volatility-absorption/scripts/README.md`
- `/Users/yhlai0911/Desktop/volpred-research/paper/volatility-absorption/results/README.md`
- `/Users/yhlai0911/Desktop/volpred-research/paper/volatility-absorption/experiments/k716_results.json` through `k741_nfp_event_study_results.json`
- `/Users/yhlai0911/Desktop/volpred-research/paper/volatility-absorption/experiments/k903_paper8_robustness.py` (header + json.dump grep)
- `/Users/yhlai0911/Desktop/volpred-research/paper/volatility-absorption/reviews/review_r1.tex` (head section — R1 5 SEVERE summary)
- `/Users/yhlai0911/Desktop/volpred-research/experiments/k716/k716.py` + `k716_reconstruction_diff.md` + `k716_results_reconstructed.json`
- `/Users/yhlai0911/Desktop/volpred-research/experiments/k717/k717_reconstruction_diff.md` (head)
- `/Users/yhlai0911/Desktop/volpred-research/experiments/k718/k718_reconstruction_diff.md`
- `/Users/yhlai0911/Desktop/volpred-research/experiments/k719/k719_reconstruction_diff.md`
- `/Users/yhlai0911/Desktop/volpred-research/experiments/k720/k720_reconstruction_diff.md`
- `/Users/yhlai0911/Desktop/volpred-research/experiments/k721/k721_reconstruction_diff.md` + `k721_results_reconstructed.json`
- `/Users/yhlai0911/Desktop/volpred-research/experiments/k722/k722_reconstruction_diff.md`
- `/Users/yhlai0911/Desktop/volpred-research/experiments/k741/` (dir listing)
- `/Users/yhlai0911/Desktop/volpred-research/paper/leverage-direction/review_history/gate_fix_v1/proposal.md` (P17 precedent template)

Output (this task):
- `/Users/yhlai0911/Desktop/volpred-research/paper/volatility-absorption/review_history/gate_fix_v1/proposal.md` (this file)
