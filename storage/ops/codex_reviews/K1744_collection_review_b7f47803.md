# K1744 independent collection review — PASS

- Reviewer: Codex GPT-5.6-sol, independent fresh-context commissioning review
- Reviewed commit: `b3b4f02a34bacfb07d4963440d00b5b93850afda`
- Reviewed worktree: `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-5f75cd52-k1744`
- Reviewed at: `2026-08-02T03:34:52Z`
- Verdict: **PASS**
- Experiment execution: **not performed**; `K1744.py` was not run during review

## Freeze and scope

The original commissioning SHA `beb30f371cc5a1baf11ad40780f9eac81ee35f74` was observed dirty while the collector was applying audit fixes. The collector subsequently froze `10b80f2457d164dbdb131d86fcedfc23dbd5c7db`; the independent review found one nested-inference defect there. The collector preserved the reviewed runtime bytes, repaired only that contract and its generated bindings, and explicitly refroze the clean worktree at `b3b4f02a34bacfb07d4963440d00b5b93850afda`. A new preflight returned an empty `git status --porcelain=v1 --untracked-files=all`. The final patch was re-audited byte-for-byte against the prior freeze before any reviewer write.

Every current claim-surface byte and all supporting artifacts were reviewed. Final identities are:

| Artifact | SHA-256 | Bytes |
|---|---:|---:|
| `K1744.py` | `1a532a7fc87573f9491ab445803d533f64da72c9e1bb38050cd292ca19dd9092` | 26,170 |
| `K1744_results.json` | `142ab9599d8681f3b2fbd39d48bf0022bf2b9c88e3c68c4d4ed66c20d7744176` | 20,293 |
| `README.md` | `234ac7e7e79a41493319162560a3d9ab8ebd129bf5eb1fc7cacc2457b1dd50ae` | 8,383 |
| `test_K1744.py` | `2a2054aa6040e36c6d1e7bd92e2b2d289b7f073ea40c4b6b63cfa050862445eb` | 6,672 |
| `proxy_preregistration.json` | `a3bc7a47f1b14227b12cc1633cfacb3cd4ad8de1f45a4137462c10c4f9dd56a5` | 9,405 |
| `raw_cache_manifest.json` | `49f4d3602838862a0e21c24321b7b6e82776433de35753ce9cdb3968e5d00a36` | 12,516 |
| `diagnostics.json` | `7b5f9fb88e69cc8025655adbe1090c4d815dad170162e9ba595acdee70353477` | 2,436 |
| `reproduce_spec.json` | `8a32b23daac8f5f43b10ba7bab1fbd61f342af6b4f22ab3ef62556226fddf352` | 2,894 |
| `reproduce_commit.json` | `4f6a899c09bf7eaca107e680a48fb67e192f127032e7e3c3359501b0d47347f9` | 999 |
| gate pre-image `d96d7ba0__K1744.py` | `d96d7ba0a4f217e6686ca586a7d78f247ed71d91aa483c185fbe5ba8bd52a513` | 25,636 |
| gate pre-image `77213405__K1744.py` | `772134059c88f625ec57acb654ff6f46fe8b137cfd92d83164b6114d96b5419e` | 25,810 |
| gate pre-image `951377ef__K1744.py` | `951377efbceedf6dd3355f02f90f45291f680747e875068046ffbd658a6f8bf1` | 25,810 |
| `gate_history/manifest.json` | `a076a41b9306c8fa5286e1b22d7e11f61514424745dd8083544fbd4cc5f11dcb` | 1,695 |

All three preserved scripts were checked by full-byte identity and successor diff. The final pre-image is byte-identical to `K1744.py` at the prior review freeze, and its manifest entry accurately records the nested-QLIKE blocker and preservation time.

## Resolved blocker re-audit

At the prior freeze, the candidate was the expanding AR(1) baseline plus a lagged exposure regressor, making the baseline a coefficient-restriction special case, but the frozen contract assigned ordinary QLIKE/DM primary inference. The repository gate text requires nested-aware inference: for QLIKE, a general-loss or recursive-bootstrap design, with ordinary DM diagnostic-only.

The final patch resolves this exactly and consistently across the machine preregistration, result, generator, README, diagnostics fragment checks, and test:

- primary realized-variance inference is a `seed=42` recursive expanding-window month-block bootstrap of QLIKE loss differences under the nested null;
- ordinary DM/HLN is explicitly diagnostic-only;
- tail-loss and beta-change primary tests use canonical-bandwidth HAC on the incremental exposure coefficient, with month-block permutation/bootstrap sensitivity;
- autocorrelation and lag sensitivity remain required for every target.

The diff from `10b80f2457d164dbdb131d86fcedfc23dbd5c7db` to the final SHA contains this contract change, regenerated identity metadata, its regression test, and the preserved pre-image; it introduces no new scientific claim or executed estimate. No blocking defect remains.

## Verified evidence

### Recovery and zero-salvage separation

The recovery brief records that `agent-brief-k1744-552fde40` exited on a quota rejection before research began. The preregistration, code, result, README, diagnostics, and tests consistently classify it as `ZERO_SALVAGE`, use no prior artifacts, and explicitly deny reclassification as success or a scientific null. No old-worktree path is read by the entrypoint.

### Proxy timing and inaccessible enumeration

`proxy_preregistration.json` was locked at `2026-08-02T02:37:52Z`, before all manifest access timestamps beginning at `02:39:40Z`. It freezes the latent variable, exact monthly final-close construction, PDI record-level enumeration identity, sponsor-release availability rule, transformation, expected signs, measurement errors, prohibited substitutions, and feasibility thresholds before any outcome request.

The manifest records no authenticated provider credentials, no record-level rows, no historical provider version timestamps, and no market-data request/cache. The current PDI landing page independently exposes only a paywalled, non-free article surface (`isAccessibleForFree=false`, gold entitlement, approximately 100 words), not a complete versioned export. Darby and Gramercy provide isolated dated examples but cannot establish a regional denominator or prove zero-event months. Treating eligible-event and nonzero-month counts as unknown (`null`), rather than zero, is correct.

### No outcome loading and timing guard

The final entrypoint imports no market-data or HTTP client, reads only the preregistration and source manifest, and stops on the failed feasibility gate. It contains the required signal path `return exposure.shift(1)`. Result fields report zero outcome rows, no requested/loaded outcome series, no estimates or p-values, and no robustness run. The runtime spec records `network="deny"`.

### Frozen design contracts

The fixed universe and channel split exactly match the brief: equities `ILF/EWW/ECH/EPU/EWZ`, FX/local bond `CEW/EMLC`, hard-currency bond `EMB`, and factor-only `UUP`. The common-sample contract is the strict nine-ticker intersection with identical baseline/candidate rows; inception, delisting, missingness, duplicates, timezone, extremes, revisions, and common-sample loss are required before any feasible estimation. Seed `42`, the nine-cell Holm family, the corrected nested-aware RV procedure, nondegenerate canonical HAC bandwidth, lag sensitivity, and secondary-only robustness labels are frozen.

### Source claims

Primary-source read-back supports the institutional claims:

- [CFA Institute LatAm article](https://www.cfainstitute.org/insights/articles/latin-america-private-credit-investment-growth): published 4 June 2026; confirms the USD650bn gap, less-than-1% penetration, USD800m LatAm fundraising, USD356bn global fundraising, and the distinction from the US LBO model.
- [CFA Institute private-markets report](https://rpc.cfainstitute.org/research/reports/2026/understanding-growth-private-markets): confirms the 22 June 2026 date, DOI, opacity, capital-formation, bank/nonbank-linkage, and risk-transmission framing.
- [ECLAC release](https://www.cepal.org/en/pressreleases/faced-financing-development-challenges-latin-american-and-caribbean-countries-need): confirms the 3 July 2025 release and approximately USD650bn annual regional financing gap.
- [NBER W34991](https://www.nber.org/papers/w34991): confirms authorship, March/April 2026 dates, DOI, and reliance on the proprietary MSCI Private Capital Universe.
- [NBER W32176](https://www.nber.org/papers/w32176): confirms authorship, February/October 2024 dates, DOI, and the shift away from bank-balance-sheet lending.
- [Oxford/Corsi](https://academic.oup.com/jfec/article-abstract/7/2/174/856522): confirms the HAR-RV context and DOI. Crossref confirms the 2008-11-07 online date; HAR-RV is correctly labeled context, not the frozen AR(1) baseline.

### Artifact identities and README claims

The live entrypoint hash/size equals both `results.code_trace` and `reproduce_spec.entrypoint`. The exact result bytes equal `reproduce_spec.canonical_result_identity` and `reproduce_commit.canonical_result_identity`; the spec bytes equal `reproduce_commit.spec_identity`; generation ID `8f21860cec7a70e505a25352db56ea08cf8787a881b18d26babafebe4911822b` and README/diagnostics output identities agree. README scientific numeric claims point to canonical JSON. Its conclusion remains appropriately narrow: inaccessible complete/PIT proxy, no transmission evidence, and no scientific null.

## Gate evidence

- `uv run python scripts/experiment_gates.py run --path experiments/K1744` → **PASS**, 5 files cleared 4 static gates at the final SHA.
- `uv run python scripts/check_experiment_artifacts.py check --path experiments/K1744` → exit 1 only for the expected pre-collection gap: no K1744 shared-knowledge entry. The reviewer/worktree is forbidden to write shared memory; no reproduce/code/result identity defect was reported.
- `K1744.py` was not executed.

## Verdict

**PASS.** The observed `INCONCLUSIVE / INSUFFICIENT_DATA` result is an honest feasibility stop, not a scientific null. It is source-supported, zero-salvage-separated, lookahead-safe, nested-inference-corrected, and byte-consistent. No blocking defect remains.
