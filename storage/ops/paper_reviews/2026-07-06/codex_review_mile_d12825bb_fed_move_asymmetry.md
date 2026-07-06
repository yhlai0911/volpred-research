# Codex 24h Review - mile_d12825bb / trending_2026_07_06_fed_move_asymmetry

- **Article**: `mile_d12825bb` — 同樣動一碼，債市只怕利率往上：MOVE 指數藏了一個方向感
- **Task**: `paper_review_mile_d12825bb`
- **Experiment**: `experiments/trending_2026_07_06_fed_move_asymmetry/`
- **Review timestamp**: 2026-07-06 23:22 Asia/Taipei
- **Verdict**: **CONDITIONAL PASS AFTER CORRECTION**

## Scope

Checked the published article and source experiment against:

- `storage/drafts/trending_2026_07_06_fed_move_asymmetry.md`
- `storage/reports/feed.json` entry `mile_d12825bb`
- `storage/reports/mile_d12825bb.json`
- `experiments/trending_2026_07_06_fed_move_asymmetry/README.md`
- `experiments/trending_2026_07_06_fed_move_asymmetry/asymmetry.py`
- `experiments/trending_2026_07_06_fed_move_asymmetry/results.json`
- `experiments/trending_2026_07_06_fed_move_asymmetry/lazypack/render_lazypack.py`
- `experiments/trending_2026_07_06_fed_move_asymmetry/lazypack_plan.json`

## Findings

1. **Lookahead / timing: PASS.**
   - The experiment is explicitly contemporaneous, not predictive. It conditions same-day MOVE percent change on same-day 10Y yield direction.
   - The article states this clearly: "這是同一天內的對照，不是預測" and "不是一套進出場訊號".
   - No lagged trading strategy, forecast regression, DM test, or Harvey comparison is claimed.

2. **Main statistical conclusion: PASS.**
   - The core descriptive asymmetry is supported by results: yield-up MOVE mean `+0.5103%`, yield-down mean `-0.2798%`, difference `+0.79pp`, Welch `t=5.522`, `p=3.562e-08`, bootstrap 95% CI `[0.5014, 1.0701]`.
   - Article claims for sample period, N=4065, up/down day counts, latest MOVE/TNX, and recent 90-day conditional means match `results.json`.

3. **Magnitude-control unit bug: FAIL before correction, PASS after correction.**
   - Original code treated `^TNX` as "yield x10" and used `df["TNX"].diff() * 10.0` as bp.
   - yfinance currently returns `^TNX` in yield-percent units, e.g. `4.485` for 4.485%, so bp conversion must be `diff() * 100.0`.
   - The old article's absolute slope claims `4.01%/bp` and `2.74%/bp` were overstated by 10x. The ratio `1.465` and sign comparison were unchanged because both slopes scaled equally.

4. **Overclaim: PASS after correction, with scope caveat.**
   - The article does not claim forecast alpha or DM/Harvey superiority.
   - "不是雜訊" is acceptable for the mean-difference test, but should be read as "the contemporaneous conditional mean difference is statistically distinguishable from zero", not as causal proof.
   - The "higher-for-longer" explanation remains an economic interpretation, not directly identified causal evidence.

## Corrections Applied

- Fixed `asymmetry.py`: `^TNX` documented as yield-percent units and bp conversion changed to `diff() * 100.0`.
- Reran the experiment and regenerated:
  - `results.json`
  - `fig_slope_asymmetry.png`
  - `lazypack/2_panel.png`
- Updated README and lazypack plan:
  - Slope values now `0.401%/bp` and `0.274%/bp`.
  - Yield semivariance now correctly reported as `60,396 bp²` vs `58,182 bp²`, ratio `1.038`.
- Updated the public article through `scripts/publish_draft.py --update`:
  - Article text now says `0.40%` and `0.27%`.
  - Removed the misleading absolute semivariance `604 / 582` prose and kept the robust ratio `1.04`.
  - Added errata metadata with `update_action=codex_review_fix`.
- Synced the single article to Supabase using the canonical `sync_article()` helper and read back the row:
  - remote `status=published`
  - remote content contains `0.40%`
  - remote content no longer contains `4.01%`

## Recommendation

Keep the corrected article live. The main result is a same-day descriptive asymmetry in MOVE reactions to yield direction, not a forecast or trading signal. Future edits should avoid describing the higher-for-longer mechanism as identified causality unless a separate design tests it.
