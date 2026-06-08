# Backlog Task Resolution — `research_volare_har_har_q_mem_amem_arxiv_2602_19732`

Date: 2026-06-09  
Resolver: Codex CLI

## Verdict

This backlog item is **already covered at the core-question level** by existing
repo work, primarily `K770b`.

The pending task is phrased as a generic standardized comparison framework for
`HAR / HAR-Q / MEM / AMEM`. The repo already has a completed standardized
comparison experiment for the core family:

- [`README.md`](./README.md)
- [`k770b_mem_unified_target.py`](./k770b_mem_unified_target.py)
- [`k770b_mem_unified_target_results.json`](./k770b_mem_unified_target_results.json)

## Why K770b already covers the main research question

`K770b` directly solves the key methodological problem that motivates a VOLARE-style
comparison framework:

1. **Same target space**
   - all models are converted into a common forecast object before scoring
2. **Same OOS protocol**
   - expanding-window, 1-day-ahead comparison across all models
3. **Same evaluation rules**
   - `QLIKE`, `MSE`, `MAE`, `DM`, `Harvey |t| > 3.0`
4. **Cross-asset evidence**
   - `SPY`, `GLD`, `0050.TW`

That is already the substance of a standardized benchmark framework, not a loose
single-model test.

## Existing evidence already answers the question

From `K770b`:

- Approach A average rank: `AMEM = 1.67`, `MEM = 1.67`, `HAR-ABS = 3.33`
- Approach B average rank: `AMEM = 1.67`, `MEM = 1.67`, `HAR-ABS = 4.00`
- `AMEM` is the reported cross-asset best model in both target conventions
- Rankings are directionally stable across both standardized target mappings

Selected strict-significance findings:

- `SPY`: `AMEM` beats `HAR-ABS` and `GJR` at the Harvey threshold
- `GLD`: `HAR-ABS` beats `GJR`
- `0050.TW`: both `MEM` and `AMEM` decisively beat `GJR`; `HAR-ABS` also beats `GJR`

So the repo already established that:

- standardized comparison is feasible,
- benchmark rankings do not collapse once fairness is enforced,
- `MEM / AMEM / HAR` are all real contenders under a shared protocol.

## Why this backlog item can be closed

The task title is generic. It does **not** ask for an exact replication package
of `arXiv:2602.19732`; it asks for the research direction. At that generic level,
the repo already has the answer.

Opening a fresh new experiment for the same core question would mostly duplicate:

- the standardized-target design from `K770b`,
- the HAR benchmark line already continued elsewhere (`K1379`, `K1396`),
- and the repo's existing fairness-gate methodology.

## Remaining gap, if someone wants to reopen it

The only meaningful residual scope is narrower:

- exact `HAR-Q` implementation and replication of the paper's full benchmark table
- same framework on realized-volatility targets rather than `|r| / r^2` proxy mappings
- broader asset universe and model-confidence-set layer on top of `K770b`

Those are **extensions**, not reasons to keep this generic backlog seed pending.
