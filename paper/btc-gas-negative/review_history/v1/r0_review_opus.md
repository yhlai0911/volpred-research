# R0 Review — BTC GAS-t Negative-Result Paper (body_v1)

- **Reviewer**: Opus max-effort academic reviewer (R0 / first round)
- **Date**: 2026-06-07 (台灣時間)
- **Scope**: `drafts/body_v1.md` (§1–§9), `drafts/v0_outline_abstract.md`, `README.md`, `data_sources.md`, `experiments.md`
- **Ground truth**: `experiments/k1133b/k1133b_results.json` (primary), `experiments/k1133/k1133_results.json`, `experiments/K1129/k1129_results.json`
- **Gate**: this review gates the .tex conversion.

---

## VERDICT: **FAIL**

The paper is **not** ready for .tex conversion. The core 5-model factorial numbers (Period 1) are clean and trace exactly to `k1133b_results.json`, and the negative-result framing of the central diagnosis is honest and well-argued. But the draft contains **multiple fabricated / unsourced statistics** and **two systemic provenance failures** that violate the research-honesty principle and the paper-workflow "三方一致" rule:

1. The entire **§8 Robustness** section and both appendices (A skewed-t/GED, B ETH/BNB) report specific numeric results that **do not exist in any results JSON**.
2. The paper's **motivating claim** — "K1129 documents the full-sample reversal DM-HLN = −4.67" — is **mis-attributed**: −4.67 is K1133b's *Period-1* statistic; K1129's actual BTC full-sample value is **−4.58** over a *different* window (1500) and a *different* sample (2021–2026, which does not even cover the pre-institutional era).
3. The **Period 2 / Period 3 date definitions** in the body and `data_sources.md` are wrong relative to the canonical experiment (Period 3 OOS is **2026-01-05→2026-04-14**, not 2024-01-21→2024-04-30).
4. A **fabricated mechanism number** in §6 ("degrees of freedom above 30") contradicts the JSON (max ν = 15.48).

These must be fixed before any LaTeX conversion or review-cycle continuation.

---

## CRITICAL issues (must-fix before .tex)

### C1. §8 Robustness + Appendices A/B — fabricated numerical results (no JSON source)
**The most serious issue.** §8 reports concrete statistics that appear in **no** results JSON (`k1133b`, `k1133`, `k1129` all checked; grep for `skewed|mse|robust_loss|boundary|exclud|leave.one|ETH|BNB|GED` returns nothing numeric):

- §8 ¶3 (period-cut): "Period 1 DM-HLN for M3 vs M1 remains **below −3.5** at the strictest cut and **below −4.9** at the most permissive" — no ±60-day boundary re-run exists.
- §8 ¶4 (loss function): re-evaluated under MSE and Patton robust loss L2; "M4 vs M3 retains DM-HLN **above +2.4**" — no alternative-loss results exist.
- §8 ¶5 (leave-one-year-out): "M3 vs M1 ranging from **−3.91 (excluding 2018)** to **−5.24 (excluding 2020)**" — no LOO results exist.
- §8 ¶2 (optimiser): "cross-seed dispersion of best log-likelihood **below 0.5 in 96% of windows** and **below 1.5 in all windows**" — no per-window multistart dispersion is stored in the JSON (only 6 MS fit-log entries with single nll values; no 5-model per-window LL distributions).
- §8 ¶6 + Appendix B (ETH/BNB): "Period 1 reversal pattern is directionally consistent on both" — **no ETH or BNB factorial results exist** in any JSON.
- Appendix A (skewed-t / GED): "skewed-t and GED specifications in Period 1 produce DM-HLN ... in the same direction" — **no skewed-t/GED results exist**.

**Also §5 ¶7** restates Appendix A as if computed; **§5 ¶8** states "maximum-to-median log-likelihood ratio below 1.5%" for M4 with "the same diagnostic reported for all five cells" — no such per-cell diagnostic exists in the JSON.

**Evidence**: `grep -ioE 'skewed|mse|robust_loss|boundary|exclud|leave.one|ETH|BNB|GED' experiments/k1133b/k1133b_results.json experiments/k1133/k1133_results.json` → empty. `k1133b_results.json` contains only Part A (5-model × 3-period), Part B (MS × 3-period), Part C verdict. No robustness sub-runs.

**Fix**: either (a) actually run these robustness experiments and write the real numbers into a results JSON before claiming them, or (b) rewrite §8 / appendices as *planned* robustness with no fabricated point estimates, or (c) delete the unsupported claims. Per CLAUDE.md research-honesty §1 + paper-workflow "三方一致", fabricated numbers are a hard stop. Until run, **§8 cannot stand**.

### C2. §6 — fabricated "degrees of freedom above 30" mechanism claim
§6 ¶7: "the high-volatility state estimated by MS-GAS-t exhibits **degrees of freedom above 30** across the multi-start basin, effectively a Normal innovation." This is the load-bearing evidence for the "regime-switching quietly de-fattens the tail → revealed preference for Normal" argument.

**Source JSON contradicts it.** `part_B_MS_GAS_t_OOS.Period1.ms_fit_log` ν values across the 6 refits: state_0 ∈ {6.90, 4.65, 3.72, 4.91, 5.12, 2.80}, state_1 ∈ {9.25, 7.06, 9.66, **14.89**, **15.48**, 14.26}. **Maximum ν = 15.48**, never above 30. (Note: "high-volatility state" is also ambiguous — state labels swap across refits; α=2.0 boundary state alternates between state_0 and state_1.)

**Fix**: change to the true range (high-ν state reaches ~15, low-ν state ~3–7) and soften the "effectively Normal" conclusion. ν≈15 is moderately fat-tailed, not Normal-equivalent — this materially weakens the "de-fattening = revealed preference for Normal" claim and the wording must be re-derived from the real estimates.

### C3. Mis-attribution of the −4.67 motivating statistic to K1129 full-sample
The paper's central hook (abstract; §1 ¶3 + ¶4; §1 contribution 1; §4 ¶1; README L31; experiments.md L9) states K1129 documents a **full-sample** BTC reversal of **DM-HLN = −4.67** / **QLIKE 9.92% worse**.

**The −4.67 / 9.92% pair is K1133b's Period-1 value, not a K1129 full-sample value.**
- `k1133b ... M3_GAS_t_vs_M1: DM_HLN_t = −4.6692, QLIKE_rel_improvement_pct = −9.9249` (Period 1).
- K1129's actual BTC full-sample: `BTC-USD.dm_tests.M3_GAS_t_vs_M1.DM_HLN_t = −4.5783`, `QLIKE_rel_improvement_pct = −3.955`, **n_oos = 1926, oos 2021-01-01→2026-04-10, window = 1500**.

Two compounding problems:
- **Wrong number**: −4.67 ≠ −4.58; 9.92% ≠ 3.96%.
- **Wrong sample / logical inconsistency**: K1129's BTC OOS is **2021–2026** — it contains *zero* pre-institutional (2017–2020) data. So the paper's claim that "the K1129 full-sample reversal is driven entirely by the pre-institutional period" (abstract; §1 contribution 1; §4) is internally impossible: K1129 never observed 2017–2020. The pre-institutional reversal lives in **K1133/K1133b** (which start the sample at 2015), not K1129.

**Fix**: re-frame the puzzle. Either cite K1129's true full-sample BTC figure (−4.58 over 2021–2026, window 1500) as the *post-2021* anomaly, OR (more coherent) make K1133/K1133b the documenting experiments for the pre-institutional −4.67 and demote K1129 to "cross-asset context / the BTC anomaly that prompted the period-split investigation." Update abstract, §1, §4, README L31, experiments.md L9 consistently. This also fixes §7.3's framing.

### C4. Period 2 / Period 3 date definitions are wrong (body + data_sources.md)
Canonical sub-period boundaries in `k1133b_results.json` / `k1133_results.json`:
- Period 2: sub-period 2021-01-01→2023-12-31, **OOS 2023-01-21→2023-12-31** (n=345).
- Period 3: sub-period 2024-01-01→2026-04-15, **OOS 2026-01-05→2026-04-14** (n=100).

Body §3.2 and `data_sources.md` L28 state **Period 3 OOS = 2024-01-21 → 2024-04-30**. This is wrong by ~2 years — the n=100 Period-3 OOS window is the **last 100 days of the 2026 sample**, not the first 100 days after the Jan-2024 ETF approval. Consequently the §3.2 / §7.2 narrative ("Period 3 begins 21 January 2024, ten trading days after the SEC approval") mis-describes what was actually evaluated. (Period 2 OOS 2023-01-21→2023-12-31 in the body is correct, but the body never states Period 2's sub-period actually starts 2021-01-01, which is what makes the "FTX-Luna era" label sensible — the OOS window itself is 2023-only.)

**Fix**: correct Period 3 OOS dates to 2026-01-05→2026-04-14 in §3.2, the abstract/outline period table, and `data_sources.md`. Re-word the Period-3 interpretation: it is a *mature* spot-ETF-era window (2 years post-approval), not the immediate post-approval window. The "preliminary, n=100" caveat is fine and should remain.

### C5. Residual methodology-drift artifacts (the fix is NOT uniform — review item 2 FAIL)
The 750-day / refit-63 / 4,121-obs / 2026-04-15 fix is mostly applied, but stale values remain:
- `data_sources.md` L18 + README L42: snapshot filename **`btc_daily_20260410.csv`** and "fetched **2026-04-10**" — but the pinned last-in-sample obs is **2026-04-15** (stated two lines above in the same file). The "20260410" / "2026-04-10" provenance is inherited from K1129 (whose OOS ends 2026-04-10), not K1133b. Pick one date and make the filename match.
- **experiments.md L19**: §3 secondary source still says "K1129 (rolling **1000-day**, refit cadence)" — residual 1,000-day drift (the very value the methodology fix was supposed to purge). K1129's actual window is **1500**, not 1000; and the paper's estimation window is 750. Delete/fix.
- §3.1 body L253 (`v1` text) says data runs "1 January 2015 through **10 April 2026**" while the abstract/outline and §1 say "April 2026" / "2026-04-15". The sample end is 2026-04-15. Fix §3.1 to 2026-04-15. (data_sources.md L10 correctly says 2026-04-15.)

**Net**: 1,000-day and 2026-04-10 still survive — the drift fix is incomplete.

---

## MAJOR issues

### M1. Inconsistent significance threshold (|t|>2 vs |t|>3) — and a Harvey-Liu-Zhu mislabel
The paper oscillates between two thresholds and mis-states what Harvey-Liu-Zhu (2016) prescribes:
- §3.6 + abstract framing + §4 narrative invoke "**Harvey, Liu, and Zhu (2016) threshold |DM-HLN| > 3**".
- Table 1 notes (§4 L327, L338) + §5 ("exceed the Harvey-Liu-Zhu threshold of **2**") + outline Key-Numbers note ("**Bold = |DM-HLN| > 2, Harvey-Liu-Zhu gate passed**") use **2**.

The JSON itself stores both `gate_DM` (|t|>2) and `gate_Harvey` and they coincide at the |t|>2 cut for the bolded cells, so the *bolding* is internally consistent at 2 — but the prose repeatedly calls 3 the "Harvey-Liu-Zhu threshold." HLZ (2016) actually argue for a **t ≈ 3.0** hurdle for *new factor* discovery; calling |t|>2 "the Harvey-Liu-Zhu gate" is a mislabel, and simultaneously claiming the threshold is 3 elsewhere is a direct contradiction. **Pick one**: if you adopt HLZ's t>3 for the headline reversal claims (M2 −3.36, M3 −4.67 both clear it; M4 −1.90 does not — clean), use 3 everywhere and stop calling the |t|>2 bolding "the HLZ gate." This is the *honest* and stronger framing for a negative-result paper. (This is the "homemade |t|>3" risk flagged in the review brief — here it is the opposite problem: the genuine HLZ-style t>3 is named correctly in some places but undercut by |t|>2 bolding labeled as HLZ elsewhere.)

### M2. DM-HLN expansions are inconsistent and one is wrong
- §4 L327: "Diebold-Mariano-**Harvey-Lin-Newey (DM-HLN)**" — wrong; it is **Harvey-Leybourne-Newbold (1997)**.
- Table 1 note L338: "**Harvey, Leybourne, and Newbould**, 1997" — misspelled (Newbold, not Newbould).
- §3.6 L317 gets it right ("Harvey-Leybourne-Newbold (1997)").
Fix all to *Harvey, Leybourne & Newbold (1997)*.

### M3. Codex review status overclaimed (CONDITIONAL PASS → presented as clean PASS)
- README L39 and experiments.md L39: lookahead audit is **"CONDITIONAL PASS as of 2026-04-17; verification follow-up scheduled before R1 submission."**
- Body §3.5 L309 + §8 L414 + outline L105 present it as a completed clean review: "an independent Codex review ... verified the absence of one-day look-ahead leakage," with no mention of the conditional status or pending follow-up.
- Also `k1133b_results.json` has **no** review/codex/audit field at all (grep empty), so the "2026-04-17 Codex review" is asserted only in prose, not recorded in the experiment artifact.

Per `.claude/rules/experiments.md` (K1259 lesson: "subagent/CONDITIONAL PASS ≠ primary-path PASS; closure needs Codex re-verify"), the body must not upgrade CONDITIONAL to clean. **Fix**: state the conditional status honestly OR complete the pending Codex re-verification and record it in the JSON before claiming clean.

### M4. §8 lookahead "removed shift" claim unsupported and internally odd
§8 ¶2 / L414: "We re-ran the headline contrast with the shift step deliberately removed and confirmed that look-ahead would have inflated the GAS-t QLIKE differential by an order of magnitude." No such ablation exists in the JSON, and the direction is suspicious (lookahead usually *improves* a model's apparent loss, not inflates an existing *deficit*). Either produce the ablation result or drop the sentence.

### M5. kurtosis ">12" claim — partially unsupported
§1 L208, §6 L374, §7.1 L390, §9 reference "realised excess kurtosis above twelve" for pre-institutional BTC, and §7.1 adds "roughly double the FTX-Luna era and triple the spot-ETF era."
- K1129 BTC full-sample (2021–2026) `kurtosis_excess = 7.97` — *that's the post-2021 sample, not pre-institutional*, so it neither confirms nor refutes >12.
- **No pre-institutional (2017–2020) kurtosis is stored** in k1133/k1133b JSON (grep for kurtosis in k1133 → none). The "double/triple across periods" comparison has no per-period kurtosis source at all.
**Fix**: compute and store per-period excess kurtosis in a results JSON, then cite the real figures; otherwise soften to a qualitative statement.

---

## MINOR issues

- **m1.** §4 L325: "before **MicroStrategy's first treasury allocation**" as the Period-1 end justification — MicroStrategy's first BTC buy was Aug 2020, inside Period 1 (ends 2020-12-31). Minor framing tension; either drop or rephrase ("before the institutional adoption wave accelerated in 2021").
- **m2.** Outline abstract L21 says reversal disappears in "FTX-Luna **(2021-2023)**" while the outline period table L60 labels Period 2 as 2023 only. The sub-period *is* 2021-01-01→2023-12-31 (so "2021-2023" is the more correct span) — but the body §3.2 describes Period 2 only as 2023. Align the era spans (sub-period 2021–2023, OOS 2023) consistently across abstract / §3.2 / data_sources.
- **m3.** §3.3 / equation block: M5 is described as "Standardized Normal" / "shift-scale standardised returns" — the body L279 says "standardized to unit unconditional variance," JSON says "shift-scale standardised." Confirm the exact standardization and state it precisely (the M5 placebo argument depends on it being a numeric no-op; JSON M5 QLIKE 1.99298 vs M1 1.99261 confirms ≈ no-op, good).
- **m4.** §4 L342 / §5: the QLIKE-difference arithmetic for Period 2 ("0.0271 = 2.3162 − 2.2891") and Period 3 ("0.0810 = 2.0563 − 1.9753") is correct against JSON — good. Keep.
- **m5.** "9.92%" vs JSON "9.9249%" and "+2.67" vs "2.6654", "+5.97" vs "5.9709", "+2.67"/"6.9%"/"6.858%", "+0.28" vs "0.2754", "p=0.008" vs 0.007775, "p=0.058" vs 0.05795 — all acceptable roundings; **verified match**.
- **m6.** Citation sanity (for citation-verifier round): Harvey, Leybourne & Newbold (1997) IJF is correctly the DM-HLN source. Klaassen (2002) Empirical Economics 27:363–394 ✓ plausible. Catania & Grassi (2017) cited as SSRN — verify it is the SSRN working paper, not a later journal version. Creal-Koopman-Lucas (2013): outline says *JAE* 28(5):777–795; k1133b references say "JASA 108:1-18" — **these are two different journals**; CKL (2013) is *Journal of Applied Econometrics* 28(5):777–795. The JSON reference list is wrong (JASA); the outline is right. Flag for citation-verifier. Gray (1996) JFE is in the JSON refs but not in the body/outline bibliography though the Klaassen recursion descends from it — consider adding. Lucas & Zhang (2016) and Catania et al. (2019): outline §2 calls Catania et al. (2019) "JFE" in one place (L50) but the bibliography L123 correctly says *IJF* 35(2):485–501 — fix the JFE mislabel.

---

## Number-provenance table

Legend: ✅ exact/rounding match · ❌ mismatch/fabricated · ⚠ misattributed source

| Body / outline claim | Source JSON value | Status |
|---|---|---|
| P1 QLIKE M1 1.9926 | k1133b P1 M1_GJR_N QLIKE 1.99261 | ✅ |
| P1 QLIKE M2 2.2339 | k1133b P1 M2_GJR_t 2.23392 | ✅ |
| P1 QLIKE M3 2.1904 | k1133b P1 M3_GAS_t 2.19037 | ✅ |
| P1 QLIKE M4 2.0402 | k1133b P1 M4_GAS_N 2.04015 | ✅ |
| P1 QLIKE M5 1.9930 | k1133b P1 M5_GJR_N_std 1.99298 | ✅ |
| P1 DM M2 vs M1 −3.36 | k1133b −3.3550 | ✅ |
| P1 DM M3 vs M1 −4.67 | k1133b −4.6692 | ✅ |
| P1 DM M4 vs M1 −1.90 (p≈0.058) | k1133b −1.8976 (p 0.05795) | ✅ |
| P1 DM M5 vs M1 −0.06 | k1133b −0.0591 | ✅ |
| P1 DM M4 vs M3 +2.67 (p≈0.008) | k1133b 2.6654 (p 0.007775) | ✅ |
| P1 innovation contrast 6.9% QLIKE | k1133b M4_vs_M3 rel 6.858% | ✅ |
| P1 "9.92% deterioration" | k1133b M3_vs_M1 rel −9.9249% | ✅ |
| P1 DM MS vs M3 +5.97 | k1133b MS_vs_M3 5.9709 | ✅ |
| P1 DM MS vs M1 +0.28 (p>0.7) | k1133b MS_vs_M1 0.2754 (p 0.783) | ✅ |
| P2 QLIKE M1 2.2891 / M3 2.3162 | k1133b P2 2.28908 / 2.31620 | ✅ |
| P2 DM M3 vs M1 −0.82 | k1133b −0.8152 | ✅ |
| P3 QLIKE M1 1.9753 / M3 2.0563 | k1133b P3 1.97530 / 2.05632 | ✅ |
| P3 DM M3 vs M1 −0.80 | k1133b −0.8031 | ✅ |
| n_total 4,121 obs | k1133b n_total_obs 4121 | ✅ |
| Window 750 / refit 63 / ms refit 252 | k1133b window_default 750 / 63 / 252 | ✅ |
| P1 n_OOS 1,441; P2 345; P3 100 | k1133b 1441 / 345 / 100 | ✅ |
| Seed 42 | k1133b seed 42 | ✅ |
| **"K1129 full-sample reversal DM −4.67"** | K1129 BTC full-sample DM = **−4.5783**; −4.67 is K1133b **P1** | ⚠/❌ misattributed + wrong value |
| **"K1129 full-sample QLIKE 9.92% worse"** | K1129 BTC rel = **−3.955%**; 9.92% is K1133b P1 | ⚠/❌ |
| **"K1129 reversal driven by pre-institutional 2017-2020"** | K1129 BTC OOS = **2021-01-01→2026-04-10** (no 2017-2020 data) | ❌ logically impossible |
| **Period 3 OOS 2024-01-21→2024-04-30** | k1133b P3 oos = **2026-01-05→2026-04-14** | ❌ wrong dates (~2 yr) |
| **§3.1 sample end "10 April 2026"** | sample end 2026-04-15 (4,121 obs) | ❌ inconsistent |
| **snapshot "btc_daily_20260410.csv" / fetched 2026-04-10** | last in-sample 2026-04-15 (same doc) | ❌ internal mismatch |
| **experiments.md §3 "rolling 1000-day"** | estimation window 750; K1129 window 1500 | ❌ residual drift |
| **§6 "high-vol state ν above 30"** | ms_fit_log max ν = **15.48** | ❌ fabricated |
| **§8 LOO "−3.91 (excl 2018) … −5.24 (excl 2020)"** | no LOO results in any JSON | ❌ fabricated |
| **§8 period-cut "below −3.5 … below −4.9"** | no ±60-day boundary results | ❌ fabricated |
| **§8 alt-loss "M4 vs M3 above +2.4"** | no MSE/robust-loss results | ❌ fabricated |
| **§8 optimiser "dispersion <0.5 in 96% / <1.5 all"** | no per-window LL dispersion stored | ❌ fabricated |
| **§5/§8 "max-to-median LL ratio <1.5% per cell"** | not in JSON | ❌ fabricated |
| **Appendix A skewed-t / GED Period-1 DM** | no skewed-t/GED results | ❌ fabricated |
| **Appendix B ETH / BNB Period-1 factorial** | no ETH/BNB results | ❌ fabricated |
| **"excess kurtosis above twelve" (pre-inst)** | only K1129 2021-26 kurt 7.97; no pre-inst kurt stored | ❌ unsupported |
| **§7.1 "double FTX-Luna, triple spot-ETF" kurt** | no per-period kurtosis stored | ❌ unsupported |

**Provenance pass/fail count**: **~24 PASS** (all Period-1/2/3 headline factorial + MS + sample/window/seed numbers trace exactly to k1133b) · **~15 FAIL** (1 misattributed-and-wrong motivating stat propagated to ~6 locations; 1 logically impossible sample claim; wrong P3 dates; residual 1000-day/2026-04-10 drift; 1 fabricated ν; ~8 fabricated robustness/appendix statistics; 2 unsupported kurtosis claims). Plus the threshold/expansion/citation MAJOR/MINOR labeling issues.

---

## Fix recommendations (priority order)

1. **[C1] Gut or ground §8 + Appendices A/B.** Run the robustness experiments and write a `k1133b_robustness_results.json` (LOO-year, ±60-day boundary, MSE/robust-loss, skewed-t/GED, ETH/BNB, per-window multistart LL dispersion), then cite real numbers. If not run before .tex, rewrite §8 as a *plan* with no point estimates and move appendices to "future robustness." No fabricated numbers may survive to .tex.
2. **[C3] Re-frame the K1129 puzzle.** Make K1133/K1133b the documenting experiments for the pre-institutional −4.67; cite K1129's true BTC full-sample (−4.58, 2021–2026, window 1500) only as the cross-asset anomaly that *prompted* the period split. Fix abstract, §1 (¶3, ¶4, contribution 1), §4 ¶1, §7.3, README L31, experiments.md L9.
3. **[C2] Fix the ν claim** in §6 to the true range (high-ν state ~15, low-ν ~3–7) and re-derive the "de-fattening" wording; ν≈15 is not Normal-equivalent.
4. **[C4] Correct Period 3 OOS dates** to 2026-01-05→2026-04-14 in §3.2, abstract/outline table, data_sources.md L28; re-word Period-3 interpretation as a mature (not immediate-post-approval) ETF window.
5. **[C5] Purge residual drift**: experiments.md L19 "1000-day"; §3.1 "10 April 2026" → 2026-04-15; reconcile snapshot filename/date (2026-04-10 vs 2026-04-15).
6. **[M1/M2] Standardize** the significance threshold (recommend HLZ t>3 stated uniformly; stop labeling |t|>2 bolding as "the HLZ gate") and the DM-HLN expansion (Harvey-Leybourne-Newbold 1997, spelling).
7. **[M3] Honest Codex status**: state CONDITIONAL PASS + pending re-verify, or complete it and record in JSON.
8. **[M4/M5] Drop or ground** the lookahead-ablation sentence and the kurtosis figures (compute per-period kurtosis to a JSON first).
9. **[Minor]** Fix CKL-2013 journal in JSON refs (JAE not JASA), Catania-et-al-2019 "JFE"→IJF mislabel, MicroStrategy timing remark.
10. **Add `reproduce.py` + snapshot CSV** (currently absent) — the paper-workflow reproduce gate is a precondition for marking ready; not blocking R0 but blocks submission.

---

## What is solid (keep)

- The **Period-1 5-model factorial** and **MS-GAS-t** headline numbers are byte-accurate to `k1133b_results.json`. This is the empirical core and it is clean.
- The **negative-result framing** is correctly a *fail-to-reject* on the dynamics contrast (−1.90 NS) and a properly-powered null on Period 2; the paper does not claim "proven no effect." Good rigor.
- The **factorial orthogonalization logic** (M4−M3 innovation vs M4−M1 dynamics, M5 placebo) is sound and the placebo (−0.06) genuinely calibrates the comparison.
- The **pre-registration** narrative (k1133 README committed before factorial) is a real strength *if* the commit dates check out (citation/repro round should verify the 2026-04-12 commit).
- **§2 literature review** covers the 16 outline citations coherently across 5 thematic strands; structure is publication-grade (modulo the journal-name fixes in m6).

Once C1–C5 and M1–M3 are resolved, the paper is a strong honest negative result suitable for IJF/JBF negative-result track. **Do not convert to .tex until the fabricated §8/appendix numbers and the K1129 misattribution are fixed.**
