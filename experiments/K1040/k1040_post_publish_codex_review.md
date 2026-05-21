# K1040 Post-Publish Review — mile_b4774629

**Article**: 經典論文搬到 OOS 會崩嗎？我們驗了 Bollerslev (2009)：能預測月報酬的不是 VRP，是 VIX 本身
**Article ID**: `mile_b4774629`
**Published (feed.json)**: 2026-05-10 12:09 UTC (status: draft)
**Review date**: 2026-05-11
**Reviewer source**: **Gemini CLI fallback** (Codex CLI primary path blocked by usage quota until 2026-05-12 19:46; Codex CLI `0.121.0` operational but `ChatGPT account` daily limit hit)
**Verdict**: **PASS**

Per `.claude/rules/agent-delegation.md` (K1018 2026-05-02 lesson), production articles require source-code-level review within 24h of publish. Codex primary path attempted first (see Bash log session `019e13ef-8571-7f43-87fa-866a1898a385`), returned `ERROR: You've hit your usage limit. ... try again at May 12th, 2026 7:46 PM`. Per `.claude/rules/experiments.md` Codex-fallback hierarchy, fell back to second-opinion reviewer; subagent dispatch tool not surfaced in this session so used `gemini-cli` (per `feedback_gemini_cli_share_load` quota-sharing policy). **This closure is NOT primary-path Codex PASS**; per K1259 2026-04-29 lesson, a primary-path Codex re-verification should be done within 48h once quota resets.

---

## 1. Byte-Accuracy (PASS)

All numeric claims in the article match `k1040_results.json` byte-for-byte (after rounding to display precision):

| Claim | Article | JSON | Match |
|---|---|---|---|
| h=22d VRP-only OOS R² | +0.77% | 0.007727 | ✓ |
| h=22d g_t-only OOS R² | +0.87% | 0.008699 | ✓ |
| h=22d VIX-only OOS R² | +5.63% | 0.056296 | ✓ |
| h=22d g_t+VRP OOS R² | +0.88% | 0.008759 | ✓ |
| h=22d Kitchen Sink OOS R² | +5.27% | 0.052749 | ✓ |
| h=22d VIX-only CW p-value | 0.021 | 0.02148 | ✓ |
| h=22d Kitchen CW p-value | 0.056 | 0.05586 | ✓ |
| h=1d LS Sharpe | -0.118 | -0.11825 | ✓ |
| h=5d LS Sharpe | -0.001 | -0.00109 | ✓ |
| h=22d LS Sharpe | -0.074 | -0.07446 | ✓ |
| BH Sharpe h=1d/5d/22d | 0.711/0.769/0.759 | 0.71085/0.76942/0.75945 | ✓ |
| h=22d VRP IS HAC t | +2.77 | 2.7739 | ✓ |
| h=5d VRP IS HAC t | +3.46 | 3.4631 | ✓ |

Pre-emptive check by main thread confirmed; Gemini independently re-verified.

## 2. Lookahead Audit (PASS — HIGHEST PRIORITY)

- **Target**: `fwd_ret_h = log_ret.rolling(h).sum().shift(-h)` (k1040.py L211). At index `t`, value = sum(r_{t+1..t+h}). Strictly forward.
- **Predictor**: gt_now / vrp_now / vix_now read at index `t` (L334-337). Observed at close of day t.
- **Training window**: `train_end = t` (exclusive, L347) → β_t fitted on indices [t-WINDOW, t-1]. The future return y_t is never seen by the regression coefficient estimation.
- **g_t precomputation refit**: A4f parameters refitted every 63 days using `all_ret[train_start:t+1]` which includes r_t. The recursion produces g_t which is the GARCH variance term using returns up to t-1 only (g[t] formula at L122 uses returns[t-1]). Parameter contamination at refit boundary is mild and acceptable for a 21-year rolling experiment.
- **Long-short loop** (L516-525): uses expanding-window median of g_ls[:i_e] and g_ls[i_e-1] for position at time i_e, earning f_ls[i_e] = sum of r_{i_e+1..i_e+h}. Lag-1 properly applied.

**Narrative wording**: Article says "用 t-1 訊號預測 t→t+h 報酬". Code uses X_t to predict r_{t+1..t+h}. These are functionally equivalent (X_t observed at close of t, target starts from t+1) but Gemini recommends clarifying the wording for precision.

## 3. Statistical Overclaim Check (PASS with minor caveat)

- **Multiple testing**: Article does not apply Bonferroni/FDR across the 15 tests (5 models × 3 horizons). The single VIX-only h=22d p=0.021 would become marginal under Bonferroni (p_adj ≈ 0.32). However, the article's main thesis is the **null** for g_t/VRP, which is a conservative position. Harvey-Liu-Zhu (2016) t>3.0 threshold not invoked; CW stat for VIX-only h=22d is +2.02, below HLZ bar.
- **CW vs DM**: Article quotes CW only. DM for VIX-only h=22d = +1.29 (p=0.198, not significant). CW is the **correct** test for nested models per Clark & West (2007) — DM is known to be undersized when comparing nested forecasts vs the unconditional mean. Methodologically defensible, not cherry-picking.
- **Sharpe annualization**: `ann = 252/h` for h=22 → 11.45. Both LS and BH use the same scaling so comparison is internally consistent. Absolute magnitudes are unconventional for an overlapping-h-day daily-stepped strategy but the article's "輸給 buy-and-hold" qualitative conclusion is robust to scaling choice.

## 4. Methodology Consistency (PASS)

- HAC NW lag = `max(h-1, 1)` (k1040.py L489): 21 lags at h=22, 4 at h=5. Standard for overlapping-h returns.
- IS HAC t-stat at h=5d VRP = +3.46 verified from JSON `results_by_horizon["5"].models.in_sample.hac_t_stats.VRP = 3.4631`.
- OOS sample size: article claims "1,805 天"; JSON `n_valid = 1805` for all three horizons.
- K1098/K1116 references in article's "VIX 充分性家族" — these K-ids exist in the broader knowledge base but are not enumerated in K1040 README. Acceptable narrative scaffolding; not a misattribution.

## 5. Chart Attribution (CONDITIONAL)

- `k1040_oos_r2_direction.png`: ✓ generated by k1040.py L644 (in repo at `experiments/k1040/`, also on Supabase 200 OK).
- `k1040_longshort_vs_bh.png`: ✓ accessible on Supabase 200 OK, but **NOT** generated by k1040.py — only the long_short Sharpe scalars are in the JSON; the chart was synthesized outside the experiment script.

**Reproducibility impact**: Reader running k1040.py cannot regenerate the longshort chart. Data (3 LS Sharpe + 3 BH Sharpe) is in JSON so the chart is data-recoverable, but not script-recoverable. Minor provenance gap.

## Recommended Actions

1. **(LOW)** Append a chart-generation block to `k1040.py` that produces `k1040_longshort_vs_bh.png` from the long_short results dict, closing the reproducibility gap.
2. **(LOW)** Add a one-line footnote acknowledging the single-test significance level for VIX-only CW p=0.021 (not Bonferroni-corrected).
3. **(OPTIONAL)** Tighten Section 三 lag wording: "X_t (predictors observed at close of day t) → r_{t+1..t+h}" instead of "t-1 信號 → t→t+h 報酬".
4. **(REQUIRED for closure)** Re-run Codex primary-path review after quota resets (2026-05-12 19:46+) to confirm Gemini PASS finding. K1259 lesson: subagent/secondary-reviewer PASS ≠ primary Codex PASS; possible blind spots not yet ruled out.

## Verdict Summary

**Gemini PASS** — article is byte-accurate, lookahead-free, methodologically defensible, with no MAJORs. Three LOW-priority improvements recommended. **Pending primary-path Codex re-verification within 48h** for full closure.

---

## Audit Trail

- Codex CLI invocation attempt: session `019e13ef-8571-7f43-87fa-866a1898a385`, prompt at `/tmp/k1040_codex_prompt.txt`, blocked by usage limit.
- Gemini CLI invocation: `gemini --prompt "$(cat /tmp/k1040_codex_prompt.txt)"` — cached creds, no quota issue.
- Source files reviewed by Gemini: `experiments/k1040/{k1040.py, k1040_results.json, README.md}`.
- Main thread independently verified byte-accuracy table prior to Gemini dispatch.
