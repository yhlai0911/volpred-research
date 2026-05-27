# Codex 24h Review — mile_91af7c48

- **Article**: 從 Sharpe 2.16 到輸基準：一場 lookahead 的攔截實錄
- **Published**: 2026-05-27T13:00:40 UTC
- **Reviewer**: Codex CLI 0.132.0 (ChatGPT auth) — source-code-level audit
- **Review run**: hourly-22 task `paper_review_mile_91af7c48`
- **Verdict**: **FAIL** (multiple SEVERE discrepancies between article claims and committed K562/K560 artifacts)

## Top findings

1. **SEVERE — algorithm description vs source**
   Article (lines 53–89) shows "錯誤寫法" using `sec_mom_arr[t][i]` and "修正後" using `sec_mom_arr[t][prev]`. Current source `experiments/k562/k562_k560_sector_validation.py:222,231,238` uses same-day `[i]` only — *not* the patched `[i-1]` version. K560 source `experiments/k560/k560_sector_rotation_vt.py:250,260` likewise has no patch.

2. **SEVERE — headline numbers not in artifacts**
   `0.7247` (strategy Sharpe after fix) and `0.9359` (benchmark) appear **nowhere** in `experiments/k562/*.json` or `experiments/k560/*.json`. Canonical values currently committed:
   - `k562_..._results.json::baseline_replication.daily_sharpe = 2.1566`
   - `benchmark_sharpe = 1.3444`
   - K560 `momentum_top1.sharpe = 2.1571`

3. **SEVERE — validation table mismatch**
   Article (lines 105–115): 1/8 pass, bootstrap p_win=1.2%.
   Current K562 `final_summary.pass_count = 6/8`, `v1_harvey_pass = true`, `v7_bootstrap.daily.p_win = 1.0` (100%), monthly `p_win = 0.1036`. Verdict in artifact: `CONDITIONALLY RECOMMENDED (daily rebalancing only — high TX cost risk)`.

4. **MAJOR — verdict overclaim direction**
   Article framing "100% 來自 bug" / "輸給基準" / null result, vs artifact verdict "CONDITIONALLY RECOMMENDED". The article's null-result framing is *not* supported by what is currently committed.

5. **MAJOR — K560 patch claim in 後記**
   Article (lines 150–156) claims K560 patched 2026-05-06 with `sig_idx = i-1` and "9 條策略 Sharpe 下跌 1.4-2.9 倍, Harvey 全部 FAIL". K560 source has no such patch and results still show multiple Harvey PASS rows.

## Root-cause analysis (cross-checked vs docs/error_log.md)

`docs/error_log.md` 2026-05-06 entry confirms the article's numbers are *real*: a lag-fix patch + rerun was performed (Sharpe 2.16 → 0.7247, benchmark 0.9359, 1/8 pass, bootstrap p_win=1.2%, VERDICT NOT RECOMMENDED FOR LISTING). The entry documents the exact patch location (`line 222 + 230`) and the rerun outcome.

**However the patched code + rerun results were never committed.** `git log -G"prev = i" -- experiments/k562/` returns nothing, and current `results.json` retains the pre-patch (Sharpe 2.16) numbers. The article therefore cites lag-fixed values that no longer have a reproducible artifact pair in repo.

This is a **research-honesty boundary case**:
- Article claim is *historically correct* (documented in error_log)
- Article claim is *currently unverifiable* against committed K562/K560 source/results
- CLAUDE.md §2 (`實驗三件套`) requires source + results.json + README per experiment; current state violates this for the lag-fixed version

## Decision

- **Do NOT unpublish**. Article narrative is factually grounded in error_log audit trail and has educational value (showcasing the lookahead BLOCK mechanism).
- **Reproduce + commit K562 lag-fixed artifacts** as follow-up. This re-anchors the article's numbers to a verifiable pair.
- **Add error_log entry** documenting this drift discovery so future audits know `2026-05-06 K562 patch was never committed`.
- **Do NOT amend article** until reproduce confirms 0.7247 / 0.9359 / 1/8 / 1.2% are reproducible; if reproduce yields different numbers, errata insert.

## Follow-up

- Task: `paper_review_followup_K562_reproduce_lag_fix` (P2, compute_queue eligible).
- Owner: subsequent hourly dispatch / compute worker.
- Done-when: `experiments/k562/k562_k560_sector_validation.py` contains `prev = i - 1` lag; `results.json` reflects Sharpe ≈ 0.7247, benchmark ≈ 0.9359, pass_count = 1/8, bootstrap daily p_win ≈ 0.012; commit lands.

## Codex transcript

Full Codex output: see `/tmp` capture in hourly-22 session log (`tokens used: 60008`). Key spans cited above. Method: `codex exec --skip-git-repo-check -s workspace-write` with structured 6-item audit checklist.
