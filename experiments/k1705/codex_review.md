# K1705 Independent Primary-Path Codex Review

**Final verdict: PASS**  
**Reviewer:** Codex CLI gpt-5.6-sol ultra  
**Reviewed at:** 2026-07-15T22:39:46Z  
**Reviewed commit:** `65c3e3199` (`65c3e31999efe552954200d55650bc3941708379`)  
**Frozen claim surface:** `README.md`, `k1705.py`, `k1705_results.json`, `test_k1705.py`

This verdict certifies only the bytes pinned in `review_verdict.json`. No frozen
claim-surface file was modified during review.

## Executive conclusion

I found no blocking methodological, implementation, numerical-direction, result-
consistency, or claim-scope defect.

K1705 correctly establishes two mechanical defects in the archived K1100c Joe
superiority narrative:

1. K1100c computes its loss differential as Joe minus DCC. Its positive stored
   differentials therefore mean that Joe has the higher, worse loss, despite the
   parent README labeling positive statistics as Joe wins.
2. K1100c's archived Joe density does not reduce to the independence density at
   theta = 1. K1705's analytical replacement does.

K1705 also correctly avoids turning its replacement dependence-score exercise
into a DCC-superiority claim. Every marginal calibration gate fails, so all four
formal decisions stop at the margins. In addition, both score directions reverse
under the deliberately severe one-trading-day delay, and neither delayed result
passes the Harvey `|t| > 3` threshold. The frozen verdict's final phrase,
`DEPENDENCE_ATTRIBUTION_NOT_ESTABLISHED`, is therefore the right scope.

## Audit population, provenance, and blind spots

I read the complete four-file claim surface at commit `65c3e3199`, not a suspect
subset. I also inspected the exact K1100c source and result fields used by the
parent-sign and parent-density audit. The full reviewed population is pinned by:

| File | SHA-256 |
|---|---|
| `README.md` | `6754d5d3f40a24017860e574cbf5027434bae7c4b50b6bfedd7fa8b44c64e0a6` |
| `k1705.py` | `a2543e60c0f0a19255d3c3217056a29582ef17a83cd3cc8da7bfaa697b0dd62d` |
| `k1705_results.json` | `b69a9e92e23971390343450e5188514401671b0833595201a8dd059907d972e1` |
| `test_k1705.py` | `71f712984ef62fff5dbd6ee9377937d04954c8491bd607b3cb33bdbf26cb6712` |

All four working-tree files equal the reviewed commit bytes. The three dependency
hashes also match the frozen JSON exactly:

- market snapshot: `467de79295c7afbaae1e6ba97b9240ee9a4bfbc0a9a191e61128b013f5f71e97`;
- K1100c results: `57990a06b8b887c27ec46d2b84e741d9935abfdf1a5dc09d1937873adce2dd32`;
- K1100c script: `2f3c970874b473ec236c16fa8e799bd56000a9ee34cd1b9499e49b53fee60b5d`.

The main artifact blind spot is that pointwise PIT, score, and parameter ledgers
are not persisted. I closed that gap for this review by recomputing the complete
four-cell experiment from the pinned source and dependencies. I did not attempt
to re-download or independently reconstruct the historical yfinance snapshot;
the empirical claim is explicitly conditional on the repository-pinned bytes.

## 1. Parent sign convention and current numerical directions

The K1100c source defines `d = l1 - l2`, and the relevant call passes Joe as
model 1 and DCC as model 2. Its stored means mechanically confirm the same sign:

- SPY-TLT: Joe `-9.1927577809` minus DCC `-9.4309064415` equals
  `+0.2381486606`;
- SPY-GLD: Joe `-9.0000704685` minus DCC `-9.1136658161` equals
  `+0.1135953476`.

These are losses, so lower is better. Positive Joe-minus-DCC means Joe is worse.
K1705's `sign_reversal_confirmed` fields and parent verdict are correct.

K1705 deliberately calls the canonical DM function as
`dm_test(dcc_loss, joe_loss)`. The canonical statistic is therefore mean
`DCC - Joe`, so negative favors DCC and positive favors Joe. The separate
`joe_minus_dcc_mean` field has the opposite sign by construction. All four JSON
rows obey these conventions (the mean identities agree to at most `6.94e-18`):

| Case | mean DCC NLS | mean Joe NLS | Joe-DCC | DM t (DCC-Joe) | Diagnostic direction |
|---|---:|---:|---:|---:|---|
| SPY-TLT, synchronous | -0.0369817 | -0.0007335 | +0.0362482 | -4.9141 | DCC |
| SPY-GLD, synchronous | -0.0167073 | -0.0047210 | +0.0119863 | -2.5551 | DCC |
| SPY-TLT, delayed | +0.0012121 | -0.0018481 | -0.0030602 | +2.2464 | Joe, not Harvey-significant |
| SPY-GLD, delayed | +0.0021512 | -0.0000811 | -0.0022323 | +1.7576 | Joe, not Harvey-significant |

The signs, booleans, narrative, and final scope are mutually consistent.

## 2. Joe density derivation and theta = 1 limit

Let

`a = (1-u)^theta`, `b = (1-v)^theta`, and `S = a + b - ab`.

For the stated Joe CDF, `C(u,v) = 1 - S^(1/theta)`, direct differentiation gives

`c(u,v) = (1-u)^(theta-1) (1-v)^(theta-1) S^(1/theta-2)`

multiplied by

`[theta*S + (theta-1)(1-a)(1-b)]`.

That is exactly the bracket implemented at `k1705.py:148`. At theta = 1, the
power terms in `(1-u)` and `(1-v)` become one, the bracket becomes `S`, and it
cancels `S^-1`; hence `c(u,v)=1` pointwise and the log density is zero. A 999-
point theta-one grid was exactly zero in floating point. At general theta values
1.1, 2, and 5, an independent mixed finite-difference derivative of the CDF
agreed with the implemented analytical density, with maximum absolute error
`6.33e-7` on the tested interior grid.

The archived K1100c bracket is `((theta-1)S + ab)`. At theta = 1 it yields
`ab/S`, not one. K1705 is correct to treat that as a defining-formula failure,
not as an empirical finding.

There are two nonblocking numerical caveats:

- K1705 floors `S` at `EPS=1e-8`. At high theta in the joint upper tail this
  ceases to be the exact Joe density (for example, `u=v=.9999, theta=5` is badly
  distorted). Across all 196 actual rolling refits, however, fitted theta stayed
  in `[1.0010046, 1.1563963]`, and zero scored observations activated the `S`
  floor. Re-estimating every refit with an unfloored stable formula changed theta
  by at most `2.87e-11` and point losses by at most about `1.1e-10`.
- The optimizer lower bound is 1.001 rather than the exact independence boundary
  1.0. Re-estimating with theta = 1 admitted changed any four-cell mean Joe loss
  by at most `1.01e-4`; it does not change the synchronous gaps, marginal stops,
  parent formula audit, or final claim. Future code should admit theta = 1 and
  use log-domain tail arithmetic.

## 3. One-sided marginal information sets

The timing is correct throughout:

- `ewma_variance` forms `h[t]` from `h[t-1]` and `return[t-1]^2`.
- At a marginal refit origin `t`, the Student-t degrees of freedom use
  `returns[start:t] / sqrt(h[start:t])`; the scored return is excluded.
- The realized return at `t` is transformed using the already available `h[t]`
  and degrees of freedom fitted only from earlier observations.
- The delayed sensitivity shifts only the second asset's return by one trading
  day and then reruns the same one-sided marginal and dependence pipeline.

Independent prefix-invariance tests changed all returns from a chosen future
index onward. Earlier PITs were identical, and the forecast variance and fitted
degrees of freedom at the mutation date were unchanged. This verifies the
one-sided implementation rather than merely matching the author's test.

## 4. Rolling DCC and Joe score implementation

`rolling_dependence_scores` constructs `history` from valid positions strictly
before the scored index. At a refit, it estimates both models on at most the
preceding 1,250 PIT pairs, with a 250-pair initial burn-in.

The DCC state reconstruction does not double-count the last history shock. The
loop at `k1705.py:182-184` consumes shocks 0 through `n-2`, leaving the state at
the last history time. Lines 185-187 then consume `history[-1]` exactly once to
form the current forecast state. Between refits the same one-shock update is
used. A mutation of the current PIT changed the current scores but left current
rho and theta unchanged, as required for a one-step forecast.

All actual DCC optimizations were also checked: each of the four cells has 49
refits and three deterministic starts per refit; all 588 L-BFGS-B starts reported
success and no fallback was used. A useful omitted diagnostic is that the DCC
persistence cap is nearly active in some TLT windows: 6/49 synchronous and 3/49
delayed selected `a+b > 0.9949`, against the 0.995 parameterization cap. GLD had
no such refit. This should be reported in a future robustness artifact, but it
does not support or invalidate a dependence winner here because all formal
decisions stop at the margins.

Joe is a rolling static copula parameter while DCC evolves its conditional
correlation between refits. That is a legitimate out-of-sample model comparison,
not a claim of equal parameterization. Both receive exactly the same marginal
PIT sequence, so the score difference isolates the fitted dependence component
conditional on those margins.

## 5. Marginal-first and two-step interpretation

The frozen procedure is best described as a conservative **absolute marginal-
calibration gate followed by a copula-score DM diagnostic**. It is not the full
Fissler-Hoga formal two-step predictive-ability test with a two-dimensional score
difference and jointly size-controlled critical values.

That distinction does not block the present conclusion. With identical marginal
forecasts, the comparative marginal score difference is identically zero and a
standard DM comparison of the copula component is the relevant relative test.
However, Fissler and Hoga explicitly note that misspecified marginal PITs remove
the theoretical guarantee that the true copula minimizes the copula score, and
recommend probabilistic-calibration assessment as a safeguard. K1705 performs
that safeguard and, on failure, refuses dependence attribution. See
https://arxiv.org/abs/2410.04165 (especially the discussion around Examples 6-7
and the calibration caveat).

The stored marginal diagnostics use all 3,306 post-start PITs, whereas the
dependence scores use the later 3,056 observations after burn-in. I repeated the
gate on the exact scored sample. It still fails for every relevant margin:
synchronous SPY KS `p=1.01e-10`, TLT `p=.0369`, and GLD `p=.00117`; SPY also has
strong squared-normal-score serial dependence. Therefore the sample mismatch
does not change any `STOP_AT_MARGINS` decision.

Downstream writing should call this a calibration-first gate, not claim that
K1705 implemented the paper's formal size-controlled two-step test.

## 6. Asynchrony sensitivity and claim scope

SPY, TLT, and GLD share the US close. K1705 correctly labels the full one-day
delay as a conservative stress test rather than evidence of actual timestamp
misalignment. It is deliberately severe: it compares SPY at day `t` with the
second asset's return from day `t-1`, with all subsequent fits still one-sided.

Both pairs reverse score direction under this stress. The delayed t-statistics
are +2.246 and +1.758, below the pre-specified Harvey threshold. Therefore the
replacement score direction is not robust, and the JSON correctly makes no
positive Joe or DCC dependence claim.

The safe claims supported by the frozen bytes are:

1. K1100c's published Joe-superiority sign interpretation is reversed.
2. K1100c's archived Joe density is invalid because it fails the theta-one
   independence limit.
3. On K1705's common one-sided margin proxy, no dependence-family attribution is
   established because the margins fail and the asynchrony direction reverses.

The bytes do **not** support a universal DCC-superiority claim, a formal
Fissler-Hoga two-step-test claim, an actual asynchronous-close claim, or a causal
flight-to-safety mechanism claim. The README and JSON stay within those limits.

One wording caveat: the success criteria are present in the frozen README and
are consistent with the outcomes, but Git history first introduces the README
and results in the same commit. Without an earlier external registration record,
`pre-specified` is verifiable while formal `pre-registered` status is not.

## 7. Result-byte consistency and focused verification

The complete experiment was rerun from the reviewed source into `/tmp`, leaving
the frozen result untouched. The rerun object equals the frozen JSON recursively
after removing only `created_at`. Replacing the rerun timestamp string with the
frozen timestamp also makes all 14,105 raw bytes identical. Thus there is no
stale-result or hand-edited-result mismatch.

Verification results:

- focused pytest: `3 passed`;
- `scripts/experiment_gates.py run --path experiments/k1705`:
  `PASS — 2 file(s) ... cleared 4 experiment-integrity gates`;
- full four-cell rerun: exact JSON equality except the expected runtime timestamp;
- Joe CDF finite-difference check: pass;
- marginal and dependence future-mutation checks: pass;
- stable Joe formula and theta-bound sensitivity: no material result change;
- all dependency and claim-surface SHA-256 checks: pass.

The supplied unit tests are narrow: they do not lock general-theta Joe density,
upper-tail stability, dependence refit timing, or full-result reproduction. The
independent checks above cover those risks for the frozen result, but future
revisions should promote them into regression tests and persist optimizer/boundary
diagnostics.

## Final verdict

**PASS.** `blocking_defects` is empty. The audit is reproducible, the parent sign
and density findings are mechanically correct, one-sided timing is intact, the
frozen numerical result matches a full rerun, and the final claim appropriately
stops short of dependence attribution.
