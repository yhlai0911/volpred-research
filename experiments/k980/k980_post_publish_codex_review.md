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

---

## PRIMARY-PATH CODEX RE-VERIFICATION (2026-05-17)

**Codex CLI version**: 0.130.0 (ChatGPT auth, gpt-5.4 model)
**Review date**: 2026-05-17
**Reviewer source**: Codex primary-path (session 019e3610-17ad-7532-afa6-20f217887832)
**Tokens used**: 55,549

### Final Verdict: FAIL

**Root cause**: TGJR estimation–evaluation mismatch. `fit_gjr()` is run on non-contiguous regime-subsets (`returns_low = returns_is[low_mask]`, `returns_high = returns_is[high_mask]`), so its internal likelihood recursion treats "the previous observation **in the subset**" as t-1. But IS recursion (lines 268-283) and OOS recursion (lines 309-323) then assume `h_t` is continuous across the full time series. The model being estimated ≠ the model being forecast/evaluated.

---

### Codex Findings

| # | Severity | Type | Finding |
|---|----------|------|---------|
| 1 | **MAJOR** | New | TGJR estimation–evaluation mismatch (root cause of FAIL) |
| 2 | **MAJOR** | New | `BASE` path hardcoded to worktree (`/.claude/worktrees/agent-a95fb3ea/experiments/k980`) — reproducibility broken for re-runs outside original worktree |
| 3 | MINOR | New | `gjr_forecast_oos()` bug at t=0 (r2_prev=0, indicator=0, first OOS h underestimates α+γ contribution) — function is **never called**, so no impact on existing results |
| 4 | MINOR | New | VaR overlay uses fixed t(5) quantile on Gaussian-MLE variance — `df=5` is not estimated from residuals; `sqrt(3/5)` scale is mathematically correct but the overlay is not model-consistent |
| 5 | MINOR | New | 15% regime constraint in code (line 248-250) vs "≥20%" in results.json metadata (line 653) |
| 6 | INFO | Confirmed | Lookahead: CLEAN — `VIX_lag = VIX.shift(1)` correctly propagated throughout |
| 7 | INFO | Confirmed | OOS recursion: CLEAN — both GJR and TGJR use `r_prev = all_returns[idx-1]` and `vix_lag_oos[t]` (already t-1) |
| 8 | INFO | Confirmed | IS threshold selection: CLEAN — `best_c` grid search is IS-only, no OOS contamination |
| 9 | INFO | Confirmed | DM test (h=1): CORRECT — `range(1,1)` empty → `var_d = gamma0/T`, valid 1-step-ahead DM |

### Codex assessment of TGJR estimation methodology

> 不是單純「方法論選擇」，而是根本性缺陷。合法的 threshold-GJR 應該在完整時間序列上聯合估計，讓 `h_t` 在 regime 切換時仍保持真實的 `t-1 → t` 連續遞迴；目前做法把 low/high 子樣本拆開估，等於估了另一個模型。

---

### Impact on published article (mile_3655a10a)

**Article status**: `draft` (not publicly visible as of 2026-05-17)

**NULL result integrity**: The null conclusion ("TGJR doesn't beat GJR") is directionally **conservative and robust**. The misspecified TGJR is at a disadvantage vs. a properly estimated one; if anything, proper joint estimation might produce a slightly better TGJR. The fact that even the misspecified version fails to beat GJR strengthens the null.

**Article narrative accuracy**: The article's "拆兩半" framing **accurately describes what was done** — the code does literally split the IS data and estimate separately. The article's explanations for failure (sample halving, state discontinuity, VIX information redundancy) are all empirically correct for this implementation.

**Required correction**: Article currently refers to "門檻型 GJR-GARCH" and the literature on threshold models. This should be clarified: the implementation is **two separate GJR models with regime switching** (not joint threshold-GARCH estimation as in Chen et al. 2011). The parameter estimates and economic ratios should be interpreted with this caveat. Draft should remain unpublished until K980-v2 with proper joint threshold-GARCH estimation is completed, OR until a methodology clarification footnote is added.

---

### Action items

1. ✅ Primary-path Codex re-verification complete (FAIL)
2. 🔴 Fix BASE path hardcoding (line 580) → use relative path or `pathlib`
3. 🔴 Fix results.json metadata `regime_constraint` (15% → matches code)
4. 📝 Add K980-v2 to next_tasks: proper joint threshold-GARCH (full sequence MLE with regime indicator in loss function)
5. 📝 Article draft: add methodology caveat OR keep draft until K980-v2 completes
