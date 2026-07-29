---
name: reproducibility-audit
description: Inventory or rerun VolPred experiment artifacts to verify reproducibility. Use for reproducing a K experiment, auditing paper/feed experiment coverage, or checking code, input, seed, and result identity drift.
---

# Audit reproducibility

Read `docs/reproducibility.md` and use `scripts/reproduce_check.py` as the execution owner.
Reproducibility and research validity are separate claims.

## Inventory

1. Resolve the exact experiment directory and canonical result.
2. Verify `reproduce_spec.json`, entrypoint identity, inputs, seeds, environment policy, and
   canonical result mapping.
3. Mark every in-scope experiment as mapped or explicitly unverified. Never guess an identity.

## Isolated rerun

1. Preserve the main checkout's code, result, and input hashes.
2. Run the bounded reproduction workflow in its prescribed isolated environment.
3. Collect `reproduce_report.json` and the immutable execution receipt.
4. Confirm the main checkout hashes are unchanged.
5. Accept only the outcome vocabulary owned by `scripts/reproduce_check.py`; only exact or
   policy-tolerated passes are success.

## Completion

Report the period, inputs, samples, seeds, code identity, result comparison, and receipt path.
State explicitly that a reproducible result is not automatically a valid empirical claim;
methodology and code review remain separate gates.
