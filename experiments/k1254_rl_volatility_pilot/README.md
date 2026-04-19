# K1254 — RL Volatility Forecasting Pilot (Scoping Doc)

**Status**: SCOPING ONLY — no `.py`, no results, no run. This is a pre-experiment specification produced 2026-04-18 by the novelty-quota workflow. Future Claude / Codex agent picks up from `## Implementation Handoff`.

**Task type**: experiment (scoping)
**Novelty source**: `docs/topic_diversity_audit.md` rank 1 candidate (`feed_ct=0`, `kb_ct=0`).
**User directive (2026-04-19)**: 「未來保留跳脫主題研究」novelty quota 20%.

---

## 1. Motivation

The platform has accumulated >1,130 experiments concentrated in 5 dominant clusters: SPY-VT (369 feed mentions), GARCH family (317), VT strategies (300), VIX & VIX-derivatives (270), GLD (203). Topic diversity audit (`scripts/build_topic_diversity_audit.py`, last run 2026-04-19) shows reinforcement learning for volatility prediction is the **single highest-novelty candidate**: zero feed coverage, zero knowledge-base records, zero matching experiment directories.

Existing K verification (2026-04-18, this scoping run):
- `experiments/` — 4 README files matched bare token `RL` but only as substring of `borderline` / `BORDERLINE`. No actual RL-vol experiment.
- `storage/memory/knowledge.json` — 0 records match `\breinforcement\b|\bDDPG\b|\bPPO\b|\bSAC\b|deep.*reinforce`.
- `research_program.md` — only mention of RL is the literal string `MED 5: bibliography ...` (acronym collision). No RL methodology line.

Conclusion: novelty claim is real. K1254 would be the platform's first RL-vol experiment.

## 2. Differentiation vs Existing Work

### vs platform internal baselines

| Existing K | What it does | What K1254 adds |
|---|---|---|
| HAR-RV (K1137 + family) | OLS regression on past 1d/5d/22d realized var | RL agent learns nonlinear policy; can adapt forecast magnitude to regime without explicit threshold |
| GJR-GARCH (K1148 + family) | MLE with leverage asymmetry | RL avoids parametric distributional assumptions; reward = QLIKE directly (not log-likelihood) |
| LSTM/Transformer vol (Paper 9 family, ~4 dirs) | Supervised regression on past returns/RV | Sequential decision framing — agent gets reward feedback per step, can implicitly learn stop-loss-style asymmetric loss |
| A4f (`alt-data` allocation strategies) | Macro-data-conditional VT | Different domain (allocation, not vol forecast) |

### vs literature (see `references.md`)

The vast majority of "RL + volatility" papers in 2023-2025 use RL for **trading or portfolio allocation** with a vol forecast (often LSTM/GARCH) **as input feature** — not as the prediction target. K1254's target is novel: **RL agent's action IS the vol forecast h+1**, scored by QLIKE/log-score. The closest precedent (Cao et al. 2024, arxiv 2410.11789) applies DRL to dynamic local-vol surface fitting under SDE constraints — adjacent but different (model calibration, not standalone forecast).

## 3. Experiment Design

### 3.1 Asset and sample

- **Primary**: SPY (US equity benchmark, daily data already in `storage/`)
- **Sample**: 2004-01-02 to 2025-12-31 (~22 yr, ~5,500 trading days). Spans dot-com tail, GFC, EU debt, taper tantrum, COVID, 2022 rate hikes, 2024-25 — at least 4 distinct vol regimes.
- **Realized variance proxy**: daily squared close-to-close returns (matches existing GJR-GARCH baseline construction). Fall-back to 5-min RV if `storage/5min_data/SPY/` ≥3 yr available; only as robustness, not main spec.

### 3.2 Baselines (must beat to claim signal)

| Baseline | Metric | Reference K |
|---|---|---|
| HAR-RV (Corsi 2009 spec) | QLIKE | K1137 |
| GJR-GARCH(1,1,1) Normal | QLIKE | K1148 |
| Rolling realized variance (22d) | QLIKE | trivial floor |

Single-asset Sharpe-style claims forbidden. Stat tests:
- **Diebold-Mariano (HLN small-sample correction)** vs HAR and GJR. Pass = |t| > 2 per Harvey threshold; **|t| > 3** for paper-publishable.
- **Model Confidence Set (Hansen 2011)**: RL must enter the 10% MCS.
- Multi-horizon (h=1,5,22): claim only the horizons where DM passes.

### 3.3 RL agent

**Algorithm choice: PPO (Proximal Policy Optimization)**

Rationale:
1. **Continuous action** (vol forecast is positive scalar) — PPO and SAC both natively support; DDPG also supports but is more brittle to hyperparameters.
2. **On-policy** — easier to debug than SAC's replay buffer + entropy temperature; less risk of silent overfitting.
3. **Stable in financial RL benchmarks** — PPO Sharpe 2.15 ± 0.05 vs DDPG/SAC in the 2025 ZenodoR risk-aware portfolio comparison (see refs).
4. **Small action dim (1)** = PPO's clipped surrogate is overkill but cheap; we get stability for free.

Fallback if PPO null: try SAC (off-policy, entropy-regularized) — but only after PPO is fully Codex-reviewed and confirmed bug-free, to avoid algorithm-shopping.

### 3.4 Action / reward / state

| Component | Spec | Lookahead guard |
|---|---|---|
| **Action** `a_t` | log-space scalar; forecast `σ̂²_{t+1} = exp(a_t)`. Clipped to [exp(-15), exp(0)] to prevent NaN. | Action emitted at t-1 close, scored against realized RV at day t. |
| **Reward** `r_t` | `-QLIKE = -(σ²_t / σ̂²_t - log(σ²_t / σ̂²_t) - 1)`. Uses **realized var at t**, agent's **forecast made at t-1**. Negate so RL maximizes. | Reward computed *after* day t closes; replay buffer / batch only contains tuples where `forecast.shift(1)` is enforced. |
| **State** `s_t` (dim ≈ 27) | Past 22d log returns + VIX_t + VIX 5d MA + 22d realized var + day-of-week dummies (4) | All inputs `shift(1)` before feeding agent. Explicit `assert state_t.index <= t-1` in loop. |
| **Episode** | Rolling 500-day blocks; agent state reset between blocks (so train/test boundary doesn't leak hidden state) | — |

### 3.5 Train / test protocol

- **Rolling-origin expanding-window**: train on first 2,000 days, walk forward 500-day OOS test windows, refit every 250 days.
- **Total OOS**: ~3,000 days (2012-2025), 6 non-overlapping test slabs.
- **Per-window**: 200,000 PPO env steps, batch 2048, lr 3e-4, clip 0.2, γ=0.95 (vol is short-memory). Hyperparameters fixed across slabs (no per-window tuning = no peeking).
- **Seeds**: `[0, 1, 2, 3, 4]` — report mean ± std of QLIKE across 5 seeds per slab. **Single-seed result is automatically rejected.**

### 3.6 Metrics

- Primary: **QLIKE** (per Patton 2011, robust to noisy proxy).
- Secondary: MSE, MAE on σ², log-score (Gneiting-Raftery proper score for predictive density if PPO outputs σ via stochastic policy).
- Statistical: DM-HLN t vs HAR / GJR / rolling-22d. Bonferroni adjustment across 3 baselines.
- Per-regime breakdown: split OOS into VIX terciles; QLIKE per tercile to detect regime-specific failures.

### 3.7 Compute budget estimate

PPO 200k steps × 6 OOS windows × 5 seeds = 6M env steps total. Single-thread CPU vectorized environment (no GPU needed for state dim 27 + scalar action). Estimated wall: **~6-10 hr** on M-series Mac (cf. existing GARCH MLE refits ~30 min). Add Codex review pass + figure generation: full cycle **~12 hr from kick-off to knowledge entry**.

If wall budget exceeds, drop seeds to 3 (still > single-seed) or shrink to SPY-only (current spec is already SPY-only). Do **not** drop OOS windows — multi-regime coverage is non-negotiable per K1128 lesson.

## 4. Predicted Failure Modes (write down before running, per research-honesty rule)

1. **Most likely**: PPO matches HAR-RV but does not beat it (DM |t| < 2). RL adds variance without adding signal in a low-SNR daily-vol setting. **Null result framing ready**: "PPO/RL does not Pareto-improve on HAR-RV at daily horizon for SPY 2012-2025 OOS; the marginal value of RL's nonlinear policy is dominated by HAR's heterogeneous-AR structure."
2. **Second most likely**: PPO beats HAR in a single OOS slab (e.g. 2020 COVID) but fails MCS overall — regime-specific edge that doesn't survive multi-period validation. K1100g_d1 / K1128 type lesson: report null and document the slab pattern.
3. **Bug risk**: Reward sign error (RL maximizes negative reward → minimizes QLIKE; easy to flip sign and silently get inverse policy). Codex must verify reward function before run.
4. **Lookahead risk**: `state_t` accidentally includes `RV_t` instead of `RV_{t-1}`. State-builder unit test required: assert that swapping in `pd.Series(0.0, index=...)` for the row at index `t` does not change `state_t`.
5. **Hyperparameter overfitting**: PPO has γ, λ, clip, lr — temptation to tune. Spec freezes them at literature defaults; if changed, must rerun all OOS (no in-flight tuning).

## 5. Success Criteria

| Tier | Criterion | Action on hit |
|---|---|---|
| **Strong PASS** | DM-HLN |t| > 3 vs both HAR and GJR, MCS-included in ≥4/6 OOS slabs, beats baseline in ≥2/3 VIX terciles | Knowledge entry + paper-section candidate (would be platform's first RL-vol paper) + Paper 9 cross-link |
| **Weak PASS** | DM |t| > 2 vs at least one of HAR/GJR, MCS-included in ≥3/6 slabs | Knowledge entry, feed article (research-tagged), no paper push without K1254b extension to GLD/0050.TW/BTC |
| **NULL** (most likely outcome) | DM |t| < 2 across the board | Knowledge entry as null result, error-log rule re: "RL adds no edge at daily-vol SNR for liquid US equities", **do not** advance to multi-asset |
| **FAIL** (bug, not finding) | Reward sign flipped, state leak detected, single-seed instability >50% std | Fix bug, rerun. Do not record as null until clean run. |

## 6. Implementation Handoff

When future agent (Claude main thread or Codex) picks this up:

1. Read this README + `references.md` + `docs/error_log.md`.
2. Implement `experiments/k1254_rl_volatility_pilot/k1254_rl_volatility_pilot.py` per spec §3.
3. Use `stable-baselines3` PPO (already in pyproject? — verify; if not, `uv add stable-baselines3 gymnasium`).
4. Custom `gym.Env` subclass:
   - `reset()` → returns `state_0`
   - `step(action)` → returns `(state_{t+1}, reward_t, done, info)`
   - **`info` must include `forecast_t, realized_var_t, t`** for post-hoc DM test reconstruction
5. Output `k1254_rl_volatility_pilot_results.json` with structure:
   ```json
   {
     "spec_version": "1.0",
     "asset": "SPY",
     "sample_period": "2004-01-02 to 2025-12-31",
     "oos_slabs": [{"start": "...", "end": "...", "qlike": {...}, "dm": {...}}, ...],
     "baselines": {"har_rv": {...}, "gjr_garch": {...}, "rolling_22d": {...}},
     "rl": {"algo": "PPO", "seeds": [0,1,2,3,4], "qlike_mean": ..., "qlike_std": ...},
     "verdict": "STRONG_PASS | WEAK_PASS | NULL | FAIL"
   }
   ```
6. **Codex review BEFORE writing knowledge** (per platform rule + K1213 lesson).
7. Generate 3 figures: (a) RL vs HAR vs GJR rolling QLIKE, (b) per-regime QLIKE bars, (c) RL forecast vs realized scatter. Save under `figures/`.
8. Knowledge entry only after Codex clears; write null-result framing if NULL verdict.

## 7. Go / No-Go Recommendation to Main Thread

**GO** — under the following conditions:

- Slot in compute schedule when no other ML / heavy MLE experiment is running (PPO 6M steps doesn't share well with parallel optim).
- Treat as **exploratory novelty experiment** under 20% novelty quota, not a planned-paper experiment. Most likely outcome is NULL; that is itself publishable as a methodological contribution ("RL provides no daily-vol edge over HAR for liquid US equities").
- Pair with mandatory Codex review pass — RL bugs (reward sign, state leak, replay-buffer leak) are notoriously easy to ship.
- If NULL, **do not** auto-extend to k1254b (GLD / 0050.TW / BTC). Stop, record lesson, recycle slot.
- If WEAK or STRONG PASS, immediately schedule k1254b cross-asset before any narrative writing — single-asset RL claims have a poor track record (cf. K1213/K1216 multistart fragility lesson, applied here as "single-asset neural-method PASS often a fluke").

**Do not commit this scoping doc as a finding.** It is a spec, not a result. Knowledge entry is created only after the actual experiment runs and Codex reviews.
