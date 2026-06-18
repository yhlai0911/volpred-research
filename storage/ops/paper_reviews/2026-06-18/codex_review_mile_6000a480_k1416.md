# Codex Source-Code Review - mile_6000a480 / K1416

- **Article**: 五個不同起點都過關，這個跨市場模型不是剛好猜中一次
- **Task**: `paper_review_mile_6000a480`
- **Experiment**: `experiments/k1416/`
- **Review timestamp**: 2026-06-18 18:01 Asia/Taipei
- **Verdict**: **CONDITIONAL PASS AFTER CORRECTION**

## Scope

This review checked the production article against:

- `storage/reports/feed.json`
- `storage/reports/mile_6000a480.json`
- `storage/drafts/k1416_general_draft.md`
- `experiments/k1416/README.md`
- `experiments/k1416/k1416.py`
- `experiments/k1416/k1416_results.json`
- `experiments/k1412/README.md`
- `experiments/k1412/k1412.py`
- `experiments/k1412/k1412_results.json`
- `experiments/paper3_E2_cross_market_copula/paper3_E2.py`
- `experiments/paper3_E2_cross_market_copula/paper3_E2_results.json`

## Findings

1. **The K1416 numeric claims match the source results.**
   - OOS starts `2014-01-02`, `2015-06-01`, `2016-01-04`, `2017-01-03`, `2018-01-02` have HLN-adjusted statistics `3.2402`, `3.8915`, `3.6607`, `3.0442`, `3.0929`.
   - The corresponding 5% critical values are about `1.9610` to `1.9615`.
   - Margins above the 5% cutoff are `1.2793`, `1.9304`, `1.6995`, `1.0829`, `1.1314`.
   - All five runs are also marked significant at 1% in `k1416_results.json`.

2. **No lookahead issue found in the referenced Paper 3 forecast loop.**
   - `oos_forecast_pair()` trains on `ret[s:t]` / `x[s:t]`.
   - The one-step forecast for time `t` uses lagged inputs `ret[t-1]` and `x[t-1]`.
   - The realized target is aligned to `port_ret[oos_idx:]`.

3. **The article's overlapping-window caveat is appropriate.**
   - K1416 is a start-date sensitivity grid, not five independent OOS replications.
   - The article explicitly says the five OOS windows overlap and should be read as pressure tests of the same finding.

4. **One public wording claim was too strong and has been corrected.**
   - The original article described `TW0050-N225` as the only Paper 3 Harvey-significant pair.
   - The current `paper3_E2_results.json` has two Student-t vs DCC Harvey-significant pairs: `TW0050-N225` and `TW0050-HSI`.
   - `TW0050-N225` remains the stronger pair (`t=3.92296`, `p=0.0000903`) versus `TW0050-HSI` (`t=2.07855`, `p=0.03778`), so the corrected public framing is "strongest / most visible pair", not "only significant pair".

## Actions Taken

- Updated `storage/drafts/k1416_general_draft.md` to remove the "only significant pair" framing.
- Updated production article `mile_6000a480` through `scripts/publish_draft.py --update`, including content, description, errata audit trail, and `details.cluster_waiver`.
- Extended `scripts/publish_draft.py --update` so future rewrites can refresh `details.cluster_waiver` and `details.dup_waiver` through the formal publisher entrypoint.
- Added a regression test for update-mode waiver metadata refresh.
- Rebuilt `storage/reports/INDEX.md` and `storage/reports/index.json`.
- Synced `mile_6000a480` to Supabase and read back the row; remote status is `published`, the cluster waiver now says "strongest Paper 3 TW0050-N225 pair", and the corrected content no longer contains the bad unique-pair wording.

## Recommendation

The corrected article is acceptable. Keep the claim scoped to K1416's start-date sensitivity evidence for the strongest Paper 3 `TW0050-N225` case, and do not describe it as the only significant cross-market pair while the current Paper 3 results also mark `TW0050-HSI` significant.
