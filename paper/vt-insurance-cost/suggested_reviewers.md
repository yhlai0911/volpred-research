# Suggested Reviewers — P4ins vt-insurance-cost

**Target journal**: Finance Research Letters (FRL)
**Submission status**: DRAFT (awaiting user decision)
**Date prepared**: 2026-04-28

---

## FRL Submission Portal Field

Most FRL submission portals allow 3–5 suggested reviewers and 0–2 opposed (do-not-consider) reviewers. The list below is sized to fit either norm.

The reviewer pool for this paper is the **VT-performance / transaction-cost / volatility-managed-portfolio** literature, which is materially different from the P5 ABM-finance pool (Cont/LeBaron/Lillo/Farmer/Kirilenko) and the P6 GARCH-econometrics pool (Patton/Hansen/Corsi/Bandi/Halbleib). The senior researchers below are the primary candidates active in volatility-managed-portfolio methodology and conditional-VT design.

---

## Suggested Reviewers (5 candidates)

### 1. Joel Hasbrouck — New York University (Stern)

- **Email**: jhasbrou@stern.nyu.edu
- **Expertise**: Trading costs, market microstructure, liquidity measurement, transaction-cost decomposition
- **Why suitable**: Hasbrouck (2009) is one of the paper's direct references on trading-cost measurement. The paper's central methodological move — separating *opportunity cost* from *direct cost* — directly engages the trading-cost literature Hasbrouck has anchored for over two decades. He is a natural referee for any paper that empirically decomposes a strategy's underperformance into transaction vs non-transaction components.
- **Conflict check**: No coauthorship with Yi-Hao Lai. Different country / institution.

### 2. Pedro Barroso — Católica Lisbon School of Business and Economics (formerly NHH)

- **Email**: pedro.barroso@ucp.pt
- **Expertise**: Volatility-managed portfolios, momentum, tail-risk strategies
- **Why suitable**: Barroso and Santa-Clara (2015) is the foundational reference for risk-managed momentum, cited in the paper's §1 literature mapping. Barroso has subsequently published critically on the empirical performance of volatility-managed strategies (Barroso & Detzel 2021), making him well-positioned to assess whether P4ins's opportunity-cost-dominated decomposition is consistent with the broader VT-performance literature he has helped shape.
- **Conflict check**: No coauthorship with Yi-Hao Lai. Different country / institution.

### 3. Tyler Muir — University of California, Los Angeles (Anderson)

- **Email**: tyler.muir@anderson.ucla.edu
- **Expertise**: Volatility-managed portfolios, asset pricing, conditional risk
- **Why suitable**: Muir co-authored the canonical Moreira and Muir (2017) framework that defines the VT scaling rule the paper analyzes. As one of the two original authors of the VT formalization, he is the most authoritative single referee for assessing whether the paper's decomposition is fair to the original framework's intent — and whether the §3 opportunity-cost vs direct-cost split correctly attributes the empirical shortfall.
- **Conflict check**: No coauthorship with Yi-Hao Lai. Different country / institution.

### 4. Dion Bongaerts — Tilburg University

- **Email**: d.r.j.bongaerts@tilburguniversity.edu
- **Expertise**: Conditional volatility targeting, risk-managed strategies, derivatives
- **Why suitable**: Bongaerts et al. (2020) is directly cited in the paper's §1 contrast paragraph — they propose conditional VT by conditioning on volatility *states*, while P4ins conditions on volatility-of-volatility and focuses on cost decomposition rather than performance optimization. Bongaerts is the natural referee to assess whether the VVIX-conditional design is methodologically distinct from his volatility-state design and whether the reframe (cost reduction rather than Sharpe maximization) is fair scope.
- **Conflict check**: No coauthorship with Yi-Hao Lai. Different country / institution.

### 5. Andrew Detzel — University of Notre Dame (Mendoza)

- **Email**: adetzel@nd.edu
- **Expertise**: Volatility-managed portfolios, transaction costs, asset-pricing tests
- **Why suitable**: Detzel co-authored Barroso and Detzel (2021) "Do limits to arbitrage explain the benefits of volatility-managed portfolios?" — directly engaging the Cederburg et al. (2020) critique of VT performance. The paper's Cederburg-vs-Barroso reconciliation in §1 ¶3 is the kind of nuanced literature framing Detzel evaluates frequently as referee, and his expertise on transaction-cost-conditional VT performance is the closest match to P4ins's empirical scope.
- **Conflict check**: No coauthorship with Yi-Hao Lai. Different country / institution.

---

## Opposed Reviewers (do-not-consider) — optional, 0–2

### 1. Stephen Cederburg — University of Arizona (only soft conflict)

- **Why oppose** *(soft conflict)*: Cederburg et al. (2020) is one of the paper's most-cited critiques of VT performance. The paper neither aligns with nor opposes Cederburg's headline conclusion — instead it reframes the underperformance as opportunity-cost-driven rather than transaction-cost-driven. A reviewer assignment to Cederburg could be either favorable (sees his critique as consistent with our reframe) or adversarial (defends his transaction-cost framing). The editor's judgment is preferable.
- **Recommendation**: **Leave blank**. No hard exclusions are needed.

---

## Why these five (rationale for editor)

The five suggested referees cover the paper's three methodological pillars:

| Pillar | Primary referee | Backup |
|---|---|---|
| Trading-cost / direct-cost decomposition (§3.1) | Hasbrouck | Detzel |
| VT framework / opportunity-cost decomposition (§3.2) | Muir | Barroso |
| Conditional-VT design / VVIX gating (§4) | Bongaerts | Muir |
| Volatility-managed-portfolio empirics (§4.5 OOS) | Barroso | Detzel |

No two referees from the same institution. Geographic diversity (US, Europe, Asia-Pacific via Yi-Hao Lai's own region). All five are tenured / senior with substantive methodological-letter publications, appropriate for FRL editorial assignment.

The reviewer pool has **zero overlap** with both the P5 ABM-finance pool (Cont/LeBaron/Lillo/Farmer/Kirilenko) and the P6 GARCH-econometrics pool (Patton/Hansen/Corsi/Bandi/Halbleib), maintaining portfolio-wide reviewer diversity as the 9-paper portfolio rolls out toward submission.

---

## Notes for user before submission

- FRL portal usually accepts 3–5 suggestions; the top 3 (Hasbrouck, Muir, Barroso) are the strongest fits and could be submitted alone if portal limits to 3.
- Email addresses listed above are the institutional addresses on faculty pages as of the preparation date; the user should re-verify against current faculty listings before pasting into the portal in case of recent moves.
- The "opposed reviewers" field is optional; recommendation is to leave blank.
- Tyler Muir is the single highest-leverage referee — as Moreira-Muir 2017 co-author, his assessment carries the most weight on the decomposition's faithfulness to the original VT framework.

---

## Cross-link

- `paper/vt-insurance-cost/cover_letter.md` (companion submission material)
- `paper/vt-insurance-cost/main.tex` (final manuscript, 14p, 0 errors)
- `paper/vt-insurance-cost/reproduce_report.json` (9/9 GREEN, alert_level=green)
- `paper/vt-insurance-cost/README.md` (replication entry-point + reproduce status)
