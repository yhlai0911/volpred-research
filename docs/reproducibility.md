# Experiment reproducibility audit

`scripts/reproduce_check.py` is the canonical experiment-level reproducibility
scanner and bounded rerun engine. It does not replace methodology or code review:
a matching rerun shows that an archived result can be regenerated under the
recorded workflow, not that the research claim is valid.

## Commands

```bash
# Fast, read-only inventory (paper manifests/submission compile closures + latest 60 published feed items)
uv run python scripts/reproduce_check.py inventory --no-write

# Persist the derived inventory to storage/ops/reproducibility/latest.json
uv run python scripts/reproduce_check.py inventory

# Rerun only experiments with a valid, pre-existing reproduce_spec.json
uv run python scripts/reproduce_check.py run --experiment K1683
```

Every runnable experiment declares its entrypoint, canonical result, pinned
input hashes, timeout, network policy, random seed, and comparison policy in
`experiments/<id>/reproduce_spec.json`. Non-default tolerances require a reason;
every ignored JSON pointer also requires a reason. Missing or ambiguous mappings
are `unverified`, never silently guessed.

## Safety and evidence

- The child runs from committed `HEAD` in a disposable clone outside the repo.
- The current code/result/input hashes must match that checkout before execution.
- macOS `sandbox-exec` denies network and writes outside the disposable root.
- Side-effect guards disable email, remote reads/writes, and canonical writes.
- Timeout owns a process group and verifies termination of descendants.
- The baseline result is removed inside the clone before execution, so exit 0
  without a newly generated result cannot pass.
- Strict JSON rejects NaN/Infinity. Types and keys compare exactly; floats use the
  predeclared symmetric tolerance.
- Canonical subject hashes are checked again after execution. The engine never
  copies regenerated results back to the main checkout.
- Latest evidence is `experiments/<id>/reproduce_report.json`; immutable run
  receipts are under `storage/ops/reproducibility/runs/<id>/`.

Outcome statuses are `pass_exact`, `pass_tolerated`, `fail_mismatch`,
`unverified`, `error`, and `timeout`. Only the first two mean the declared result
was reproduced. Daily checkup calls the pure, read-only `build_status()` adapter;
it never starts an experiment.

The design follows Peng (2011, DOI `10.1126/science.1213847`), Sandve et al.
(2013, DOI `10.1371/journal.pcbi.1003285`), and Stodden et al. (2016, DOI
`10.1126/science.aah6168`) on separating reproducibility from validity and
recording code, inputs, workflow, and environment provenance.
