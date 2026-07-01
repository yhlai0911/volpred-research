# Codex Review - research_transfer_learning_for_new_issues_vol

**Verdict**: PASS as a scoped null-result pilot.  
**Claim strength**: limited to daily close-to-close public-data proxy. Do not cite
as evidence against high-frequency realized-volatility transfer learning.

## Checks Performed

- `uv run python -m py_compile experiments/research_transfer_learning_for_new_issues_vol/research_transfer_learning_for_new_issues_vol.py`
- `uv run python experiments/research_transfer_learning_for_new_issues_vol/research_transfer_learning_for_new_issues_vol.py`
- `jq` inspection of verdict, panel QLIKE means, primary loss differentials, target-level sign tests, and bootstrap intervals.
- PNG non-empty and dimensions checked via `file`.

## Review Notes

1. **Lookahead protection is explicit**: feature construction uses
   `signal.shift(1)` and `rolling(...).mean().shift(1)`. Evaluation starts after
   day 60, while target training uses only day <= 60.
2. **Source selection is pre-evaluation**: selected source windows must end
   before each target's evaluation start date.
3. **No fabricated data**: prices are downloaded from yfinance with
   `auto_adjust=True` and cached as CSV; all 10 targets have real price coverage
   through 2026-07-01 in the cache.
4. **Baseline interpretation was corrected**: the primary claim is benchmarked
   against `naive_har22`, not the unstable `target_only_ridge`.
5. **Null result is reported honestly**: transfer improves over unstable
   target-only Ridge but loses to naive HAR22 on 10/10 target assets.
6. **Randomness is pinned**: target-level bootstrap uses `seed=42`, B=1000.

## Residual Risk

- Daily squared returns are noisy, so QLIKE can be dominated by isolated days.
- The source-similarity rule is a simple Euclidean proxy, not the DTW procedure
  in the 2025 paper.
- Newey-West pooled inference does not fully handle cross-target dependence.
- yfinance symbol histories for spin-offs can include listing-continuity quirks;
  the experiment records first available price dates and should be treated as a
  public-data pilot.
