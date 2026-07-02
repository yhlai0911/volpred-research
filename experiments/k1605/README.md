# K1605 — Bank market-to-book / Tobin's Q divergence as a delayed-loss prior for regional-bank realized volatility

**Status**: Phase-1 (data diagnostic + descriptive + first-look lead-lag). Heavy
formal estimation deferred to the compute queue (`k1605_formal.py`).
**Data**: 100% free (yfinance). **Seed**: 20260702.

---

## 1. Motivation

The 2023 regional-bank crisis (SVB, Signature, First Republic) exposed a
timing gap in bank accounting: held-to-maturity (HTM) and available-for-sale
(AFS) securities carry **unrealized losses** that are largely invisible to
reported book equity and regulatory capital, yet are economically real. SVB
alone sat on ~$15B of HTM unrealized losses — over 90% of its total equity —
while still reporting healthy book value (Kansas City Fed, *Economic Review*
108(2), 2023; Boston Fed SRA note 2301, 2023).

The market prices these hidden losses (and credit deterioration) faster than the
balance sheet recognizes them. A bank whose **market cap trades at a discount to
book equity** (market-to-book, M/B < 1) — or whose M/B is **falling** — is
plausibly a stock where the market has already begun pricing a *delayed loss*
that has not yet hit book. **Hypothesis**: the market-to-book divergence in `t`
LEADS a rise in *realized* volatility (RV) at `t+5` / `t+22` for the stock and
for KRE/KBE.

### Why this could matter (mission fit)
A free, fundamentals-based leading indicator for regional-bank RV would feed
both content (a defensible "which banks are the market flagging?" article) and
strategy (a vol-timing / risk overlay signal). But the honest prior is mixed —
see §3.

## 2. Differentiation vs prior K

| Prior K | Relation | How K1605 differs |
|---|---|---|
| K1481 (inventory-surprise → commodity RV = **NULL**) | fundamental-feature → RV, NULL precedent | Different asset class + a market-priced (not physical) fundamental; explicit delayed-loss channel |
| K1162 (EAV binary fundamental = NS) | fundamental → cross-section, NS precedent | M/B is a *valuation* signal, not an accounting level; tests RV not EAV |
| K1001 (VIX GARCH-X > macro fundamental) | implied beats fundamental | K1605 uses a *balance-sheet-valuation* signal, not macro; cross-sectional, not GARCH-X |
| K1104/K1106b (firm θ₂ fundamental) | firm-level fundamental → param | Different target (RV lead-lag) + different signal (M/B) |
| K1301/K1303/K450/K456 (semivariance/HAR) | RV/semivariance methods | Reused RV + downside semivol construction only; no signal overlap |

Knowledge-base check (jq over `knowledge.json`): **zero** coverage of
bank / market-to-book / Tobin's Q / KRE / KBE / HTM-AFS. No double-agent
(`experiments/k1605` and worktrees clean at start).

**Honest prior from the literature**: cross-sectional evidence that Tobin's Q /
book-to-market predicts *volatility* (as opposed to *returns*) is **weak and
mixed**. A MENA panel study finds Tobin's Q insignificant for stock-return
volatility after firm/time controls; the NBER structural model (w17975, Kogan &
Papanikolaou) ties Q to *idiosyncratic vol* through investment-specific shocks
but does not establish Q as a *forward RV predictor incremental to lagged RV*.
So a NULL or WEAK result would be fully consistent with existing evidence — we
report it as such if that is what the data shows.

## 3. Data

| Series | Source | Coverage |
|---|---|---|
| KRE, KBE adjusted close | yfinance `history` | 2005/2006 → present (long) |
| ~29 regional-bank constituents, adjusted close | yfinance `history` | 2020 → present |
| Book equity (Common Stock Equity) | yfinance `balance_sheet` (annual, 2021–2025) + `quarterly_balance_sheet` (2024Q4–2026Q1) | see diagnostics |
| Shares outstanding history | yfinance `get_shares_full` | 2018 → present (step) |

**Constituent list** (survivors only): RF, KEY, CFG, HBAN, FITB, MTB, ZION,
CMA, WAL, PNC, USB, TFC, FHN, SNV, CFR, WBS, VLY, ONB, CBSH, BOKF, EWBC, WTFC,
UMBF, FNB, ASB, BKU, HWC, PB, RJF. Chosen as currently-listed mid/regional banks
representative of KRE/KBE holdings.

### Data limitations (reported as first-class findings)
1. **Book-equity history is thin.** yfinance provides only ~5 annual + ~6
   quarterly book-equity points per bank. Lag-safe book equity therefore only
   spans ~2022 → present, and the *fundamental* information updates just a few
   times per bank. Daily M/B variation comes mostly from **price** (see #2).
2. **Price confound.** Because M/B = (price·shares)/book and book steps only
   quarterly, daily M/B moves are dominated by price. Price is mechanically tied
   to RV (volatility clustering + persistence), so a raw "M/B predicts RV"
   finding could be spurious. **Every predictive test controls for trailing
   own-RV** so the reported M/B effect is *incremental* to the volatility-
   persistence baseline.
3. **Survivorship bias.** The banks whose M/B-divergence → RV signal would be
   strongest (SVB, SBNY, FRC — all failed 2023) are absent because their
   fundamentals are no longer retrievable. This biases the survivor cross-section
   **toward NULL / underpowered**. Flagged explicitly.

## 4. Method

- **Signal (lag-safe M/B).** For each bank, `M/B(t) = price(t)·shares_avail(t) /
  book_avail(t)`, where `book_avail(t)` is the most recent book equity whose
  **conservative filing-available date** (quarter_end + 45d, or fiscal_year_end
  + 75d) is `≤ t`. Signals are additionally `shift(1)` (info through `t-1`).
- **Targets.** Forward annualized RV over `(t, t+H]`, `H ∈ {5, 22}`; forward
  downside semivol likewise. Trailing 22-day RV is the control / baseline.
- **Time-series test.** Cross-sectional median `log M/B(t-1)` (and its 22-day
  change) → KRE/KBE forward RV, via Newey-West OLS with **HAC lag = H** (to
  absorb the MA(H−1) autocorrelation from overlapping forward windows), always
  **including trailing own-RV** as a control.
- **Cross-sectional test (K1355-compliant).** Fama-MacBeth: each date run a
  cross-sectional regression `fwdRV_i = a + b·logM/B_i(t-1) [+ c·lagRV_i]`
  across banks; collect `b(t)`; then HAC (lag ≥ H) the **time series of `b(t)`**.
  This aggregates by date before inference — it does **not** treat asset-days as
  iid, per the K1355 rule.

### Lookahead protection (head risk #1)
- Book equity never aligned to period-end; always to a conservative
  filing-available date (10-Q +45d, 10-K +75d).
- All signals `shift(1)`; forward RV strictly over future window `(t, t+H]`.
- Multi-horizon: HAC/inference horizon = the target's own `H`.

## 5. Success criteria / verdict rule

Phase-1 first-look verdict (conservative, |t|>2 on *incremental*, lagRV-
controlled, correct-sign tests):
- **signal**: ≥3 incremental tests with correct sign (M/B↓ → RV↑) and |t|>2.0
- **weak**: 1–2 such tests
- **null**: 0

Formal DM/Harvey `|t|>3`, block-bootstrap CIs, panel HAC with full controls, and
OOS expanding-window refit are **deferred to the compute queue** (see §6). A
Phase-1 "signal/weak" is only a *screen*, never a publication claim.

## 6. Phase-1 vs deferred scope

- **Phase-1 (this run)**: data diagnostic, descriptive M/B dispersion + 2023
  stress case study, first-look time-series + Fama-MacBeth lead-lag with
  lagRV control and HAC.
- **Deferred → `k1605_formal.py` (compute queue)**: (a) DM test of an
  M/B-augmented RV forecast vs an RV-only (HAR-lite) baseline; (b) block
  bootstrap CIs on the Fama-MacBeth means; (c) OOS expanding-window refit with
  `target_end < forecast_origin` guard; (d) downside-semivol targets;
  (e) robustness to filing-lag assumption (45/60/90d).

## 7. Reproduce

```bash
uv run python experiments/k1605/k1605.py          # Phase-1
# heavy formal (enqueue, not inline):
uv run python scripts/compute_queue.py enqueue \
  --script experiments/k1605/k1605_formal.py \
  --title "K1605 formal RV lead-lag" \
  --result-artifact experiments/k1605/k1605_formal_results.json \
  --followup-brief "解讀 K1605 formal panel/DM/bootstrap 結果" \
  --followup-task-type paper_review --timeout 3600
```

Outputs: `k1605_results.json`, `k1605_fig1_mb_dispersion.png`,
`k1605_fig2_scatter_kre.png`, `k1605_fig3_fama_macbeth.png`.

## 8. References (literature anchors, trend-level; verify before paper use)

1. Marsh, W. B., & Laliberte, B. (2023). *The Implications of Unrealized Losses
   for Banks.* Federal Reserve Bank of Kansas City, Economic Review 108(2).
2. Federal Reserve Bank of Boston (2023). *Accounting for Debt Securities in the
   Age of Silicon Valley Bank.* SRA Note 2023-01.
3. Congressional Research Service (2023). *Banks' Unrealized Losses* (IN12231/
   IN12232).
4. Kogan, L., & Papanikolaou, D. (2012/2013). *A Theory of Firm Characteristics
   and Stock Returns: The Role of Investment-Specific Shocks.* NBER WP 17975 /
   RFS. (Tobin's Q ↔ idiosyncratic vol via IST shocks.)
5. Campbell, J. Y., Hilscher, J., & Szilagyi, J. *Predicting Financial Distress
   and the Performance of Distressed Stocks.*
6. *The Dynamics of Performance Volatility and Firm Valuation*, JFQA (M/B ↔
   performance-volatility dynamics).
7. MENA panel evidence: Tobin's Q insignificant for stock-return volatility
   after firm/time controls (cited as the mixed/null prior).

*References are trend-level anchors from web search; exact metadata must be
re-verified via citation-verifier before any paper use.*
