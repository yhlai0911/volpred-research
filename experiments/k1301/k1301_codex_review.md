# K1301 Codex Primary-Path Code Review

**Date**: 2026-05-13
**Reviewer**: Codex CLI (gpt-5.4, ChatGPT account mode)
**Task ID**: task-k1301-codex-review-primary
**Verdict**: **CONDITIONAL PASS**

---

## Review Context

Per `.claude/rules/experiments.md` K1259 lesson: "subagent fallback PASS ≠ Codex primary-path PASS;
primary-path Codex re-verification mandatory before closure_status can be final."

K1301 had a Gemini CLI fallback CONDITIONAL PASS (2026-05-11, quota-blocked Codex).
This document records the mandatory primary-path Codex review completed 2026-05-13.

---

## Findings

### Finding 1 — `pass_3sigma` naming/semantic inconsistency (LOW)

**Location**: `k1301_har_rs.py` line 485

The `dm_hln.pass_3sigma` field in `evaluate_asset()` is computed as:
```python
"pass_3sigma": (not np.isnan(dm_t)) and abs(dm_t) > 3.0,
```
This only checks `|DM_HLN_t| > 3.0`, NOT the second condition `har_rs_lower_mse`.

The declared `pass_rule` in the methodology header (line 58) says:
```
"|DM_HLN_t| > 3 AND HAR-RS lower MSE"
```

The `_pass()` function in `main()` (line 568) DOES correctly require both conditions:
```python
return r["dm_hln"]["pass_3sigma"] and r["dm_hln"]["har_rs_lower_mse"]
```

**Risk**: Downstream consumers reading only `dm_hln.pass_3sigma` from the JSON may interpret
it as the final pass flag, missing the `har_rs_lower_mse` requirement.

**Impact on verdict**: NONE — the TX1 NULL conclusion is unchanged. TX1 `pass_3sigma=False`
(t=1.29 << 3.0) so both the field and the `_pass()` function give False.

**Recommendation**: Rename `pass_3sigma` to `dm_t_exceeds_3sigma` or add a comment.
Non-blocking for this result.

### Finding 2 — Module-level `RNG` unused (LOW)

**Location**: `k1301_har_rs.py` line 94

```python
RNG = np.random.default_rng(SEED)
```

This module-level `RNG` is never called. The only randomness is in `bootstrap_mse_ci()`,
which creates its own local `rng = np.random.default_rng(seed)` (line 384) with `seed=SEED=42`.

**Impact**: No reproducibility issue — bootstrap is correctly seeded. The module-level `RNG`
is dead code. Non-blocking.

---

## Per-Item Checklist

| Item | Finding | Severity | Verdict |
|------|---------|----------|---------|
| 1. Lookahead bias | `rv_lag1 = d["rv"].shift(1)` applied before rolling; `Y = log(d["rv"].shift(-1))` uses raw rv column; no future leakage detected | — | PASS |
| 2. Random seed | `bootstrap_mse_ci()` uses `np.random.default_rng(seed=42)` correctly; module-level RNG is dead code but no reproducibility harm | LOW | CONDITIONAL PASS |
| 3. DM-HLN formula | `d = loss_a - loss_b`; HLN = DM × sqrt((T+1-2h+h(h-1)/T)/T) matches Harvey 1997; p-value uses t(df=T-1); h=1 uses gamma0 only (correct) | — | PASS |
| 4. Semivariance definition | `rs_plus = sum(r² * 1(r>0))`, `rs_minus = sum(r² * 1(r<0))`, zero returns correctly excluded, rv = rs_plus + rs_minus by construction | — | PASS |
| 5. Train/test split | `n_train = floor(T*0.7)`, `idx_test = arange(n_train, T)`, purely chronological, no shuffle; both models trained on identical idx_train rows | — | PASS |
| 6. OOS prediction | beta_rv and beta_rs estimated only on idx_train; predictions only on idx_test; no train contamination | — | PASS |
| 7. `pass_3sigma` logic | Field only checks `\|t\| > 3`; full AND condition (with har_rs_lower_mse) is in `_pass()` — naming inconsistency but correct overall verdict | LOW | CONDITIONAL PASS |

---

## Overall Verdict: CONDITIONAL PASS

**Core research integrity confirmed:**
- No lookahead bias
- Chronological OLS train/test split with no leakage
- HAR-RV and HAR-RS estimated on identical training rows
- DM-HLN implementation matches Harvey-Leybourne-Newbold (1997) h=1 formula
- BNKS semivariance decomposition correctly computed (RS+ + RS- = RV by construction)
- Seed=42 is correctly applied to the only random process (bootstrap CI)

**Conditions (both LOW severity, non-blocking for NULL verdict):**
1. `pass_3sigma` field semantics differ from declared pass_rule; recommend rename or comment
2. Module-level `RNG = np.random.default_rng(SEED)` is dead code; no reproducibility impact

**Closure status**: `codex_conditional_pass` — primary-path Codex review complete.
K1259 protocol satisfied. The NULL verdict (TX1: DM-HLN t=1.29, p=0.197, Harvey 3σ not met)
stands as the canonical result.

---

## Reviewer metadata

```json
{
  "reviewer": "Codex CLI primary path",
  "model": "gpt-5.4",
  "auth_mode": "ChatGPT account",
  "codex_version": "codex-cli 0.121.0",
  "session_thread": "019e1fd6-af70-7850-9a59-f73267154855",
  "date": "2026-05-13",
  "task_id": "task-k1301-codex-review-primary",
  "prior_review": "Gemini CLI fallback CONDITIONAL PASS (2026-05-11, quota-blocked)"
}
```
