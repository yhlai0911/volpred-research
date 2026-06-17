# Codex 24h Review: mile_9fdad80e / K1459

Date: 2026-06-17
Reviewer: codex-cli
Article: `mile_9fdad80e` - "為什麼龐氏一定會崩？問題不在道德，先在數學"
Experiment: `experiments/k1459_ponzi_collapse_math/`

## Verdict

CONDITIONAL_PASS_WITH_PATCH

The article's reported formulas, scenario numbers, and figure references are traceable to K1459 source/results. No fabricated numeric claim found. Two wording issues could overstate the model-to-world mapping; both were patched before approving the article to remain live.

## Findings

1. Numeric formula claims match source. The article's core cash-flow identity `new money = (r + w) * active` is implemented in `flat_new_entrant_requirement` (`k1459_ponzi_collapse_math.py:31-32`), and the flat-reserve active base grows as `N0 * (1+r)^t` (`k1459_ponzi_collapse_math.py:35-37`).

2. Scenario and historical-scale numbers match results. K1459 uses fixed `SEED = 42`, `ROUND_HORIZON = 120`, `MC_REPS = 400` (`k1459_ponzi_collapse_math.py:16-18`). The rerun reproduced: aggressive 10% scenario deterministic collapse round 17 and Monte Carlo collapse probability 1.0; Madoff-scale monthly needs of USD 175M / 525M / 1.05B; Charles Ponzi 50% round-10 entrants 1,922.17 and cumulative participants 5,766.50.

3. Methodological caveat: "Ponzi always collapses" is true only after adding finite-market / no-infinite-recruitment realism. The model itself explicitly states the asymptotic condition `g > r` (`k1459_ponzi_collapse_math.py:269-273`) and includes a stable scenario with entrant growth above promised return (`k1459_ponzi_collapse_math.py:280-282`). The article now says `g > r` survives in the model but cannot persist as infinite high-speed recruitment in reality (`article_draft.md:24-28`).

4. Madoff-scale wording needed precision. The code hard-codes `outstanding_capital = 17.5e9` as an illustrative scale for the cash-flow formula (`k1459_ponzi_collapse_math.py:166-178`); it is not a forensic reconstruction of monthly outstanding capital. The article now frames it as "用 175 億美元這種規模做示意" (`article_draft.md:42-43`).

5. No lookahead concern applies. This is an analytical/simulation experiment, not a time-series forecast or trading signal. There is no same-day classification, rolling signal, or return target alignment issue.

## Article-Level Corrections Applied

- `storage/drafts/k1459_ponzi_collapse_general_draft.md`: clarified `g > r` as model survival with real-world finite-recruitment caveat; changed Madoff line to illustrative-scale wording.
- `experiments/k1459_ponzi_collapse_math/article_draft.md`: same corrections.
- `storage/reports/feed.json`: patched the published article body for `mile_9fdad80e` with the same two corrections.

## Approval

Approve keeping article live: YES, with the above caveat now patched. No delisting required.
