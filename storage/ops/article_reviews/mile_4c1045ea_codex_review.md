# Article Review — mile_4c1045ea (K663 升降息環境 黃金避險)

- **Date**: 2026-05-29 03:10 台灣時間
- **Task**: paper_review_mile_4c1045ea (Codex 24h-rule)
- **Reviewer**: codex-cli gpt-5.4 (medium effort)
- **Verdict**: **CONDITIONAL_PASS**
- **Confidence**: high
- **Action taken**: errata footnote appended to feed.json + reports/<id>.json

## Numeric verification (主線程預審)

| Field | Article | results.json | Match |
|---|---|---|---|
| sample_days | 4,962 | 4962 | ✓ |
| rising n / pct / yld_change | 1,023 / 20.6% / +85bp | 1023 / 20.6 / 85.0 | ✓ |
| stable n / pct / yld_change | 2,998 / 60.4% / −2.7bp | 2998 / 60.4 / −2.7 | ✓ |
| falling n / pct / yld_change | 941 / 19.0% / −93bp | 941 / 19.0 / −93.0 | ✓ |
| Rising Sharpe 12/VIX SPY | 0.65 | 0.646 | ✓ |
| Rising Sharpe 50/50 | 0.27 | 0.265 | ✓ |
| Rising Sharpe 60/40 SPY/TLT | −0.04 | −0.04 | ✓ |
| Falling Sharpe 50/50 | 1.31 | 1.311 | ✓ |
| Falling Sharpe 60/40 SPY/TLT | 1.08 | 1.082 | ✓ |
| SPY-TLT corr rising | +0.023 | 0.0227 | ✓ |
| SPY-TLT corr falling | −0.534 | −0.5341 | ✓ |
| Q1 Sharpe Δ rising | −0.381 | 0.265 − 0.646 | ✓ |
| Q1 Sharpe Δ falling | +0.97 | 1.311 − 0.341 | ✓ |
| Range 1.046 | 1.046 | 1.311 − 0.265 | ✓ |

All 14 quoted numbers verified against results.json. No fabrication, no inflation.

## Codex critical issues

1. **Lookahead audit PASS**: `vt_weight.shift(1)` at line 179 — signal lag correct.
2. **Ex-post regime segmentation framing**: lines 33 ("「降息買金」這條規則沒問題") / 80 ("「黃金避險」是條件性的") read as actionable real-time rule, but regime is computed from past-126-day yield change ending at t — descriptive, not a signal usable at decision time.
3. **Statistical overclaim**: "差了整整 1.35 個 Sharpe，這不是雜訊" (line 35) without DM test / Harvey-haircut / bootstrap CI.

## Action taken

Appended `## 方法論誠實補充（2026-05-29 Codex 24h-review）` section (607 chars) between "## 給投資人的可操作 takeaway" and "## 相關研究" disclosing:

1. Ex-post regime segmentation — not a real-time signal
2. No formal statistical test performed
3. Parameter sensitivity (50bp threshold, 126d lookback, TLT proxy) untested

## Future K's flagged

- **K-sensitivity-test**: 50bp ±20bp + 126d ±63d sweep, see if Sharpe matrix is robust
- **K-formal-test**: DM test on 50/50 (rising vs falling), bootstrap CI on Sharpe difference
- **K-regime-proxy**: real-time observable regime indicator (Fed funds futures? FOMC dot plots? PMI-driven?) for true conditional strategy
- **K-TLT-alternative**: replace TLT with IEF (7-10y) / TIP (inflation-protected) — does "long bond in rising rate = anti-hedge" hold for medium-duration?

These do NOT block current article publication; they extend K663 narrative for future research direction (per article's own Q3 caveat).
