# K904 Codex re-review (round 2) — 2026-07-20

Target: frozen commit `834b6144c48fa83cc3d28d4e1067899ccaf52fa0` on `k741-nfp-canonical`.

## Verdict

**PASS — B1, B2, and B3 are resolved; no new merge-blocking regression found.**

## Narrow verification

- **B1 resolved.** `run_cell` now raises when the exact `map_forward` path has an exclusion or a mapped-count mismatch. My adversarial 2026-04-03 release with prices ending 2026-04-02 raised `RuntimeError` before estimation. The archived path remains deliberately permissive: it allowed 2026-04-03 to map backward to 2026-04-02, and a separate 2026-04-10 probe was recorded as 0/1 mapped without raising. The exemption is keyed to `map_archived`; `main()` wires both forward cells directly to `map_forward`, and the headline is explicitly `official__forward_mapper`, so it cannot inherit the archived exemption in the committed execution path.
- **B2 resolved.** The committed JSON reports proxy archived/forward as 196/196 and official archived/forward as 195/195. Its provenance identifies the extra proxy observation as 2025-10-03. The README now states those counts correctly and calls the archived comparison approximate, giving the actual absolute difference `1.04e-4` (relative `9.1e-5`) and explicitly disavowing digit/bit-level reproduction.
- **B3 resolved, not merely relocated within the experiment surface.** The archived `k904_chart3_nfp_by_vix.png` is byte-identical at round 1 and round 2 (SHA-256 `ff4e6af291a4e929e67e7105acf77656128f376a8f5224d5861fae4541788df6`). The README now identifies it as archived proxy output, lists its proxy values and unsupported old conclusion, and says not to cite it as current K904. The new `k904_chart3_nfp_by_vix_canonical.png` is emitted directly from `official__forward_mapper`; both visual inspection and regeneration showed `1.305 / 1.230 / 1.165 / 0.935`, matching the committed JSON. Its title calls the result descriptive and explicitly says regime differences were not tested and the four tests were not multiplicity-adjusted. The already-published article that still uses the archived image/text remains a disclosed main-thread correction item, but preserving that published artifact while adding a clearly distinguished canonical figure is not a blocker to merging this experiment fix.
- **Regression passed.** With `FRED_API_KEY` loaded, an isolated full canonical rerun produced JSON exactly equal to the committed result and a byte-identical canonical PNG (SHA-256 `18541f57615b129c425cd4a1545ad22029f1d467a839b708a29ac7075d421901`). No numerical claim drifted. Outside the expected K904 changes, `paper/volatility-absorption/reproduce_report.json` changed only its `generated_at` timestamp; gate status, 135/135 checks, and all claim content are unchanged, so this is not merge-blocking.

## Skipped

Per the narrow-review instruction, I did not redo the already-passed 2x2 arithmetic, Good-Friday mapping-direction/collision audit, archived full pipeline, paper audit, or published-feed correction. I did not modify any file other than this review artifact.

VERDICT: PASS
