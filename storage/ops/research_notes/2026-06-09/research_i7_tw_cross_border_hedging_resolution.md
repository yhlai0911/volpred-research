# Prior-Evidence Resolution — research_rp_7c58652216

- Task ID: `research_rp_7c58652216`
- Topic: `I7: 台灣投資人跨境避險實務`
- Date: 2026-06-09
- Resolution: `core question already substantially answered by prior experiments; no immediate same-shape rerun`

## Existing in-repo evidence

This backlog prompt is already substantially covered by two existing research blocks:

1. `K758`: `experiments/k758/k758_tw_cross_border_hedge.py`
2. `I9 / I9b`: proper futures hedging effectiveness and strict 1-step-ahead OOS hedge-ratio evaluation

Relevant files:

- `experiments/k758/k758_tw_cross_border_hedge_results.json`
- `experiments/i9/i9_proper_hedging_effectiveness.py`
- `experiments/i9b/i9b_proper_rolling_oos_hedge.py`

## What K758 already answers

K758 is directly about FX hedging for Taiwan investors holding US equities.

Stored findings in repo / knowledge:

- FX adds only `2.6pp` to SPY volatility from a TWD investor perspective (`17.1% -> 19.7%`)
- FX explains about `24%` of SPY(TWD) variance
- `Corr(SPY, FX) ~= 0.002` on average
- USD strengthens modestly during crashes, giving Taiwan investors a weak natural hedge
- Full FX hedging cost is estimated at:
  - retail: `4.86%/yr`
  - institutional: `1.86%/yr`
- Cost breakdown in results:
  - interest-rate differential: `1.14%/yr`
  - retail NDF spread: `3.6%/yr`
  - margin opportunity cost: `0.12%/yr`

Practical recommendation stored in `K758`:

- for Taiwan retail investors using 複委託 / US brokerage:
  - `50% 0050 + 30% SPY + 20% GLD`
  - `0% FX hedge`
  - rationale: FX hedge is too expensive for retail, while USD exposure provides some crisis cushioning

## What I9 / I9b already answer

The backlog wording also mentions futures hedging practice.

`I9` and `I9b` already answer the core implementation question of when futures hedging is worth doing:

- `SPY-ES=F` correlation around `0.97`
- naive hedge ratio `h=1` is already sufficient
- OOS hedging effectiveness is about `94.4% - 94.5%`
- dynamic complexity adds little for near-one spot/futures pairs
- `I9b` explicitly fixes look-ahead by estimating `h_t` only with `[0, t-1]` data

This means the repo already contains the key practical conclusion for liquid index futures hedging:

- if spot/futures correlation is extremely high, simple futures hedging works and extra model complexity adds little

## What is still not fully answered

This task is **not** a perfect duplicate of one single prior experiment because the wording also mentions:

- `用台指期避台股`
- explicit Taiwan investor operational details beyond US-equity FX hedging
- tax / product-availability / contract-size specifics in a Taiwan-local implementation

Those details are only partially addressed today.

So the correct classification is:

- `substantially answered at the core research level`
- `not fully exhausted as a Taiwan-local implementation memo`

## Decision

Do not rerun a same-shape broad experiment immediately.

If revived later, split into a new, narrower design, for example:

1. `台指期 / 0050 / 2330` Taiwan-local futures hedge implementation study
2. contract-size / margin / roll-cost comparison for retail-sized accounts
3. Taiwan-tax and brokerage-route comparison as an operational note rather than a generic "cross-border hedging" rerun

For the current backlog task, prior evidence is sufficient to close it without duplicate rerun.
