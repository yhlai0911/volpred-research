# Cover Letter — P6 Periodic Realized GARCH

**Target journal**: Finance Research Letters (FRL)
**Submission category**: Original Research (Letter)
**Date prepared**: 2026-04-28
**Status**: DRAFT (awaiting user submission decision)

---

## Cover Letter Body (FRL submission portal "Comments to Editor" field)

Dear Editor,

I am pleased to submit the manuscript "Periodic Realized GARCH: Session-Boundary Information Transfers and Volatility Forecasting" for consideration as a Letter at *Finance Research Letters*.

The paper develops the **Periodic Realized GARCH (PRG)** model, which extends the periodic GARCH framework of Bollerslev and Ghysels (1996) from calendar periodicity to **session-frequency periodicity** (overnight versus intraday). The mechanism is parsimonious — a single GARCH recursion with 6–8 session-specific parameters — yet it embeds a structural information bridge: the conditional variance from one session carries directly into the next, capturing cross-session feedback that close-to-close GARCH discards.

Three results motivate the submission:

1. **Cross-asset robustness.** PRG significantly outperforms GJR-GARCH under QLIKE on six markets — Taiwan futures (TAIFEX, tick-level), four U.S. ETFs (SPY, QQQ, GLD, EEM), and Taiwan 0050 ETF — with Diebold–Mariano statistics ranging from 4.26 to 6.63, all exceeding the Harvey, Liu, and Zhu (2016) $|t|>3.0$ threshold. An ablation removing the session-boundary update collapses the advantage to $t=-0.57$, identifying the boundary mechanism as the source of forecasting gain.

2. **Methodological correction.** Following Hansen and Lunde (2005) and Patton (2011), I convert all forecasts to a common variance target $\sigma^2_{\text{full}} = r^2_{\text{overnight}} + r^2_{\text{intraday}}$ before evaluation. Under this fair comparison, the long-claimed HAR dominance over GJR collapses ($t=0.57$, NS), revealing that prior literature compared models on mismatched targets — an evaluation bias the paper makes explicit.

3. **Fair-information benchmark.** A GJR-X specification on SPY enriches GJR with overnight realized variance as an exogenous regressor, equalizing the information set with PRG. PRG still dominates ($t=7.72$), and GJR-X does not improve upon GJR ($t=-0.53$, NS), showing that PRG's gain is **structural** (the session-boundary recursion) rather than informational (mere access to overnight $RV$).

The paper is concise (15 pages, 22 references, 5 tables, 7 equations). A complete replication package — `reproduce.py` with 22 byte-match checks, snapshot data CSVs, and signed JSON results — is included. The replication script returns `match_rate=100%` (`alert_level=green`) against the manuscript's reported numbers.

The work fits FRL's scope on volatility forecasting, GARCH-class methodology, and applied econometric letters with cross-market evidence. The contribution is a single self-contained mechanism with broad cross-asset implications, suited to FRL's letter format.

This manuscript is not under consideration at any other journal and has not been previously published.

Thank you for your consideration. I look forward to your editorial assessment.

Sincerely,

**Yi-Hao Lai**
Associate Professor, Department of Finance
Da-Yeh University, Changhua, Taiwan
Email: yhlai@mail.dyu.edu.tw

---

## Notes for user before submission

- FRL portal usually accepts plain-text cover letter; markdown headings can be stripped.
- Word count of body above: ~430 words (FRL norm 300–600).
- Replication package paragraph is a deliberate signal — FRL editorial board values reproducibility, and the byte-match `reproduce.py` is unusually strong evidence vs typical GitHub-link submissions.
- "Not under consideration elsewhere" boilerplate required by FRL.
