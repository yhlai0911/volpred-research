# Codex Review

Reviewer: Codex
Date: 2026-07-03
Experiment: `research_data_driven_vc_screening_shock_public_innovation`

## Verdict

**CONDITIONAL_PASS_SOURCE_REVIEW / research verdict remains NULL_PUBLIC_PROXY_DIAGNOSTIC**

The implementation is acceptable as a reproducible public-proxy diagnostic. The
research result is a null: no OOS cell passes the Harvey-style `t <= -3.0`
incremental QLIKE gate, and aggregate HAC diagnostics do not support a positive
volatility-spillover claim.

## Checks

- Experiment triplet present:
  - `README.md`
  - `research_data_driven_vc_screening_shock_public_innovation.py`
  - `research_data_driven_vc_screening_shock_public_innovation_results.json`
- Data sources are explicit and reproducible:
  - yfinance adjusted closes for `ARKK/IPO/IGV/SOXX/AIQ/QQQ/SPY`
  - SEC EDGAR full-index `master.gz` quarterly files, counted by filing date
- Lookahead check passes:
  - Attention feature uses `attention["attention_z"].shift(1)`.
  - Forward-label training embargo uses `target_end_pos < current_pos`.
  - The OOS endpoint guard compares target end to the original data max position,
    not the already target-filtered frame, after review correction.
- Randomness:
  - Seed fixed as `SEED = 42`; no stochastic inference is used in the main path.
- DM / loss convention:
  - `dm_test(loss_augmented, loss_baseline, h=horizon)` means negative `t`
    favors the augmented model.
  - The PASS gate correctly requires augmented QLIKE lower and `t <= -3.0`.
- Claim discipline:
  - Results are framed as SEC public-proxy diagnostics only.
  - The README explicitly says this does not replicate or refute Bonelli's
    private-market VC mechanism.

## Residual Limitations

- SEC S-1/F-1 count is a financing-window proxy, not VC screening automation.
- `innovation_event_count` is company-name keyword based and should not be used
  as a formal sector classifier.
- yfinance ETF baskets are not point-in-time VC-backed public-company cohorts.
- Daily close-to-close variance is coarse for event-time or filing-time effects.

## Result Snapshot

- Verdict: `NULL_PUBLIC_PROXY_DIAGNOSTIC`.
- OOS cells: `10`.
- OOS Harvey pass count: `0`.
- Directionally better OOS cells: `6`.
- Strongest directional OOS cell: `IGV 21d`, QLIKE improvement `+3.21%`, DM
  `t=-1.69`, still below Harvey threshold.
- Aggregate HAC pass count: `0`.
- Top-decile SEC attention contrast is opposite-sign for 5d innovation basket
  RV: shock mean `0.00119` vs non-shock `0.00194`, Welch `t=-6.87`.

No changes required before knowledge entry, provided the entry preserves the
proxy limitation and null verdict.
