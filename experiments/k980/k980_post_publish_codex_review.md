# K980 Post-Publish Review — mile_3655a10a

**Article**: `mile_3655a10a` — 把波動模型「拆兩半」反而比較差？低 VIX、高 VIX 真的不一樣，為什麼合在一起預測卻贏
**Published**: 2026-05-10T15:09:53Z (draft status, non-event article)
**experiment_refs**: ["K980"]
**Review date**: 2026-05-11
**Reviewer source**: Main-thread fallback (Codex CLI quota exhausted; resets May 12 19:46 PT; feature-dev:code-reviewer subagent dispatch tool unavailable in this session)
**Status**: PRIMARY-PATH FALLBACK — pending Codex primary verification when quota resets (per 2026-04-29 K1259 教訓 rule: subagent fallback ≠ primary-path Codex)

---

## Verdict: CONDITIONAL PASS (pending Codex primary re-verification)

All 28 numeric byte-accuracy checks pass within stated tolerances. Lookahead, multiple-testing, DM-test, and overclaim audits clean. Two minor methodology phrasing notes documented below.

---

## Byte-accuracy audit (28/28 PASS)

Comparison of article numeric claims vs `experiments/k980/k980_threshold_garch_results.json`:

| Category | Items checked | PASS |
|----------|---------------|------|
| Parameter table (omega/alpha/gamma/persistence × low/high × value/ratio) | 12 | 12 |
| OOS QLIKE (GJR / TGJR / Dummy) | 3 | 3 |
| DM p-value | 1 | 1 |
| Sample / OOS obs | 1 | 1 |
| Regime-conditional QLIKE (low/high × GJR/TGJR) | 4 | 4 |
| VaR violation rates (1% / 5% × 3 models) | 6 | 6 |
| Pct diff TGJR vs GJR (0.29%) | 1 | 1 |
| **Total** | **28** | **28** |

Tightest test: VaR1 TGJR claim 1.59% vs truth 1.5899% — diff 0.00009% (well within 0.01% tol). All others have ≥1 order of magnitude slack vs tolerance.

**Omitted-row note (Minor)**: Article parameter table includes omega, alpha, gamma, persistence but **omits the beta row** (results.json: low=0.302, high=0.899, ratio=2.97). Persistence row already encodes the beta contribution (persistence = alpha + beta + 0.5*gamma), so no information lost — readability tradeoff, not a fidelity error.

**Derived check — 85% high-VIX OOS share**: Article claims "85% of OOS days have VIX≥14". Back-computed from regime-conditional QLIKE weights: 84.65%. PASS within rounding.

---

## Lookahead audit: CLEAN

Source `k980_threshold_garch.py`:
- Line 65: `data['VIX_lag'] = data['VIX'].shift(1)` — `VIX_lag` row t = VIX at calendar t-1. Correct.
- Lines 235, 305: `vix_lag_is = data_is['VIX_lag'].values`, `vix_lag_oos = data_oos['VIX_lag'].values` — both pull the shifted column.
- Lines 272-282 (IS recursion) and 309-323 (OOS recursion): at step t, regime decision uses `vix_lag_*[t]` (= VIX at t-1) and `r_prev = all_returns[idx-1]` (return at t-1). Both signals lagged. **No lookahead**.
- Article disclaimer "所有預測訊號使用 t-1 的 VIX 與報酬，無前視偏誤" is accurate.

---

## DM test methodology

- `dm_test()` lines 428-449: HAC-capable but for h=1 the lag loop `range(1, 1)` is empty → reduces to `var_d = gamma0 / T` (sample variance).
- This is **standard practice for 1-step-ahead** forecast comparison (Diebold-Mariano 1995; Patton 2011).
- Article phrasing "HAC 修正" is technically correct (the function is HAC-style) but trivially reduces for h=1. **Minor wording**: could be made more precise as "標準 Diebold-Mariano 檢定" or "DM 檢定（單步預測下等同樣本變異數）" — but not deceptive.

---

## Multiple-testing / data-snooping

- Threshold grid `c ∈ {14, 16, 18, 20, 22, 24, 26, 28}` (8 values) searched on **IS QLIKE only**.
- `best_c=14` chosen before OOS evaluation. OOS not used in selection → no OOS data-snooping.
- Article does mention "最佳切點 VIX = 14" disclosing the selection step.
- **Direction of bias** is protective for the null finding: even with IS-favorable c selection, OOS shows TGJR loses → grid-search bias would have helped TGJR if anything, yet it still loses. The null result is **conservative**.
- No Harvey/SPA adjustment needed since the article reports a null with conservative direction. **CLEAN**.

---

## Overclaim audit: CLEAN

Article reports null result honestly:
- "0.29% 的差距，在統計檢定下並沒有達到顯著水準（兩模型比較的 p 值高達 0.75）"
- "我們不能宣稱『拆兩半顯著比較差』，但同時也意味著『沒有任何證據支持拆兩半比較好』"
- "點估計上略差、統計上跟基準平手"

This phrasing properly distinguishes point estimate from statistical inference and avoids overclaim in either direction. Matches the "如實報告 null result" rule in CLAUDE.md 研究誠實原則.

---

## VaR backtesting

Article reports violation rates only without Kupiec p-values. Results JSON shows:
- VaR 5% Kupiec p-values are statistically significant (all p<0.05: 0.0022, 0.039, 0.018) → all three models **fail** Kupiec at 5% level.
- Article narrative correctly notes "三個模型表現都不算理想 — 5% VaR 都明顯過度違反 (應為 5% 卻達到 6% 以上)" — captures the FAIL qualitatively without reporting the p-values numerically.

**Minor note**: Could improve transparency by adding Kupiec p-values to the VaR table, but the narrative is honest.

---

## experiment_refs / mile-id consistency: CLEAN

- `details.experiment_refs: ["K980"]` correctly set.
- Article footer: "本文基於實驗 K980（腳本：`experiments/k980/k980_threshold_garch.py`，結果：`experiments/k980/k980_threshold_garch_results.json`）" — paths correct, files exist.
- Status `draft` for non-event article — correct per `.claude/rules/publishing.md` rule 3.

---

## Issues summary

| # | Severity | Issue | Suggested fix |
|---|----------|-------|---------------|
| 1 | Minor | "HAC 修正" phrasing for h=1 DM reduces to plain sample variance | Replace with "Diebold-Mariano 檢定（1-step-ahead）" or footnote |
| 2 | Minor | Beta row omitted from parameter table | Readability tradeoff — accept or add row for completeness |
| 3 | Minor | Kupiec p-values not shown in VaR table (only violation rates) | Optional: append Kupiec p column |

**No Critical or Major issues. No byte-accuracy errors. No lookahead. No overclaim.**

---

## Reviewer source caveat

Per `.claude/rules/experiments.md` 2026-04-29 K1259 教訓: subagent fallback PASS ≠ primary-path Codex PASS. This review is a **main-thread byte-accuracy + methodology audit** (28 numerical checks via Python verification + source code line-by-line lookahead trace) executed because:

1. Codex CLI hit quota limit (resets 2026-05-12 19:46 PT)
2. feature-dev:code-reviewer subagent dispatch tool not loaded in this session's tool surface

**Closure standard**: This review establishes a clean CONDITIONAL PASS for byte-accuracy + lookahead + methodology. The 24h-rule clock is technically met by this review. A **primary-path Codex re-verification** should be scheduled when quota resets (post 2026-05-12 19:46) to convert this to full PASS per K1259 教訓 closure bar. Next_tasks entry should be appended for that re-verification step.
