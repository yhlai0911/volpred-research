# Codex 24h Review — mile_153d2908 (K1568)

- **Article**: K1568：Federal Register 監管文件流量能預測 ETF 波動率嗎？144 個檢定、14 個 raw 顯著、Bonferroni 全滅
- **Task**: `paper_review_mile_153d2908`
- **Reviewed**: 2026-06-29 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **PASS with minor caveats**

## Summary

這篇研究讀者版文章和 K1568 canonical source 對齊。核心敘事是 Federal Register RULE / PRORULE 廣域流量有少數 raw-positive controlled-HAC cell，但在 144-test family 的 Bonferroni 與 Holm 校正後沒有任何 survivor；因此 verdict 只能是 `WEAK_RAW_ONLY`，不能當成交易訊號或 robust compliance-burden volatility signal。文章的數字、lookahead 描述、proxy 限制、圖表和結論強度都符合 `k1568_results.json`、`README.md` 與既有 `codex_review.md`。

Minor caveats: deterministic provenance gate 對 `14 raw significant` 與 `8 ETF` 這類 derived count 會報 false positive，因為它們是陣列長度 / family design 推得，不是 results JSON 的單一 numeric leaf；本 review 已人工核對。另，K1568 source review 已指出 downside semivariance 的 `log(var + 1e-12)` 有零點質量，文章沒有把 downside cell 當成 confirmed signal，因此不是 blocker。

## Numeric Verification

| Article claim | Source | Match |
|---|---|---|
| Federal Register documents = 78,564 | `sample.federal_register_docs` | yes |
| Sample = 2012-01-03 to 2026-06-26 | `sample.start/end` | yes |
| Trading rows = 3,641 | `sample.n_trading_rows` | yes |
| Target ETF count = 8 | `len(sample.targets)` | yes |
| Target ETFs = IJR/IWM/KRE/KBE/XLF/XLV/XLI/XRT | `sample.targets` | yes |
| Family size = 8 x 2 x 3 x 3 = 144 | `multiple_testing.n_tests` and design constants | yes |
| Positive raw p<0.05 cells = 14 | `len(verdict_assessment.positive_raw_p_lt_0_05)` | yes |
| Bonferroni alpha = 0.000347 | `multiple_testing.bonferroni_alpha` | yes |
| Bonferroni survivors = 0 | `multiple_testing.bonferroni_survivors=[]` | yes |
| Holm survivors = 0 | `multiple_testing.holm_survivors=[]` | yes |
| Top cell XLI 5d downside proposed-rule coef +0.505, HAC t +3.19, p 0.0014 | nested `primary_tests` + `multiple_testing.holm_decisions[0]` | yes |
| Top cell Spearman rho +0.075 CI [0.019, 0.128], AUC 0.558 CI [0.520, 0.596] | nested `primary_tests` diagnostics | yes |
| Verdict = `WEAK_RAW_ONLY` | `metadata.verdict` / `verdict_assessment.verdict` | yes |

## Findings

No blocking or major findings.

1. **Lookahead description is source-aligned** — article method table and timing paragraph; `experiments/k1568/k1568.py:230`, `experiments/k1568/k1568.py:279`, `experiments/k1568/k1568.py:315`
   Federal Register documents are mapped to the first ETF trading date on or after publication date, tested signals are explicitly `shift(1)`, and forward targets are built with `shift(-i)` for `i=1..H`. The article's two-layer lag explanation is accurate.

2. **Multiple-testing conclusion is correct** — article headline and correction section; `experiments/k1568/k1568_results.json:multiple_testing`
   The strongest raw p-value is 0.001417, above Bonferroni alpha 0.000347, and Holm rejects none. The article correctly says this is a clear failure under the primary family-wise gate.

3. **Raw-signal interpretation is appropriately weak** — article raw-cell table and reader-meaning section; `experiments/k1568/k1568_results.json:verdict_assessment`
   The text notes proposed-rule flow is directionally visible in XLI/XLV but keeps the conclusion at hypothesis generation. It does not convert raw p-values into a strategy or robust predictor claim.

4. **Proxy limitation is not buried** — article research-background, method, and limitations sections; `experiments/k1568/README.md`
   The article explicitly distinguishes Federal Register flow from RegData, OIRA paperwork burden, firm-level legal spend, and Hassan et al.-style firm-level political-risk text data. This is the key scope boundary.

5. **Minor derived-count caveat for automated provenance** — deterministic gate output during review
   `audit_content_provenance(content, ["K1568"])` flagged `14` and two `8` values because they are derived from `len(...)` / design multiplicands rather than literal JSON leaves. Manual verification confirms them, so this is not a content issue.

6. **Minor wording/copy caveat** — article phrase "IPO IJR 與 IWM"
   This appears to be a typo for `IJR` / `IWM`; it does not change a research claim and does not need an urgent correction. A future cleanup pass can remove `IPO`.

## Source-Code Audit

- PASS — rolling z-score baselines use shifted rolling mean/std; see `experiments/k1568/k1568.py:125`.
- PASS — tested signal columns are `*_lag1 = signal.shift(1)`; see `experiments/k1568/k1568.py:279`.
- PASS — forward RV, downside variance, return, and volume windows use strictly future `shift(-i)` terms; see `experiments/k1568/k1568.py:315`.
- PASS — controlled OLS uses statsmodels HAC with horizon-specific `maxlags`; see `experiments/k1568/k1568.py:361`.
- PASS — Holm/Bonferroni correction is computed over the full controlled-HAC family; see `experiments/k1568/k1568.py:443`.
- PASS_WITH_CAVEATS — downside semivariance uses `log(var + 1e-12)`, so raw downside p-values have the zero-mass caveat already documented in `experiments/k1568/codex_review.md`.
- N/A — The article makes no QLIKE, DM, Harvey, Sharpe, VaR, or strategy-performance claims.

## Verification Commands

```bash
uv run python -m py_compile experiments/k1568/k1568.py
```

Additional deterministic checks run during review:

- `audit_image_urls(content)` returned `broken=[]` for all 3 embedded Supabase image URLs.
- `_infer_audience(...)` returned `research`, matching article metadata.
- `verify_article_live("mile_153d2908")` returned `True`.
- `audit_content_provenance(content, ["K1568"])` returned 3 derived-count findings, manually verified above as non-content issues.

The full K1568 experiment was not rerun during this article review because it fetches Federal Register and yfinance vendor data and would risk refreshing canonical artifacts. Existing canonical results, source code, review notes, figures, public image URLs, and the live article page were inspected.
