# K989 Post-Publish Review — mile_ecb736a6

**Article**: 兩個各有 +9.5% 的好點子加在一起，會變 +19% 嗎？我們做了實驗，答案出乎意料
**Article ID**: `mile_ecb736a6`
**Published**: 2026-05-09T17:43:41+00:00 (status=draft)
**Review date**: 2026-05-11
**Review trigger**: 24h post-publish audit (agent-delegation.md 2026-05-02 K1018 rule)
**Reviewer source**: Gemini CLI 0.33.1 (Codex primary unavailable; quota resets 2026-05-12 19:46 PT)
**Verdict**: **PASS**

---

## Reviewer-source disclosure

Codex primary path attempted; CLI returned:
> ERROR: You've hit your usage limit. Upgrade to Pro ... or try again at May 12th, 2026 7:46 PM.

Per `.claude/rules/experiments.md` fallback ladder, escalated to (a) main-thread fresh-context audit + (b) Gemini CLI as second-opinion subagent. K1259 lesson applies: **subagent fallback PASS ≠ primary-path Codex PASS** — Codex primary re-verification queued post-2026-05-13.

## Audit dimensions

### 1. Byte-accuracy (article ↔ `k989_mf2_vix2_results.json`)

| Article claim | Source field | Match |
|---|---|---|
| MF2-Piecewise QLIKE 0.8486, +9.54% | `evaluation.MF2-Piecewise.QLIKE = 0.8485873...`, `improvements_vs_gjr_pct.MF2-Piecewise = 9.5369...` | ✓ |
| MF2-VIX QLIKE 0.8487, +9.52% | 0.8487047..., 9.5244... | ✓ |
| MF2-VIX² QLIKE 0.8549, +8.86% | 0.854927..., 8.8611... | ✓ |
| GJR-X QLIKE 0.8751, +6.71% | 0.8750628..., 6.7145... | ✓ |
| MF2-Poly QLIKE 0.8923, +4.87% | 0.8923385..., 4.8729... | ✓ |
| GJR baseline 0.9380 | 0.9380483... | ✓ |
| Piecewise δ = 0.001 | `tau_calibration.MF2-Piecewise.delta = 0.001` | ✓ |
| MF2-Poly OOS R² = −0.99 | `evaluation.MF2-Poly.OOS_R2 = -0.9862` | ✓ |
| MF2-VIX² OOS R² = −0.82 | `evaluation.MF2-VIX2.OOS_R2 = -0.8166` | ✓ |
| Sample 5,093 / IS 3,269 / OOS 1,824 | `sample_sizes` | ✓ |
| IS 2006-2018, OOS 2019-2026 | `IS_period`, `OOS_period` (2026-04-06 end) | ✓ |
| Seed 42 | `seed: 42` | ✓ |
| K987 VIX² OOS R² 0.258 vs 0.202 linear | K987 (cited; not in this JSON, taken from K987 result) | ✓ (external cite) |

**No byte-level discrepancies found.**

### 2. Lookahead audit

`experiments/k989/k989_mf2_vix2.py`:
- Line 62: `spy['ret'] = np.log(spy['Close'] / spy['Close'].shift(1)) * 100` (return alignment OK)
- Line 88: `spy['tau_vix'] = ((vix_close / np.sqrt(252)) ** 2).shift(1)` (tau uses t-1 VIX) ✓
- Line 93: `vix_shifted = vix_close.shift(1)` (universal t-1 signal) ✓

All VIX-derived predictors are lagged. **PASS lookahead gate.**

### 3. Additivity claim audit (headline thesis)

Headline: "two ideas each +9.5% combined ≠ +19%; in fact = +9.5%."

**Mathematical decomposition**:
- "Idea 1" (K970): tau = (VIX/√252)² as long-run component → +9.5% QLIKE improvement
- "Idea 2" (K987): VIX² has nonlinear/convex predictive power (OOS R² 0.258 > linear 0.202)
- Article's claim: "Idea 2" is **mathematically identical** to "Idea 1" — both are the **same squared-VIX convex transformation**

This is **logically sound and rigorous**:
- K970's tau = (VIX/√252)² IS the squared VIX (scaled by 252)
- K987's "VIX² convexity" is the descriptive finding that VIX² beats VIX-linear
- Both findings reflect a single underlying nonlinearity. The +9.5%↔+9.5% redundancy is a **factual identity**, not a coincidence.
- Empirical confirmation: Piecewise δ optimal = 0.001 (essentially zero residual signal after K970 baseline absorbs convexity)

**The +19% naive expectation is explicitly framed as the reader's intuitive (wrong) prior** — pedagogically honest, not a strawman.

**Additivity audit: PASS.**

### 4. DM / Harvey threshold compliance

Article claim: "兩者差異在嚴謹的學術顯著性檢驗下，遠遠談不上有意義" + "no VIX² variant significantly beats MF2-VIX (all |t| < 3.0)"

Ground truth DM tests:
- MF2-VIX vs MF2-Piecewise: t=0.815, p=0.415 → clear null ✓
- MF2-VIX vs MF2-VIX²: t=-2.265, p=0.024 → fails Harvey |t|≥3.0 ✓
- MF2-VIX vs MF2-Poly: t=-3.783 → significant (Poly worse) — correctly reported ✓
- MF2-VIX vs GJR-X: t=-4.449 → significant (GJR-X worse) — correctly reported ✓

**Harvey (2016) |t|≥3.0 threshold correctly applied.** Article does not overclaim Piecewise's nominal +0.01% lead.

### 5. Cost-model framing audit

The brief mentions "v2 errata 已修 round-trip semantic" — but this is a **forecasting comparison (QLIKE)**, not a portfolio strategy. No trading-cost, round-trip, or P&L claims appear in the article. The cost-model errata pattern (K1018 systemic issue) is **N/A** to mile_ecb736a6.

(Cross-check: `mile_9b327220` "K1020 資訊重疊" published 2026-05-10 is a separate article about a different K — not a K989 v2 errata.)

### 6. Research-integrity tone

- Null result honestly reported (Mission Goal 2: 把實驗與研究做好)
- Explicitly rejects "+0.01% Piecewise winner" framing
- Acknowledges K987 VIX² convexity is **descriptive** not **additive predictive power**
- Future-work section properly redirects to short-run component (g_t)
- Citation provenance complete: K970/K987/K986 in `details.experiment_refs`, code path in 研究背景說明

**Tone: aligned with 研究誠實原則.**

## Verdict: PASS

No required fixes. Article is publication-ready (status currently `draft`; release_pool cron will surface it per non-time-sensitive schedule).

## Caveats / follow-ups

1. **Primary-path Codex re-verify queued** for post-2026-05-13 (quota reset). If Codex primary returns FAIL or CONDITIONAL on any dimension subagent missed, this entry will be **retracted** per K1259 lesson.
2. Audit methodology was full-population walk (all 6 model rows × all numerical claims), not subset (K1259 v2 lesson applied).
3. Subagent fallback verdict is **provisional**; canonical closure requires Codex primary PASS.
