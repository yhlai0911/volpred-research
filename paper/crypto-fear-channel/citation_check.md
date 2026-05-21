# Paper 10 (crypto-fear-channel) — Citation Audit

**Status**: Initial inventory 2026-05-11 (24 unique citations extracted from `main.tex`)
**Target**: Verify each citation is real (DOI / arXiv / journal URL), correctly attributed, and load-bearing in the narrative position where used.

## Inventory by topical cluster

### Crypto-equity volatility spillover (core literature)

- `bouri2020` — Bouri, Lucey, Roubaud (2020) "The volatility surprise of leading cryptocurrencies" — VERIFY: J Bank Finance / Finance Research Letters?
- `corbet2018` — Corbet, Lucey, Yarovaya (2018) "Datestamping the Bitcoin and Ethereum bubbles" — VERIFY: Finance Research Letters
- `klein2018` — Klein, Pham Thu, Walther (2018) "Bitcoin is not the New Gold" — VERIFY: International Review of Financial Analysis
- `conrad2020` — Conrad, Custovic, Ghysels (2020) — VERIFY: spillover paper (Energy Economics? J Empirical Finance?)
- `matkovskyy2019` — Matkovskyy, Jalan (2019) "From financial markets to Bitcoin markets" — VERIFY: International Review of Financial Analysis / Finance Research Letters
- `shahzad2019` — Shahzad, Bouri, Roubaud, Kristoufek, Lucey (2019) "Is Bitcoin a better safe-haven investment than gold and commodities?" — VERIFY: International Review of Financial Analysis
- `akyildirim2020` — Akyildirim, Corbet, Lucey, Sensoy, Yarovaya (2020) "The relationship between implied volatility and cryptocurrency returns" — VERIFY: Finance Research Letters
- `yarovaya2022` — Yarovaya, Brzeszczynski, Goodell, Lucey, Lau (2022) "Rethinking financial contagion: Information transmission mechanism during the COVID-19 pandemic" — VERIFY: J Int Financial Markets Institutions Money / Finance Research Letters
- `iyer2022` — Iyer (2022) — VERIFY: which "iyer 2022" paper exactly (multiple candidates in crypto literature)
- `conlon2020` — Conlon, McGee (2020) "Safe haven or risky hazard? Bitcoin during the Covid-19 bear market" — VERIFY: Finance Research Letters

### Methodology — Granger / asymmetric causality

- `hatemi2012` — Hatemi-J (2012) "Asymmetric causality tests with an application to the United States" — VERIFY: Empirical Economics
- `diks2006` — Diks, Panchenko (2006) "A new statistic and practical guidelines for nonparametric Granger causality testing" — VERIFY: J Econ Dynamics & Control
- `hong2001` — Hong (2001) "A test for volatility spillover with application to exchange rates" — VERIFY: J Econometrics

### Methodology — quantile regression

- `koenker1978` — Koenker, Bassett (1978) "Regression Quantiles" — VERIFY: Econometrica (foundational)
- `adrian2016` — Adrian, Brunnermeier (2016) "CoVaR" — VERIFY: American Economic Review

### Methodology — spillover index

- `diebold2009` — Diebold, Yilmaz (2009) "Measuring financial asset return and volatility spillovers, with application to global equity markets" — VERIFY: Economic Journal
- `diebold2012` — Diebold, Yilmaz (2012) "Better to give than to receive: Predictive directional measurement of volatility spillovers" — VERIFY: Int J Forecasting
- `diebold2014network` — Diebold, Yilmaz (2014) "On the network topology of variance decompositions" — VERIFY: J Econometrics
- `diebold1995` — Diebold, Mariano (1995) "Comparing predictive accuracy" — VERIFY: J Business & Economic Statistics

### Methodology — OOS forecasting / multiple-testing thresholds

- `harvey1997` — Harvey, Leybourne, Newbold (1997) "Testing the equality of prediction mean squared errors" — VERIFY: Int J Forecasting (HLN small-sample DM adjustment)
- `harvey2016` — Harvey, Liu, Zhu (2016) "...and the cross-section of expected returns" — VERIFY: Review of Financial Studies (|t|>3 threshold)
- `andrews1991` — Andrews (1991) "Heteroskedasticity and autocorrelation consistent covariance matrix estimation" — VERIFY: Econometrica (HAC/Newey-West)

## Quick-win sanity checks (TODO before submission)

1. Each citation has a `\bibitem` in the same .tex file or imported .bib file — `grep \\\\bibitem main.tex` count
2. Each `\citet/\citep` key resolves at compile time (`grep "undefined references" main.log`)
3. No 2025+ citations (paper sample ends 2026-04 but most published cites should be ≤2024)
4. Cross-check on Google Scholar / DOI for each VERIFY tag
5. NotebookLM-RAG fact-check pass: feed PDFs of 5 most load-bearing cites (diebold2012, hatemi2012, harvey2016, corbet2018, bouri2020) into a `paper10_citations` notebook and ask whether body's framing of each matches the source paper's actual claim

## Followup workflow

- Run `paper-review-cycle` skill's `citation-verifier` sub-agent when Codex quota resets (2026-05-12 19:46 PT)
- That agent automates the VERIFY tags + Google Scholar fact-check pass + populates an authoritative bib summary

## Provenance

- Generated 2026-05-11 by main-thread `grep -oE` extraction from `main.tex` (24 unique citations)
- No external lookup yet performed; this file is the inventory + workflow scaffold for the eventual verifier pass
