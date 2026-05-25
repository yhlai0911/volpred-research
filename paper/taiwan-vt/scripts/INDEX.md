# Scripts Index — Paper 2: Volatility Targeting in Taiwan

All experiment scripts are stored in `paper/taiwan-vt/experiments/` and the shared
`experiments/` root. This index groups them by paper section and links to the canonical
entry-point `.py` file. **Do not copy or symlink scripts here** — run them in place.

## Reproduction Entry Point

| Script | Purpose |
|--------|---------|
| [`../reproduce.py`](../reproduce.py) | Master number-verification script — loads all experiment JSONs and compares against body_v2.tex / section5_hf_draft.tex claimed values |

---

## Section 2: Data and Methodology

| Experiment | Script | Purpose |
|------------|--------|---------|
| K892 | [`../experiments/k892_verify_tw_gamma.py`](../experiments/k892_verify_tw_gamma.py) | Canonical GJR-GARCH(1,1) gamma for 0050.TW / TWII / TSMC (resolves paper conflict) |
| K1302 | [`../../experiments/k1302/k1302.py`](../../experiments/k1302/k1302.py) | Table 2 individual-stock γ rebuild — 9 stocks, 100-multistart, full provenance |
| K1302b | [`../../experiments/k1302b/k1302b.py`](../../experiments/k1302b/k1302b.py) | GJR-GARCH γ for 5 unlisted Taiwan individual stocks |
| K1181 | [`../../experiments/k1181/k1181.py`](../../experiments/k1181/k1181.py) | VIXTWN stats + Steiger Z reproduction (VIX-proxy motivation) |

---

## Section 3: The Leverage Effect in the Taiwan Market

| Experiment | Script | Purpose |
|------------|--------|---------|
| K892 | [`../experiments/k892_verify_tw_gamma.py`](../experiments/k892_verify_tw_gamma.py) | Canonical gamma values; Table 1–2 source |
| K1302 | [`../../experiments/k1302/k1302.py`](../../experiments/k1302/k1302.py) | Individual stock gamma panel (9 stocks) |
| K1370 | [`../../experiments/k1370/k1370.py`](../../experiments/k1370/k1370.py) | Block-bootstrap 90% CI for TAIEX-to-individual amplification ratio (canonical BW-robust) |
| K1370c | [`../../experiments/k1370c/k1370c.py`](../../experiments/k1370c/k1370c.py) | N_start sensitivity micro-test for K1370 |
| K636 | [`../../experiments/k636/k636.py`](../../experiments/k636/k636.py) | Taiwan amplification factor deep dive (regime and period analysis) |
| K461 | [`../experiments/k461_ssvs_taiwan.py`](../experiments/k461_ssvs_taiwan.py) | SSVS macro predictors — SPY cross-market spillover (Sec 3.3) |

---

## Section 4: Volatility Targeting Strategies for Taiwan

| Experiment | Script | Purpose |
|------------|--------|---------|
| K1175 | [`../../experiments/k1175/k1175.py`](../../experiments/k1175/k1175.py) | Table 3 VT 2010–2026 canonical replication (buy-hold / EWMA / GJR / VIX-863) |
| K900 | [`../experiments/k900_taiwan_vt_performance.py`](../experiments/k900_taiwan_vt_performance.py) | VT performance tables — full-period and common-period comparison |
| K886 | [`../experiments/k886_prg_0050tw.py`](../experiments/k886_prg_0050tw.py) | PRG strategy on 0050.TW (daily frequency, multi-layer evaluation) |
| K472 | [`../../experiments/k472/k472_taiwan_comprehensive.py`](../../experiments/k472/k472_taiwan_comprehensive.py) | Comprehensive vol-prediction integration (EWMA / HAR / semivariance) |
| K553 | [`../experiments/k553_leveraged_vt_taiwan.py`](../experiments/k553_leveraged_vt_taiwan.py) | VIX-conditional leverage VT variants — Taiwan adaptation |
| K558 | [`../experiments/k558_k553_taiwan_validation.py`](../experiments/k558_k553_taiwan_validation.py) | K553 deep validation for strategy listing (8 gates) |
| K1098 | [`../../experiments/k1098/k1098.py`](../../experiments/k1098/k1098.py) | A4f with VIXTWN — linearity robustness / VIX-TWN ratio |
| K896 | [`../experiments/k896_taiwan_es_supplement.py`](../experiments/k896_taiwan_es_supplement.py) | Expected shortfall analysis (Paper 2 supplement; also Sec 6) |

---

## Section 5: Earnings Announcement Volatility (A4f-EAV)

| Experiment | Script | Purpose |
|------------|--------|---------|
| K1145 | [`../../experiments/k1145/k1145.py`](../../experiments/k1145/k1145.py) | A4f-EAV pooled panel — N=31 Taiwan stocks (placebo robustness) |
| K1147 | [`../../experiments/k1147/k1147.py`](../../experiments/k1147/k1147.py) | A4f-EAV pooled panel — N=30 US S&P 500 large-caps (cross-market) |
| K1150 | [`../../experiments/k1150/k1150.py`](../../experiments/k1150/k1150.py) | A4f-EAV pooled panel — N=30 TOPIX Japan large-caps (cross-market) |
| K512 | [`../../experiments/k512/k512_tw_exdividend.py`](../../experiments/k512/k512_tw_exdividend.py) | Taiwan ex-dividend volatility study (Sec 4 / Sec 5 macro) |

---

## Section 5 (High-Frequency): TAIFEX Tick Evidence

*(Results referenced in section5_hf_draft.tex; K848–K854 use TAIFEX tick data)*

| Experiment | Script | Purpose |
|------------|--------|---------|
| K848 | [`../experiments/k848_taifex_5min_rv.py`](../experiments/k848_taifex_5min_rv.py) | TAIFEX 5-min realized volatility construction and descriptive stats |
| K847 | [`../experiments/k847_overnight_gap_decomposition.py`](../experiments/k847_overnight_gap_decomposition.py) | Overnight gap decomposition into tradable / non-tradable slots |
| K849 | [`../experiments/k849_har_rv_taifex.py`](../experiments/k849_har_rv_taifex.py) | HAR-RV vs GJR-GARCH forecast comparison (5-min RV target) |
| K851 | [`../experiments/k851_jump_dynamics.py`](../experiments/k851_jump_dynamics.py) | Jump dynamics — BNS test, HAR-CJ model, jump contribution to RV |
| K852 | [`../experiments/k852_realized_garch.py`](../experiments/k852_realized_garch.py) | Realized GARCH (GARCH structure + 5-min RV measurement) |
| K852b | [`../experiments/k852b_regime_har.py`](../experiments/k852b_regime_har.py) | Regime-dependent HAR model coefficients |
| K853 | [`../experiments/k853_proxy_ablation.py`](../experiments/k853_proxy_ablation.py) | Proxy ceiling ablation — isolate proxy choice effect on HAR vs GJR ranking |
| K844 | [`../experiments/k844_futures_vs_stock_vt.py`](../experiments/k844_futures_vs_stock_vt.py) | TX futures VT vs 0050.TW stock VT comparison |

---

## Section 6: VaR and Risk Management

| Experiment | Script | Purpose |
|------------|--------|---------|
| K850 | [`../experiments/k850_har_rv_var_taiwan.py`](../experiments/k850_har_rv_var_taiwan.py) | HAR-RV vs GJR VaR for 0050.TW (VaR trinity backtest) |
| K854 | [`../experiments/k854_common_sample_var.py`](../experiments/k854_common_sample_var.py) | Common-sample VaR — fix K850 unfair 450 vs 481 comparison |
| K896 | [`../experiments/k896_taiwan_es_supplement.py`](../experiments/k896_taiwan_es_supplement.py) | Expected shortfall (ES) analysis — GJR+HistSim best, FZ test |

---

## Section 8: Discussion

| Experiment | Script | Purpose |
|------------|--------|---------|
| K1302 | [`../../experiments/k1302/k1302.py`](../../experiments/k1302/k1302.py) | TSMC concentration robustness (Table 2 γ provenance) |
| K1370 | [`../../experiments/k1370/k1370.py`](../../experiments/k1370/k1370.py) | Amplification CI for cross-market validation claim |

---

## Appendix: Time-Zone Information Transmission

| Experiment | Script | Purpose |
|------------|--------|---------|
| K1176 | [`../../experiments/k1176/k1176.py`](../../experiments/k1176/k1176.py) | Cross-market VT comparison — c2c / o2o Sharpe replication |
| K1256 | [`../../experiments/k1256/k1256.py`](../../experiments/k1256/k1256.py) | Paper 1 3-spec disambiguation pattern (methodology reference) |

---

*Total experiments covered: 29 (17 local in `paper/taiwan-vt/experiments/`, 12 in root `experiments/`)*
*Generated: 2026-05-26 — do not edit manually; update via task paper_taiwan_vt_self_contained*
