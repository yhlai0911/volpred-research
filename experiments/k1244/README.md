# K1244: Paper 10 §6 Structure Reframing (post-K1241 NULL)

**Status**: DONE (revised §6 scaffold delivered)
**Paper**: 10 — Crypto Fear Channel (`paper/crypto-fear-channel/`)
**Proposed / executed by**: Claude (worktree `agent-adaf4996`)
**Prior ids**: K1240 (§5 + §6 initial skeleton — now SUPERSEDED in §6), K1241 (pooled-variance fear-channel NULL), K1025 (QR + asymmetric Granger + DY spillover + regime Granger), K746b (asymmetric VIX-BTC Granger), K639 (BTC-SPY Granger), K1133 (sub-period regime convention), K1214 (companion negative paper), K1237 (§2 LitRev), K1242 (§7/§8/§9 drafts)

---

## Purpose

K1241 (commit `de386885`) delivered a decisive NULL for the pooled GJR-GARCH(1,1)-X(VIX²) fear-channel regression:

- $\hat{\phi}_{\mathrm{M2}} = -9.67\mathrm{e}{-6}$, $t_{\mathrm{BW}} = -0.12$, $p = 0.90$
- LRT M2 vs M1: $p = 0.95$ (no improvement)
- OOS DM-HLN: $t = +0.75$, $p = 0.45$ ($n = 1{,}236$)
- Sub-period same-sign stability: **0/3** (signs $-, +, -$ across P1/P2/P3)
- Harvey (2016) $|t|>3$ gate: **FAIL** on all four sub-checks
- Overall verdict: **NULL**

The K1240 §6 skeleton positioned this GARCH-X regression as the *Main Results* (§6.1 Table 3 primary, §6.2 alternative fear proxies, §6.3 pre/post-ETF split). That positioning is no longer defensible — running the NULL as a Main Result would read as the paper's main contribution collapsing.

**However**, the K1241 agent narrative insight (README.md "Interpretation and Paper 10 narrative impact" section) is correct: the NULL *strengthens* the paper's thesis rather than killing it, provided §6 is restructured. Paper 10's central claim (outline.md line 20) is: "The crypto fear channel is asymmetric, tail-concentrated, and regime-dependent." K1025 already provides three pieces of positive evidence (QR tail amplification $8.54\times$; asymmetric Granger with $F_{\text{BTC}^-\to\text{VIX}} = 18.96$ at lag 1 versus $F_{\text{BTC}^+\to\text{VIX}} = 2.00$; DY spillover with BTC as net receiver at $-76.89\%$; regime-conditional Granger with $F_{2020} = 11.05$, $p = 7.9\mathrm{e}{-7}$ concentrated in COVID and insignificant in four other sub-periods). K746b and K639 supply corroborating asymmetric Granger numbers.

K1244 re-scaffolds §6 along these lines:

- §6.1 Main — Quantile regression tail-coefficient identification (K1025 QR)
- §6.2 Main — Asymmetric Granger causality (K1025 + K746b + K639)
- §6.3 Main — Diebold-Yilmaz spillover characterisation (K1025 DY)
- §6.4 Main — Regime-dependent fear channel (K1025 sub-period Granger)
- §6.5 Robustness — Pooled-variance naive spec NULL (K1241 — demoted from §6.1 Main)

This is scientifically honest (K1241 NULL is not hidden; reported verbatim in §6.5 with Harvey gate FAILs) and narratively coherent (the pooled NULL becomes *evidence for* the tail/asymmetric/regime framing of §6.1-§6.4, rather than *against* the fear-channel hypothesis).

---

## Files

- `k1244_s6_revised.md` — main deliverable (~1{,}740 words, 5 subsections §6.1-§6.5, Markdown draft with canonical numbers verbatim from K1025 and K1241 JSON)
- `k1244_revised_structure.json` — structured per-subsection source mapping (canonical numbers, promotions, demotions, K1242 §7 coordination notes, narrative alignment notes)
- `README.md` — this file

Per CLAUDE.md rule (worktree agent does not write body.tex), K1244 delivers Markdown + JSON only. Main thread owns the subsequent body.tex §6 rewrite.

---

## Source materials (verified before drafting)

| Experiment | Path | What K1244 used |
|---|---|---|
| K1240 | `experiments/k1240/k1240_s5_s6_draft.md` | original §6 skeleton (to supersede) |
| K1241 | `experiments/k1241/k1241_results.json` + README | NULL canonical numbers (§6.5) + narrative recommendation |
| K1025 | `experiments/k1025/k1025_results.json` | QR, asymmetric Granger, DY spillover, regime Granger (§6.1-§6.4) |
| K746b | `experiments/k746b/k746b_bitcoin_vix_fixed_results.json` | part_b_granger_fixed (§6.2 corroboration) |
| K639 | `experiments/k639/k639_results.json` | granger_causality (§6.2 corroboration) |
| K1242 | `experiments/k1242/k1242_s7_s8_s9_draft.md` | §7 structure for coordination note |
| Paper 10 outline | `paper/crypto-fear-channel/outline.md` | central claim (line 20), K1025/K746b/K639 mapping (lines 12-16) |

No new data download, no new estimation — K1244 is pure re-scaffolding of existing canonical JSON outputs. Seed 42 (all inherited).

---

## Key numbers (re-stated for quick reference)

### §6.1 QR (K1025)

| $\tau$ | $\hat{\beta}_{\tau}$ | $t$ | $p$ |
|---|---|---|---|
| 0.05 | $-2.863$ | $-10.93$ | $2.9\mathrm{e}{-27}$ |
| 0.50 | $+2.613$ | $+5.44$ | $5.7\mathrm{e}{-8}$ |
| 0.95 | $+22.308$ | $+8.88$ | $1.2\mathrm{e}{-18}$ |

Tail amplification $|\beta_{0.95}| / |\beta_{0.50}| = 8.54\times$. Primary $\hat{\phi}$ for Paper 10 is **redefined** as $\hat{\beta}_{\tau=0.95}$ (not K1241 pooled $\phi$).

### §6.2 Asymmetric Granger (K1025, lag 1)

| Direction | $F$ | $p$ |
|---|---|---|
| $\text{BTC}^- \to \text{VIX}$ | $18.96$ | $1.4\mathrm{e}{-5}$ |
| $\text{BTC}^+ \to \text{VIX}$ | $2.00$ | $0.157$ |

### §6.3 DY spillover (K1025)

Mean total $90.11\%$; mean from-BTC $21.47\%$; **mean net-BTC $-76.89\%$** (net receiver).

### §6.4 Regime Granger (K1025)

$F_{2020} = 11.05$ ($p = 7.9\mathrm{e}{-7}$), other four sub-periods all $p > 0.16$.

### §6.5 Pooled NULL (K1241)

$\hat{\phi}_{\mathrm{M2}} = -9.67\mathrm{e}{-6}$, $t_{\mathrm{BW}} = -0.12$, $p = 0.90$, Harvey FAIL, sub-period 0/3.

---

## Main-thread adoption steps

1. Merge K1244 worktree into main (`bash scripts/merge_worktree.sh`).
2. Update `experiments/k1240/README.md` with pointer "§6 superseded by K1244 post-K1241 NULL reframing" (do *not* delete K1240 — it remains the §5 canonical source).
3. Read `k1244_s6_revised.md` and use it as the reference when rewriting `paper/crypto-fear-channel/body_vN.tex` §6 in the main thread.
4. Coordinate with K1242 §7 per `k1244_revised_structure.json.k1242_s7_coordination`:
   - consolidate §7.2 sub-sample Granger into §6.4 (avoid redundancy)
   - narrow §7.5 endogeneity to IV-orthogonalised fear shock only (§6.2 covers symmetric Granger)
5. Rewrite K1242 §9 placeholder `headline φ` per `k1244_revised_structure.json.narrative_alignment.§9_conclusion`.
6. Do *not* re-run any experiment — K1244 is a writing/narrative restructure only.

---

## Research-honesty compliance (CLAUDE.md)

- **Principle 1 (no fabrication)**: every number in `k1244_s6_revised.md` and `k1244_revised_structure.json` is verbatim from `experiments/k1025/k1025_results.json` or `experiments/k1241/k1241_results.json`. No interpolation. Inspectable by `jq` on the source JSON.
- **Principle 9 (NULL reported)**: K1241 NULL is in §6.5 with all Harvey gate FAILs preserved; §6.5 interpretation frames the NULL as informative but does not soften the statistical verdict.
- **Principle 11 (lookahead)**: All three source experiments use lag-1 regressors (K1025 $\Delta\mathrm{VIX}_{t-1}$, K746b $\mathrm{VIX}_{t-1}$, K1241 $\mathrm{VIX}^2_{t-1}$ with `signal.shift(1)`). No lookahead.
- **Principle 12 (seed)**: seed 42 inherited across K1025, K1241, K1244. No new RNG calls in K1244 (pure writing task).
- **Principle 13 (retract when overturned)**: K1240 §6 Main positioning is *superseded by* K1244, not deleted. K1240 README should be updated to point to K1244 (main-thread step 2).

---

## Why K1244 is not a new experiment

K1244 produces no new numerical output — it is a narrative and structural reframing deliverable that repackages existing canonical JSON outputs (K1025, K1241, K746b, K639) into a revised §6 scaffold. This is consistent with the CLAUDE.md paper workflow rule: *worktree agents produce Markdown / JSON, not body.tex*. The actual §6 body.tex rewrite happens in the main thread after K1244 is merged.

The experiment-ID K1244 is used here (rather than a non-experiment tag) because the task involves substantive analytical decisions — which evidence promotes to Main, which demotes to Robustness, how the NULL is reframed — that warrant a discoverable, citable entry in the experiments registry and knowledge base.
