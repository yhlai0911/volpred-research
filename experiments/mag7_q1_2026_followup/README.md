# mag7_q1_2026_followup

Source-attributed rewrite support for `mile_d716099a` (Mag 7 Q1 2026 financial reports article).

## Why this folder exists

Codex paper review on 2026-05-07 returned **FAIL** on the original 2026-05-06 article (`mile_d716099a`):

- **CRITICAL**: Meta FY2026 capex prior range cited as $114–118B, but official disclosure was **$115–135B** (raised to $125–145B). Source: investor.atmeta.com Q1 2026 press release.
- **MAJOR 1**: $725B hyperscaler capex aggregate had no per-company source breakdown.
- **MAJOR 2**: MSFT AI +123% / Alphabet Cloud +63% lacked claim-level attribution.
- **MAJOR 3**: "earnings healthy 縮水" conclusion lacked shown math.
- **MAJOR 4**: "all numbers from SEC 8-K" overstated provenance ($725B is a market analyst aggregate).

This folder hosts the rewrite assets:

- `generate_charts.py` — Reproducible matplotlib script that builds the 3 PNG charts and uploads them to Supabase article-images bucket. Hard-codes per-company numbers from each Q1 2026 official press release (sources commented inline).
- `mag7_q1_2026_capex_guide.png` — Bar chart: 4 hyperscalers' FY2026 capex guide ranges + Q1 2026 actual.
- `mag7_q1_2026_ni_vs_capex.png` — Bar chart: GAAP NI vs Q1 capex with one-time gain hatching (Meta tax benefit, Amazon Anthropic mark-up).
- `mag7_q1_2026_ai_growth.png` — Horizontal bar: AI/Cloud YoY growth across 5 companies, source URL annotated per row.

## Reproduce

```bash
uv run python experiments/mag7_q1_2026_followup/generate_charts.py
```

Re-uploads the same filenames to Supabase (`x-upsert: true`); the rewritten article references the public URLs in the `article-images` bucket so updates flow through automatically.

## Number provenance (canonical)

| Datapoint | Value | Source URL |
|---|---|---|
| Meta FY2026 capex prior range | $115–135B | https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-First-Quarter-2026-Results/default.aspx |
| Meta FY2026 capex raised range | $125–145B | (same) |
| Meta tax benefit | $8.03B | (same — US Treasury Notice 2026-7) |
| Microsoft Q3 capex | $31.9B | https://www.microsoft.com/en-us/investor/earnings/fy-2026-q3/press-release-webcast |
| Microsoft FY2026 capex guide | ~$190B | (same) |
| MSFT AI run-rate +123% | $37B run-rate | https://news.microsoft.com/source/2026/04/29/microsoft-cloud-and-ai-strength-fuels-third-quarter-results/ |
| Alphabet Q1 capex | $35.7B | https://s206.q4cdn.com/479360582/files/doc_financials/2026/q1/2026q1-alphabet-earnings-release.pdf |
| Alphabet FY2026 capex guide | $180–190B | (same) |
| Alphabet Cloud +63% | $20.0B Cloud rev | (same) |
| Amazon Q1 capex | $44.2B | https://ir.aboutamazon.com/news-release/news-release-details/2026/Amazon-com-Announces-First-Quarter-Results/ |
| Amazon FY2026 capex (Feb proj) | ~$200B | (same) |
| Amazon Anthropic mark-up | $16.8B pre-tax | (same — non-operating gain disclosure) |
| AWS +28% | $37.59B | (same) |
| Meta Q1 revenue +33% | $56.31B | https://investor.atmeta.com/... |
| Apple Q2 FY26 revenue +17% | $111.2B | https://www.apple.com/newsroom/2026/04/apple-reports-second-quarter-results/ |

## Safety notes

- This folder contains **no backtest, no signal, no model fitting** — only chart-rendering of public financial-disclosure numbers. lookahead/seed rules in `.claude/rules/experiments.md` do not apply (those govern strategy backtests).
- All numbers are public Q1 2026 disclosures published 2026-04-29 and 2026-04-30; verified via WebSearch on 2026-05-08.
- The associated rewrite of `mile_d716099a` set `errata.action = rewrite_complete` per the standard rewrite_complete pattern (matches `mile_d70be85c` precedent).
