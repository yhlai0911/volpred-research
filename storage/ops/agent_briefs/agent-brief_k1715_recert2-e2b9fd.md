# K1715 re-certification round 2 (bounded doc/format diff review)

**Model**: claude-opus-4-8 / high (per model_router)

## Context
K1715 (score-driven GAS/DCS vs GARCH for joint VaR+ES on SPY, n=6678, defensible
NULL) earned a Codex PASS on its **science** at primary review (blocking_defects=[]).
The reproducibility-artifact round then hit ONE blocking defect at recert round 1
(`experiments/K1715/codex_recert.md`, reviewer Codex gpt-5.6-sol/xhigh):

> Lossy snapshot serialization: `load_returns()` wrote `K1715_source_snapshot.csv`
> with `float_format="%.10f"`, so the frozen snapshot is NOT bit-identical to the
> auto-adjusted close that produced the archived results (max |Δclose| ≈ 5.0e-11,
> max |Δreturn| ≈ 1.6e-10). **This is a reproducibility-artifact defect, not a
> science defect** — model/estimation/evaluation/seed/lag logic unchanged, no lookahead.

Codex's recert round 1 offered **two accepted remedies**, one of which was:
"explicitly re-scope reproduction to the declared reproduce_spec tolerance and
document the snapshot as a tolerance-level, not byte-level, freeze."

The main thread applied exactly that **option B** (no re-run, snapshot file unchanged):
prior K1715.py sha256 `11953fcd8daf9a644a516c0b4cded2aab437ed920bd0a3e7670f88c882facb25`
→ current `379a67cd82bd148142bdd7f475099db9ec56c54928e81d43adedfe3413a42713`. The diff is:
1. `load_returns()` docstring re-scoped: removed the false "freezes the exact ... window
   that produced the archived results" claim; now states the snapshot is a TOLERANCE-LEVEL
   freeze (Δreturn ≈ 1.6e-10 « declared atol=1e-8), reproduction guaranteed at
   rtol=1e-6/atol=1e-8 per the platform-sensitivity rationale, NOT at the bit level.
2. Snapshot writer changed `float_format="%.10f"` → `%.17g` (lossless future re-freeze).
   The **currently pinned** snapshot is unchanged (sha256 `d5dae218…` still matches
   `reproduce_spec.json` inputs[0]) and is honoured as the tolerance-level freeze.
3. `reproduce_spec.json` `comparison.reason` extended to document the snapshot scope.

**No statistical / model / evaluation / seed / lag logic changed.** The pinned snapshot,
`K1715_results.json`, the 3 figures, README.md and build_readme.py are all byte-unchanged.

## Your task (bounded — NOT a fresh full review, NOT a model re-run)
Work in this worktree cwd. Use `codex exec` (codex-cli, ChatGPT auth) for the actual
review judgement, exactly as the prior recert did.

1. `git -C . diff 11953fcd..HEAD -- experiments/K1715/K1715.py experiments/K1715/reproduce_spec.json`
   (or diff the prior FAIL bytes vs current) to isolate the exact change. **Confirm the
   ONLY changes are: the load_returns() docstring, the snapshot writer float_format
   (%.10f → %.17g, write-path only — never touches the already-pinned snapshot read),
   and the reproduce_spec `reason` string.** No model/estimation/evaluation/seed/lag logic.
2. Verify the pinned snapshot is unchanged: `shasum -a 256 experiments/K1715/K1715_source_snapshot.csv`
   must equal `d5dae218deed40ea38969fb295c72a84f9e3711a6bf2837ea473bf7093174fec` and match
   `reproduce_spec.json` inputs[0].sha256. Re-run the window check: load the snapshot,
   compute `100*log(close/close.shift(1))`, confirm n_ret=6678, first 2000-01-04, last
   2026-07-24 — matching K1715_results.json `data`. Report the numbers.
3. **Adjudicate the option-B remedy**: does re-scoping reproduction to the declared
   reproduce_spec tolerance (rtol=1e-6/atol=1e-8) and documenting the snapshot as a
   tolerance-level freeze resolve the recert-round-1 defect? The measured max |Δreturn|
   ≈ 1.6e-10 is ~2 orders of magnitude inside atol=1e-8; the reproduce_spec rationale
   already declares the near-integrated likelihood ridge is not bit-reproducible. Rule on
   whether the loader now HONESTLY represents its reproducibility scope (no byte-exact
   claim) and whether the archived verdicts (DM stats, Harvey |t|, coverage counts) are
   preserved at the declared tolerance. Do NOT demand a full multistart-MLE + bootstrap
   re-run — that is not required to certify a doc/format diff.
4. If Codex confirms the option-B remedy is sound → fill the verdict:
   `uv run python scripts/experiment_gates.py verdict-template --path experiments/K1715 --out experiments/K1715/review_verdict.json`
   then write verdict=PASS, reviewer=<Codex model/effort + session>, reviewed_at,
   review_artifact=`experiments/K1715/codex_recert2.md` (save the Codex log there), and
   `reviewed_sha256` covering the FULL claim surface AT THIS COMMIT: K1715.py (must equal
   `379a67cd82bd148142bdd7f475099db9ec56c54928e81d43adedfe3413a42713`), the 3 figures,
   K1715_results.json, README.md, build_readme.py. Commit the verdict + codex log to this
   worktree branch (`git -C . commit`).
5. If Codex finds the remedy is NOT sound (e.g. option B is not acceptable, or the change
   is not doc-only) → do NOT certify; write the defect into
   `experiments/K1715/codex_recert2.md`, leave verdict FAILing, and say so in your result.

## Result artifact
`experiments/K1715/review_verdict.json` updated so `reviewed_sha256["K1715.py"]`
== `379a67cd82bd148142bdd7f475099db9ec56c54928e81d43adedfe3413a42713` with verdict=PASS
(or an explicit FAIL with the defect recorded in codex_recert2.md).
