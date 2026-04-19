# K1255 References

3 篇核心方法論論文 + 補充候選。所有 metadata 來自 WebSearch / SSRN / 原始期刊頁面（2026-04-18 verified）。

---

## Core (3 篇 — Phase 1 必引)

### 1. Andersen, T. G., & Bollerslev, T. (1997)
**Intraday periodicity and volatility persistence in financial markets**
- *Journal of Empirical Finance*, 4(2-3), 115-158.
- DOI: 10.1016/S0927-5398(97)00004-2
- PDF (open): https://finance.martinsewell.com/stylized-facts/volatility/AndersenBollerslev1997b.pdf
- Semantic Scholar: https://www.semanticscholar.org/paper/Intraday-periodicity-and-volatility-persistence-in-Andersen-Bollerslev/13322ed875401a08562c5413ce6ace7359095b7f
- **方法貢獻**: 提出 **Flexible Fourier Form (FFF)** 作為 deterministic intraday seasonal filter；證明若不先 de-seasonalize, ARCH/GARCH long-memory 估計會被 diurnal U-shape 偽造放大
- **K1255 用途**: M2 (MC-GARCH FFF spec) 的 s_k 估計直接用 FFF basis；FFF basis order P=5 (10 sin/cos pair + intercept)
- **延伸文獻**: Andersen & Bollerslev (1998, IER) "Deutsche Mark-Dollar Volatility..."; Andersen, Bollerslev, Diebold, & Vega (2003, AER) macro announcement effects

### 2. Engle, R. F., & Sokalska, M. E. (2012)
**Forecasting intraday volatility in the US equity market: Multiplicative component GARCH**
- *Journal of Financial Econometrics*, 10(1), 54-83.
- DOI: 10.1093/jjfinec/nbr005
- ResearchGate (full text): https://www.researchgate.net/publication/227464921_Forecasting_intraday_volatility_in_the_US_equity_market_Multiplicative_component_GARCH
- **方法貢獻**: 將 intraday return variance 分解為 **σ²_{t,k} = q_t · s_k · g_{t,k}** (daily × diurnal × stochastic)；NYSE 1-min 跨 2336 stocks 顯示 MC-GARCH OOS QLIKE 顯著勝 naive intraday GARCH 和 fixed-day GARCH
- **K1255 用途**: M2 / M3 / M4 MC-GARCH 的 model spec 直接 replicate；q feeder 替換為 HAR-RV / Realized GARCH / PRG 三種 robustness
- **關鍵 design choice**: q_t 是外部 plug-in（separable estimation）— 不是 joint MLE；g_{t,k} 跑在 de-seasonalized standardized residual r̃_{t,k} = r_{t,k} / √(q_t · s_k)

### 3. Hansen, P. R., Huang, Z., & Shek, H. H. (2012)
**Realized GARCH: a joint model for returns and realized measures of volatility**
- *Journal of Applied Econometrics*, 27(6), 877-906.
- DOI: 10.1002/jae.1234
- 已是 Paper 6 PRG 引文（Lai/Sheu 2024 PRS 系延伸基礎）
- **方法貢獻**: 同時 model returns + realized measures 的 joint likelihood；高頻 RV 顯著改善 daily vol forecast accuracy
- **K1255 用途**: M3 spec 的 q_t feeder；可直接重用 Paper 6 K880v2 的 PRG daily backbone forecasts 比 MC-GARCH (HAR-RV-q) 哪個更好

---

## Supporting (Phase 1 / robustness extras)

### 4. Bollerslev, T., & Ghysels, E. (1996)
**Periodic autoregressive conditional heteroscedasticity**
- *Journal of Business & Economic Statistics*, 14(2), 139-151.
- DOI: 10.1080/07350015.1996.10524640
- **K1255 relevance**: Periodic GARCH 原始 reference (calendar-period: day-of-week)；K1100h / Paper 6 PRG 從這延伸到 session-period；MC-GARCH 是這條線的另一條分支（multiplicative vs joint）

### 5. Bauwens, L., Giot, P., Grammig, J., & Veredas, D. (2004)
**A comparison of financial duration models via density forecasts**
- *International Journal of Forecasting*, 20(4), 589-609.
- **K1255 relevance**: Ultra-high-frequency GARCH 比較框架；ACD/UHF-GARCH 替代 MC-GARCH 的 alternative spec（Phase 2 可考慮）

### 6. Vatter, T., Wu, H.-T., Chavez-Demoulin, V., & Yu, B. (2013, SSRN)
**Non-Parametric Estimation of Intraday Spot Volatility: Disentangling Instantaneous Trend and Seasonality**
- SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2330159
- **K1255 relevance**: Non-parametric (kernel) alternative to FFF；M2/M3 robustness 測試 — 若 FFF 過 fit, 改 kernel smoothing 看是否更穩

### 7. Liu, R., Pun, C. S., & Wong, H. Y. (2024)
**Intraday FX Volatility-Curve Forecasting with Functional GARCH Approaches**
- arXiv: https://arxiv.org/abs/2311.18477
- **K1255 relevance**: Functional GARCH 是 MC-GARCH 的 functional-data extension；Phase 2 / paper extension 可比 functional vs componentwise

### 8. Moreno-Pino, F., Zohren, S. (2024)
**DeepVol: Volatility forecasting from high-frequency data with dilated causal convolutions**
- *Quantitative Finance* (Tandfonline): https://doi.org/10.1080/14697688.2024.2387222
- **K1255 relevance**: ML/DL baseline as Phase 2 comparator；MC-GARCH (M2) vs DeepVol head-to-head 是有趣 econometric vs DL 對比（但 K1255 Phase 1 不做，留 Phase 2）

### 9. Lai, Y.-H., Wang, A.-L., & Chang, T.-S. (2024)
**Periodic regime-switching GARCH model for foreign exchange rate volatility**
- *Asia-Pacific Financial Markets*, 31(2), 339-364.
- DOI: 10.1007/s10690-023-09421-y
- **K1255 relevance**: PRS 是用戶 own paper，PRG (Paper 6) 是 PRS 簡化版；K1255 MC-GARCH 是 **第三條 component-decomposition 路線**，與 PRS regime-switching / PRG deterministic-session 並列。**Phase 1 paper drafting 必引此 paper as positioning anchor**

---

## Reading priority for K1256 (Phase 1) agent prompt

1. **必讀全文**: Engle & Sokalska (2012) — model spec 直接 replicate
2. **必讀 §3-4**: Andersen & Bollerslev (1997) — FFF basis construction details
3. **重讀 §2-3**: Hansen, Huang & Shek (2012) — q_t feeder choice
4. **參考 Table 2**: Lai/Wang/Chang (2024) — positioning vs PRS
5. **Skim**: 其餘條目 (4-8) — Phase 2 extension scope

---

## DOI 驗證 status (2026-04-18)

| Ref | DOI 驗證 | Notes |
|-----|---------|-------|
| 1 (AB97) | ✅ via PDF + Semantic Scholar | Open PDF 可直接下載 |
| 2 (ES12) | ✅ via JFE journal page | ResearchGate full text 可用作 cross-check |
| 3 (HHS12) | ✅ Paper 6 已用 | 重用既有 BibTeX entry |
| 4 (BG96) | ⚠️ Phase 1 啟動前用 `/citation-verifier` 確認 | DOI 格式正確，需確認 page range |
| 5 (BGGV04) | ⚠️ 同上 | |
| 6 (Vatter+) | ✅ SSRN ID 確認 | working paper, no DOI |
| 7 (LPW24) | ✅ arXiv ID 確認 | preprint, watching for journal version |
| 8 (DeepVol) | ✅ DOI 已確認 | published in Q. Finance |
| 9 (LWC24) | ✅ User own paper | Paper 6 PRG / Paper 1 PRS 已用 |
