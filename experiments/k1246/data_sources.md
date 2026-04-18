# Paper 10 — Data Sources

**Paper**: The Crypto Fear Channel — Asymmetric, Tail-Concentrated, and Regime-Dependent Volatility Spillover from Bitcoin to Equity Markets
**Status**: drafting
**Compliance**: Item (1) of the 5-item self-contained paper folder checklist (`docs/paper-guide.md`).
**Last updated**: 2026-04-17

---

## 1. Series

Three daily series constitute the primary dataset. All three are retrieved from
Yahoo Finance via the `yfinance` Python package (open-source, no licensing
restriction on academic reproduction, see §4 below).

| Ticker    | Role                     | Type          | Coverage window (retrieved 2026-04-08, extended 2026-04-14 for §6.5) |
|-----------|--------------------------|---------------|----------------------------------------------------------------------|
| `BTC-USD` | Cryptocurrency proxy     | Close price   | 2015-01-01 — 2026-04-14                                              |
| `^VIX`    | Equity-fear proxy        | Index level   | 2015-01-02 — 2026-04-14                                              |
| `SPY`     | Equity market proxy      | Adjusted close | 2015-02-02 — 2026-04-08                                              |

**Aligned sample in main body (K1025 primary framework)**: $N = 2{,}812$ daily
observations from 2015-02-02 to 2026-04-08, after intersecting the three
trading calendars.

**Extended sample in §6.5 (K1241 pooled GARCH-X robustness)**: $N = 4{,}120$
daily observations from 2015-01-03 to 2026-04-14, using VIX forward-fill on
BTC-only weekend dates (see §3.2 below).

Start date (2015-02-02) is the earliest point at which BTC-USD, SPY, and VIX
all have reliable daily closing prices on Yahoo Finance, per the coverage
verified in K639 and K1025.

## 2. Retrieval (one-shot reproduction)

```python
import yfinance as yf
data = yf.download(
    ["BTC-USD", "^VIX", "SPY"],
    start="2015-01-01",
    end="2026-04-15",
    auto_adjust=False,
    progress=False,
)
# Use Close (not Adj Close) for BTC-USD and ^VIX (neither has splits/dividends);
# Use Adj Close for SPY (to handle dividends/splits across 11-year window).
```

The K1025 script (`experiments/k1025/k1025.py`) and K1241 script
(`experiments/k1241/k1241.py`) both embed equivalent retrieval loops. Both are
reproducible as long as Yahoo Finance continues to serve the three symbols with
their historical data; no paid API key is required.

## 3. Preprocessing

### 3.1 Returns and realized volatility

- **Log returns** for SPY and BTC-USD: $r_{i,t} = \ln(P_{i,t}/P_{i,t-1})$.
- **VIX** used directly at close-of-day level (not returns) — standard
  Diebold-Yilmaz convention.
- **20-day annualized realized volatility**:
  $\mathrm{RV}_{i,t}^{(20)} = \sqrt{252} \cdot \sqrt{\tfrac{1}{20}\sum_{k=0}^{19}(r_{i,t-k}-\bar{r}_i)^2}$.

### 3.2 Calendar alignment (primary vs §6.5 robustness)

- **Primary (§3–§7 main body)**: intersect the three trading calendars.
  Weekends and U.S. holidays on which SPY/VIX do not quote are discarded.
  No forward-fill, no imputation. This is the K1025 convention.
- **§6.5 robustness (K1241 pooled GARCH-X)**: retain the full BTC-USD daily
  calendar (which trades 7 days a week); forward-fill `^VIX` onto BTC-only
  dates. Rationale: "fear state persists across the weekend" — standard
  in Bouri et al. (2020) and Matkovskyy & Jalan (2019). This expands the
  sample from 2,812 to 4,120 observations.

### 3.3 Asymmetric decomposition (used in §5.1)

$r^{+}_{\mathrm{BTC},t} = \max(r_{\mathrm{BTC},t}, 0), \quad r^{-}_{\mathrm{BTC},t} = \min(r_{\mathrm{BTC},t}, 0).$

Partial realized-volatility series $\mathrm{RV}^{\pm}_{\mathrm{BTC},t}$ follow
Hatemi-J (2012) cumulative-sum transformation before entering the asymmetric
Granger VAR.

### 3.4 Lookahead-bias discipline

All forecasting signals on date $t$ use only information available through
$t-1$. In K1025, this is enforced in code by `signal.shift(1)` before any
Diebold-Mariano comparison. In K1241, the VIX$^2$ regressor is explicitly
lagged one trading day before entering the conditional-variance recursion;
K1241 includes an `allclose` assertion against a reconstructed reference
shifted series (line ~161 of `k1241.py`) to prevent silent lookahead drift.

### 3.5 Random seed

All downstream random procedures (bootstrap, sub-sample Granger tests,
rolling Diebold-Yilmaz) use `seed = 42`, set at the top of each K script.

## 4. License, access, and reproducibility

- **yfinance**: MIT-licensed Python wrapper around Yahoo Finance public data.
  No API key required. Yahoo Finance Terms of Service govern the underlying
  data; academic reproduction (non-commercial) has been standard in the
  empirical finance literature since at least Bouri et al. (2017).
- **Risks to long-run reproducibility**:
  - Yahoo Finance may adjust historical splits/dividends for SPY; we use
    `auto_adjust=False` and pull raw `Close` consistently.
  - BTC-USD history on Yahoo is aggregated from CoinMarketCap; very early
    points (pre-2015) show occasional missing bars, which is why our sample
    starts 2015-02-02 after confirming data integrity across all three
    series.
  - VIX historical series has no known revision from CBOE.
- **Replication fallback**: If Yahoo Finance becomes unavailable, the raw
  retrieved CSVs for §6.5 are snapshotted inside `experiments/k1241/` and
  for §5 framework inside `experiments/k1025/` (when present). Snapshot
  CSVs are not the canonical source, but they allow bit-for-bit
  replication of paper numbers in the event of upstream data loss.

## 5. 5-item compliance cross-reference (`docs/paper-guide.md`)

| Item | paper-guide requirement | Source in this file |
|------|--------------------------|---------------------|
| (1) Data origin, period, license | Yahoo Finance via yfinance; 2015-02-02 to 2026-04-14; MIT-licensed wrapper | §1, §2, §4 |
| (1.a) Exact period | 2015-02-02 to 2026-04-08 (primary), extended to 2026-04-14 (§6.5) | §1 |
| (1.b) API endpoint | `yfinance.download([...])` | §2 |
| (1.c) License terms | MIT (wrapper) + Yahoo ToS (underlying data); academic non-commercial use standard | §4 |
| (1.d) Data path on disk | snapshots in `experiments/k1025/` and `experiments/k1241/` if upstream fails | §4 |

## 6. Version log

| Date       | Change                                                                                    | K source |
|------------|-------------------------------------------------------------------------------------------|----------|
| 2026-04-08 | Primary 2015-02-02 – 2026-04-08 sample (N=2,812) established for §3–§7                    | K1025    |
| 2026-04-14 | Extended 2015-01-03 – 2026-04-14 sample (N=4,120) with VIX weekend forward-fill for §6.5   | K1241    |
| 2026-04-17 | Paper renumbered from Paper 6 to Paper 10                                                  | outline  |

## 7. See also

- `experiments.md` — supporting K-experiment index (item 4 of the 5-item checklist)
- `scripts/README.md` — reproduction entry points (part of item 2)
- `experiments/k1025/` — primary framework (K1025 script and JSON)
- `experiments/k1241/` — pooled GARCH-X NULL (K1241 script and JSON)
- `experiments/k639/` — BTC→SPY Granger baseline
- `experiments/k746b/` — asymmetric BTC→VIX Granger
