# K1161 — Options-implied IV crush as continuous EAV regressor (DATA_INFEASIBLE)

> **TL;DR (Verdict: DATA_INFEASIBLE):** yfinance's option-chain API does not retain
> OHLC history for expired option contracts (5/5 expired contracts tested returned
> empty data), and currently-listed contracts retain only ~90 days of OHLC history
> (AAPL Dec-2028 LEAPS starts 2026-01-12 → 93 days span). Therefore historical
> IV_pre / IV_post cannot be reconstructed for any earnings event prior to the
> last ~90 days. Realistic coverage ceiling = **0 / 1,439 events = 0.00%**, far
> below the pre-registered 10% termination threshold. Per the prompt rule
> ("若覆蓋率 < 10% → 立即終止"), the experiment is terminated at the data
> feasibility step without fabricating IV values. **Paper 2 §5 implication:**
> K1148_d2 binary EAV claim (US OOS panel DM t=-5.58, PASS) retained as the
> main spec; no market-implied magnitude subsection can be added without a
> paid data source (OptionMetrics IvyDB, CBOE DataShop, ThetaData,
> HistoricalOptionData.com, ORATS, or Bloomberg OVDV).

[提出: Claude (承接 K1151 next_tasks K1161), 執行: Claude]

---

## 1. 動機（Why）

K1151 tested continuous `|Surprise(%)|` as an EAV regressor on the US N=30
panel and found it **NS** (cluster-bootstrap t=+1.11, p=0.41; placebo p=0.10;
AIC favours binary by 5479 units). Binary EAV remains sufficient.

K1161 asked a different question: **is market-aggregated, forward-looking
expectation (option-implied IV) a better signal than backward-looking,
accounting-based Surprise(%)?**

The proposed signal is **IV crush**: the collapse of ATM option-implied
volatility between the pre-earnings close (IV_pre, t-1) and the post-earnings
close (IV_post, t+1). Earnings-week option IV is well-known to be elevated
("vol risk premium") and to collapse at the event ("crush"). The magnitude
of the crush is a market-consensus, ex-ante measure of how big the event was
expected to be.

If IV crush dominated Surprise(%) in predicting realised vol uplift, Paper 2
§5 could be upgraded from a "binary event indicator" narrative to a "market-
implied magnitude" narrative — the stronger causal claim.

### Pre-registered scenarios (per prompt)

| Scenario | M3 IV crush PASS | M5 joint dominant regressor | Paper 2 §5 Implication |
|----------|------------------|------------------------------|-------------------------|
| **A: IV crush dominates** | ✅ (t ≤ −3) | IV crush | §5 adds "market-implied magnitude" subsection |
| **B: Complements binary** | ✅ (t ≤ −2) | Binary + IV crush both significant | Dual-factor narrative |
| **C: Only raw IV_pre matters** | M4 ✅ | IV_pre | "Forward expectation is the driver, crush magnitude is secondary" |
| **D: All IV NULL** | ❌ | — | IV signal < K1148_d2 binary EAV reliability |
| **DATA_INFEASIBLE** | — | — | **Experiment terminated at Step 1; coverage < 10%** |

**Actual outcome: DATA_INFEASIBLE.**

---

## 2. 方法（What was attempted）

### 2.1 Panel & earnings (reused from K1148_d2)

- **30 US S&P 500 large-caps** (AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA,
  BRK-B, UNH, V, JPM, WMT, MA, JNJ, XOM, PG, HD, CVX, ABBV, AVGO, COST, PEP,
  KO, MRK, ADBE, CSCO, TMO, CRM, MCD, ABT)
- **Earnings dates**: `experiments/k1148_d2/data/earnings_dates_surprise_us.json`
  — 1,439 events total, 120 per year × 12 years (2014-2025)

### 2.2 IV data requirement

For each earnings event `e` at date `t_e`, the experiment needed:
- `IV_pre = ATM option IV at close(t_e − 1)`
- `IV_post = ATM option IV at close(t_e + 1)`
- `IV_crush = IV_pre − IV_post`

Since yfinance does not expose IV directly in historical OHLC, the plan was:
1. Locate the ATM option contract (strike closest to spot, shortest expiry
   after `t_e`) for each earnings event.
2. Fetch its historical OHLC via `yf.Ticker(contract_symbol).history()`.
3. Back out IV at `t_e ± 1` via Black-Scholes (inverting mid-price with spot,
   strike, time-to-expiry, and risk-free rate).

### 2.3 Data feasibility probes (`k1161.py`)

Four probes were executed before any modelling:

| Probe | What it tested | Result |
|-------|----------------|--------|
| **P1** yfinance API sanity on current chain | Does `option_chain` return an `impliedVolatility` column? | ✅ Yes (AAPL: 69 rows, IV column present on all) |
| **P2** Earnings distribution across time | How many events are in recent vs old windows? | 1,439 total; 26 in last 6m (1.8%), 87 in last 1y (6.0%), 207 in last 2y (14.4%) |
| **P3** Expired-contract retrieval | Can `yf.Ticker('AAPL240315C00180000').history(period='2y')` return OHLC? | ❌ **0/5 tested expired contracts returned data** (AAPL240315C00180000, AAPL230721C00190000, MSFT240119C00330000, NVDA230915C00420000, AMZN231117C00140000 — all return "possibly delisted; no price data found") |
| **P4** Currently-listed reachback | How far back does OHLC go on the longest-dated LEAPS? | AAPL281215C00210000 (2028-12 expiry): only **93 days** of history, starting 2026-01-12 |

### 2.4 Coverage ceiling calculation

- If yfinance could serve 6 months of history on currently-listed contracts:
  coverage = 26/1,439 = **1.8%** (already < 10% threshold)
- If yfinance could serve 2 years: coverage = 207/1,439 = 14.4% (hypothetical)
- **Actual observed reachback: ~90 days** → events in last 90 days: 0/1,439 = **0.00%**
- Expired contracts retrieval rate: 0/5 = **0%**

Realistic coverage ceiling = **0.00% << 10% threshold**.

### 2.5 Pre-registered model specs (NOT EXECUTED)

These are documented for transparency — they would have been run if data
had been feasible:

| Spec | τ_{i,t} | Purpose |
|------|---------|---------|
| **M1 binary baseline** (K1148_d2 refit) | θ · EAV_{t-1} | Reference point |
| **M2 continuous Surprise** (K1151 baseline) | θ · \|Surprise_%\| · EAV_{t-1} | Comparison anchor |
| **M3 IV crush** (NEW) | θ · IV_crush · EAV_{t-1} | Primary hypothesis |
| **M4 IV_pre raw** (NEW) | θ · IV_pre · EAV_{t-1} | Forward expectation-only |
| **M5 horse race** | θ₁·EAV + θ₂·\|Surprise\| + θ₃·IV_crush | Joint regression; incremental t test |

OOS panel DM spec was to verbatim reuse K1148_d2's infrastructure: per-stock
DM-HLN on QLIKE(r²), stock-bootstrap 10,000 reps, Harvey (2016) joint PASS
threshold (t ≤ -2 AND p_one < 0.05), BH adjustment across 5 specs.

---

## 3. 結果（Feasibility findings）

### 3.1 API sanity (P1) — PASS

```
AAPL current option_chain:
  n_expirations   = 23
  first_exp       = 2026-04-17
  last_exp        = 2028-12-15
  calls_rows      = 69
  impliedVolatility column present = True
  IV rows > 0     = 69 / 69
```

yfinance's **current-day** option chain works. But this is only a snapshot;
for time-series IV we need historical OHLC on individual contracts.

### 3.2 Earnings distribution (P2)

| Window | N events | % of 1,439 |
|--------|----------|-----------|
| Last 6 months | 26 | 1.8% |
| Last 1 year | 87 | 6.0% |
| Last 2 years | 207 | 14.4% |
| Last 90 days | 0 (as of 2026-04-17 cache) | 0.0% |
| Total 2014-2025 | 1,439 | 100.0% |

The 2014-2023 block (>99% of events) is completely inaccessible.

### 3.3 Expired-contract retrieval (P3) — FAIL

5/5 expired contracts return empty data:
```
AAPL240315C00180000 → possibly delisted; no price data found
AAPL230721C00190000 → possibly delisted; no price data found
MSFT240119C00330000 → possibly delisted; no price data found
NVDA230915C00420000 → possibly delisted; no price data found
AMZN231117C00140000 → possibly delisted; no price data found
```

Yahoo Finance **purges expired options OHLC** — this is a known limitation
of the free API (confirmed by Gemini review). Any earnings event before
the most recent 1-2 quarters cannot be reconstructed via expired contracts.

### 3.4 Currently-listed reachback (P4) — very shallow

Tested against the **longest-dated** LEAPS on AAPL:
```
Contract:      AAPL281215C00210000 (exp 2028-12-15)
n_rows:        52
Date range:    2026-01-12 ~ 2026-04-16 (93 days)
```

Even with a 2.7-year expiry, Yahoo only retains ~90 days of OHLC. This is
Yahoo's server-side retention window, NOT the contract's inception date.
Therefore even currently-listed contracts only serve the **last 90 days**
of earnings, not the 2-year window one might have hoped for.

### 3.5 Coverage funnel

See `iv_crush_vs_surprise.png` (attached). Funnel:
- 1,439 total earnings events (2014-2025)
- 207 in last 2y (theoretical ceiling if yfinance had 2-year history — it does not)
- 87 in last 1y (still below 10%)
- 26 in last 6m (well below 10%)
- 0 in last 90 days (realistic ceiling, as of cache date 2026-04-17)

**0 / 1,439 = 0.00% coverage ceiling ⇒ DATA_INFEASIBLE.**

---

## 4. Gemini review (外部審查)

Gemini (via `gemini-cli`, 0.33.1) was asked to verify the feasibility logic:

> **(a) Is the expired-contract probe sound?** YES. Sampling 5 contracts
> across multiple tickers and expiration dates is statistically sufficient
> as a canary test. yfinance relies on Yahoo's public API, which purges
> expired option contracts once delisted.
>
> **(b) Is 90-day reachback a fair upper bound?** YES (and likely optimistic).
> Yahoo usually stores OHLC for active options only for the duration of
> their current listing, and often truncates granular history to the last
> few months. The LEAPS test confirms history is truncated to Yahoo's
> "start of tracking", not the contract's inception.
>
> **(c) Any free alternatives for pre-2026 individual IV?** NO for
> high-fidelity research. Free tiers of AlphaVantage / Polygon typically
> exclude options or cap history. CBOE DataShop, ThetaData, OptionMetrics,
> HistoricalOptionData.com all require payment for 10+ year individual-
> stock IV. VIX cannot substitute for individual IV (prompt §禁止).
>
> **(d) Is DATA_INFEASIBLE defensible?** DEFENSIBLE. With 0% coverage
> ceiling, the experiment cannot proceed without fabrication. Terminating
> at the data step prevents model hallucination and preserves research
> integrity. Recommendation: record the verdict; unblock requires budget
> for ThetaData Standard or HistoricalOptionData.com.

Full review in `run.log` (appended).

---

## 5. 結論

### Verdict: **DATA_INFEASIBLE**

yfinance does not provide the option-history depth required to build IV_pre /
IV_post for earnings events over the K1148_d2 2014-2025 panel. Under the
pre-registered prompt rule ("若覆蓋率 < 10% → 立即終止"), the experiment is
terminated at the data feasibility step.

### README Verdict section (per prompt Step 7 format)

```
## Verdict: DATA_INFEASIBLE

IV coverage: 0 / 1,439 events (0.00% << 10% threshold)
  - Expired contracts retrieval rate: 0/5 (tested)
  - Currently-listed contract reachback: ~90 days (Yahoo retention cap)
  - Events in last 90 days (cache date 2026-04-17): 0

M1 binary baseline OOS DM: NOT RUN
M2 continuous Surprise OOS DM: NOT RUN
M3 IV crush OOS DM: NOT RUN
M4 IV_pre OOS DM: NOT RUN
M5 joint horse race: NOT RUN

Paper 2 §5 upgrade candidate: NO — requires paid data source
Rationale: experiment terminated at data step per pre-registered rule
```

### Paper 2 §5 Implication

**No market-implied magnitude subsection can be added using free data.** The
current Paper 2 §5 narrative remains anchored on:

1. **K1148_d2 US binary OOS PASS** (panel DM t=-5.58, p<0.0001, 19/30 stocks
   individually DM ≤ -2) — Scenario A_BOTH decisive cross-market validation
2. **K1151 Surprise(%) NS** — binary EAV is the information-carrying spec;
   Surprise magnitude is noise at the event-day layer

K1161's DATA_INFEASIBLE verdict does NOT weaken these claims — it simply
documents that an alternative continuous regressor (IV crush) was considered
but could not be tested with free data. Future work with paid options data
could resurrect the hypothesis.

### Honest self-check (preamble rule #5)

1. **Mechanical vs empirical?** Terminating at data step is the correct
   response to an infeasible probe — not a mechanical result. The
   alternative would be to fabricate IV values (explicitly forbidden by
   the prompt) or use a bad proxy like VIX (also forbidden).
2. **vs research honesty principles?** Fully compliant:
   - Principle #2 (data transparency): yfinance limits documented
   - Principle #8 (null / infeasible as important as positive): reported
     in full with plots and logs
   - Principle #10 (acknowledge limits): the limitation is the experiment
3. **Would a different proxy change the conclusion?** The prompt explicitly
   forbids VIX as an individual-stock IV proxy. A synthetic IV built from
   realised vol pre/post would defeat the purpose (circular: predicting
   realised vol from realised vol).
4. **Result > 2x baseline?** N/A — no results produced.
5. **Strength vs evidence?** We claim exactly what we tested: yfinance
   cannot serve the data. We do NOT claim IV crush is irrelevant
   empirically — only that this specific experiment cannot be run.

### 局限 (limitations of the feasibility study itself)

1. Only `yfinance` was tested; `polygon.io` free tier and Alpha Vantage
   free tier were not explicitly probed, but Gemini review confirms they
   share the same restriction (no long historical individual-stock IV).
2. The 90-day reachback was probed on AAPL only; other tickers may vary
   slightly, but Yahoo's retention policy is platform-wide — no reason
   to expect materially different results.
3. An alternative free path exists in theory: scraping end-of-day option
   Greek snapshots from brokerage platforms (TD Ameritrade / Schwab API,
   IBKR) with a registered account. These APIs exist but are gated
   behind live-brokerage accounts and are not generally considered
   reproducible "free data sources". Flagged for K1161_b if pursued.

---

## 6. 衍生 next_tasks

| K ID | 主題 | 優先度 | 前置條件 |
|------|------|--------|----------|
| K1162 | Paper 2 §5 narrative finalisation: commit K1148_d2 (binary PASS) + K1151 (Surprise NS) + K1161 (IV crush DATA_INFEASIBLE) as the three-prong "event-day clustering, not surprise-magnitude" story | 高 | none |
| K1161_b | IF budget allows: buy 2-year ThetaData Standard ($80/mo) or HistoricalOptionData.com EOD greeks ($50/mo per ticker) for the 30 US tickers → retry M3/M4/M5 with proper IV data | 低 | requires funding decision |
| K1161_c | Alternative free angle: use SPY / sector ETF IV as market-level proxy for individual-stock IV crush regression (weak proxy but may detect aggregate signal) | 中 | none |
| K1163 | Replace IV crush with an **alternative free continuous signal**: (a) overnight pre-ann trading volume z-score; (b) pre-ann ATR change; (c) analyst estimate revision dispersion (via yfinance analyst estimates). These are information-content proxies that do not require options data | 高 | none |
| K1164 | Test whether the K1147 US binary result's magnitude scales with **firm size / analyst coverage** — heterogeneity across the 30-stock panel | 中 | none |

---

## 7. 檔案

- `k1161.py` — feasibility probe script (main entry point; DOES NOT run the
  planned M1-M5 spec pipeline — terminates at Step 1 per the 10% rule)
- `k1161_results.json` — feasibility results (API sanity, earnings counts,
  expired-contract probes, reachback probe, coverage ceiling, verdict)
- `iv_crush_vs_surprise.png` — coverage funnel showing why the experiment
  cannot proceed (total events → last-2y → last-6m → last-90d → 10% line)
- `theta_comparison.png` — placeholder annotated with DATA_INFEASIBLE
  rationale; provided so the file path from the prompt template exists
- `run.log` — full stdout of `k1161.py` execution (feasibility findings
  + probe outputs + verdict) plus Gemini review text
- `data/` — empty; no IV data was fabricated

---

## 8. 參考文獻

- Engle, Ghysels & Sohn (2013). GARCH-MIDAS. *REStat* 95(3), 776-797
  *(long-run τ framework for the ultimate K1161 model if data becomes available)*
- Patton (2011). Volatility forecast comparison using imperfect proxies.
  *JoE* 160(1), 246-256 *(OOS DM QLIKE loss — for the planned M1-M5 comparison)*
- Harvey, Liu & Zhu (2016). ... and the cross-section of expected returns.
  *RFS* 29(1), 5-68 *(t > 3 threshold; t > 2 OOS joint PASS criterion)*
- Patell & Wolfson (1979). Anticipated information releases reflected in
  call option prices. *JAR* 17(1), 117-140 *(classical IV crush paper;
  motivates IV_pre as forward expectation of earnings vol)*
- Dubinsky, Johannes, Kaeck & Seeger (2019). Option pricing of earnings
  announcement risks. *RFS* 32(2), 646-687 *(modern IV-crush decomposition)*

## 9. 相關 K 編號

- **K1145** — TW N=31 binary EAV pooled panel (IS PASS)
- **K1147** — US N=30 binary EAV pooled panel (IS boot t=+4.50, PASS)
- **K1148** — TW continuous |Surprise| EAV (OOS panel DM Marginal FAIL)
- **K1148_d1** — TW binary EAV OOS panel DM (Scenario B Marginal FAIL)
- **K1148_d2** — US binary + continuous EAV OOS panel DM (A_BOTH decisive PASS) — the baseline for K1161
- **K1151** — Continuous Surprise(%) on US N=30 (binary sufficient; continuous NS)
- **K1161** — **THIS**: IV-crush continuous regressor → DATA_INFEASIBLE
- **K1162** (next) — Paper 2 §5 narrative finalisation
