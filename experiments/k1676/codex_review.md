# Codex final review — K1676

Verdict: **PASS_NULL_RESULT**

Reviewer: Codex primary path, with an independent source-only red-team before
the binding rerun.

## Review history

The first self-review was too permissive. An independent reviewer returned
after the first non-binding run and found three majors:

1. returns were computed after the cross-asset join;
2. the fixed −2% robustness result was not connected to the verdict;
3. the tracked `experiments/K1609/` input path used incorrect case.

The initial run was retracted. Source was fixed, statically rechecked, and the
independent reviewer returned `PASS_FOR_BINDING_RERUN`. Only the later reruns
are binding.

## Source checks

- **Return alignment — PASS**: each asset return is computed on its native
  index; merged rows must have identical return-start dates. One mismatched row
  is mechanically removed and counted in results.
- **Lookahead — PASS**: UUP state is shifted one day. DFII10 uses backward
  `merge_asof` plus an extra market-day availability lag. Rolling correlations
  are shifted one day. Same-day SPY/GLD tail co-movement is explicitly
  descriptive and never becomes a strategy signal.
- **Interaction hierarchy — PASS**: mean protection and tail beta are separate
  models; all triple beta interactions include their lower-order terms; USD and
  real yield enter the canonical joint model together.
- **Inference — PASS**: HAC lag 21, one four-test Holm family, Harvey
  `|t|>=3`, 5,000-rep block bootstrap, LOYO sign test, sparse-cell gate and
  binding −2% sign/sparsity robustness.
- **Artifacts — PASS**: seed=42; atomic JSON temp-write/parse/replace;
  current-vintage FRED and ETF proxy limitations disclosed.

## Result verification

- Sample: 2,503 days, 2016-07-06 through 2026-06-18.
- Primary tail events: 272; −2% robustness events: 88.
- Four primary HAC t-statistics: `+0.342`, `−1.494`, `−1.151`, `−0.973`.
- Four Holm p-values: `0.750`, `0.541`, `0.750`, `0.750`.
- Every 21-day block-bootstrap 95% CI crosses zero.
- Strict primary passes: 0/4.
- USD weak primary bucket is n=47; −2% robustness also has sparse cells. These
  gates would prevent PASS even if a coefficient were superficially strong.
- Joint-state VIF is about 1.05, so the NULL is not explained by severe USD / real-yield collinearity.

The JSON numbers were read directly after execution; no agent-reported number
was trusted without artifact verification.

## Reproducibility

- Binding script completed with exit 0 twice after the final source change.
- Canonical JSON SHA-256 excluding `generated_at_utc` matched twice:
  `85d69f125ca6844a83eb15da0e968eb75ba4ff98eaabdd1110520b372cb99165`.
- `jq empty`, `python -m py_compile`, and `git diff --check` pass.
- Both PNGs decode successfully: 2127×1600 and 1959×801.

## Claim gate

Approved claim: lagged USD and real-yield states do not provide robust partial
moderator evidence for GLD tail-day mean protection or SPY–GLD tail beta in
this 2016–2026 U.S.-ETF sample.

Disallowed claims: causal “decoupling”, historical point-in-time FRED trading
availability, bullion-wide inference, a forecast, or an investable strategy.
