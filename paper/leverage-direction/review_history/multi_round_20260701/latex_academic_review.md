# Latex Academic Review — 2026-07-01
Verdict: FAIL_MAJOR_REVISION
High findings: 8
Medium findings: 7

## High Findings

H1. The prior v13 technical READY checkpoint does not survive the 2026-07-01 contribution gate.

Evidence: the v13 review was explicitly a "focused confirmation of v12 H5 final blocker" and only closed the TLT/BTC QLIKE numerical contradiction (`paper/leverage-direction/review_history/v13/confirmation_review.md:5`, `paper/leverage-direction/review_history/v13/confirmation_review.md:8`, `paper/leverage-direction/review_history/v13/confirmation_review.md:10`). The new contribution gate says "CONTRIBUTION BORDERLINE - needs reframing" and would not recommend JBF R&R in the current form (`paper/leverage-direction/review_history/codex_contribution_gate_20260701.md:12`, `paper/leverage-direction/review_history/codex_contribution_gate_20260701.md:14`). Treat v13 as a numerical/compile checkpoint only, not a current submission-readiness checkpoint.

H2. The manuscript still has no single controlling contribution after the gate.

Evidence: the abstract claims implications for "model selection, risk management, and portfolio construction" plus a "complexity ceiling" (`paper/leverage-direction/main.tex:39`). The literature review similarly says the paper tests where gamma matters for "forecasting, VaR, and portfolio construction" (`paper/leverage-direction/body.tex:25`). The body then branches into VaR/ES, timing tests, crisis validation, VT insurance, VIX targeting, complexity ceiling, HAR paradox, crowding risk, and behavioral costs (`paper/leverage-direction/body.tex:209`, `paper/leverage-direction/body.tex:328`, `paper/leverage-direction/body.tex:345`, `paper/leverage-direction/body.tex:411`, `paper/leverage-direction/body.tex:442`, `paper/leverage-direction/body.tex:488`, `paper/leverage-direction/body.tex:501`, `paper/leverage-direction/body.tex:503`). This leaves the JBF contribution looking like a broad empirical exercise rather than a clean finance mechanism paper.

H3. Sample-period and OOS language is internally inconsistent.

Evidence: the abstract says the study uses 2017--2025 data with 2026 reserved for OOS validation (`paper/leverage-direction/main.tex:39`). The data section says the source period is January 2017 through March 2026 (`paper/leverage-direction/body.tex:34`). The sample-period paragraph says 2023--2024 is the main OOS period and 2025--March 2026 is validation (`paper/leverage-direction/body.tex:42`). The data-characteristics section and Table 1 instead call 2017--2025 the in-sample period with 2026 reserved (`paper/leverage-direction/body.tex:120`, `paper/leverage-direction/tables_main.tex:5`), while Table 3 treats 2025 itself as OOS (`paper/leverage-direction/tables_main.tex:52`, `paper/leverage-direction/tables_main.tex:54`, `paper/leverage-direction/tables_main.tex:56`, `paper/leverage-direction/tables_main.tex:58`, `paper/leverage-direction/tables_main.tex:60`). A first-round referee will not accept any OOS claim until one sample map controls every table and prose claim.

H4. The "primary sample" universe changes across analyses.

Evidence: the introduction defines seven primary assets including SLV and BTC-USD (`paper/leverage-direction/body.tex:11`), and Table 2 reports gamma for all seven (`paper/leverage-direction/tables_main.tex:31`, `paper/leverage-direction/tables_main.tex:37`). Table 3 has eleven QLIKE rows but omits SLV and BTC 2025, with a comment that BTC 2025 has no canonical source row (`paper/leverage-direction/tables_main.tex:51`, `paper/leverage-direction/tables_main.tex:62`). The VT table uses only five assets and asset-specific windows (`paper/leverage-direction/tables_main.tex:136`, `paper/leverage-direction/tables_main.tex:147`). The abstract/conclusion switch among seven primary assets, six OOS classifications, five primary VT assets, twelve diverse assets, fourteen extended VT assets, and 26 validation assets (`paper/leverage-direction/main.tex:39`, `paper/leverage-direction/body.tex:13`, `paper/leverage-direction/body.tex:511`, `paper/leverage-direction/body.tex:513`, `paper/leverage-direction/body.tex:515`). These universes need named panels and a mapping table.

H5. The gold/safe-haven taxonomy still overclaims relative to the canonical estimates.

Evidence: the introduction states that "safe-haven assets show inverted leverage" (`paper/leverage-direction/body.tex:11`). But the canonical GLD result is mean gamma `+0.002`, HAC `t = +0.15`, and model choice GARCH (`paper/leverage-direction/tables_main.tex:34`); the body correctly says the unconditional mean "does not establish inverted leverage for gold" (`paper/leverage-direction/body.tex:134`) and rests the gold claim on the regime decomposition (`paper/leverage-direction/body.tex:158`). The discussion and conclusion nevertheless repeat the broad taxonomy "safe-haven assets (inverted)" / "safe-haven assets ($\gamma < 0$)" (`paper/leverage-direction/body.tex:361`, `paper/leverage-direction/body.tex:513`). The paper must state the gold claim as regime-dependent only unless the unconditional evidence is changed.

H6. The model-selection rule is not yet an operational out-of-sample decision rule.

Evidence: the rule is stated as a real-time single-window `t > 1.65` decision (`paper/leverage-direction/body.tex:194`, `paper/leverage-direction/body.tex:197`), but the main headline applies the rule to the retrospective quarterly-mean HAC statistic (`paper/leverage-direction/body.tex:200`, `paper/leverage-direction/tables_main.tex:24`). The paper admits the threshold and significance rule are calibrated on the evaluation sample and that the OOS test has only `N = 6` (`paper/leverage-direction/body.tex:202`). It also reports that the single-point rule misses SPY while the four-quarter average succeeds (`paper/leverage-direction/body.tex:204`). In VT implementation, the selected GJR assets are "namely SPY and EEM" (`paper/leverage-direction/body.tex:247`), while Table 2's HAC rule chooses GJR for SPY, QQQ, EEM, and BTC (`paper/leverage-direction/tables_main.tex:31`, `paper/leverage-direction/tables_main.tex:36`). This is not yet a pre-specified, auditable OOS rule.

H7. The VT contribution relies on heterogeneous, partly non-reconstructable table inputs.

Evidence: the body draws formal cross-asset conclusions from the five-asset VT table, including correlations between base volatility and MaxDD improvement (`paper/leverage-direction/body.tex:251`, `paper/leverage-direction/body.tex:272`). The table note says each asset uses its native evaluation window, with GLD on 2022--2026, SPY on 2014--2026, TLT/EEM around 2015--2026, and BTC post-2019 (`paper/leverage-direction/tables_main.tex:146`). The replication note says a uniform 2015--2026 window matched only 6/20 cells and GLD requires the paper-original data vintage (`paper/leverage-direction/tables_main.tex:147`). Formal inference should be based on a uniform frozen panel; otherwise the VT mechanism contribution is not stable enough for submission.

H8. Main tables expose internal audit/vintage instability that should not appear in a submission.

Evidence: Table 2 says earlier estimates came from "a vintage whose source experiment could not be re-located" (`paper/leverage-direction/tables_main.tex:24`). Table 4 says yfinance backfills may shift violation counts by up to `+/- 3` (`paper/leverage-direction/tables_main.tex:84`). Table 6 says original values were not reproducible under data-vintage variations (`paper/leverage-direction/tables_main.tex:125`). Table 7 says exact GLD reconstruction requires the paper-original data vintage (`paper/leverage-direction/tables_main.tex:147`). The contribution gate already flagged these notes as damaging for first-round submission (`paper/leverage-direction/review_history/codex_contribution_gate_20260701.md:108`, `paper/leverage-direction/review_history/codex_contribution_gate_20260701.md:112`). Freeze the dataset and move audit history to replication documentation.

## Medium Findings

M1. The rolling-gamma figure caption conflicts with the main methodology.

Evidence: the method and Table 2 use 504-day rolling windows (`paper/leverage-direction/body.tex:132`, `paper/leverage-direction/tables_main.tex:24`), but Figure 1 is captioned as "Rolling 252-day GJR-GARCH gamma estimates" (`paper/leverage-direction/body.tex:238`). If the plotted figure really uses 252 days, the text must say so; otherwise the caption is wrong.

M2. The VT implementation needs one explicit no-lookahead portfolio-return equation.

Evidence: the GARCH forecast is produced from `t-w` to `t-1` for date `t` (`paper/leverage-direction/body.tex:61`) and the VT weight is written as `w_t = sigma_target / sigma_hat_t` (`paper/leverage-direction/body.tex:109`). The VIX section later says properly lagged weights use `VIX_t` for `r_{t+1}` and warns that same-day implementation inflates Sharpe (`paper/leverage-direction/body.tex:436`, `paper/leverage-direction/body.tex:476`). The GARCH and VIX strategy sections should both define the traded return with the same timing convention, e.g. forecast-origin weight times next tradable return.

M3. GJR-GARCH positivity/stationarity constraints are not stated despite negative-gamma claims.

Evidence: the model permits `gamma < 0` as inverted leverage (`paper/leverage-direction/body.tex:46`, `paper/leverage-direction/body.tex:50`), and the core gold regime result uses negative gamma values (`paper/leverage-direction/body.tex:134`, `paper/leverage-direction/body.tex:173`). The manuscript does not state the parameter constraints used to keep conditional variance positive and stationary when `gamma` is negative. Add the constraints and state how the `arch` estimation enforces them.

M4. The gamma testing direction is inconsistent with the positive-gamma selection rule.

Evidence: the leverage-direction test is specified as `H0: E[gamma] >= 0` versus `H1: E[gamma] < 0`, i.e. an inverted-leverage one-sided test (`paper/leverage-direction/body.tex:97`, `paper/leverage-direction/body.tex:101`). The model-selection rule later uses positive significance, `t > 1.65`, to choose GJR (`paper/leverage-direction/body.tex:197`, `paper/leverage-direction/tables_main.tex:24`). The paper needs a signed testing protocol covering both standard and inverted leverage, or it should explain why only positive gamma triggers the asymmetric model.

M5. BTC mixes calendar-day data with ETF trading-day language.

Evidence: BTC has `N = 3285` observations while ETFs have `N = 2260` in the same descriptive table (`paper/leverage-direction/tables_main.tex:11`, `paper/leverage-direction/tables_main.tex:16`), but the rolling method repeatedly refers to 504 "trading days" (`paper/leverage-direction/body.tex:59`). Clarify whether BTC is estimated on calendar days, exchange trading days, or an aligned ETF calendar, because this affects window length and cross-asset comparability.

M6. Symbol overload around gamma remains too high for a paper whose core object is gamma.

Evidence: gamma denotes the GJR leverage parameter throughout, but the paper also uses `gamma_HM` for Henriksson-Merton timing (`paper/leverage-direction/body.tex:382`), `gamma_i` for the mechanism mapping (`paper/leverage-direction/body.tex:393`), and `gamma_RA` for CRRA risk aversion (`paper/leverage-direction/body.tex:423`). The footnotes help, but the paper needs a notation table or a stronger convention because gamma is the central construct.

M7. ES/FRTB material should be demoted unless the deferred tests are completed.

Evidence: the ES section says direct SPY ES computation is infeasible with only six 1% exceedances and that the full Bayer-Dimitriadis ES regression test is deferred to the replication supplement (`paper/leverage-direction/body.tex:227`, `paper/leverage-direction/body.tex:233`). The abstract still advertises broad risk-management implications (`paper/leverage-direction/main.tex:39`). Keep ES as a limitation/appendix unless the promised full-panel ES test is actually run and integrated.

## Bottom Line

The manuscript is not submission-ready after the contribution gate. The old v13 READY status remains useful only as evidence that one technical QLIKE blocker was closed and the prior source compiled. The current first-round academic blocker is structural: the paper must narrow the contribution, freeze and name its samples/universes, rebuild the OOS rule as a transparent decision exercise, and remove table/prose signals that the main results depend on unreproducible vintages.
