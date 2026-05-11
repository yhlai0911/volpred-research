# K981 mile_ec876702 Post-Publish Review

- **Article**: `mile_ec876702` — 「小波分解能救 HAR 嗎？信號處理碰上日頻波動率的反直覺結局」
- **Published**: 2026-05-10 09:11:49 UTC (status=draft, awaiting release_pool)
- **Experiment**: K981 (HAR + Wavelet Decomposition, SPY 2006-2026)
- **Review date**: 2026-05-11
- **Reviewer source**: **Gemini CLI fallback** (model `gemini-2.5-pro`) — Codex primary quota-exhausted (resets 2026-05-12 19:46 PT). Primary-path Codex re-verify queued per K1259 lesson.
- **Verdict**: **CONDITIONAL_PASS**

## Scope

Byte-accuracy + lookahead + DM/Harvey + multiple-testing + wavelet-specific spec audit, per 24h-rule (K1018 lesson, 2026-05-02).

## Issues found

### Tier: Major

1. **GJR-GARCH significance over-claimed under Harvey (2016) standard**
   - DM `t = -2.65` (p = 0.0081) vs AR(1) — passes single-test 1% but **fails Harvey 3σ rule** for financial multiple-testing.
   - Article line 62 calls GJR「冠軍」based on point QLIKE — acceptable as ranking statement, but combined with the implicit DM significance claim, an attentive reader may infer formal statistical superiority. Recommend tempering to "best-performing by point estimates; not Harvey-3σ distinguishable from AR(1)".

2. **WHAR_HAR_db4 QLIKE = 474.48 numerical-artifact framing**
   - Article line 60 attributes it to "wavelet 能量在某些 OOS 觀測值上劇烈失準, 把 QLIKE 的非對稱懲罰拉爆". Correctly diagnoses **mechanism** but does not flag that this magnitude (>2 orders) is closer to a **numerical artifact** than a loss-function-meaningful comparison. Driver: `predictions.loc[date] = max(pred, 0.0001)` floor (py L172) — clip at 1e-4 lets `log(a/p)` explode.
   - Recommend a one-line caveat: "474.48 should be read as a model-failure flag, not a comparable QLIKE figure; QLIKE is poorly defined near p→0."

### Tier: Minor

3. **OOS observation count off-by-one**
   - Article: "OOS 2019-2026 = 1,824 obs" (line 24 and line 127).
   - JSON: `n_oos = 1823` (every model). Code uses `target = r2.shift(-1)` so last obs has no target, leaving 1823 forecasts.
   - README also says "1824 obs" for raw OOS rows — consistent w/ article, but the actual model-evaluated n is 1823. Recommend clarifying: "OOS rows 1,824; model-evaluated forecasts 1,823 (final-day target unavailable)".

4. **IS R² = 0.126 missing from results JSON**
   - Article line 77 cites IS R²=0.126 for the wavelet OLS regression. README line 64 echoes it. **Not stored in JSON**. Code lines 484-485 print it but the value is not persisted to `results_json`. Traceability gap; reader cannot reproduce-from-JSON.
   - Recommend adding `results_json['wavelet_is_r2'] = float(reg.score(X_wavelet, y_target))` to the script and regenerating JSON (or noting reproducibility path explicitly).

5. **Multiple-testing not disclosed**
   - 6 models, 6 DM tests vs AR(1), plus 1 HAR-vs-WHAR test = 7 tests. No Bonferroni / Romano-Wolf / SPA / MCS applied or mentioned. Article's main claim (HAR vs WHAR `t = 5.98`) easily clears Bonferroni-adjusted thresholds, so the NULL conclusion stands — but the omission deserves a methodology-section line.

### Tier: Nit

6. **HAR-vs-WHAR DM `t = 5.98` only in README/code, not in JSON `dm_tests`**
   - JSON `dm_tests` only stores DM-vs-AR(1); HAR-vs-WHAR is printed at py L440 but not saved. Article cites this number; reproducibility currently requires re-running the script. Recommend persisting all pairwise DM stats.

7. **Wavelet boundary effects undiscussed**
   - 64-day rolling window for 5-level `pywt.wavedec` (64 ≥ 2^5 = 32 ✓). Standard, but db4 has support length 8 → edge artifacts non-trivial. Article does not mention. Optional caveat.

## Byte-accuracy check (article ↔ JSON)

| Claim | Article | JSON | Status |
|-------|---------|------|--------|
| Period | 2006-01-04 ~ 2026-04-06 | 2006-01-04 to 2026-04-06 | ✓ |
| Total obs | 5,094 | (5094 implied by IS 3270 + OOS+target alignment) | ✓ |
| IS obs | 3,270 | 3270 | ✓ |
| OOS obs | **1,824** | **1823** | Off-by-one (Minor #3) |
| GJR QLIKE 1.531 | 1.531 | 1.5307621810 | ✓ (rounding) |
| HAR QLIKE 1.541 | 1.541 | 1.5407730280 | ✓ (rounding) |
| AR(1) 1.737 | 1.737 | 1.7368471948 | ✓ (rounding) |
| WHAR_db4 1.801 | 1.801 | 1.8010784357 | ✓ (rounding) |
| WHAR_haar 50.19 | 50.19 | 50.1935593434 | ✓ (rounding) |
| WHAR_HAR_db4 474.48 | 474.48 | 474.4839100821 | ✓ (rounding) |
| GJR R²_OOS 0.255 | 0.255 | 0.25514166 | ✓ |
| GJR MZ_R² 0.282 | 0.282 | 0.28236148 | ✓ |
| GJR Corr 0.531 | 0.531 | 0.53137697 | ✓ |
| HAR vs AR(1) DM (implicit) | — | t=-3.30, p=0.00098 | matches README; passes Harvey-3σ |
| HAR vs WHAR_db4 DM | t≈5.98 | (README only; not in JSON `dm_tests`) | Nit #6 |
| GJR vs AR(1) DM (implicit "冠軍" claim) | — | t=-2.65, p=0.0081 | **Below Harvey-3σ** — Major #1 |
| IS t-stats D1-A5 | 1.14/4.11/-3.16/3.30/7.86/-2.49 | 1.1379/4.1137/-3.1574/3.2995/7.8571/-2.4908 | ✓ (rounding) |
| IS R² 0.126 | 0.126 | (not in JSON; in README only) | Minor #4 |

## Lookahead audit

- `np.random.seed(42)` at module top ✓.
- `signal.shift(1)` applied to **all** predictors (r2, r2_5, r2_22, w_D1-A5, haar_D1-A5) before OLS — py L178-184.
- Wavelet rolling window: `segment = values[t-window:t]` (strictly before t), then `.shift(1)` re-applied — double protection.
- `target = r2.shift(-1)` shifts target forward, so the (t-1 features, t target) alignment is correctly: predict next-day r² using yesterday's information. **No lookahead**.
- `rolling_oos_forecast` uses `df.index < date` for training — expanding window, no leak.

## Cross-K refs

K973 (Hurst rough vol NULL), K986 (LASSO/Ridge HAR NULL), K188/K744 (GARCH ceiling), K953 (HAR-RV 34-day pilot) — all 5 dirs exist under `experiments/`. K-id formatting consistent.

## Conclusion strength

NULL result cleanly stated; no over-claim of wavelet utility. Caveats around daily r² proxy / intraday RV applicability appropriate.

## Recommendations (CONDITIONAL_PASS → close after)

1. (Major #1) Temper GJR-GARCH significance language: add explicit "point-estimate winner; not Harvey-3σ distinguishable from AR(1)" qualifier.
2. (Major #2) Add 1-line caveat on QLIKE 474.48 as numerical-artifact flag.
3. (Minor #3) Footnote: OOS rows 1,824 vs forecasts 1,823 (target shift).
4. (Minor #4) Persist `wavelet_is_r2` to results JSON for reproducibility.
5. (Minor #5) Add 1-line methodology note about absence of MT adjustment + main HAR-vs-WHAR DM survives any reasonable correction.
6. (Nit #6) Persist HAR-vs-WHAR DM to JSON.

Items 1-3 are content edits to the article; 4 & 6 are script/JSON edits. Suggested follow-up: queue a `mile_ec876702_v2` content patch + a `k981_v2` JSON refresh in next_tasks.

## Primary-path Codex re-verify

Per K1259 lesson: subagent fallback PASS ≠ Codex primary PASS. **Queue Codex primary re-verify task post-2026-05-13** when quota resets, to confirm no residual issues outside Gemini's scan.
