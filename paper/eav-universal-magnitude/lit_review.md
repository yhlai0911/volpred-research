# Literature Review — EAV Cross-Market Regularity Paper (v2)

> **v2 rewrite (2026-05-17, main thread)** — adds 6 P1 references identified in
> `review_v1.md` Section 2: Patell (1976), Beaver (1968 deepened citation),
> Bollerslev (1986), Bollerslev-Patton-Quaedvlieg (2016), Harvey-Liu-Zhu (2016),
> Diebold (2015), Diebold-Mariano (1995). v1 archived as
> `lit_review_v1_pre_rewrite_backup.md`.

Minimum 3 anchors required before writing Introduction — **MET**: lines (A1),
(A2), (B1) below are canonical anchors with full citation traceability pending
citation-verifier pass.

---

## A. Earnings-Announcement Volatility — Canonical Anchors

### A1. Patell (1976) JAR — *canonical EAV anchor*
**Patell, J. M. (1976).** "Corporate forecasts of earnings per share and stock price behavior: Empirical test." *Journal of Accounting Research*, 14(2), 246–276.
- First systematic event study of corporate earnings forecasts on stock return/variance behavior.
- The "Patell standardization" of event-study test statistics originates here.
- **Use in this paper**: foundational citation for "earnings announcements move volatility, not just returns".

### A2. Patell & Wolfson (1979) JFE — *follow-up on options & EAV*
**Patell, J. M., & Wolfson, M. A. (1979).** "Anticipated information releases reflected in call option prices." *Journal of Financial Economics*, 7(2), 117–140.
- Documents implied-volatility run-up before earnings, decay after.
- **Use**: shows market participants anticipate the EAV spike — supports the binary-indicator specification (the event itself, not the surprise magnitude, is what matters most).

### A3. Beaver (1968) JAR Supplement — *variance ratio anchor*
**Beaver, W. H. (1968).** "The information content of annual earnings announcements." *Journal of Accounting Research*, 6(Supplement), 67–92.
- Documents trading volume ≈ 2× baseline and return variance ≈ 1.5–2× baseline around earnings announcements.
- **Use**: comparison anchor — our θ_EAV magnitudes (US 1.91e-4, JP 1.41e-4, TW 6.36e-5) correspond to variance-amplification ratios that should be reported alongside Beaver's ~2× as a direct conversation.

### A4. Ball & Kothari (1991) — cross-sectional EAV
**Ball, R., & Kothari, S. P. (1991).** "Security returns around earnings announcements." *The Accounting Review*, 66(4), 718–738.
- Cross-sectional analysis of earnings-announcement returns and volatility.
- **Use**: motivates within-market firm-attribute heterogeneity tests (K1109/K1113); helps frame the null finding.

### A5. *Need: international cross-market EAV anchor*
Candidate searches:
- Landsman & Maydew (2002) JFE on international earnings information content
- Cohen, Lou, & Malloy (2014) RFS on cross-country information acquisition
- DeFond, Hung, Li, Li (2015) TAR on international earnings announcement patterns
**Action item**: NotebookLM RAG pass over the top 5 candidates before introduction drafting.

---

## B. Multiplicative GARCH Framework

### B1. Bollerslev (1986) JoE — GARCH origin
**Bollerslev, T. (1986).** "Generalized autoregressive conditional heteroskedasticity." *Journal of Econometrics*, 31(3), 307–327.
- Baseline GARCH(1,1) specification.
- **Use**: per-stock g_{i,t} component baseline.

### B2. Engle & Rangel (2008) RFS — Spline-GARCH
**Engle, R. F., & Rangel, J. G. (2008).** "The Spline-GARCH model for low-frequency volatility and its global macroeconomic causes." *Review of Financial Studies*, 21(3), 1187–1222.
- First systematic multiplicative decomposition σ²_t = g_t · τ_t separating short-run (g) and long-run (τ) components.
- **Use**: theoretical motivation for the multiplicative decomposition; **clarify in citation that we use a parametric covariate-driven τ, not a non-parametric spline** — to avoid misleading readers about specification.

### B3. Engle, Ghysels, Sohn (2013) — GARCH-MIDAS
**Engle, R. F., Ghysels, E., & Sohn, B. (2013).** "Stock market volatility and macroeconomic fundamentals." *Review of Economics and Statistics*, 95(3), 776–797.
- **Citation correction**: v1 listed this as *Journal of Business & Economic Statistics*; per review_v1.md flag, this is actually *Review of Economics and Statistics*. **Pending citation-verifier pass for final confirmation.**
- Closest framework to our specification: τ driven by macroeconomic covariates.
- **Use**: methodological lineage for our τ = θ₀ + θ_VIX·VIX² + θ_EAV·EAV decomposition.

### B4. Bollerslev (1987) — GARCH-t innovations
**Bollerslev, T. (1987).** "A conditionally heteroskedastic time series model for speculative prices and rates of return." *Review of Economics and Statistics*, 69(3), 542–547.
- Student-t innovations for fat tails.
- **Use**: appendix robustness on innovation distribution.

---

## C. Pooled Panel Volatility Estimation

### C1. Pesaran, Schuermann, Weiner (2004) — GVAR-style pooled panel
**Pesaran, M. H., Schuermann, T., & Weiner, S. M. (2004).** "Modeling regional interdependencies using a global error-correcting macroeconometric model." *Journal of Business & Economic Statistics*, 22(2), 129–162.
- Canonical pooled panel cross-section estimation in econometrics.

### C2. Bauwens, Laurent, Rombouts (2006) JoE survey
**Bauwens, L., Laurent, S., & Rombouts, J. V. K. (2006).** "Multivariate GARCH models: A survey." *Journal of Applied Econometrics*, 21(1), 79–109.
- Survey of multivariate / panel GARCH specifications including pooled-coefficient identification.
- **Use**: methodological positioning of our pooled-τ + heterogeneous-g identification strategy.

### C3. Cipollini, Engle, Gallo (2013) — multiplicative MEM
**Cipollini, F., Engle, R. F., & Gallo, G. M. (2013).** "Semiparametric vector MEM." *Journal of Applied Econometrics*, 28(7), 1067–1086.
- Related multiplicative-component panel approach.

---

## D. Forecast Evaluation Methodology (mandatory — all DM citations)

### D1. Diebold & Mariano (1995) JBES — *DM test origin*
**Diebold, F. X., & Mariano, R. S. (1995).** "Comparing predictive accuracy." *Journal of Business & Economic Statistics*, 13(3), 253–263.
- Original DM test for equal predictive ability.
- **Use**: K1148_d2 panel DM, K1149 absorption DM tests, and §6.3 spec-consistency narrative.

### D2. Harvey, Leybourne, Newbold (1997) IJF — small-sample DM correction
**Harvey, D., Leybourne, S., & Newbold, P. (1997).** "Testing the equality of prediction mean squared errors." *International Journal of Forecasting*, 13(2), 281–291.
- Harvey-adjusted t-statistic correction for finite-sample DM bias.
- **Use**: the "Harvey-adjusted |t| > 3.0" threshold cited throughout — must be properly anchored to this paper.

### D3. Diebold (2015) JBES — DM test pitfalls
**Diebold, F. X. (2015).** "Comparing predictive accuracy, twenty years later: A personal perspective on the use and abuse of Diebold-Mariano tests." *Journal of Business & Economic Statistics*, 33(1), 1–9.
- Critical retrospective on DM test usage; cautions on nested-model comparison and population-level vs estimated-model inference.
- **Use**: defensive citation against reviewer concerns about DM application; our spec-consistency framing (K1148_d2) is precisely the non-nested case where DM is on solid footing.

### D4. Bollerslev, Patton, Quaedvlieg (2016) JBES — QLIKE loss
**Bollerslev, T., Patton, A. J., & Quaedvlieg, R. (2016).** "Exploiting the errors: A simple approach for improved volatility forecasting." *Journal of Business & Economic Statistics*, 34(3), 446–471.
- QLIKE loss-function justification for noisy variance proxies.
- **Use**: forecast loss-function choice for OOS panel DM (K1148_d2 uses QLIKE).

### D5. Patton (2011) JoE — robust loss functions
**Patton, A. J. (2011).** "Volatility forecast comparison using imperfect volatility proxies." *Journal of Econometrics*, 160(1), 246–256.
- "Robust" loss-function class (MSE, QLIKE) for noisy proxies.
- **Use**: QLIKE selection justification supplement to D4.

---

## E. Multiple Testing in Finance

### E1. Harvey, Liu, Zhu (2016) RFS — *…and the Cross-Section of Expected Returns*
**Harvey, C. R., Liu, Y., & Zhu, H. (2016).** "…and the cross-section of expected returns." *Review of Financial Studies*, 29(1), 5–68.
- Documents replication crisis in cross-sectional asset pricing; argues t > 3.0 should be the new threshold for financial research given multiple-testing intensity.
- **Use**: motivates our Bonferroni / BH-FDR adjustments across 3 markets × 5 robustness layers × 2 specs (binary/continuous). Our 3-market joint test with |t| > 2.39 even after Bonferroni adjustment is the response to this critique.

### E2. Romano & Wolf (2005) Econometrica — stepwise multiple testing
**Romano, J. P., & Wolf, M. (2005).** "Stepwise multiple testing as formalized data snooping." *Econometrica*, 73(4), 1237–1282.
- Stepwise multiple testing with dependence structure.
- **Use**: alternative to BH-FDR for the joint cross-market test if reviewers prefer stronger FWER control.

### E3. Benjamini & Hochberg (1995) JRSS-B — BH-FDR
**Benjamini, Y., & Hochberg, Y. (1995).** "Controlling the false discovery rate: A practical and powerful approach to multiple testing." *Journal of the Royal Statistical Society: Series B*, 57(1), 289–300.
- BH-FDR procedure.
- **Use**: K1145/K1147/K1150 each run 3-row BH-FDR; cited for the procedure.

---

## F. To Search / Verify (citation-verifier queue)

- [ ] Verify Patell & Wolfson (1979) — JFE vs JFQA (review_v1.md flagged JFE)
- [ ] Verify Engle, Ghysels, Sohn (2013) — JBES vs ReStat (review_v1.md flagged ReStat)
- [ ] Find at least 1 international cross-market EAV paper (see A5 candidates)
- [ ] Find at least 1 paper on binary vs. continuous surprise specification choice in GARCH (Andersen-Bollerslev-Diebold-Vega 2003?)
- [ ] Check: Berger, Stotz, Wagner (corporate announcement + GARCH), any recent IJF / JEF

---

## G. Citation Search Query (NotebookLM RAG seed)

Search terms for Google Scholar / Sci-Hub / NotebookLM topic-notebook:
- "earnings announcement" "GARCH" "volatility" "cross-country"
- "earnings announcement effect" "multiplicative GARCH"
- "EAV" "event volatility" "pooled panel" "firm-level"
- "earnings announcement" "international comparison" "Japan" "Taiwan"
- "volatility forecasting" "QLIKE" "Diebold-Mariano" "panel"
- "multiple testing" "finance" "Harvey Liu Zhu"
