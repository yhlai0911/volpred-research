# Paper 10 — Supporting Experiments Index

**Paper**: The Crypto Fear Channel — Asymmetric, Tail-Concentrated, and Regime-Dependent Volatility Spillover from Bitcoin to Equity Markets
**Compliance**: Item (4) of the 5-item self-contained paper folder checklist (`docs/paper-guide.md`).
**Last updated**: 2026-04-17

This file indexes every VolPred K-experiment that materially contributes evidence
to Paper 10's body and robustness sections. Each entry lists the K identifier,
the on-disk path, a one-line contribution statement, and the paper section(s)
in which the evidence is cited. A reviewer wishing to reproduce any single
Paper 10 table or figure can follow the K-path and execute the listed
`experiments/kXXXX/kXXXX*.py` entry directly (see `scripts/README.md`).

---

## 1. Primary-evidence experiments (Sections 5–7)

### K1025 — Full fear-channel framework (primary source, §5.1–§5.3, §6.1–§6.2, §7.1)

- **Path**: `experiments/k1025/`
- **Entry point**: `k1025.py`
- **Contribution**: Complete spillover framework in a single experiment —
  symmetric and asymmetric Granger causality (§5.1), quantile regression
  across $\tau \in \{0.05, 0.25, 0.50, 0.75, 0.95\}$ for tail dependence
  (§5.2), EWMA correlation by VIX regime (§5.3), 252-day rolling Diebold-
  Yilmaz spillover index (§6.1), 5-subperiod structural breakdown (§6.2),
  and honest out-of-sample DM test of AR(VIX) vs AR(VIX)+BTC_RV with Harvey
  (2016) $|t|>3$ threshold (§7.1).
- **Key numbers cited in paper**: $N=2{,}812$; QR $\beta$ ratio $8.5\times$;
  COVID sub-period $F=11.05$, $p<10^{-6}$; OOS DM $t=-0.98$, $p=0.33$;
  mean Diebold-Yilmaz total spillover $90.11\%$; BTC net spillover $-76.89\%$.
- **Result file**: `experiments/k1025/k1025_results.json`.

### K639 — BTC→SPY Granger baseline (§5.1 first-stage baseline)

- **Path**: `experiments/k639/`
- **Entry point**: `k639_crypto_equity_vol.py`
- **Contribution**: First-stage bilateral BTC-SPY volatility linkage with
  tail dependence, rolling correlation across pre/post-2020, Granger tests
  at lag 1–10, and HAR + $|r_{BTC}|$ forecasting. Provides the base
  symmetric-Granger result used as a consistency cross-check in §5.1 before
  K1025's asymmetric decomposition.
- **Role in Paper 10**: cited in §5.1 and §2 (literature-gap positioning).
- **Result file**: `experiments/k639/k639_results.json`.

### K746b — Asymmetric BTC→VIX Granger (§5.1 confirmation)

- **Path**: `experiments/k746b/`
- **Entry point**: `k746b_bitcoin_vix_fixed.py`
- **Contribution**: Forward-looking asymmetric Granger test of $|r_{BTC,t}|$
  and its signed decomposition against next-day VIX changes. K746b fixed
  two K746-era issues flagged by Codex review: (i) forward-looking target
  $|r_{BTC,t+1}|$ replacing backward-looking 22d rolling RV; (ii) Fisher
  z-test on VIX-BTC_RV correlation (not the original BTC-SPY return
  correlation) plus Andrews (1993) unknown-breakpoint sup-Wald test.
- **Role in Paper 10**: §5.1 lag-by-lag asymmetric-Granger robustness cross-
  check for K1025. Confirms BTC downside branch dominance.
- **Result file**: `experiments/k746b/k746b_bitcoin_vix_fixed_results.json`.

## 2. Robustness / NULL-result experiments (Section 6 robustness appendix)

### K1241 — Pooled GARCH-X(VIX²) conditional-variance NULL (§6.5 / Table 3)

- **Path**: `experiments/k1241/`
- **Entry point**: `k1241.py`
- **Contribution**: Canonical $\varphi$ coefficient, Bollerslev-Wooldridge
  (1992) robust standard error, LRT vs baseline, OOS DM-HLN, sub-period
  robustness (K1133 convention: P1 2015–20, P2 2021–23, P3 2024–26), and
  Harvey (2016) $|t|>3$ verdict for the pooled GARCH-X(VIX$^2$) conditional-
  variance specification. **Verdict: NULL** ($\varphi_{M2}=-9.67\times10^{-6}$,
  $t_{BW}=-0.12$, $p=0.90$; LRT $p=0.95$; OOS DM-HLN $t=+0.75$; sub-period
  stability $0/3$).
- **Role in Paper 10**: §6.5 Table 3 — pooled conditional-variance
  specification is NOT a fear channel; this NULL strengthens the paper's
  thesis that the fear channel is tail-concentrated and regime-dependent
  rather than a simple linear conditional-variance loading.
- **Side finding**: $\gamma=0$ in BTC GJR-GARCH(1,1), consistent with
  Baur & Dimpfl (2018) — no BTC leverage effect. Cited as §4.1 footnote
  when introducing the GJR specification.
- **Result file**: `experiments/k1241/k1241_results.json`.
- **Lookahead guard**: explicit `allclose` assertion against reconstructed
  reference shifted series (line ~161 of `k1241.py`).

## 3. Regime-context experiments (Section 8 discussion)

### K1133 — BTC sub-period regime decomposition (§6.2 context, §8 mechanism)

- **Path**: `experiments/k1133/`
- **Contribution**: Establishes the 3-regime partition convention used in
  K1241 and cited throughout §6: P1 pre-institutional (2015–2020), P2 FTX /
  Luna / BlockFi turbulence (2021–2023), P3 spot-ETF era (2024–2026). The
  partition isolates whether any observed fear channel is an artifact of
  pre-institutional BTC market microstructure.
- **Role in Paper 10**: §6.2 anchor for 5-subperiod Granger and §8.3 margin
  design discussion.

### K1133b — 5-model Student-t attribution + MS-GAS-t OOS (§8 mechanism support)

- **Path**: `experiments/k1133b/`
- **Contribution**: Decomposes BTC GAS-t underperformance into innovation-
  distribution vs score-driven-dynamics components, and tests whether
  Markov-switching regime extension (MS-GAS-t) rescues it. Result: Student-t
  innovation accounts for ~75% of the GAS-t–vs–GJR-Normal gap, and the MS
  extension does NOT close the residual gap.
- **Role in Paper 10**: §8.3 footnote / discussion support that a
  regime-switching amplification of fear is not mechanically achievable
  through standard MS-GAS-t formulations. Provides a methodological
  counterpoint to mechanical regime-switching explanations.

## 4. Companion paper cross-references

### K1214 — BTC GAS-t negative-result methodology paper (companion draft)

- **Path**: `experiments/k1214/`
- **Contribution**: Full-length Markdown draft of the BTC GAS-t negative-
  result paper assembling K1129 + K1133 + K1133b findings. **Not** a
  Paper 10 source by itself, but cited alongside Paper 10 in §2 literature
  review and §8 discussion as a companion paper sharing the honest-NULL
  methodology stance.
- **Role in Paper 10**: §2.4 (positioning) and §8 (discussion) cross-cites.
  Reader navigation aid, not a primary-evidence experiment.

## 5. Paper-framing experiments (writing-only, no numerical claims)

### K1234 — Paper 10 §2–§9 kickoff guide

- **Path**: `experiments/k1234/`
- **Contribution**: Writing roadmap: per-section word targets, subsection
  structure, K-source per section, primary claims, and open decisions
  (memecoin inclusion, Deribit IV, multi-asset receiver, honest-NULL
  section length). Contains no new numerical claims.
- **Role in Paper 10**: Drafting reference for main-thread writing.

### K1238 — Paper 10 §3 Data and Preliminaries initial draft

- **Path**: `experiments/k1238/`
- **Contribution**: First Markdown draft of §3 (Data and Preliminaries),
  approximately 600 words with Table 1 descriptive statistics placeholder
  populated from `k1025_results.json`. Not `.tex` (CLAUDE.md rule: main-
  thread owns `.tex`).
- **Role in Paper 10**: §3 first-pass content; main-thread converts to
  `.tex` during body drafting.

### K1246 — Reproduction package drafts (this experiment)

- **Path**: `experiments/k1246/`
- **Contribution**: Drop-in Markdown drafts for the 5-item paper folder
  checklist: `data_sources.md`, `experiments.md` (this file), and
  `scripts/README.md`. Contains no new numerical claims.
- **Role in Paper 10**: Pre-flight reproduction package.

---

## 6. Minimum reproduction bundle

To reproduce the main results (Tables 2–5, Figures 1–4) the minimum required
bundle is **K1025 + K639 + K746b + K1241**. All other entries provide context
or writing scaffolding. This bundle is the target of `scripts/README.md` and
(when built) `reproduce.py`.

## 7. Experiments-index compliance (`docs/paper-guide.md` item 4)

This file:

- lists every supporting K by id (§1–§5);
- gives a one-line contribution for each (§1–§5);
- points at the on-disk path for each (§1–§5);
- identifies the minimum reproduction bundle (§6);
- is maintained alongside `data_sources.md` and `scripts/README.md` as the
  three-file pre-flight package.

Any new K-experiment that supplies numbers to Paper 10 must be appended here
**before** its numbers land in the body `.tex` (per paper-guide three-way
consistency rule).
