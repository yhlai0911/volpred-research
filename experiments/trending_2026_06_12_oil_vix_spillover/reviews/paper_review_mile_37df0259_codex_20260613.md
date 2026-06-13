# Codex Post-Publish Review: mile_37df0259

- Article: `mile_37df0259`
- Title: 中東風險還在，OVX/VIX 卻從 4.17 降到 2.90：油市恐慌怎麼外溢？
- Task: `paper_review_mile_37df0259`
- Reviewer: Codex hourly
- Review date: 2026-06-13
- Evidence package: `experiments/trending_2026_06_12_oil_vix_spillover/`

## Verdict

PASS after one numeric table correction.

The headline, sample window, latest market levels, percentile claims, 5/20-to-6/11 changes, and qualitative conclusion match the experiment outputs. The article does not make a trading backtest claim, does not use same-day signal returns, and does not overstate formal DM/Harvey inference; it explicitly frames the exercise as a descriptive spillover diagnostic.

## Correction Applied

The 20-day lead-lag row in the article mixed result fields:

- `OVX_t -> VIX_t+1` was written as `-0.15`, but `trending_2026_06_12_oil_vix_spillover_results.json` reports `0.0008929808`, which rounds to `0.00`.
- `WTI_t -> SPY_t+1` was written as `0.08`, but the 20-day result is `0.0996045590`, which rounds to `0.10`.

Updated `storage/drafts/trending_oil_vix_spillover_2026_06_12.md` and republished locally via:

```bash
MPLCONFIGDIR=/tmp/matplotlib-volpred .venv/bin/python scripts/publish_draft.py storage/drafts/trending_oil_vix_spillover_2026_06_12.md --update mile_37df0259 --update-action codex_review_fix --update-summary 'Codex review found the 20-day lead-lag row used the wrong result fields. Corrected OVX_t to VIX_t+1 from -0.15 to 0.00 and WTI_t to SPY_t+1 from 0.08 to 0.10; headline, sample, and main conclusions remain unchanged.'
```

The first update attempt failed because the sandbox has no DNS access and the draft still contained relative image paths, causing the publisher to try a Supabase image upload. The successful retry used the existing public Supabase image URLs already present in the article.

## Checked Claims

- Latest common date: 2026-06-11.
- Sample: 2007-07-30 to 2026-06-11, `common_days=4693`.
- Latest values match JSON: OVX 56.30, VIX 19.44, OVX/VIX 2.90, WTI 86.86, Brent 89.45, SPY 737.76.
- Percentiles match JSON: OVX P91, VIX P60, OVX/VIX P90, WTI P71, Brent P69.
- Since 2026-05-20 changes match JSON: OVX -22.63%, VIX +11.47%, ratio -30.59%, WTI -11.60%, Brent -14.83%, SPY -0.47%.
- 5-day changes match JSON: OVX -5.84%, VIX +26.23%, WTI -6.64%, Brent -5.87%.
- Same-day correlations match JSON: 20/60/120/252-day OVX-VIX = 0.10/0.40/0.39/0.39; WTI-VIX = 0.09/0.33/0.33/0.24.
- Corrected next-day correlations match JSON: 20/60/120/252-day OVX-to-next-VIX = 0.00/-0.08/-0.00/-0.05; WTI-to-next-SPY = 0.10/0.08/0.01/0.02.

## Residual Notes

- Supabase feed sync was not run from this sandbox because network/DNS is unavailable. The local feed and single-report JSON were updated.
- The analysis remains descriptive. It should not be reused as causal evidence or as a standalone trading rule without a formal event-study or predictive-regression design.
