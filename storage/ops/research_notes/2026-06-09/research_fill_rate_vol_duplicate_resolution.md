# Prior-Evidence Resolution — research_rp_8f163c50fd

- Task ID: `research_rp_8f163c50fd`
- Topic: 「填息率」與波動率的關係——填息快的股票 vol 是否較低？
- Date: 2026-06-09
- Resolution: `already partially answered by prior experiment; no immediate rerun`

## Existing in-repo evidence

This question is already explicitly listed as Research Question 3 in:

- `experiments/k512/k512_tw_exdividend.py`
- `experiments/k512/k512_tw_exdividend_results.json`

Relevant nearby context:

- `K1373`: pre-ex-dividend uncertainty / event-window event study
- `K1375`: ETF-level ex-dividend volatility NULL for 0056 / 00878 / 00919

## What K512 already shows

### 0050.TW

- fill rate: `79.2%` (`19/24`)
- average fill days: `3.3`
- median fill days: `1`
- filled vs not-filled fill-period vol:
  - `t = -0.807`
  - `p = 0.450`

### 0056.TW

- fill rate: `90.5%` (`19/21`)
- average fill days: `6.6`
- median fill days: `1`
- filled vs not-filled fill-period vol:
  - `t = +1.338`
  - `p = 0.229`

## Interpretation

Current evidence does **not** support the claim that faster filling is associated with lower volatility.

More specifically:

1. The strongest directly stored comparison in K512 is `filled` vs `not filled`, and both 0050 / 0056 are non-significant.
2. The `fast_vs_slow_fill_vol` fields are `null` because the usable sample inside those subgroups is too small after `fill_vol` availability filtering.
3. Therefore the repo already contains a directional attempt at this question, but the answer today is:
   - `insufficient evidence`
   - not a clean PASS
   - not worth immediate duplicate rerun without a redesigned panel

## Why not rerun immediately

The current backlog prompt is too close to K512 to justify a same-shape rerun. A meaningful next experiment would need to change design, for example:

- move from ETF-level to larger stock panel
- model `fill_days` as outcome and post-ex vol as predictor
- control for dividend yield, sector, market regime, and event clustering

That is a new experiment design, not a repetition of the existing one.

## Literature anchors

1. Elton, E. J., and M. J. Gruber (1970), *Marginal Stockholder Tax Rates and the Clientele Effect*, Review of Economics and Statistics 52(1), 68-74.
2. Frank, M., and R. Jagannathan (1998), *Why Do Stock Prices Drop by Less than the Value of the Dividend? Evidence from a Country without Taxes*, Journal of Financial Economics 47(2), 161-188.
3. Michaely, R., and J.-L. Vila (1995), *Investors' Heterogeneity, Prices, and Volume around the Ex-Dividend Day*, Journal of Financial and Quantitative Analysis 30(2), 171-198.

## Decision

Mark this backlog task as resolved by prior evidence.

If this topic is revived later, it should be reframed as a **new panel design** rather than re-running K512-style ETF event windows.
