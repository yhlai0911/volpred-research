# Orphan reaper `StopIteration` flake investigation

**Date:** 2026-07-23  
**Task:** `assign_86f26cf3`  
**Original failure:** 2026-07-19 PHASE-Z isolation gate

## Verdict

**Known intermittent; not reproduced. Keep observing.**

No production fix is justified by the available evidence. The reaper and its
regression test were deliberately left unchanged.

## Exact signal

The harness runs only:

```text
scripts/tests/test_orphan_reaper.py::test_job_reaper_rejects_agent_external_directory_symlink_and_ignored_paths
```

This is the original failing assertion path. The test raises
`StopIteration` when `result["held"]` has no `compute-invalid` entry, so the
signal detects the reported symptom directly rather than inferring it from a
nearby outcome.

## Reproduction command

```bash
uv run --extra dev python scripts/run_orphan_reaper_flake_harness.py \
  --iterations 5 --parallel-workers 4
```

The command completed with exit code 0:

```text
attempts: 80
failures: 0
variants: 16
```

Each environment variant passed 5/5 attempts.

## Environment matrix

The 16 variants are the cross-product of:

| Dimension | Values |
|---|---|
| `TMPDIR` spelling | `/var/tmp`, `/private/var/tmp` |
| Git executable | `/usr/bin/git` 2.50.1 Apple Git-155, `/opt/homebrew/bin/git` 2.43.0 |
| global `core.excludesFile` | empty; a fixture matching both `*.tmp` and `outside.txt` |
| subprocess pressure | serial; 4 concurrent pytest subprocesses |

The test repository itself sets a local empty `core.excludesFile`. Retaining
that behavior is intentional: the global-config variants check whether host
configuration leaks through the test's local isolation, which was one of the
incident's proposed environment dependencies.

## What this result establishes

- None of the four requested dimensions, alone or in this tested cross-product,
  is sufficient to reproduce the failure on the current checkout.
- The result does **not** prove the 2026-07-19 failure was spurious. It remains
  a real recorded intermittent failure with no reproduced cause.
- Because there is no red loop and no falsifiable cause, changing path
  resolution, ignore handling, or held-job policy would be an evidence-free
  patch and could weaken the orphan-preservation invariant.

The reusable harness remains in
`scripts/run_orphan_reaper_flake_harness.py`. A future recurrence should be
captured with the failing harness JSON plus the process environment needed to
turn one of these variants red before any production change is attempted.
