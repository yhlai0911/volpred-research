# K1677-rev — Fraud/enforcement peer contagion, five-method revision

**Revises:** K1677 (Codex verdict `FAIL`)  
**Primary verdict:** `CONTROLLED_RV_NULL_NO_STRICT_SECONDARY_ASSOCIATION_UNDERPOWERED`  
**Sensitivity verdict:** available-peer specification finds a strict market-adjusted Corwin–Schultz spread association, but it is not promoted to a knowledge-grade finding because the historical peer universe is incomplete.

## Research question

After a public fraud/enforcement revelation, do the focal firm's declared same-industry peers exhibit higher volatility, downside risk, or illiquidity over `t+1..t+10`?

This is an empirical event study of 28 hand-curated salient events, not a causal estimate and not the full SEC AAER population.

## Five repairs

1. **Directional inference.** All eight pre-declared outcomes are oriented so positive means contagion. The script reports one-sided iid, CR1 time-cluster, and exact cluster sign-flip tests; Bonferroni and BH always use `m=8`. A strict claim requires cluster `t≥3`, iid/cluster/sign-flip BH `<.05`, and cluster Bonferroni `<.05`.
2. **Fail-closed peer data.** The focal ticker is asserted absent. Primary inference requires every peer in the frozen event-specific list to have all 49 pre returns, all 10 post returns, and complete OHLCV; otherwise the whole event is dropped. The former available-peer behavior is retained only as a labelled sensitivity.
3. **Clean placebos.** A placebo `[-60,+10]` footprint cannot overlap any real event's full footprint and must finish before the focal event's baseline begins. All three placebo-normalized outcomes share the same event-stable random origins. Audited sampled overlap and future-origin counts are both zero.
4. **Measure definitions.** Downside semivariance is `mean(min(r,0)^2)` over all days and uses the un-floored difference `post−pre`. Amihud returns are computed on the full SPY-aligned series before window slicing, retaining `t0→t+1`.
5. **Time dependence/common shocks.** Events whose full analysis windows overlap form one connected time cluster. Inference uses CR1, whole-cluster pairs bootstrap, and exact enumeration of all sign patterns when `G≤16`. RV, worst-day, Corwin–Schultz, and Amihud comparisons also remove contemporaneous SPY movement where applicable.

## Data audit

- Price source: cached yfinance daily OHLCV, 1998-01-02 to 2025-12-30, `auto_adjust=False`.
- Input events: 28.
- Complete-event primary: 20 events, 13 connected time clusters.
- Available-peer sensitivity: 28 events, 16 connected time clusters.
- Missing: 8 unique tickers / 9 peer occurrences — `BMWYY`, `CS`, `ENDP`, `FI`, `FSR`, `K` (twice), `NKLA`, `TUP`.
- Eight events are therefore excluded from primary rather than silently reweighted.
- One primary event lacks enough strictly historical clean placebos; only its placebo-family fields are missing. Other families retain the event.

The frozen ticker lists are **not** a CRSP/WRDS historical industry-universe reconstruction and focal exclusion is ticker-level, not PERMCO-level. Accordingly, this revision is a fail-closed declared-list analysis, not a claim that the full point-in-time peer universe has been recovered.

## Results

### Complete-event primary

| Outcome | n | Oriented mean | Cluster t | Cluster BH | Exact sign-flip BH | Cluster Bonferroni | Strict hit? |
|---|---:|---:|---:|---:|---:|---:|---|
| RV, market-adjusted | 20 | -0.0359 | -0.30 | 0.705 | 0.704 | 1.000 | No |
| RV, clean-placebo z | 19 | +0.0785 | 0.33 | 0.498 | 0.491 | 1.000 | No |
| RV, raw log ratio | 20 | -0.0658 | -0.83 | 0.789 | 0.791 | 1.000 | Diagnostic only |
| Semivariance, market-adjusted difference | 20 | +0.000168 | 1.26 | 0.203 | 0.284 | 0.925 | No |
| Semivariance, clean-placebo z | 19 | +0.750 | 1.33 | 0.203 | 0.284 | 0.846 | No |
| Worst day, SPY-adjusted clean-placebo z | 19 | +0.459 | 1.31 | 0.203 | 0.284 | 0.865 | No |
| Corwin–Schultz spread, market-adjusted | 20 | +0.372 | 3.19 | 0.031 | **0.075** | 0.031 | **No** — exact cluster gate fails |
| Amihud, market-adjusted | 20 | +0.184 | 1.20 | 0.203 | 0.309 | 1.000 | No |

The primary conclusion is narrow: controlled peer RV remains NULL. Market-adjusted spread widening is directionally strong under iid/CR1 inference but does not survive the exact cluster-sign gate after FDR correction.

### Available-peer sensitivity

The old available-peer specification retains all 28 events and finds market-adjusted spread widening:

- mean log change relative to SPY: `+0.3688`
- cluster `t=4.206`
- cluster BH `q=0.0031`
- exact cluster-sign BH `q=0.0083`
- cluster Bonferroni `p=0.0031`

This is a genuine robustness signal, not the primary finding: its basket construction excludes unavailable/delisted peers and therefore remains exposed to survivor-data bias. Worst-day risk no longer survives after contemporaneous SPY adjustment and strict gates (`t=2.42`, cluster BH `q=0.057`).

## Interpretation

- **RV contagion:** NULL in both specifications.
- **Liquidity:** spread widening is economically and statistically suggestive, but depends on the peer-availability policy. It should be treated as a follow-up requiring archival delisted-security data and an effective-dated entity/industry universe.
- **Knowledge gate:** do not write this result to `knowledge.json` as a confirmed peer-contagion finding. A CRSP/WRDS-style reconstruction using stable security/entity identifiers is the remaining requirement.

## References

- Gleason, Jenkins & Johnson (2008), *The Accounting Review*, DOI `10.2308/accr.2008.83.1.83`.
- Karpoff, Lee & Martin (2008), *JFQA*, DOI `10.1017/S0022109000004221`.
- Corwin & Schultz (2012), *Journal of Finance*, DOI `10.1111/j.1540-6261.2012.01729.x`.
- Amihud (2002), *Journal of Financial Markets*, DOI `10.1016/S1386-4181(01)00024-6`.

## Reproduce

```bash
uv run python experiments/K1677-rev/K1677-rev.py
```

Outputs:

- `K1677-rev.py`
- `K1677-rev_results.json`
- `K1677-rev_event_table.csv`
- `K1677-rev_directional_results.png`
