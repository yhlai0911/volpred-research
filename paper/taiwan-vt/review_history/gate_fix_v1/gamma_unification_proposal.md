# Paper 2 (taiwan-vt) Gate Fix v1 — Gamma Unification Proposal + 23 Untraceable Triage

**Date**: 2026-04-18
**Authoring agent**: claude-worker (task_c2650c6be1b3, P17 paper_review)
**Scope**: Diagnose canonical gamma window → propose Table 2 vs Sec 4.5 unification → triage the 23 UNTRACEABLE claims from 2026-04-19 `reproduce_report.json` (73.1% match, gate=fail).
**Hard constraint**: no `.tex` / `body.tex` / `_results.json` edits; diagnosis + patch proposals only.

---

## 1. Gamma Window Diagnosis (K892 + K900)

### 1.1 All known 0050.TW γ estimates

| Configuration | Source | γ | t(γ) | n | Notes |
|---|---|---|---|---|---|
| Full sample 2008–2026 (Normal) | K892 `full_sample` | **0.0970** | 3.60 | 4,219 | Canonical single-fit |
| Full sample Student-t | K892 `tw50_2008_2026_t` | 0.0801 | 3.48 | 4,219 | Dist mis-specified if Normal is canonical |
| 2018–2026 window (w=2000) | K892 `tw50_2018_2026` | 0.1356 | **2.19** | 2,001 | t=2.19 **matches paper 2.20** |
| Last 2000 of 2008–2026 | K892 `tw50_last2000_of_2008` | 0.1360 | 2.19 | 2,000 | Identical to 2018–2026 (alias) |
| First 2000 of 2008–2026 | K892 `tw50_first2000_from_2008` | 0.0888 | 3.81 | 2,000 | γ=0.089 ≈ **paper 0.087** but t≠2.20 |
| Rolling w=2000 mean (9 windows) | K892 | 0.1064 | 2.78 | — | |
| Rolling w=2000 median | K892 | 0.1034 | — | — | |
| Rolling w=2000 min | K892 | 0.0888 | — | — | Same as first 2000 |
| Rolling 252d daily, full series mean | K900 | 0.1546 | 19.86 (HAC) | 3,964 | Different estimator (per-day refit) |
| Rolling 252d daily median | K900 | **0.1248** | — | — | **≈ 0.124 Sec 4.5 value** |

### 1.2 TSMC (2330.TW)

| Configuration | Source | γ | t(γ) | n |
|---|---|---|---|---|
| Full sample (6,525 days, 1999–2026) | K892 | 0.0525 | 3.98 | 6,525 |
| Period 2008–2026 (matched) | K892 | 0.0466 | 2.58 | 4,470 |
| Rolling w=2000 last window | K892 | 0.0478 | 1.34 | 2,000 |
| Rolling w=2000 mean | K892 | 0.0658 | 2.33 | — |

### 1.3 Diagnosis — what each paper number actually is

**Table 2 / tab:gamma (body.tex:138–162), footnote says "rolling window w=2000"**:

- **0050.TW 0.087 / t=2.20**: *No single K892 spec produces this pair*.
  - Closest γ: K892 first-2000 (γ=0.0888) but its t=3.81.
  - Closest t: 2018–2026 w=2000 (t=2.19) but γ=0.136.
  - Interpretation: **γ=0.087 comes from an old N120 run (deprecated) or from a different data vendor/split adjustment; t=2.20 comes from the 2018–2026 w=2000 fit**. The claim is a piecemeal table update — violates research-honesty §1.
- **TWII 0.272 / t=3.18**: K892 rolling w=2000 *max*=0.236, last window=0.261/t=3.32. Neither exactly matches; TWII 0.272 is also N120-style legacy.
- **TSMC 0.039 / t=0.87**: K892 full=0.0525/t=3.98, rolling-last=0.0478/t=1.34. *No single spec* reproduces (0.039, 0.87). N121 knowledge reports 0.057 for TSMC.
- **SPY 0.211 / t=5.79**: matches K892 rolling mean 0.214 / t_mean=5.31 within tolerance (CLOSE).

**Sec 4.5 / body.tex:531 (TSMC Concentration Robustness)**:

- **0050.TW γ=0.124, t=2.46**: matches K900 `gamma_0050.median_gamma=0.1248` (rolling **252-day** daily refit series, median). HAC t-stat on 3,964 rolling estimates is 19.857, not 2.46 — so **paper's t=2.46 is the t-stat of the mean rolling 252d gamma against zero with a different SE calculation, OR it's a bespoke sub-period fit never saved to JSON**.
- **TSMC γ=0.054, t=1.07**: no K892/K900 cell exactly matches. Closest: K892 full γ=0.0525 (but t=3.98) — t=1.07 signals a short-window sub-period fit (e.g., ex-TSMC 2020–2026) that never got saved.

**Conclusion — the two subsections use different estimators entirely**:
- Table 2 footnote claims `w=2000 rolling` but **actually reports a heterogeneous mix**: legacy N120/N121 headlines for TAIEX/0050/TSMC (0.272/0.087/0.039) and K892-rolling for SPY (0.211).
- Sec 4.5 uses the **K900 rolling-252d per-day refit median** (0.1248 for 0050) but labels it as a single point estimate with a bespoke t-stat.
- This is the **root cause** of the reproducibility gate failure: two different estimators, two different sampling conventions, presented as if comparable.

---

## 2. Canonical γ Recommendation

**Recommended canonical spec (single estimator for all γ in the paper)**:

> **GJR-GARCH(1,1) Normal full-sample MLE, 2008–2026, n≈4,219 for 0050.TW / 2008–2026 for TSMC / 1997–2026 for TWII, estimated on log returns × 100 (percentage units).**

**Rationale**:
1. **Reproducible**: K892 already stores these exact fits with full params + HAC t-stats. No new experiment needed.
2. **Single convention**: removes all ambiguity between rolling w=2000 vs rolling 252d vs first-2000 vs last-2000.
3. **Publication standard**: Pacific-Basin Finance Journal and similar outlets accept a single pooled MLE with clear window documentation; rolling-window estimates belong in an appendix robustness table, not Table 2.
4. **Conservative on story**: TWII full-sample γ=0.109 (vs paper's 0.272) shrinks the headline "4.6×" amplification, but research honesty §1 requires following the data. Paper's lead claim must be rewritten to match.

### 2.1 Canonical values (from K892) — what Table 2 *should* read

| Asset | γ (canonical) | t (canonical) | n | Source cell in K892 |
|---|---|---|---|---|
| TWII (TAIEX) | **0.109** | 5.62 | 7,044 | `assets.^TWII.full_sample` |
| 0050.TW | **0.097** | 3.60 | 4,219 | `assets.0050.TW.full_sample` |
| SPY | **0.220** | 6.94 | 4,592 | `spy_control.spy_2008_2026` |
| TSMC (2330) | **0.053** | 3.98 | 6,525 | `assets.2330.TW.full_sample` |
| TSMC 2008–2026 matched | **0.047** | 2.58 | 4,470 | `assets.2330.TW.period_2008_2026` |

Individual stocks (Hon Hai 0.052, MediaTek 0.044, 0056 0.112, Mega Fin 0.179) **have no K892 JSON source** — only N121 knowledge summary; these must be regenerated (see §5, UNTRACEABLE-HH class) or dropped from Table 2.

### 2.2 Headline amplification under canonical spec

- TWII γ=0.109; 10-stock avg γ is *currently unreproducible* (only N121 summary exists).
- If we trust N121's 0.060 stock average (pending regeneration): ratio = 0.109 / 0.060 = **1.82×** (not 4.6×).
- 0050-based ratio: 0.097 / 0.060 = **1.62×** (not 1.45×).
- US benchmark (SPY 0.220, avg individual ≈ 0.079 per literature): 2.79× (unchanged).

**⇒ The paper's lead claim "TAIEX exhibits 4.6× diversification amplification" is not supported by canonical full-sample MLE. Headline must be revised downward in main-thread body-rewrite phase.**

---

## 3. Patch Proposal — Table 2 + Sec 4.5 Unification

### 3.1 Option A (**RECOMMENDED**): unify to full-sample MLE; demote rolling to appendix

**Table 2 rewrite (body.tex:138–162, `tab:gamma`)**:

```latex
\caption{GJR-GARCH Leverage Parameters Across Taiwan and U.S. Markets}
\label{tab:gamma}
...
TWII (TAIEX, 1997--2026) & 0.109 & 5.62 & 0.039 & 0.892 & 0.985 \\
0050.TW (2008--2026)      & 0.097 & 3.60 & 0.032 & 0.893 & 0.973 \\
SPY (2008--2026)          & 0.220 & 6.94 & 0.013 & 0.852 & 0.975 \\
\midrule
\multicolumn{6}{l}{\textit{Individual Taiwan Stocks (full available sample)}} \\
TSMC (2330, 1999--2026)   & 0.053 & 3.98 & 0.032 & 0.930 & 0.989 \\
[Hon Hai / MediaTek / Mega Fin / 0056 rows → DROP or regenerate via new K-experiment; flag TODO]
10-stock average          & [regenerate] & --- & ... \\
...
\small \textit{Notes:} GJR-GARCH(1,1) full-sample MLE with Normal innovations, estimated on percentage log returns. $t$-statistics from inverse Hessian (not rolling-window HAC). See Appendix~\ref{app:rolling_gamma} for rolling w=2000 robustness.
```

**Sec 4.5 rewrite (body.tex:531)**:

> "The 0050.TW index exhibits a GJR-GARCH leverage parameter of $\gamma = 0.097$ ($t = 3.60$, full sample 2008–2026), whereas TSMC alone shows $\gamma = 0.047$ ($t = 2.58$, matched 2008–2026 sample)."

Drop the "0.124 / 2.46" and "0.054 / 1.07" — these are artifacts of an unsaved rolling-252d median and an unsaved sub-period fit.

**New appendix** (optional, shrinks to a paragraph): report K892 rolling w=2000 stats (mean 0.106, median 0.103, t_mean 2.78) and K900 rolling 252d daily median 0.1248 as time-variation evidence, not as point estimates.

**Story revision needed in abstract + intro + conclusion**:
- "4.6× amplification" → "~1.8× amplification" (pending 10-stock regeneration)
- "γ = 0.272, t = 3.18" for TWII → "γ = 0.109, t = 5.62"

### 3.2 Option B (weaker, for comparison): document window inconsistency explicitly, don't rewrite

Add explicit note to Table 2 caption: "$\gamma$ values are last-window w=2000 rolling (selected to emphasize recent leverage regime); t-statistics use Newey-West HAC. Sec 4.5 uses rolling-252d median (see Appendix)."

- **Con 1**: Still inconsistent within-table (SPY uses rolling *mean*, others use rolling *last*).
- **Con 2**: Does not resolve paper's (γ=0.087, t=2.20) which **no K892 spec reproduces simultaneously**.
- **Con 3**: Violates research-honesty §1 — keeping an unreproducible number with a comment is not fixing it.

**Recommend against Option B.**

### 3.3 Option C (most conservative, longest): new canonical K experiment regenerating all gammas on a single vendor/split

Run a new experiment (e.g., K1200-series) that:
1. Downloads 0050.TW + 10 individual stocks + TWII + SPY on one vendor (yfinance currently) on one date (today).
2. Fits full-sample Normal MLE for all assets with a single identical spec.
3. Produces a JSON with every γ + t in Table 2 directly from one script.
4. Archives rolling w=2000 + rolling 252d as robustness appendix tables.
5. Publishes **new canonical numbers** — paper then matches this canonical.

**This is the gold standard** and what Paper 2 ultimately needs for clean submission. Main thread decision: whether to invest this scope now (likely 2-3 hours of experiment + review) or accept Option A's quick rewrite.

### 3.4 Recommendation to main thread

**Pick Option A now + commit to Option C as a follow-up** (paper is not yet at ready_for_submission; there's time). Option A unblocks the gate immediately (moves from 73.1% to ~90%+ depending on individual-stock regeneration); Option C delivers a reproducible canonical for submission readiness.

---

## 4. What Changes in `reproduce.py` After Applying Option A

The 6 MISMATCH cells resolve as follows (estimated):

| Mismatch | Before | After Option A | Post-fix status |
|---|---|---|---|
| Table 2: 0050 γ | 0.087 vs 0.097 | 0.097 vs 0.097 | VERIFIED |
| Table 2: 0050 t | 2.20 vs 2.19 (alt window) | 3.60 vs 3.60 | VERIFIED |
| Table 2: TWII γ | 0.272 vs rolling max 0.236 | 0.109 vs 0.109 | VERIFIED |
| Table 2: TSMC γ | 0.039 vs 0.053 | 0.053 vs 0.053 | VERIFIED |
| Internal 0050 T2 vs 4.5 | inconsistent | both 0.097 | VERIFIED |
| Internal TSMC T2 vs 4.5 | inconsistent | T2 0.053 / 4.5 0.047 + note | VERIFIED w/ explicit period diff |
| SPY γ (CLOSE) | 0.211 vs 0.214 | 0.220 vs 0.220 | VERIFIED |

**Table 3 SSVS Own-return PIP mismatch** (0.312 vs K461 AR(1)=0.9994) is *separate* from γ unification and needs its own investigation (likely a different SSVS prior run never saved to K461).

**Tab VaR K852 GJR+Normal** (9 vs 11) is also separate — likely a refit schedule mismatch, not γ-related.

**Post-Option A reproduce_report projection**:
- Matched: 79 + 6 γ unifications → 85
- Mismatches: 6 − 4 γ = 2 (SSVS PIP + VaR K852)
- Untraceable: 23 (unchanged by γ fix — needs §5 plan)
- Match rate: 85/108 = **78.7%**
- Traceable: 85/85 = **100%** (up from 92.9%)

**To hit ≥95%**: also need to retire ≥9 untraceable claims (either backfill JSON, flag errata, or drop from paper). See §5.

---

## 5. 23 UNTRACEABLE Triage

Full list from 2026-04-19 reproduce.py run. Each classified as:
- **(a) backfillable from existing JSON / knowledge** — no new experiment needed
- **(b) needs new experiment** — scope required
- **(c) errata / drop / rewrite** — cannot reproduce, flag in errata

| # | Claim | Location | Triage | Resolution |
|---|---|---|---|---|
| 1 | TWII mean daily 0.019% | Table 1 | **(b)** new exp | K892/K900 use different periods; run 1-file descriptive stats script 1997–2026. ~15 min. |
| 2 | TWII std daily 1.45% | Table 1 | **(b)** | same script as #1 |
| 3 | TWII skewness −0.31 | Table 1 | **(b)** | same; but flag K900 shows +0.473 for 0050 → Table 1 signs may all be flipped. Verify. |
| 4 | TWII kurtosis 5.82 | Table 1 | **(b)** | same; K900 gives 5.935 approximate, close. |
| 5 | BH Sharpe 0.729 | Table 4 | **(c)** errata | K1175 (canonical replication) gives 0.799 for 2010–2026. Paper's 0.729 from legacy run with 2008–2026 vendor data no longer available. **Rewrite Table 4 caption to 2010–2026 K1175 period, update all 12 cells.** |
| 6 | EWMA VT Sharpe 0.796 | Table 4 | **(c)** errata | K1175 gives 0.701. Same period correction as #5. |
| 7 | GARCH VT Sharpe 0.994 | Table 4 | **(c)** errata | K1175 gives 0.950 (CLOSE, 4.5% diff). Same period correction. |
| 8 | GJR VT Sharpe 1.108 | Table 4 | **(c)** errata | K1175 gives 1.074 (CLOSE, 3.1% diff). Same period correction. |
| 9 | Table 5 common-period all values | Table 5 | **(c)** errata | Same period issue; K1175 provides 2020–2026 common period cells. Rewrite with K1175 values. |
| 10 | Import growth partial r=0.214 | Sec 6 | **(a)** backfill | G12 knowledge entry exact match. Promote to `experiments/g12/` with results JSON extracted from knowledge (or cite G12 explicitly in `experiments.md`). **Still risky: knowledge entry has no reproducible script**. Recommend (b) as fallback: re-run 30-min macro sweep. |
| 11 | BCI momentum t=3.74, R²=7.1%, Sharpe 0.732 | Sec 6 | **(a)** backfill | G20 knowledge entry exact match. Same recommendation as #10 — promote + script reproduce. |
| 12 | Taiwan c2c Sharpe 1.473 | Appendix TZ / Table 4' | **(c)** errata | K1176 gives 1.915 (DIVERGENT, vendor yfinance vs TEJ). **Rewrite with K1176 values + caption note.** |
| 13 | TW+JP 50/50 Sharpe 1.810 | Appendix TZ | **(c)** errata | K1176 gives 2.192 (DIVERGENT). Same resolution. |
| 14 | TSMC VT Sharpe 1.121 | Sec 4.5 | **(b)** new exp | No TSMC-dedicated VT backtest in any K. Required scope: run a K1200-series TSMC isolated backtest with matched 0050 period, ~1 hour. |
| 15 | TSMC 52.5% of 0050 return variance | Sec 4.5 | **(b)** | same experiment as #14, adds R² / variance decomp step. |
| 16 | VIXTWN/VIX ratio 1.393 (CV 10%) | Sec 2.5 | **(b)** new exp | 64-month overlap; ~30-min script pulling VIXTWN + VIX, compute ratio stats + Spearman. |
| 17 | TWD/USD p=0.08 | Sec 3 | **(b)** new exp | Granger test script; adds to #16 experiment bundle. |
| 18 | 0056.TW robustness t=5.67 | Sec 4.4 | **(b)** new exp | 0056-specific conditional leverage repeat of K558 protocol. ~45 min. |
| 19 | Hon Hai γ=0.052, t=1.14 | Table 2 | **(b)** new exp | Regenerate in canonical-spec K1200 (§3.3 Option C). Currently only N121 average. |
| 20 | MediaTek γ=0.044, t=0.96 | Table 2 | **(b)** | same as #19 |
| 21 | 0056.TW γ=0.112, t=1.87 | Table 2 | **(b)** | same as #19 |
| 22 | BH MDD −41.3% | Table 4 | **(c)** errata | K1175 gives −33.83% (2010–2026 yfinance). Same Table 4 rewrite as #5. |
| 23 | EWMA VT MDD −18.4% | Table 4 | **(c)** errata | K1175 gives −21.17%. Same rewrite. |

### 5.1 Triage summary

| Class | Count | Effort |
|---|---|---|
| (a) backfillable from G12/G20 knowledge | 2 (#10, #11) | low — document + cite; may still need formal experiment to truly reproduce |
| (b) needs new experiment | 11 (#1–#4, #14–#21) | 3–5 hours total across 4 focused mini-experiments |
| (c) errata / rewrite Table 4/5 to K1175/K1176 canonical | 10 (#5–#9, #12–#13, #22–#23) | 30 min — mechanical text update by main thread |

### 5.2 Recommended sequencing (smallest → biggest impact)

1. **Immediate (main thread, ≤30 min)**: apply Option A γ rewrite (§3.1) + Table 4/5 period correction (class (c), 10 items). Expected post-fix match rate: ~90% (85 + 10 retired via errata rewrite = 95/108 = **88%**, all **traceable** = 100%).
2. **Short follow-up (new mini-experiments, ~1 hour)**: K1200 (canonical γ sweep, §3.3) resolves #19–#21 + promotes §3.1 to Option C. Match rate → ~92%.
3. **Deferred (medium, ~2 hours)**: VIXTWN/TWD experiment (#16–#17) + TSMC-isolated VT backtest (#14–#15) + 0056 robustness (#18). Match rate → ~97%.
4. **Optional**: G12/G20 formal reproduction (#10–#11). If deferred to R1 response, cite knowledge entry in `experiments.md` as "knowledge-entry-level replication, formal script pending".

### 5.3 Gate target

- After step 1: gate status `fail` → `yellow` (88% match, 100% traceable, but below 95% threshold).
- After step 2: `yellow` → ~92%.
- After step 3: ~97% → **green**, submission-ready.

---

## 6. Apply Plan for Main Thread (L188 or whichever apply pass)

### 6.1 Dry-run checklist

- [ ] Verify §3.1 canonical values against K892 JSON fields cited in §2.1 (spot-check 2 cells).
- [ ] Confirm whether to go Option A (quick) or Option A+C (canonical regen) — **user/main-thread call**.
- [ ] Decide whether to rewrite abstract "4.6×" headline now or flag as "pending abstract revision" for next review round.

### 6.2 Patch sequence (main thread, not this agent)

1. **Edit body.tex:138–162** (Table 2) → Option A canonical cells + drop/regenerate individual-stock rows + update caption.
2. **Edit body.tex:531** (Sec 4.5) → replace "0.124 / 2.46" with "0.097 / 3.60"; "0.054 / 1.07" with "0.047 / 2.58".
3. **Edit Table 1** (body.tex ~52–56) → match Table 2 γ values (currently duplicates Table 2; must stay consistent).
4. **Edit body.tex:136** (Index-Level Leverage narrative) → 0050.TW gamma 0.087 → 0.097, TWII 0.272 → 0.109.
5. **Edit Abstract (main.tex:35)** → 4.6× → ~1.8× (or flag for user decision); γ=0.272 → γ=0.109.
6. **Edit body.tex:166** (Diversification Amplification) → rewrite 4.6× paragraph with canonical ratios.
7. **Edit body.tex:184, 580** (Conclusion) → same corrections.
8. **Rewrite Table 4 / Table 5 / Sec 5 / Sec 8** narrative per K1175/K1176 canonical values (class (c) errata, 10 items).
9. **Add `experiments.md`** at `paper/taiwan-vt/experiments.md` listing K892, K900, K1175, K1176, K515, K516, K512, K558, K461, K847, K848, K849, K850, K851, K852, K886, K896 and their paper sections (currently absent — is a Paper 2 self-contained requirement).
10. **Re-run** `uv run python paper/taiwan-vt/reproduce.py` → expect 85–95/108 match (depending on which classes applied), 100% traceable.
11. **Commit** with message "Paper 2 gate fix v1: unify γ to canonical full-sample MLE, Table 4/5 errata to K1175/K1176, 23 untraceable triaged".
12. **Log**: append to `docs/error_log.md` one lesson: "Paper 2 Table 2 mixed N120 legacy γ + piecemeal t-stats; canonical full-sample spec is K892 full_sample. Always bind paper tables to a single JSON cell; never mix estimators in one table without explicit column-by-column source notes."
13. **knowledge.json**: add one K entry summarizing γ unification outcome for future papers.

### 6.3 Hard do-NOTs

- Do NOT attempt to fabricate a γ=0.087 spec to justify Table 2 (research-honesty §1, §3).
- Do NOT commit Option B unless explicitly approved — it paper-overs inconsistency without fixing it.
- Do NOT merge a body_v(n+1).tex without running `reproduce.py` to re-score the gate.

---

## 7. Files referenced / read

- `/Users/yhlai0911/Desktop/volpred-research/paper/taiwan-vt/main.tex` (shell)
- `/Users/yhlai0911/Desktop/volpred-research/paper/taiwan-vt/body.tex` (lines 44–62, 128–184, 198–214, 516–548)
- `/Users/yhlai0911/Desktop/volpred-research/paper/taiwan-vt/reproduce.py` (gate script)
- `/Users/yhlai0911/Desktop/volpred-research/paper/taiwan-vt/reproduce_report.json` (2026-04-19 ad5d95 batch)
- `/Users/yhlai0911/Desktop/volpred-research/paper/taiwan-vt/experiments/k892_verify_tw_gamma_results.json` (canonical γ source)
- `/Users/yhlai0911/Desktop/volpred-research/paper/taiwan-vt/experiments/k900_taiwan_vt_performance.py` lines 687–765 (rolling 252d amplification)
- `/Users/yhlai0911/Desktop/volpred-research/paper/taiwan-vt/experiments/k900_taiwan_vt_performance_results.json` `amplification.gamma_0050` block
- `/Users/yhlai0911/Desktop/volpred-research/paper/taiwan-vt/reproducibility_audit/README.md`, `diff_report.md`, `nosource_rescan_report.md`, `main_tex_numbers.csv`
- `/Users/yhlai0911/Desktop/volpred-research/paper/taiwan-vt/reviews/audit_step1_2.md` lines 25–52, 345–375
- `/Users/yhlai0911/Desktop/volpred-research/.claude/rules/paper-workflow.md` (gate rule binding)

## 8. One-line summary for task finish

Canonical γ = K892 full-sample Normal MLE; Table 2 rewrite 0050 0.087→0.097, TWII 0.272→0.109, TSMC 0.039→0.053; Sec 4.5 0.124→0.097, 0.054→0.047. 23 UNTRACEABLE split as: 2 G12/G20 backfillable, 11 need 4 new mini-experiments (≤5h), 10 retire via Table 4/5 K1175/K1176 errata rewrite. Post-apply projection: 88% match (Option A only) → 95%+ green after step 3.
