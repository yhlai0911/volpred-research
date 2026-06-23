# K1365 Codex Source Review

Reviewer: Codex CLI (`codex-vscode`)
Date: 2026-06-23

## Verdict

**CONDITIONAL_PASS for the source and null/reverse-diagnostic conclusion.**

The code is reproducible and the reported `NULL_PROXY` conclusion is supported. It must not be promoted as evidence that leader ETF liquidity concentration raises index volatility. The only Harvey-strength signal is a reverse EM fragmentation diagnostic, and it is correctly scoped as follow-up rather than the original hypothesis.

## Scope

Reviewed:

- `experiments/k1365/K1365.py`
- `experiments/k1365/K1365_results.json`
- `experiments/k1365/K1365_regression_table.csv`
- `experiments/k1365/README.md`

Verification run:

```bash
uv run python experiments/k1365/K1365.py
python -m py_compile experiments/k1365/K1365.py
```

## Checks

| Check | Status | Evidence |
|---|---|---|
| Three-piece experiment output | PASS | README, `K1365.py`, `K1365_results.json` exist; figures, raw cache, regression CSV also produced. |
| Data provenance | PASS | Results state `yfinance daily adjusted OHLCV, auto_adjust=True`; raw per-ticker CSV cache saved under `data/raw/`. |
| Literature-first requirement | PASS | README and results cite four relevant ETF liquidity / volatility / arbitrage papers. |
| Lookahead protection | PASS | All liquidity signals use rolling z-score then `.shift(1)` in `K1365.py:262-270`. |
| Forward target handling | PASS with caveat | `forward5_rv` uses `shift(-4)` target construction (`K1365.py:283`) and is evaluated against lagged signals with HAC `maxlags=5`; no trading/backtest claim is made. |
| Formal inference | PASS | Regression uses OLS-HAC (`K1365.py:366-367`), Harvey-style `t >= 3`, and BH q-values across all regressions (`K1365.py:394-410`). |
| Proxy honesty | PASS | Code and README explicitly exclude NAV premium/discount, creation/redemption, historical AUM, investor clientele, and bid-ask quotes. |
| Conclusion strength | PASS | Results verdict is `NULL_PROXY`; README reports the EM reverse signal without turning it into a general same-index ETF claim. |

## Key Numbers Checked

- Primary leader-share tests: 16.
- Positive primary leader-share Harvey hits: 0.
- Positive primary leader-share Harvey + BH q<=0.05 hits: 0.
- Negative primary leader-share Harvey + BH q<=0.05 hits: 3, all EM targets.
- Secondary reverse fragmentation/entropy hits: 2, both EM `forward5_rv`, HAC t about 4.86 and BH q about 2.86e-05.

## Residual Risk

- Same-index ETF groups are tiny; this is time-series inference within four groups, not broad ETF cross-section inference.
- yfinance volume share is a weak proxy for liquidity clientele and cannot separate AP activity, NAV dislocation, fee effects, or AUM migration.
- Forward 5-day targets overlap; HAC mitigates serial correlation but a weekly non-overlapping robustness design would be cleaner.

## Required Wording

Use:

> K1365 rejects the simple free-data proxy claim that leader ETF volume-share concentration predicts higher next volatility. A reverse EM-only fragmentation signal appears and deserves follow-up.

Do not use:

> ETF liquidity concentration raises same-index volatility.
