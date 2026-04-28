# Cover Letter — P10 crypto-fear-channel

**Target journal (1st)**: Journal of International Financial Markets, Institutions & Money (JIMFIM)
**Target journal (2nd)**: Journal of Empirical Finance (JEF)
**Backup**: Finance Research Letters (FRL, short-form)
**Submission category**: Original Research Article
**Date prepared**: 2026-04-28
**Status**: DRAFT (awaiting user submission decision)

---

## Cover Letter Body (submission portal "Comments to Editor" field)

Dear Editor,

I am pleased to submit the manuscript "The Crypto Fear Channel: Asymmetric, Tail-Concentrated, and Regime-Dependent Volatility Spillover from Bitcoin to Equity Markets" for consideration at the *Journal of International Financial Markets, Institutions & Money*.

The paper documents three new empirical regularities in the volatility spillover from Bitcoin to U.S.\ equity markets, using daily data on SPY, BTC-USD, and the VIX from 2015 through April 2026 ($N = 2{,}812$). The contribution rests on four well-established methodological building blocks (asymmetric Granger causality, quantile regression, Diebold-Yilmaz spillover, Diebold-Mariano forecast comparison) applied jointly within a single framework, plus a multi-asset robustness extension to the NASDAQ-100 fear gauge.

Three contributions motivate the submission:

1. **Tail-concentrated sign-reversing structure.** The conditional response of equity fear to Bitcoin realized variance, estimated by quantile regression at $\tau \in \{0.05, 0.25, 0.50, 0.75, 0.95\}$, is significantly *negative* in the lower tail (e.g.\ $-2.86$ at $\tau = 0.05$), turns positive at the median ($+2.61$), and amplifies $8.5\times$ to $+22.31$ at the 95th percentile. The sign reversal at lower quantiles is, to our knowledge, a new finding; conditional-mean estimators (OLS, DCC-GARCH) average over the two regimes and obscure both halves. A multi-asset robustness check on the NASDAQ-100 fear gauge VXN preserves the sign-reversing structure across the index swap.

2. **COVID-2020 as a structural watershed.** A five-subperiod breakdown reveals that Granger causality from Bitcoin realized volatility to VIX is statistically significant only during 2020 ($F = 11.05$, $p < 10^{-6}$), with the four other subperiods (2015--2017, 2018--2019, 2021--2022, 2023--2026) all failing to reject non-causality. Combined with a Diebold-Yilmaz net-receiver decomposition of $-77$ percentage points for Bitcoin, the spillover reframes from "crypto as fear originator" to "crypto as fear amplifier conditional on pre-existing equity stress."

3. **Granger causality versus forecastability discipline.** Each in-sample finding is paired with an out-of-sample evaluation under the Harvey, Liu, and Zhu (2016) $|t| > 3$ multiple-testing threshold. The augmented AR(VIX) + BTC realized volatility specification fails the OOS DM test ($t = -0.98$, $p = 0.33$), and we report this null transparently as a methodological lesson rather than hiding it. Granger causality is a necessary but not sufficient condition for forecastability; informative signals concentrated in the upper tail and in a single subperiod do not necessarily improve point forecasts on average.

The paper is concise (17 pages, 22 references, 7 tables, 5 equations). A complete replication package — `reproduce.py` with **37 byte-match checks** against the manuscript's reported numbers (29 K1025 main + 8 K1025b multi-asset robustness), snapshot data CSVs, and signed JSON results — is included. The replication script returns `match_rate=100%` (`alert_level=green`).

The work fits JIMFIM's scope on cross-asset volatility spillover, financial fragility, and applied econometric methodology with cross-market evidence. The decomposition framework and the joint reporting discipline aim to supply a methodological template for the broader cryptocurrency-equity spillover literature.

This manuscript is not under consideration at any other journal and has not been previously published.

Thank you for your consideration. I look forward to your editorial assessment.

Sincerely,

**Yi-Hao Lai**
Associate Professor, Department of Finance
Da-Yeh University, Changhua, Taiwan
Email: yhlai@mail.dyu.edu.tw

---

## Notes for user before submission

- JIMFIM portal usually accepts plain-text cover letter; markdown headings can be stripped.
- Word count of body above: ~530 words (JIMFIM norm 400--800).
- Three contribution points are ordered by methodological depth: (1) the sign-reversal QR finding is the most novel; (2) the regime-watershed + DY net-receiver finding is the most actionable for policy; (3) the OOS NULL discipline is the methodological transferable lesson.
- The replication-package paragraph emphasizes 37-check `reproduce.py` (29 + 8) as unusually transparent for a multi-method spillover paper — JIMFIM editorial board values reproducibility, and `reproduce.py` byte-match goes beyond GitHub-link norms.
- "Not under consideration elsewhere" boilerplate required by all three target journals (JIMFIM, JEF, FRL).
- For JEF backup, the cover letter body text is reusable with two minor adjustments: replace "JIMFIM" → "JEF" and consider trimming contribution 3 (JEF reviewers may prefer methodological-novelty framing over discipline-lesson framing).
- For FRL backup short-form: trim cover letter to ~350 words and drop §6.4 multi-asset extension narrative from the contribution paragraph (FRL letter format does not have space for the extension table).
