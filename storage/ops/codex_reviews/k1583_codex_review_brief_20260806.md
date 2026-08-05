# K1583 Codex primary-path review brief — corrected-matrix rerun

**Prepared**: 2026-08-06 05:30 CST by `hourly-slot-1-1a139cc184724ad1b3afb0589043bc5c`
**Task**: `k1583_corrected_k1380_matrix_rerun_20260802` (parent `assign_b8abe71a`)
**Why this brief exists**: the rerun is finished, reproduced and artifact-gated; the ONLY
outstanding gate is Codex primary-path review, which is blocked on subscription quota until
2026-08-08. This brief pins what to review so the first post-quota round is one-shot.

## What is already established (do NOT re-litigate)

Verified by the 2026-08-06 fire against live bytes, not from prose:

| Gate | Status | Evidence |
|---|---|---|
| Corrected K1380_v4 matrix consumed | ✅ | `experiments/K1380_v4/k1380_v4_losses_all.npy` sha256 `2b7232b9…55f4` is **byte-identical** at working tree, `HEAD`, and commit `ded2450de` |
| Artifact gate | ✅ | `check_experiment_artifacts.py check --path experiments/k1583` → PASS |
| Clean-clone reproduction | ✅ | `reproduce_report.json` → `outcome.status=pass_tolerated`, `comparison.mismatches=[]` |
| Null result preserved | ✅ | unconditional MCS 16/16 retained, set-level p=0.221, T=1017 |
| Old K1583 knowledge untouched | ✅ | single entry, `verdict=SUPERSEDED`; no replacement written |

Bytes under review are frozen at commits `6cd5e8098` / `f2424375c`; `git status` on
`experiments/k1583/` is clean.

## What to review (primary path)

### 1. Lookahead — the highest-risk axis

`k1583.py` is an ex-post meta-analysis over already-realized losses, so the usual
`signal.shift(1)` idiom does not apply. Check instead the three places leakage could enter:

- **Conditioning variables are contemporaneous by design.** `vix_close` describes the day's
  realized regime; it is *not* used as a predictor. Confirm this is sound for a conditional
  MCS, and that no conditioning series is inadvertently forward-filled from the future.
- **`USRECD` is a pinned snapshot** (`data/usrecd_snapshot.json`), ffilled across non-trading
  days. NBER recession dating is **retroactively revised** — confirm that pinning (rather than
  live fetch) is the correct call for reproducibility, and that ffill does not smear a
  recession start earlier than its as-of-then classification in a way that matters.
- **Rolling MCS at origin t uses only the trailing 252 days** of loss differentials. Verify no
  window reaches past its origin.

### 2. Statistical method

- **Listwise deletion is the dominant result-shaping choice.** B1/B2/B3 have 1457/1395/1772
  valid obs of 1900; requiring all 16 eligible specs on a common day drops 1900 → **T=1017**.
  Is listwise the right treatment here, or does it induce selection on regime (are the dropped
  days systematically high-vol)? **This is the single most important question in the review** —
  if the 883 dropped days are non-random w.r.t. volatility, every conditional MCS below inherits
  that bias.
- **MCS routine**: `src/volpred/stats/mcs.py::model_confidence_set`, HLN (2011) T_R variant,
  stationary bootstrap, HAC SE, α=0.10, B=1000 static / B=500 rolling. Check the bootstrap
  block-length choice and whether B=500 is adequate for the rolling arm.
- **Uniform p-values are expected, not a bug**: all 16 specs report p=0.221 because the
  algorithm cannot reject at the first elimination round, so the whole set shares one stopping
  p. Confirm the README states this correctly (it does, §Unconditional MCS) and that no
  downstream text reads it as a per-spec score.
- **Uncorrected multiplicity across 6 MCS families.** The lone non-null — B0 eliminated in
  VIX-low, p=0.012, T=162 — is not family-wise corrected. README reports Bonferroni-adjusted
  0.072 and explicitly declines to claim it. Confirm that hedge is adequate, or whether the
  cell should be withdrawn entirely given T=162 against M=16.
- **Recession cell is inference-free**: T=20, algorithm returns a trivial set. Confirm it is
  labelled as such and carries no weight in the verdict.

### 3. Claim-surface honesty

The README's central claim is that the new NULL and the superseded NULL **agree in direction
but not in evidentiary basis** — the old matrix filled values on days B1/B2/B3 had no valid
sample, so its T≈1854 was inflated. Confirm the README does not overclaim beyond this, and that
Limitation 7 (old matrix no longer in repo → only conclusion-level, not pointwise, comparison is
possible) is stated rather than papered over.

## Mechanics for the reviewer

The gate reads `experiments/k1583/review_verdict.json` and binds the verdict to exact bytes.
**Generate the skeleton, do not transcribe it** (schema drift burnt a k1709 round on 2026-07-14):

```bash
uv run python scripts/experiment_gates.py verdict-template \
  --path experiments/k1583 --out experiments/k1583/review_verdict.json
```

Generate it **at review time** so `reviewed_sha256` pins the bytes actually read. Fill
`verdict` / `reviewer` / `reviewed_at` / `reviewed_commit` / `review_artifact` /
`blocking_defects`. Anything other than `PASS` blocks the merge — that is intended.

## After a PASS

Only then may the main thread create the replacement K1583 knowledge entry via the canonical
knowledge writer (K1259: **knowledge entries are main-thread-only**; numbers must be read
programmatically from `k1583_results.json`, never transcribed from README or an agent summary).
Do not revive or hand-edit the old SUPERSEDED entry.

## Do not substitute the reviewer

Codex is the primary path for this certification. The `certify` gate's `reviewer` field is free
text, so an agy/Claude verdict would mechanically pass — that would be gaming the gate, not
clearing it. The lazypack codex→agy fallback is a *rendering* fallback and sets no precedent for
scientific review. Precedent for waiting: `codex_primary_reverify_k1714_k1735_20260808`.
