# Cover Letter — P4ins vt-insurance-cost

**Target journal**: Finance Research Letters (FRL)
**Submission category**: Original Research (Letter)
**Date prepared**: 2026-04-28
**Status**: DRAFT (awaiting user submission decision)

---

## Cover Letter Body (FRL submission portal "Comments to Editor" field)

Dear Editor,

I am pleased to submit the manuscript "The True Cost of Volatility Targeting: Insurance Premium Decomposition" for consideration as a Letter at *Finance Research Letters*.

Volatility-targeting (VT) strategies are a standard dynamic risk-management tool, formalized by Moreira and Muir (2017), with documented tail-risk reduction (Harvey et al., 2018) but persistent return shortfalls relative to buy-and-hold. The dominant attribution in the literature has been *trading friction* — turnover, brokerage, market impact (Harvey et al., 2018; Cederburg et al., 2020). This paper argues that this attribution conflates two economically distinct cost components and provides the first empirical decomposition.

The paper makes three contributions:

1. **Insurance-premium decomposition.** Using daily S&P 500 data over 2012–2024 ($N$ = 3,262 trading days), I decompose the VT–buy-and-hold return gap into *opportunity cost* (foregone equity participation when volatility-managed exposure is below 100%) and *direct cost* (transaction expenses from rebalancing). Under unconditional VT, opportunity cost accounts for **91% of the total premium** (4.20% vs 0.43% per annum). The dominant cost is foregone upside, not trading friction — a redirection of the VT design problem from minimizing turnover to minimizing opportunity loss through regime conditioning.

2. **VVIX-conditional regime gating.** Activating VT only when the volatility-of-volatility $z$-score exceeds 1.0 reduces total cost by **74%** in the full sample (4.62% → 1.22%), primarily by eliminating unnecessary hedging during calm markets. Cross-OOS analysis reveals the cost reduction is sample-dependent (S2 outperforms in 1 of 4 non-overlapping windows), framing VVIX-conditional VT as **infrequent tail insurance** rather than a consistently superior strategy — an honest characterization that the paper's §4.5 OOS analysis develops in detail.

3. **Structural rebalancing-premium benchmark.** I document that the canonical 50/50 SPY/GLD benchmark generates a structural rebalancing premium of **54 basis points per annum**, creating a high bar for VT to clear. While VVIX-conditional VT (S2) achieves a higher Sharpe ratio (0.63 vs 0.50), the comparison is not apples-to-apples: S2 is 100% equity with occasional VT, while 50/50 includes gold diversification. The paper makes this comparison transparent rather than concealing the benchmark gap.

The paper is concise (14 pages, 17 references). A complete replication package — `reproduce.py` with 9 byte-match checks against the manuscript's reported numbers, snapshot data, and signed JSON results — is included. The replication script returns `match_rate=100%` (`alert_level=green`). The 50/50 rebalancing-premium check uses a documented dual-convention tolerance (10 bps reflecting `auto_adjust=True` vs `auto_adjust=False` Adj Close handling, footnoted in §3.2).

The work fits FRL's scope on volatility-management methodology, transaction-cost decomposition, and conditional-strategy evaluation with cross-period validation. The decomposition framework is methodologically simple but its empirical implications redirect a substantive line of VT-design research.

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
- Word count of body above: ~470 words (FRL norm 300–600).
- Three contribution points are ordered by logical narrative: (1) the decomposition is the core methodological contribution, (2) VVIX-conditional gating is the empirical headline, (3) the rebalancing-premium benchmark is the disciplining honest comparison.
- Replication package paragraph signals 9-check byte-match `reproduce.py` + dual-convention tolerance documentation — unusually transparent for a transaction-cost paper.
- The 50/50 SPY/GLD comparison framing is deliberately humble ("not apples-to-apples"); reviewers in this literature appreciate honest scope language over over-claiming.
- "Not under consideration elsewhere" boilerplate required by FRL.
