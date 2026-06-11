# K1473: HAR vs Deep Learning Across Forecast Horizons (Honest Proxy)

## Research Question

Does a simple HAR-style daily variance model lose to lightweight deep learning models only at medium or long horizons, or does HAR still dominate even there?

The queued task asked for a 5-minute realized-volatility comparison on US equity indices. This repo does not pin one canonical, long-sample intraday RV panel for that exact setup, so this experiment follows the repo's honest-proxy rule instead of inventing unavailable data. The target here is a daily close-to-close variance proxy built from squared log returns.

## Motivation

The research backlog hypothesis was:

- HAR often wins at `h=1`
- LSTM / simplified Transformer might only show value at `h=5` or `h=22`

This experiment is a bounded falsification test of that claim under a simple, reproducible local setup.

## Related Prior Work in Repo

- `K767`: earlier multi-horizon HAR idea, but later error-log notes warned about multi-horizon label timing risk.
- `K1312`: structured GARCH-LSTM experiment; again mostly null.
- Multiple prior ML-vs-classical runs in `knowledge.json` already suggest a high null rate.

K1473 differs by asking a narrower question: horizon boundary only, same data, same target proxy, same train/OOS split, same loss.

## Data

- `SPY`: `experiments/k1206/data/SPY.csv`
- `QQQ`: `experiments/k1206/data/QQQ.csv`

Sample coverage after local snapshot availability:

- SPY: 2000-01-03 to 2026-04-16
- QQQ: 2000-01-03 to 2026-04-16

## Target and Timing Discipline

- Base variance proxy: daily squared log return
- Horizons:
  - `h=1`: next 1 trading day variance
  - `h=5`: mean variance over the next 5 trading days
  - `h=22`: mean variance over the next 22 trading days
- Forecast-time information set:
  - HAR features use only lagged variance information through `t-1`
  - LSTM / Transformer sequences also stop at `t-1`
  - No same-day signal uses same-day return

## Models

- `HAR`: OLS on lag-1 / lag-5 / lag-22 variance proxies
- `LSTM1`: small single-layer LSTM on a 22-day sequence of lagged log-variance
- `TinyTransformer`: small Transformer encoder on the same 22-day lagged sequence

These are intentionally small models. The point is not to maximize neural performance with large tuning budgets, but to test whether a clean DL edge appears at longer horizons under a fair local comparison.

## OOS Protocol

- Frozen train / test split
- OOS starts: `2021-01-04`
- Training sample is all eligible observations before OOS start
- Validation is the last 20% of pre-OOS observations
- Fixed random seed: `42`

## Evaluation

- Primary loss: OOS `QLIKE`
- Pairwise significance: Diebold-Mariano test vs HAR
- Interpretation rule:
  - negative DM `t` means challenger beats HAR
  - large positive DM `t` means HAR beats challenger

## References

- Corsi (2009), *A Simple Approximate Long-Memory Model of Realized Volatility*
- Patton (2011), *Volatility forecast comparison using imperfect volatility proxies*
- Diebold and Mariano (1995), *Comparing predictive accuracy*
- Harvey, Leybourne, and Newbold (1997), small-sample DM refinement

## Main Result

In this local proxy version, the boundary claim is **not** supported. A small Transformer does beat HAR in parts of the OOS sample, but the gains are not confined to `h=5` or `h=22`; they already appear at `h=1`, especially on SPY and QQQ.

So the honest reading is:

- "DL only wins at medium/long horizon": **not supported**
- "some lightweight DL specs can beat HAR in this daily proxy setup": **partially supported**

That does **not** prove the same pattern will hold in a paper-grade intraday RV setting. It only means the original horizon-boundary narrative does not survive a clean local proxy audit with fixed timing discipline and matched evaluation.

## Files

- `k1473.py`: experiment script
- `k1473_results.json`: results artifact
- `k1473_horizon_qlike.png`: relative QLIKE comparison chart
