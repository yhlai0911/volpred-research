# research_program.md Delta — Session 2026-04-17 晚 ~ 2026-04-18 凌晨

> **Draft produced by K1212 worktree agent.** Consolidation of K1108-K1211 session findings. Worktree agent 禁止直接改 `research_program.md`；本 delta 供主線程 review → merge。
>
> **Scope**: Paper 1/2/3/4/6 narrative states + BTC GAS negative paper candidate + methodology upgrades. Canonical K 數字均源自 `storage/memory/knowledge.json` 2026-04-17/04-18 entries 與 `storage/next_tasks.json`。

---

## Section 1 — Findings delta (per paper / direction)

### Paper 1 (leverage-direction, JBF target) — Reproducibility batch progression

- **Batch 1 已 commit** (hash `0a442356`, 本 session 早段)：含 K1175/K1181-K1198 反向驗證一批 paper 數字（K1181 Spearman 0.5914 vs paper 0.595、K1182 Granger F=58.9 vs paper 58.8、K1183 TSMC VT Sharpe 1.1244 vs paper 1.121、K1184 skew-t η=4.97 vs 5.2 λ=-0.059 vs -0.05、K1188 T8 15/15 MATCH、K1195 JBF Robustness Suite 5/6 MATCHED、K1196 Structural Leverage Panel 3/4 MATCHED、K1197 GJR-vs-EWMA crisis MDD direction confirmed、K1198 T10-12/C3 3/6 MATCHED 含 T12 Spearman=1.000 EXACT）。
- **Batch 2 K1209 draft pending**: 待處理 divergences — Paper 1 Table 3 vs Table 8 同設定 GJR QLIKE `-9.034 vs -8.671`、GLD mean γ=-0.067 反推不出、T10-12 3 KB-only 值（footnote 或 new experiments）、D4 γ_HM 4.7 vs 5.4 衝突、K1187 T7 5-asset cross-section 6/20 MATCHED (30%) 區間不一致。
- Next actionable: cherry-pick K1209 draft 的 errata pack → paper-update cycle。

### Paper 2 (taiwan-vt) — 5-iter trajectory + foundry mechanism DECISIVE NULL

- **Foundry capex mechanism 6-LAYER NULL stack (COMPLETE)**：
  - K1108 single-firm TSMC binary INCONCLUSIVE (t=0.94, n=48)
  - K1108b 5-foundry pooled binary **DECISIVE NULL** (commit `5bcd8143`)
  - K1108c continuous `guide_delta_pct` (-32.5%~+60.6%) on 4-firm pool N=135: beta_1 HAC t=-1.34 NS
  - K1108d D2 non-capex (utilisation/wafer-ASP/R&D) PRELIMINARY NULL (coverage 8.9%): max HAC |t|=0.968, partial-F p=0.791
  - K1108e D3 operating-leverage: max HAC |t|=1.58, partial-F(3,37)=2.22 p=0.102, firm-FE absorbs SMI channel
  - K1108f D4 regime-split (up-cycle vs down-cycle): Wald chi²=0.036 p=0.849 cannot reject equality, bootstrap CI [-6.21e-05, +3.63e-05]
- **Non-foundry verification continues**: K1173 refined institutional-share proxy (emerging-market); K1207 sector-FE decomposition (N=12 markets Spearman rho=+0.441 p=0.152 fails Harvey but signal-positive after sector-orthogonal).
- **K1172 N=12 cross-market ladder**: +LatAm (MX 10/10)、ID 10/10、ZA dropped UNDERPOWERED (yfinance JSE 0-4 events/ticker < 15 filter). Primary Spearman rho(inst_pct, theta_rel)=+0.441 p=0.152.
- **K1211 §5 narrative draft pending** (synthesis agent): universal-magnitude reframe + 3 caveats (EM institutional-share under-proxy / TSMC foundry null / Table 3 K1175 errata).

### Paper 3 (vt-trend-following) — K1128 4-branch pivot gate met

- **4-branch NULL complete** (K1128 narrative-state-machine gate: ≥3 互補實驗)：
  - (1) K1128 discrete VIX tertile IS-fixed: OOS degenerate coverage (0/854/20060 low/mid/high)
  - (2) K1131 natural cubic spline continuous VIX: NULL with IS-extrapolation explosion to COVID VIX=82
  - (3) K1142 vol-normalized `|OFI|/sigma_t` (regime-free): PARTIAL OOS t=+2.255 Harvey fail, AUC 0.671 (best among 4)
  - (4) K1199 expanding-window adaptive VIX quantile: NULL, coverage 0/6816/14098 (still degenerate), DM t=+1.14 FAILS Harvey+weak, AUC 0.548
- **Structural root cause identified (K1199)**: IS 2017-2019 VIX range 9-37 does NOT intersect COVID OOS 12-83; once expanding window ingests Feb-Mar 2020 spike, q33 permanently rises → OOS low-regime coverage zero.
- **Alternative path: K1100g weak-but-universal gap²** — K1100g_d7 currently running（cross-market replicate SPY overnight / N225 morning→afternoon）. If d7 passes Harvey 2/2 cross-market → candidate for Paper 3 pivot option (b).
- **K1193 split-sample finds r=0.793** vs paper 0.487 — STRENGTHENING direction (paper 原 narrative 為 attenuation)；需 main-thread Panel B re-write.
- **K1190 Sector 11 SPDR**: gamma range MATCHED but cross-sectional r DIVERGES (K1190 r=0.089 vs paper 0.163).
- K1205 synthesis draft pending (recommends option (b): adopt pooled microstructure + drop VIX-regime narrative).

### Paper 4 (vix-sufficiency) — 7/7 UNIVERSAL_NULL declared

- **PIT alignment chain complete** (K1116c → K1116f → K1201 → K1203)：
  - K1116 / K1116b / K1117 / K1117b robust NULL even under calendar shift(1)/shift(2)
  - K1116c ALFRED vintage path blocked (API timeout + FRED_API_KEY 未取得)→ fallback release-calendar PIT
  - K1116f cross-asset GLD/TLT/BTC confirm SPY K1116c NULL universality
  - TLT finstress DM t=+3.74 (pit_shift0) single-cell positive but triple-gate fail: (a) QLIKE improvement only +0.50% < 5% gate; (b) subperiod 2/3 years NS; (c) all-alt aug overfits DM t=-5.67
  - K1118 shift(1) NULL, K1118b cross-asset confirm, K1121 / K1123 cross-asset alt-data matched-pair
- **Declaration**: 7/7 assets × 5 alt-data families UNIVERSAL_NULL (SPY / GLD / TLT / BTC / 0050.TW + 2 extension cells) under true publication-lag PIT.
- K1208 synthesis draft pending → body_v4 rewrite unlocked.
- **Flag CONFLICT-A4**: `Paper4_channel_specific_pivot` next_tasks 狀態為 `decision_made_awaiting_body_rewrite`。主線程需決定 body_v4 narrative 為「channel-specific claims」或「UNIVERSAL_NULL final」。K1208 draft 應 match 用戶 2026-04-17 7ecab636 decision（Paper 2 §5 Option 4 + Paper 4 channel-specific pivot）。

### Paper 6 (prg-periodic-garch) — defensibility CONFIRMED

- **K1200 K880v2 replication**: K880 line 512 使用 `r2_overnight[t]`（same-day overnight realized）預測 `h_intraday_t` → K880v2 改用 t-1 close-time info. K1200 replication confirms K880v2 as canonical → Paper 6 SPY main result 應改為 K880v2 (DM 6.00 → -0.57, FRL target).
- **K1200 audit verdict**: Paper 6 defensibility CONFIRMED — K880 lookahead 結構性問題已由 K880v2 two-phase forecast timing 解決，option (b) 並非偽造而是合理 narrative pivot。
- Paper 6 other issues stack (next_tasks): Paper6_DIV2 0050.TW OOS date errata (2019/12 vs K886 2021-01-08)、Paper6_DIV3 SPY VaR VR=0.93% 無 source、experiments.md 加 K874c/K874e、K880v2 canonical update.

### Paper 9 (garch-x-vix) — robustness retained

- K1027 Paper 9 7-window sub-period: (a) Claims substantiated, A4f 7/7 wins CONFIRMED. DM t P1=-4.375, P2=-3.488, P3=-2.124, P4=-1.858, P5=-2.xx, … pooled t=6.535→6.977 (K1027 update).
- K1144 Paper 9 FEZ/STOXX50E A4f OOS 2019-2026 canonical replication (ticker forensic pending — ^STOXX50E vs ^ESTX50 30% QLIKE 差).
- K995b Paper 9 Table 11 殘差診斷: Paper 9 submission status confirmed; integration pending: K998 vrp_autocorr_lag1 JSON write, experiments.md 加 K1045 as Table 11 source.

### New direction — BTC GAS-t negative-result paper candidate

- **K1129 / K1133 / K1133b regime-concentrated reversal**: K1133 DM t=-4.58 decomposes into
  - P1 pre-institutional 2017-2020 (n=1441): DM t=-4.67 Harvey-significant
  - P2 FTX/Luna 2023 (n=345 PRELIMINARY): t=-0.82 NS
  - P3 spot-ETF 2026 (n=100 PRELIMINARY): t=-0.80 NS
- **K1133b innovation-decomposition**: GJR-t=-3.36, GAS-t=-4.67 (K1133 baseline), GAS-Normal=-1.90 (NS), GJR-N control=-0.06. M4 vs M3 DM=+2.67 → GAS-Normal significantly BEATS GAS-t. Student-t innovation drives ~75% of P1 reversal, GAS dynamics ~25% (NS).
- **Paper candidate framing**: "Score-driven vol models fail on institutionalised crypto — a regime-concentrated negative result." Target journals: J. Futures Markets / Int. Rev. Finan. Analysis / Empirical Econ.
- Requires independent verification: commodity GAS-t (USO/UNG/GLD, K1135 already started) + crypto robustness beyond BTC (ETH/SOL).

---

## Section 2 — Narrative-state-machine transitions

| Paper | Before this session | After | Gate passed? |
|-------|---------------------|-------|-------|
| **Paper 1** | Reproducibility batch in-progress | Batch 1 committed `0a442356`, Batch 2 K1209 draft ready for errata pack | Batch 1 merged; Batch 2 pending main-thread cherry-pick |
| **Paper 2 foundry mechanism** | Pending foundry hypothesis tests | **PROVISIONAL → FINAL: 5-LAYER NULL STACK (DECISIVE)**. Capex/non-capex/op-leverage/regime all NULL. Foundry channel abandoned. | Yes (5 互補 specs, Gemini/Codex review where available) |
| **Paper 2 §5 narrative** | decision_made_awaiting_body_rewrite (用戶 2026-04-17 Option 4) | K1211 draft pending → main-thread §5 rewrite | Decision already made, body rewrite still pending main thread |
| **Paper 3 K1128 regime-switching** | 3 branches tested | **decision_candidate: 4-branch pivot gate met (K1128+K1131+K1142+K1199)**. Structural IS/OOS VIX range disjoint identified as root cause. | Yes for gate; user A/B/C decision still open (`Paper3_strategic_decision`) |
| **Paper 3 split-sample** | Paper claimed attenuation (r=0.487) | K1193 finds STRENGTHENING (r=0.793) | Panel B re-write pending main thread |
| **Paper 4 UNIVERSAL_NULL** | channel-specific pivot already user-decided 2026-04-17 (7ecab636) | 7/7 UNIVERSAL_NULL verified across PIT chain + cross-asset alt-data | **CONFLICT-A4**: body_v4 rewrite_unlocked, but narrative final form (channel-specific vs UNIVERSAL_NULL) needs main-thread clarification |
| **Paper 6 defensibility** | K880 lookahead issue flagged | **CONFIRMED** via K1200 two-phase K880v2 replication | Yes; FRL submission path clearer |
| **BTC GAS negative paper** | N/A | **New paper candidate (decision_candidate)**: Paper 10 slot or standalone. | Needs user kick-off decision |

**Rewrite unlocked** (body work may proceed after main-thread review): Paper 4 body_v4, Paper 2 §5, Paper 3 Panel B, Paper 6 SPY main result (K880 → K880v2).

**Still locked**: Paper 3 strategic A/B/C (user decision); Paper 10 BTC GAS kick-off (user decision); new paper folder scaffolding for BTC GAS.

---

## Section 3 — Backlog delta (completed + new + blocked)

### Completed this session (selected — full list in commit log)

- K1108b / K1108c / K1108d / K1108e / K1108f — Paper 2 foundry NULL 5-layer
- K1116f — PIT alignment cross-asset GLD/TLT/BTC
- K1133 / K1133b — BTC GAS-t regime-concentrated reversal + innovation decomposition
- K1142 — vol-normalized OFI (Paper 3 4-branch gate)
- K1172 — N=12 cross-market ladder (ZA underpowered, MX/ID 10/10)
- K1173 — Emerging-market institutional-share proxy refinement
- K1175-K1198 — Paper 1/2/3/6/9 reproducibility forensic pack (selected K numbers in §1)
- K1199 — Expanding-window adaptive VIX quantile (K1128 rescue attempt)
- K1100e — N=13 pairs cross-asset λ_L threshold (H1 confirmed Spearman=-0.791 p=0.001)
- K1193 — Paper 3 split-sample STRENGTHENING discovery

### New queued (post-session synthesis / integration tasks)

- **K1108d_transcript_scrape** — transcript-based non-capex guidance re-extraction (targets K1108d coverage 8.9% → higher)
- **K1202b primary-source** — Paper 2 primary-source authorisation chain (Taiwan earnings dataset licensing trail)
- **K1210 AU forensic** — Paper 2 ASX/Alpha Vantage earnings coverage extension (K1171 follow-up)
- **Paper4_body_rewrite** (post K1208) — main thread, match user 2026-04-17 7ecab636 decision
- **Paper2_section5_rewrite** (post K1211) — main thread, universal-magnitude reframe + 3 caveats
- **Paper1_Table6_errata** — 4 new K experiments needed for Paper 1 Tables 4/6/7/8 15 no-source values
- **Paper1_Batch2_cherry_pick** from K1209 draft
- **Paper3_pivot_decision** await user A/B/C
- **Paper10_BTCGAS_kickoff** await user decision on new paper slot

### Blocked (persistent)

- **K1100h**: Tick-level PRG on TAIFEX TX needs Dropbox 2017-2021 access (user-gated)
- **K1116d**: True ALFRED vintage blocked — needs `FRED_API_KEY` (user-gated)
- **K1161b**: IV crush retry blocked — needs paid options data (ThetaData / OptionMetrics), `blocked_on_user`
- **K1175 (older)**: Full 96-files-per-day GDELT scan OR GCP-authed BigQuery rerun (capacity-bound)
- **I4**: VIX futures roll yield — yfinance 無 VIX futures 歷史數據

---

## Section 4 — Methodology upgrades (session level)

### PIT alignment framework matured

Chain K1116 → K1116b → K1116c → K1116f → K1201 → K1203 establishes:

- True publication-lag PIT with calendar `shift(1)/shift(2)` correction
- ALFRED vintage fallback path (release-calendar PIT) when API blocked
- Triple-gate test for "positive" cells: (a) QLIKE improvement ≥ 5%; (b) Subperiod majority (≥2/3 years) significant; (c) All-alt augment does not overfit (no sign flip DM < 0)
- Single-cell positives (e.g., TLT finstress DM t=+3.74) rejected if any gate fails → prevents publication-leak artifact false positives

**Addition to research_program.md "行為準則" section recommended.**

### Sector-FE decomposition (K1207) as standard cross-market control

- Paper 2 foundry mechanism required ex-sector (orthogonalising earnings-date vol from sector loading) to test EAV within-sector variation
- K1207 formalises sector-FE as standard control in cross-market earnings panel regressions
- Generalisation candidate: any cross-market theta_EAV / theta_OFI experiment should include sector-FE variant

### Two-phase forecast timing (Paper 6 K880v2 precedent)

- K1200 verification confirms: same-day realized info (e.g., `r2_overnight[t]`) predicting `h_intraday_t` IS lookahead
- Proper two-phase: phase-1 uses t-1 close info for opening forecast; phase-2 uses t-open info for intraday update
- Applicable beyond PRG: any intraday vol forecast that "stitches" overnight and intraday components

### Synthesis agent pattern (K1204 / K1205 / K1208 / K1209 / K1211 / K1212)

- Multiple experiments per paper → dedicated worktree agent consolidates into narrative-state delta draft
- Worktree agent CANNOT modify `research_program.md` / `.tex` / paper body; ONLY produces delta markdown under `experiments/kXXX/`
- Main thread review → cherry-pick → merge → commit
- Precedent for future multi-experiment papers (reduces main-thread context pollution, per 2026-04-17 CLAUDE.md token discipline)

---

## Section 5 — Research directions forward (per-paper actionable)

### Paper 1 (leverage-direction)

- **Immediate**: Batch 2 cherry-pick from K1209 draft → 4 new K experiments (Tables 4/6/7/8 backfill) + 6 KB-only footnotes for T10-12/C3 + 3 critical direction errata (Table 3 vs Table 8 GJR QLIKE conflict, GLD γ=-0.067 forensic, D4 γ_HM 4.7 vs 5.4)
- **Post**: `uv run volpred ops paper-update --paper-id leverage-direction` once errata stack clears
- Target: JBF submission-ready within 2 iterations

### Paper 2 (taiwan-vt)

- **Immediate**: K1211 draft → main-thread §5 rewrite (universal-magnitude narrative + 3 caveats)
- **Then**: Paper2_errata_Table3_full_rewrite (K1175 canonical) + Data section + abstract + Table 4 doc errata + G20 T4 IS Sharpe 0.732 vs 0.413 errata + G12/G20 Section 6 formal experiments pending K1179
- **Foundry chapter**: 5-layer NULL stack → appendix or drop entirely; abandon foundry mechanism claim
- Target: Pacific-Basin Finance Journal submission window post K1211 merge

### Paper 3 (vt-trend-following)

- **Immediate**: USER DECISION on Paper3_strategic_decision (A/B/C). K1205 synthesis recommends (b) adopt pooled microstructure signal, drop VIX-regime narrative.
- **Alternate (a)**: Reframe as Taiwan microstructural study (Paper3_reframe pending)
- **Alternate (c)**: Abandon + repurpose findings as feed articles / negative-result paper
- **Before any decision**: wait K1100g_d7 cross-market replicate (SPY overnight / N225 morning→afternoon). If d7 passes Harvey 2/2 → (b) becomes strongest option.
- Also pending main thread: Paper3_D1 TSMOM direction errata (research integrity), Paper3_D2 Table 5 K1178 update + ρ=0.830 removal, Panel B K1193 STRENGTHENING re-write

### Paper 4 (vix-sufficiency)

- **Immediate**: K1208 synthesis draft → body_v4.tex rewrite (main thread). **First clarify CONFLICT-A4**: body_v4 narrative = channel-specific (user decided) OR UNIVERSAL_NULL (session implied)? Recommendation: adopt channel-specific pivot (user's 2026-04-17 decision 7ecab636), document UNIVERSAL_NULL as the "baseline-to-beat" in section setting up channel-specific claims.
- **Errata stack**: DIV1 41.8% direction CRITICAL, DIV3 Table 3 Sharpe ranking possibly flipped, DIV4 Table 6 era Harvey passes hidden, DIV2 CV 0.33 → 0.37 (6 處 typo)
- Target: JFE / RFS (paper was originally PROVISIONAL Paper 4)

### Paper 6 (prg-periodic-garch)

- **Post K1200**: submission-ready path clear. SPY main result → K880v2 canonical (DM -0.57 not 6.00, honest null).
- **Errata**: Paper6_DIV2 0050.TW OOS date (2019/12 vs K886 2021-01-08), DIV3 SPY VaR VR=0.93% source, experiments.md 加 K874c/K874e
- Target: FRL (Finance Research Letters) as originally planned

### New paper — BTC GAS-t negative-result methodology paper

- **Kick-off decision required** (user input):
  - Paper 10 slot (currently Paper10_start = "Crypto Fear Channel"; potentially conflicting scope)
  - Standalone new paper folder `paper/btc-gas-negative/`
  - Appendix of Paper 6 / Paper 9
- **Content ready**: K1129 / K1133 / K1133b regime-concentrated reversal; P1 DM t=-4.67 Harvey, P2/P3 NS preliminary; Student-t 75% vs GAS dynamics 25% decomposition
- **Required before kick-off**: P2/P3 expand sample (FTX/Luna and spot-ETF eras are n=345/n=100 PRELIMINARY, need more post-2023 data); commodity GAS-t cross-check (K1135 status?)
- Target: J. Futures Markets / Int. Rev. Finan. Analysis / Empirical Econ. (negative-result-friendly)

---

## Merge checklist for main thread

- [ ] Review §1 canonical K numbers against `storage/memory/knowledge.json` entries for 2026-04-17/18
- [ ] Resolve **CONFLICT-A4** (Paper 4 narrative)
- [ ] Decide Paper 3 A/B/C (wait K1100g_d7 first?)
- [ ] Decide BTC GAS paper slot (Paper 10 vs standalone)
- [ ] Merge §1 findings into `research_program.md` 面向 H (paper section) + 面向 A/B/C (methodology findings)
- [ ] Merge §4 methodology upgrades into 行為準則 section (PIT triple-gate, sector-FE standard, two-phase forecast)
- [ ] Update backlog in `storage/next_tasks.json` with §3 new queued items + mark §3 completed items
- [ ] Error log update: `docs/error_log.md` should capture Paper 3 K1128 structural IS/OOS VIX range disjoint lesson, Paper 6 K880 lookahead pattern, foundry mechanism 5-layer stack method as "null-confirmation standard"
- [ ] Post-merge: `git commit` with narrative transitions logged; subsequent paper-update cycles can reference new canonical state

---

*End of K1212 delta draft. ~1900 words (body, excluding checklist / flags). Produced 2026-04-18 ~ by worktree agent. Seed 42 (nominal, no random process used).*
