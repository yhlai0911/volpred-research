# Cover Letter — P5 vt-crowding-abm

**Target journal**: Finance Research Letters (FRL)
**Submission category**: Original Research (Letter)
**Date prepared**: 2026-04-28
**Status**: DRAFT (awaiting user submission decision)

---

## Cover Letter Body (FRL submission portal "Comments to Editor" field)

Dear Editor,

I am pleased to submit the manuscript "When Positive-Feedback Strategies Crowd: A Family-Level Threshold Framework via Agent-Based Simulation" for consideration as a Letter at *Finance Research Letters*.

The crowding-risk literature on volatility targeting (VT) has, until now, treated VT as a singular case. Yet VT shares a procyclical position-update structure with trend-following (TF) and short-horizon mean-reversion (MR): each strategy class can in principle generate self-reinforcing trading flows under widespread adoption. The question this paper addresses is whether the resulting crowding threshold is VT-specific or a generic property of positive-feedback strategies.

The paper makes three contributions:

1. **Family-level threshold framework.** Using a Kyle (1985) market microstructure with 1,000 heterogeneous agents and 200 fixed noise traders across 46,800 Monte Carlo simulations distributed over three layered phases, I document that TF and MR thresholds lie *at or below* the VT threshold under matched microstructure — in 12/12 strategy-spec cells (Phase 2: scaling × window robustness) and 5/5 microstructure cells (Phase 2b: λ/γ ±50% OAT). The qualitative ordering TF/MR ≤ VT is preserved across all 17 perturbation checks, establishing positive-feedback crowding as a *family-level* phenomenon rather than a VT-specific artifact.

2. **NoiseControl falsifier.** A deterministic-weight (w=0.5) NoiseControl treatment, calibrated to match the noise-trader baseline mean order flow, never produces a critical threshold across the 17 cells × 7 adoption levels tested. This anchors the family-level claim to the positive-feedback property *per se* rather than to any mechanical artifact of large coordinated agent blocks. The falsifiability anchor is, to my knowledge, novel in the ABM crowding literature.

3. **Calibration to canonical baseline.** The Sharpe-only detector applied to the cell1 baseline (λ=0.005, γ=200) reproduces *exactly* the 70% VT crowding threshold reported in the standalone VT analysis — establishing that the family-level reframing is consistent with prior published thresholds rather than reframing the result.

The paper is concise (26 pages, 22 references, 4 tables, 7 equations). A complete replication package — `reproduce.py` with 47 byte-match checks against the manuscript's reported numbers, snapshot data, and signed JSON results — is included. The replication script returns `match_rate=100%` (`alert_level=green`).

The work fits FRL's scope on systemic-risk modeling, agent-based finance, and applied econometric letters with cross-class evidence. The contribution is a single self-contained mechanism (positive-feedback crowding) tested across three strategy classes plus a falsifiability anchor, suited to FRL's letter format.

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
- Three contribution points are deliberately ordered by methodological novelty: (1) the family-level reframe is the headline contribution, (2) the NoiseControl falsifier is the strongest single methodological innovation, (3) the calibration anchor establishes external validity against prior literature.
- Replication package paragraph signals to FRL editorial board: 47-check byte-match `reproduce.py` is unusually strong evidence vs typical "code-on-request" submissions.
- "Not under consideration elsewhere" boilerplate required by FRL.
