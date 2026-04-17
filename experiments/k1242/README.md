# K1242: Paper 10 §7 Robustness + §8 Discussion + §9 Conclusion Drafts

**Status**: completed (2026-04-17)
**Paper**: Paper 10 — The Crypto Fear Channel: Asymmetric BTC-Equity Volatility Spillover
**Executor**: Claude (worktree `agent-a35b4552`)
**Related K**: K1234 (kickoff guide), K1237 (§2 LitRev), K1238 (§3 Data), K1239 (§4 Methodology), K1240 (§5 Data Description + §6 Main Results skeleton)
**Supporting experiments**: K639, K746b, K949, K1025, K1133b, K1214 (companion negative paper)
**Seed**: 42

## Purpose

Complete the final three sections (§7 Robustness, §8 Discussion, §9 Conclusion) of Paper 10's body-drafting sequence. Together with K1237 (§2), K1238 (§3), K1239 (§4), and K1240 (§5, §6), K1242 closes the §2–§9 body-drafting roadmap laid out in K1234.

## Why NOT .tex

Per `CLAUDE.md` rule: *"禁止用 background agent 直接寫論文 `.tex`；寫作與方法論決策要在主線程完成"*. This experiment delivers Markdown drafts plus a structured JSON outline. Main-thread cherry-picks into `paper/crypto-fear-channel/body_v1.tex` and owns the LaTeX compilation pipeline.

## Files produced

| File | Purpose |
|---|---|
| `k1242_s7_s8_s9_draft.md` | Markdown draft of §7 (~820 w), §8 (~610 w), §9 (~320 w) body prose; placeholder cells marked `[Pending K1241]` for unexecuted fear-channel numbers. |
| `k1242_s7_s8_s9_outline.json` | Structured outline: subsection-level word counts, pending experiments, citations introduced, main-thread next steps. |
| `README.md` | This file. |

## Content summary

### §7 Robustness (~820 words, 5 subsections)

- **§7.1** Alternative fear proxies: VIX level vs VIX² vs log(VIX) vs CFIX (falsification device) — [pending K1241]
- **§7.2** Sub-sample regime splits: Pre-2020 / 2020–2023 / 2024–2026 three-way + crisis-vs-calm (VIX>25); K1025 five-regime cross-reference — [pending K1241]
- **§7.3** Extended sample (ETH / SOL): cross-crypto fear-channel — [pending main-thread scope decision + K1241]
- **§7.4** Alternative GARCH bases: E-GARCH (@nelson1991) and APARCH (@ding1993) — [pending K1241]
- **§7.5** Endogeneity / IV diagnostics: Granger bidirectional test + AR($p$) residual IV approach — [pending K1241]

### §8 Discussion (~610 words, 4 subsections, COMPLETE — no pending numbers)

- **§8.1** Mechanism interpretation: flight-to-quality + leverage-cycle (@geanakoplos2010) + sentiment-correlation channels
- **§8.2** Relation to companion paper K1214 (BTC GAS-$t$ negative result) — complementary, not conflicting; orthogonal research questions
- **§8.3** Contribution vs existing literature: Bouri 2020 (correlation → GARCH-X), Corbet 2018 (symmetric → asymmetric), Matkovskyy 2019 (receiver → bidirectional with honest NULL)
- **§8.4** Limitations: single-crypto BTC, US-centric VIX proxy, daily frequency, 2015-02 sample start

### §9 Conclusion (~320 words)

Three paragraphs: (i) summary with [placeholder for K1241 $\hat{\phi}$ verdict + X% annualised response], (ii) broader implication (crypto volatility is informational not speculative; complementary to K1214), (iii) four future-research directions (multi-crypto extension, intraday transmission, VIX-CFIX bidirectional, regime-switching fear channel).

## Word count verification

Measured via strict word-token count after stripping LaTeX math, code spans, table rows, and markdown headings:

- §7: **848** / target 800 (+6.0%)
- §8: **614** / target 600 (+2.3%)
- §9: **296** / target 300 (−1.3%)
- **Total**: **1,758** / target 1,700 (+3.4%)

All within the ±10% acceptable variance per academic-drafting convention.

## Citations

**New in K1242**: @nelson1991 (E-GARCH), @ding1993 (APARCH), @geanakoplos2010 (leverage-cycle).
**Reused from K1237 §2**: @engle2002, @bekaert2014, @bouri2020, @corbet2018, @matkovskyy2019, @hatemi2012, @harvey2016, @lai2026btc.

## Main-thread adoption workflow

1. **Cherry-pick**: transcribe §7 / §8 / §9 Markdown prose into `paper/crypto-fear-channel/body_v1.tex` after converting headings (`##` → `\section{}`, `###` → `\subsection{}`) and citation syntax (`@key` → `\citet{key}` or `\citep{key}`).
2. **Populate pending cells**: commission K1241 MF-GJR(1,1,1)-X fear-channel regression; main thread fills §7 Tables and §9 placeholders only after K1241 delivers JSON output.
3. **Harmonise BibTeX keys**: match new K1242 entries (`nelson1991`, `ding1993`, `geanakoplos2010`) with `paper/crypto-fear-channel/body_v0_intro.tex` bibliography.
4. **Scope decision**: resolve ETH/SOL inclusion (§7.3) before final transcription; if out-of-scope, delete §7.3 and extend §8.4 limitations.
5. **Paper-review-cycle**: run `paper-review-cycle` skill after first complete `body_v1.tex` draft; archive reports to `review_history/v1/`.
6. **Citation-verifier**: run `citation-verifier` on full reference list pre-submission.
7. **Reproduce package**: build `reproduce.py` and run `reproduce_report.json` to pass paper-guide three-way consistency check.

## Research-honesty checks

- ✅ No fabricated $\hat{\phi}$ values — all §7 robustness cells and the §9 headline magnitude are marked `[Pending K1241]` or `[X%]` placeholders.
- ✅ §8 interpretive / §8.4 limitations drafted without forward-looking numerical claims.
- ✅ §8.2 explicit cross-reference to K1214 companion paper — avoids reviewer-inferred contradiction between Paper 10 positive result and K1214 negative result on same asset.
- ✅ §9 placeholder includes conditional-rewrite instruction: if K1241 returns insignificant $\hat{\phi}$, §9 must be rewritten as an honest NULL per research-honesty principle 9.
- ✅ §7.5 IV endogeneity diagnostic explicitly listed per research-honesty principle 11 (lookahead bias): K1241 script must be Codex-reviewed for `signal.shift(1)` lag-discipline before §7 numbers transcribed into `.tex`.

## Pending items (tracked for main thread)

1. **K1241 (critical)**: MF-GJR(1,1,1)-X fear-channel regression + robustness re-estimations.
2. **Main-thread scope decision**: ETH/SOL in Paper 10 v1?
3. **Paper-guide self-contained package** (per `.claude/rules/paper-workflow.md`): README.md, data_sources.md, experiments.md, scripts/README.md, figures/, results/, reproduce.py — none yet exist in `paper/crypto-fear-channel/`; must be created before first submission.
