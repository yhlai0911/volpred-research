# K1239 — Paper 10 §4 Methodology: Initial Draft (Fear-Channel GARCH-X Module)

**Status**: Draft complete (markdown-only per CLAUDE.md rule "agent 不寫 body.tex")
**Date**: 2026-04-17
**Parent K**: K1234 (Paper 10 kickoff guide)
**Sister tasks (parallel)**: K1237 (§2 Literature Review), K1238 (§3 Data)

## Purpose

K1239 drafts the Methodology section (§4) of Paper 10 ("The Crypto Fear Channel: Asymmetric BTC-Equity Volatility Spillover"). Per the K1234 kickoff specification, this draft focuses on the *fear-channel regression* module — a GARCH-X variance-domain transmission test that augments the outline's existing Granger / quantile-regression / Diebold–Yilmaz blocks — and on the associated statistical-test battery and identification strategy.

The main thread will later decide whether this module appears as §4.1 (anchoring methodology) or as a later subsection (complementing the asymmetric-Granger block already sketched in `paper/crypto-fear-channel/outline.md`).

## Source material

| Item | Path | Role |
| --- | --- | --- |
| Kickoff guide | `experiments/k1234/k1234_kickoff_guide.md` | §4 outline (currently absent from this worktree; referenced by spec) |
| Paper outline | `paper/crypto-fear-channel/outline.md` | Numbering, K-anchors, existing §4 subsections |
| Paper body v0 | `paper/crypto-fear-channel/body_v0_intro.tex` | Abstract, Intro, bibliography stubs |
| Paper 9 precedent | `experiments/k949/README.md` | MF-GJR(VIX) specification and Harvey-threshold evidence |
| Data summary | `experiments/k1238/*` (pending) | Sample description (CLAUDE.md: K1238 in progress) |

## Deliverables

| File | Content |
| --- | --- |
| `k1239_methodology_draft.md` | Markdown draft of §4 (§4.1 regression spec, §4.2 base-model selection, §4.3 statistical tests, §4.4 identification) |
| `k1239_methodology_outline.json` | Structured outline (subsection IDs, word-count targets, citation list, K-references) |
| `README.md` | This file |

## Methodological approach

§4.1 specifies the GARCH-X fear-channel regression
$$
\sigma_{t}^{2} = \omega + \alpha \varepsilon_{t-1}^{2} + \gamma \varepsilon_{t-1}^{2} \mathbb{I}(\varepsilon_{t-1}<0) + \beta \sigma_{t-1}^{2} + \phi \text{Fear}_{t-1}^{2},
$$
with the null $H_{0}: \phi = 0$ (no fear channel) tested against the one-sided alternative $H_{1}: \phi > 0$.

§4.2 motivates the choice of MF-GJR with Student-$t$ innovations as the primary specification, citing K949's cross-market evidence (Harvey-significant gains in 4 of 5 equity markets, VIX elasticity $\theta_{1} \approx 2.1$) and K1129's kurtosis diagnostic ($\hat{k} = 7.97$ for BTC returns).

§4.3 assembles the statistical-test battery: robust $t$-statistic for $\phi$, likelihood-ratio test vs. GJR baseline, Diebold–Mariano (1995) with Harvey (1997) small-sample correction under Patton (2011) QLIKE loss, Harvey et al. (2016) $|t| > 3.0$ threshold for multiple-testing protection, and pre-/post-ETF sub-sample robustness (K1133b).

§4.4 addresses causal identification via (a) exogeneity of VIX relative to BTC, (b) directional-precedence Granger tests, and (c) an AR-filtered VIX-innovation IV variant.

## Rules followed

- Markdown only — no `.tex` edits (per CLAUDE.md: "禁止用 background agent 直接寫論文 `.tex`").
- Academic writing style, Patton / Harvey / DM standards cited explicitly.
- Seed 42 declared in draft header for all subsequent Monte-Carlo / bootstrap operations in later experiments that consume this methodology.
- All outputs kept inside `experiments/k1239/` (worktree agent rule).

## Next steps (main thread)

1. Review whether §4.1–§4.4 integrate with or replace the existing outline §4.1–§4.5 blocks.
2. Decide ordering: fear-channel GARCH-X as anchor vs. appendix module.
3. Harmonise bibliography keys with `body_v0_intro.tex`.
4. Transcribe into `body_v1_full.tex` via main-thread writing session (not an agent task).
