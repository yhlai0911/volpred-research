# K446 Source-Code Review (24h-rule audit)

- **Reviewer**: Codex CLI 0.139.0 (gpt-5.4, ChatGPT auth)
- **Triggered by**: paper_review_mile_eabd7e46 (hourly-03 dispatch, 2026-06-18 03:08 CST)
- **Article**: mile_eabd7e46「地緣政治風險指數能預測美股波動嗎？」(published 2026-06-17T16:07Z)
- **Experiment**: K446 — GPR vs SPY realized volatility (2000-2026, N=6552, OOS 2023-2024 N=502)

## Verdict: **FAIL**

## Critical Issues (4)

1. **OOS split forward-label leak** (k446_gpr_vol.py:320, 334) — 固定 2023 OOS 用 `data.index < oos_start` 但 train tail 含 5/21 日 forward target overlap 進 2023 OOS → DM p=0.148 結論不乾淨。
2. **Rolling OOS leak** (k446_gpr_vol.py:667, 671) — 每步 `data.iloc[:i]` train tail forward label 含 test day 後 returns → 年度 mse_ratio 不是嚴格 OOS。
3. **DM 21d horizon wrong** (k446_gpr_vol.py:247) — 21d target 仍用 `h=5`；無 Harvey-Leybourne-Newbold small-sample correction → JSON 21d DM p=0.148 不是有效 21d overlapping-forecast DM p-value。
4. **Harvey (1997) threshold 無 HAC** (k446_gpr_vol.py:573, 602, 638) — partial-correlation t 用 naive OLS formula，無 Newey-West 處理 overlapping forward RV serial correlation；`|t|>3` 是硬編碼門檻非正式檢定。

## Moderate Issues (4)

- Granger F-test 無 AIC/BIC lag selection（lag1 p=0.0499 是邊界值，不能升級為穩健結論）
- 體制與事件分析是 ex-post descriptive（p50/p75/p90 用全樣本分位數、事件窗手選、無 CI/bootstrap/multi-testing 控制）
- z-score normalization 敏感性主張只對 21d 成立；5d z-score `t=-3.1037, p=0.0019` 仍顯著（文章宣稱 "結論完全相反" 對 21d 正確、對 5d 錯誤）
- QLIKE 實作用 volatility level ratio 而非 canonical variance QLIKE

## Minor Issues (2)

- Raw data 未 pin（GPR `/tmp/gpr_daily.xls`，SPY/VIX yfinance live，無 hash / vendor snapshot）
- `rolling_oos_analysis(window=500)` 名實不符（expanding 非 rolling；overall 含 2025/2026）

## Overclaim Audit

| Article Claim | Verdict |
|---|---|
| Harvey (1997) threshold pass (t=-7.20, -6.43) | **OVERSTATED** — raw t 對，但 significance 主張無 HAC 校正且 forward target overlap |
| z-score 後不顯著（"結論完全相反"） | **OVERSTATED** — 21d 對，5d 仍顯著 t=-3.10 |
| OOS VIX+GPR vs VIX-only DM p=0.148 | **OVERSTATED** — JSON 數字對，但 OOS split leak 且 DM h=5 wrong horizon for 21d target |
| Granger GPR→VIX lag1 p=0.0499 | **OVERSTATED** — p-value 對但邊界值且無 lag selection / robustness |
| 7-event correlation range -0.18 to 0.61 | **VERIFIED**（descriptive only） |
| 極端 GPR n=656 corr=0.200 | **VERIFIED**（descriptive only，不可作為 inferential regime evidence） |

## Followup Action

1. 文章 `mile_eabd7e46` 末段補 audit caveat：specific statistical claims 為 indicative 非 conclusive；mixed-result narrative 保留（與 audit 結論一致）
2. 排 followup task 重跑 K446 with:
   - `h`-step embargo (drop train tail 21 日)
   - Harvey-Leybourne-Newbold DM correction with proper h
   - Newey-West HAC SE for partial-corr t
   - AIC/BIC lag selection for Granger
   - QLIKE 用 canonical variance formula
3. K446 knowledge.json 標 FAIL + critical_issues 列表

