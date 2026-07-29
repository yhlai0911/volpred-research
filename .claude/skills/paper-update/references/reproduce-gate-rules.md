# Paper Reproduce Gate

This reference is loaded by `paper-update`, `paper-review-cycle`, and
`paper-submission-pipeline`. It defines the evidence required before review or
submission; it does not define pipeline stages.

## 1. Candidate manifest

Every gate run starts with one immutable manifest containing:

- paper id and manuscript/PDF hashes;
- every central claim, table, and figure location;
- the supporting experiment id and result path;
- result/spec/code/input hashes;
- data source, period, sample size, seed, and timing convention;
- checker command, timestamp, exit status, and receipt path.

If a central item lacks this binding, the gate is `BLOCKED`.

## 2. Data snapshot pinning

Investible or revisable sources such as yfinance, FRED, and vendor APIs must use
a pinned local snapshot for archived paper results. Live re-fetch is not an
acceptable default reproduction path because corporate-action adjustments and
historical revisions can change results.

- Record snapshot date, source, retrieval method, license/access constraints,
  and content hash.
- Preserve the old snapshot when an R&R extends the sample.
- Record price-adjustment conventions explicitly; do not silently change raw
  versus adjusted prices.
- A refresh creates a new candidate and invalidates downstream evidence.

## 3. Experiment reproducibility gate

For every experiment in the candidate manifest, run the installed checker:

```bash
uv run python scripts/reproduce_check.py run --experiment <K-id> --timeout <seconds>
```

The gate passes only when:

1. the command exits successfully and emits a valid receipt;
2. the reproduced canonical result matches its archived specification;
3. code, input, seed, and result identities are present;
4. the reproduced result is the one cited by the current paper candidate;
5. all required paper-specific reproduction checks also pass.

A historical review report, an inventory-only result, or an executable script
does not replace a current run receipt.

## 4. Source binding

Every reported number must be traceable to a precise source field or
deterministic transformation. For example:

```latex
% source: experiments/k732/k732_results.json .bsi_t_stat
```

The manifest should express equivalent structured binding:

```json
{
  "Table2.K732.is_t_stat": {
    "paper_value": 5.29,
    "source": "experiments/k732/k732_results.json",
    "field": "bsi_t_stat",
    "source_value": 5.29,
    "transformation": "identity",
    "status": "match"
  }
}
```

Composite rows must list every component and the combination rule. Figures must
identify the data/result source and rendering script. Aggregate match rates
cannot hide an unbound row.

## 5. Freshness

Reproducibility evidence becomes stale when any of these changes:

- manuscript number, table, figure, caption, or interpretation;
- experiment code/spec/result/input snapshot;
- sample period, seed, lag, estimator, baseline, or transformation;
- supporting artifact path or identity.

After a candidate change, rerun only the affected experiment checks, rebuild
the manifest, and invalidate all downstream review reports tied to old hashes.
A stale receipt cannot advance the submission pipeline.

## 6. Failure handling

When script, data, and manuscript disagree:

1. diagnose the producing logic and evidence chain;
2. fix the reusable script/process or correct the manuscript in the main
   thread;
3. rerun and compare;
4. read back the downstream artifact;
5. record the root-cause lesson in the required canonical documentation when
   an old conclusion is overturned.

Never hand-edit a result artifact, hard-code a desired output, search seeds for
a preferred result, or hide a null. An unresolved mismatch is `BLOCKED`, not a
near-pass.

## 7. Workflow ownership

- `paper-review-cycle` runs this gate before independent reviewers.
- `paper-update` runs it for changed claims and source binding before sync.
- `paper-submission-pipeline` requires fresh receipts for the exact candidate
  at the relevant transitions.
- `uv run volpred ops paper-update` synchronizes paper artifacts; it does **not**
  by itself certify this reproducibility gate.

## 8. Submission package check

Before arXiv or journal upload, verify:

- every main table/figure maps to an archived artifact and rendering path;
- replication instructions work from a clean environment;
- data-source documentation covers endpoints, dates, access, and licensing;
- all experiment references in the paper are bound or explicitly unused;
- package files and the reviewed PDF share the approved candidate identity.

The gate output must be `PASS`, `FAIL`, or `BLOCKED`, with the manifest and
receipts attached.
