# Codex Review: `mile_2fb1dfb3` / K740

- Date: 2026-06-13
- Reviewer: Codex
- Task: `paper_review_mile_2fb1dfb3`
- Verdict: PASS after local corrections; remote chart re-upload pending network access

## Scope

Reviewed the published article "投資策略是不是越複雜越厲害？我們把 14 套方法排在一起，答案有點反直覺" against:

- `storage/drafts/k740_general_draft.md`
- `storage/reports/feed.json`
- `storage/reports/mile_2fb1dfb3.json`
- `experiments/k740/k740_strategy_meta_analysis.py`
- `experiments/k740/k740_strategy_meta_analysis_results.json`
- `storage/paper_trading.json`
- `storage/strategy_metrics.json`

## Findings

1. Reproducibility path bug: the script used `Path(__file__).resolve().parent.parent` as `BASE`, so `STORAGE` resolved to `experiments/storage`, not repo-root `storage`. Running the script from the repo failed before loading data.

2. Floating live-data window: the article cites 2023-01-04 to 2026-03-27, but the script did not filter `paper_trading.json` by that fixed window. Because paper-trading history is append-only, later rows changed the regenerated numbers.

3. Published numeric drift / math error: the article stated SPY-only average 1.176 and SPY+GLD average 2.546 but said the gap was 0.826. The corrected fixed-window values are 1.173 and 2.544, gap 1.371. The 0.826 value came from a different grouping concept in the older results.

4. Result overclaim: the old result text said VIX-based signals outperformed momentum/hybrid even though its own numbers had VIX below the comparison group. The script now states the weaker, supported interpretation.

5. Experiment README was a placeholder with `Status: planning`, so the experiment was not self-documenting despite being used for a published article.

6. Published article failed the anti-ai-style validator due repeated `不是...而是` phrasing.

## Corrections Made

- Fixed K740 script root paths and result path.
- Pinned `COMMON_START = "2023-01-04"` and `COMMON_END = "2026-03-27"`.
- Added deterministic chart generation for:
  - `experiments/k740/k740_top_strategy_ranking.png`
  - `experiments/k740/k740_complexity_vs_sharpe.png`
  - mirrored local copies under `storage/reports/assets/`
- Regenerated `k740_strategy_meta_analysis_results.json` from the fixed script.
- Replaced placeholder README with data source, method, results, limitations, and review notes.
- Updated the published local article via `scripts/publish_draft.py --update`:
  - composite score 0.790
  - SPY-only Sharpe 1.173
  - SPY+GLD Sharpe 2.544
  - SPY-only vs SPY+GLD gap 1.371
  - complexity rho 0.294, p = 0.308
  - monthly/daily Sharpe 2.339 vs 2.213
- Replaced stale full-content description with a short corrected summary.
- Removed anti-ai-style false-philosophy phrasing from the article body.

## Verification

- `.venv/bin/python experiments/k740/k740_strategy_meta_analysis.py` completes successfully.
- `storage/reports/feed.json` and `storage/reports/mile_2fb1dfb3.json` contain the corrected numbers and matching content.
- `scripts/validate_anti_ai_style.py --recent 20 --json` no longer flags `mile_2fb1dfb3`.

## Remaining Limitation

The sandbox cannot resolve `qxhfgdfzazwpkdgesavm.supabase.co`, so `publish_draft.py` could not re-upload the regenerated PNGs to Supabase storage. Local chart assets are updated, but the remote public image objects need a later network-enabled sync/upload.
