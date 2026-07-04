# K1632 Codex Review

**Verdict**: `CONDITIONAL_PASS`

## Scope

Reviewed experiment `experiments/k1632/k1632.py` and reran:

```bash
uv run python experiments/k1632/k1632.py
uv run python -m py_compile experiments/k1632/k1632.py
```

Both completed successfully. Visual QA of both PNGs showed readable CJK text and non-empty charts.

## Findings

No blocking issues found.

## Checks

- **Lookahead control**: `rv20_low_threshold` and `range20_low_threshold` are both computed with `.shift(1)` before rolling quantiles ([k1632.py](/Users/yhlai0911/volpred-research/experiments/k1632/k1632.py:120)); forward targets use `ret_log.shift(-i)` for `i=1..h`, so targets start at t+1 ([k1632.py](/Users/yhlai0911/volpred-research/experiments/k1632/k1632.py:136)).
- **Same-day breakout honesty**: `breakout_day_abs_ret` is reported separately and README labels it descriptive / non-tradable; it is not mixed into the forward signal claim ([k1632.py](/Users/yhlai0911/volpred-research/experiments/k1632/k1632.py:141)).
- **TW data hygiene**: 0050.TW uses `clean_tw50_data` before returns/features are generated ([k1632.py](/Users/yhlai0911/volpred-research/experiments/k1632/k1632.py:99)).
- **Formal inference**: forward volatility and absolute-return differences use HAC dummy regressions; breakout-day diagnostics use Welch tests; primary diff also has moving-block bootstrap with seed=42 ([k1632.py](/Users/yhlai0911/volpred-research/experiments/k1632/k1632.py:145), [k1632.py](/Users/yhlai0911/volpred-research/experiments/k1632/k1632.py:261)).
- **Reproducibility**: all outputs are generated from local `price_cache.db`, with no live data dependency.

## Residual Risk

- 10-day squeeze events are small samples: SPY n=14, 0050.TW n=17. The result is directionally consistent, but this remains a diagnostic myth test rather than a publishable universal law.
- The squeeze definition is one reasonable ex-ante choice, not an exhaustive search over every technical-analysis variant.
- Daily close-to-close data may miss intraday breakouts that reverse by the close.

## Key Result

The main claim is supported: after the primary `squeeze_reaches_10d` signal, next-20-day annualized volatility is lower, not higher:

- SPY: 11.48% vs 14.85%, diff -3.37pp, HAC p=0.00377, block-bootstrap 95% CI [-5.77pp, -1.04pp].
- 0050.TW: 14.79% vs 17.81%, diff -3.03pp, HAC p=0.00339, block-bootstrap 95% CI [-4.81pp, -0.80pp].

Episode endings show a same-day move effect, but it is descriptive and not a forward tradable signal.
