# Blog Fact-Check 2026-06-27

## Motivation

User asked whether this Blogger article can be verified:

`https://kelvenslife.blogspot.com/2026/06/blog-post_27.html`

The article mixes verifiable market facts with causal claims about political
actors, Wall Street, corporate insiders, and retail investors. This experiment
separates:

1. claims that can be verified from official or downloadable aggregate data;
2. claims that are partially supported but not final facts;
3. claims that require micro-level trade records or regulator findings.

## Data Sources

- Blog article HTML: Blogger URL above.
- SOX index: FRED `NASDAQSOX` CSV, `https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQSOX`.
- TWSE market turnover: `https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK`.
- TWSE institutional cash-market flow: `https://www.twse.com.tw/rwd/zh/fund/BFI82U`.
- TAIFEX institutional futures position: `https://www.taifex.com.tw/cht/3/futContractsDateDown`.
- Trump Truth Social archive: American Presidency Project, `https://www.presidency.ucsb.edu/documents/truth-social-posts-april-9-2025`.
- OpenAI IPO reference: official OpenAI confidential S-1 page, `https://openai.com/index/openai-submits-confidential-s-1/`.

## Method

Run:

```bash
python3 experiments/blog_factcheck_20260627/blog_factcheck_20260627.py
```

The script:

1. extracts the article text and stores short snippets around target claims;
2. downloads FRED SOX daily data and calculates selected-window returns;
3. downloads TWSE market data for TAIEX and 2026-06-26 turnover;
4. downloads TWSE institutional flow totals for 2026-03-27 to 2026-06-26 using late-March daily values plus April, May, and June monthly aggregates;
5. downloads TAIFEX TXF institutional futures CSV for 2026-06-26 and decodes Big5;
6. checks the 2025-04-09 Truth Social archive for the buy-call and tariff-pause posts;
7. classifies each claim into factual, partly supported, or not proven.

No random process is used; `seed=null` in the result JSON.

## Results

Output:

- `blog_factcheck_20260627_results.json`

### Claim-Level Verdict

| Claim | Verdict | Evidence |
|---|---|---|
| SOX rose about 80% in one quarter from late March | Mostly true, rounded up | FRED: 2026-03-27 to 2026-06-26 = +77.047%; 2026-03-31 to 2026-06-26 = +74.001%. |
| Trump posted a buy call on 2025-04-09 and tariff pause occurred same day | True for date and posts | American Presidency Project archive contains the buy-call phrase and 90-day pause post. |
| Foreign investors had about 70k TXF short futures contracts | True for 2026-06-26 net position | TAIFEX TXF foreign net open interest = -76,391 contracts. |
| Since late March, foreign investors almost did not net buy Taiwan stocks | True, stronger than stated | TWSE cash-market flow: 2026-03-27 to 2026-06-26 = net sell NTD 293.85bn, or about 2,938.5 億元. From 2026-04-01 only = net sell NTD 112.81bn. |
| Taiwan market turnover was very high on 2026-06-26 | True | TWSE turnover = NTD 1.6728tn; TAIEX close = 44,571.76, daily change = -1,683.50. |
| OpenAI is going public this year at USD 1tn valuation | Partly supported, needs caution | Confidential S-1 or media valuation reports are process/expectation evidence, not final IPO date or final valuation. |
| The observations prove coordinated manipulation / retail setup | Not proven by aggregate data | Requires beneficial-owner records, order-book/broker sequencing, or regulator/legal findings. |

## Interpretation

The article is not pure fabrication. Several market observations are materially
supported:

- SOX did rally roughly mid-70% from late March to 2026-06-26.
- Foreign investors were net short TXF by about 76k contracts on 2026-06-26.
- Foreign investors were net sellers, not net buyers, in TWSE cash-market flow
  over the selected window.
- 2026-06-26 Taiwan turnover was indeed above NTD 1.6tn.

But the article's strongest conclusion is not established. Aggregate data can
show price movement, cash-market flow, futures positioning, and turnover. It
cannot identify "left-hand-right-hand" trading, coordinated manipulation, or
named actors profiting unless we have trade-level ownership records, order-book
evidence, or a regulator/legal finding.

## Internal Context

Relevant project memory found before running:

- Taiwan sentiment indicators have often failed as predictive signals.
- Foreign net buy/sell can be contemporaneous or lagging, so it should not be
  treated as causal evidence without a lagged design.
- Same-day relationships are not sufficient for causal claims.

Therefore this experiment makes no trading signal claim and does not write to
`storage/memory/knowledge.json`.

## Limitations

- OpenAI official pages may block non-browser fetches. The script records the
  source URL but does not use that page as a numeric source.
- The SOX return depends on how "late March" is operationalized. Using 2026-03-27
  yields +77.0%; using 2026-03-31 yields +74.0%.
- TAIFEX futures net short is not equivalent to directional speculation; it may
  include hedge and arbitrage positions.
- TWSE foreign cash flow is aggregate-level and cannot identify who ultimately
  held the shares after trades.
- This is a fact-check memo, not a formal causal study of manipulation.
