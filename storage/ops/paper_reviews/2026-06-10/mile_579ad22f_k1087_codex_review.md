# Codex Review — mile_579ad22f / K1087

## Verdict

`FAIL`

## Critical bugs

1. `experiments/k1087/k1087.py:376-379, 457-463, 487-490`
   - Bug: A4f / GARCH-MIDAS-style recursion uses the **current-period** long-run component `tau_t` to standardize the **previous-period** return `r_{t-1}`.
   - Current code:
     - training filter: `u_prev = returns[t-1] / np.sqrt(tau[t])`
     - state init: `u_prev = train_ret[i-1] / np.sqrt(tau[i])`
     - OOS forecast update: `u_prev = r_prev / np.sqrt(tau_t)`
   - Why this is wrong:
     - `r_{t-1}` was generated under `tau_{t-1}`, not `tau_t`.
     - This is an off-by-one recursion error in the A4f state update, affecting **all** A4f variants (`VIX`, `MOVE`, `Level`, `Slope`, `RateVol`, `Butterfly`, `Combo`).
     - It is not classic lookahead bias, but it is a model-definition bug in the conditional variance filter.
   - Fix:
     - use previous long-run component when standardizing lagged return:
       - in training/state recursion, standardize `returns[t-1]` by `tau[t-1]`
       - in OOS update, carry `tau_prev` as state and use `r_prev / sqrt(tau_prev)`, then build `tau_t` for the next day
     - rerun K1087 before trusting any A4f-vs-GJR ranking or article narrative.

## Methodology concerns

1. `experiments/k1087/k1087.py:658-659`
   - `qlike_loss = log(fc) + r2/fc` is a constant-shifted equivalent of QLIKE for model ranking, but not the canonical Patton-style expression as usually written.
   - This is not usually ranking-changing, but if the article says "Patton (2011) QLIKE" without qualification, the formula statement is imprecise.

2. `experiments/k1087/k1087.py:662-679, 778-781`
   - Code reports ordinary HAC DM `p`-values and separately applies internal `|t| > 3.0` as the "Harvey pass" gate.
   - This is acceptable as a house rule if stated clearly, but it is not the same thing as a Harvey-Leybourne-Newbold small-sample corrected DM test.

3. `experiments/k1087/k1087.py:403-406, 479-482`
   - `lagged[0] = raw[0]` duplicates the first regressor value instead of marking the first lagged observation unavailable.
   - This only affects the first in-window observation, so it is minor, but it is not a clean lag convention.

## Article overclaims

1. The title `債券波動明明最怕利率，為什麼最後還是 VIX 比較有用？` is too strong relative to the code output.
   - In the stored results, `A4f_VIX` vs `GJR` is only `dm_t = +2.018`, `harvey_pass = false`.
   - `A4f_MOVE` is `+1.865`, also `harvey_pass = false`.
   - So the code supports "VIX is the best point estimate among tested variants" more than "VIX is meaningfully useful."

2. Body copy is mostly honest about the NULL:
   - it explicitly says no model passes the strict threshold
   - it does not falsely claim statistical significance
   - the main overstatement risk is the headline / framing, not the detailed paragraphs.

## Recommendation

`amend`

Do not keep the article as-is.

Required next step:

1. fix the A4f recursion bug in `k1087.py`
2. rerun K1087
3. update article headline and body if rankings or margins move
4. if the corrected rerun still shows a full NULL, reframe headline toward:
   - "利率因子也沒救回 TLT 波動預測"
   - rather than "VIX 比較有用"
