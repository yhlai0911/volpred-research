# K1745 independent certification review — round 1

Verdict: **FAIL**.

I verified every supplied SHA-256 hash and byte count against the frozen worktree. All match exactly. The worktree HEAD reviewed is `f4f045dd90363a302024ff879e572237ec16ca0a`; the worktree was clean. I reviewed the frozen source, results, README, sidecar, figure, tests, reproduction metadata, source manifest, and both gate-history blobs without rerunning or regenerating the experiment.

## Blocking defects

### 1. Raw DM/HLN is not justified for this nested, expanding-window comparison

Severity: **blocking**.

At the structural level, setting state noise to zero reduces the random-walk coefficient model to a constant-state HAR. With the OLS initialization in `K1745.py:215-217`, the zero-noise Kalman coefficient recursion approaches recursive OLS. Thus, the competing model contains the static conditional-mean specification as a restriction or limiting case.

Nevertheless:

- `K1745.py:267-290` applies an unadjusted HAC mean test to `TVP loss − static loss`, followed only by the HLN small-sample factor.
- Those p-values feed the four-cell Holm family at `K1745.py:496-503`.
- They then feed the verdict at `K1745.py:523-537`.
- No Clark–West statistic is computed for MSE, and no nested-appropriate general-loss bootstrap or encompassing design is used for QLIKE.

HLN rescales DM; it does not remove nested-model estimation bias. Clark–West addresses nested MSPE comparisons, but cannot simply be relabelled as a QLIKE test. The repository’s own ratchet says exactly this at `scripts/tests/test_nested_dm_misuse_ratchet.py:81-94`.

Giacomini–White does allow nested *forecasting methods* because estimation uncertainty remains asymptotically nonvanishing under bounded estimation windows. But its assumptions explicitly rule out expanding-window schemes. K1745’s static estimator expands through `x[:i], y[:i]` at `K1745.py:223-227`. Different estimation procedures do not supply the missing theorem. See the original [Giacomini–White paper](https://doi.org/10.1111/j.1468-0262.2006.00718.x) and [Clark–West](https://doi.org/10.1016/j.jeconom.2006.05.023).

The ratchet should have required review here. Its lexical detector missed the structural nesting because the source never explicitly calls the pair “nested models.” Consequently, the reported SPY QLIKE significance against TVP and the favourable 0050.TW/MSE significance are both unsupported as formal inference. Point loss differences remain descriptive.

There is an additional nuance: the two forecast outputs do not coincide exactly at `q=0`. Static uses `exp(xβ + r_ols/2)` at `K1745.py:226-227`, whereas TVP uses `exp(mean + predictive_variance/2)`, including state uncertainty, at `K1745.py:229-231`. That method-specific correction is defensible—the actual state-space precedent uses the same distinction—but it does not establish admissibility of raw DM under this mixed fixed/expanding estimation design.

### 2. The claimed “formal Giacomini–Rossi” inference is a custom, unsupported bootstrap

Severity: **blocking**.

The rolling statistic’s 20% window and full-sample HAC standardization at `K1745.py:305-314` follow the broad Giacomini–Rossi construction. The critical-value procedure does not:

- `K1745.py:315-335` replaces the published fluctuation-test limiting distribution with a 499-draw circular moving-block bootstrap.
- It centers the full loss path and tests against a stated “equal average predictive ability” null, rather than binding the procedure to the published local-equality null and critical law.
- No cited source or validation establishes that this data-dependent bootstrap has correct size for the expanding/nested forecasting design.
- The resulting 5% critical values vary radically by cell—e.g. `3.779` for 0050.TW QLIKE and `2.144` for its MSE at `K1745_results.json:478-538`. The published two-sided 5% fluctuation critical value for window fraction 0.2 is `3.179`, common across cells under the canonical asymptotic construction. See [Giacomini–Rossi](https://doi.org/10.1002/jae.1177) and the critical-value table in Rossi’s [Advances in Forecasting Under Instability](https://crei.cat/wp-content/uploads/2016/07/AFUM.pdf).

The block length of HAC lag plus one is a plausible heuristic, but is not justified here. With 499 draws, p-value resolution is 0.002, but a 95th percentile estimated from roughly 25 upper-tail draws is not credible to three decimals. The 0050.TW QLIKE peak at index 3016/3018 is not lookahead, but it is an edge-localized result that should be treated as a current endpoint regime warning.

Calling these values “formal Giacomini–Rossi” is unsupported. The custom p-values and critical values therefore cannot enter a certified finding.

### 3. The Results section selectively omits the only favourable Holm-significant cell

Severity: **blocking**.

The declared family includes all four market/loss cells at `K1745.py:39`, and Holm is applied to all four at `K1745.py:496-503`. Yet `README.md:28-35` prints only the two QLIKE cells.

The omitted 0050.TW/MSE result is recorded at `K1745_results.json:498-541`:

- improvement `+3.311%`;
- HLN t `−3.946`;
- raw p `8.11e-05`;
- Holm p `3.24e-04`.

MSE being secondary and unable to rescue the preregistered QLIKE decision does not license suppressing it. A bare JSON pointer is not adequate disclosure when the only favourable adjusted cell directly qualifies the broad “no TVP-HAR edge” narrative. Its formal significance is itself invalid under defect 1, but the frozen artifact currently claims it; that claimed result must be shown and appropriately caveated.

The tiny raw MSE differential, `−4.4e-10`, is not floating-point noise. Squaring a variance-scale target around `1e-4` naturally produces losses around `1e-8`; the relative 3.31% difference is numerically meaningful within this market. MSE is scale-dependent and heavily weights extreme-variance days, which plausibly explains its disagreement with QLIKE.

### 4. The state-space precedent is a false bibliographic record

Severity: **blocking**.

`README.md:40`, `K1745.py:472`, and `K1745_results.json:61-66` attribute “Forecasting realized variance measures using time-varying coefficient models” to Manner, Türk, and Eichler and give DOI `10.1016/j.ijforecast.2017.12.001`.

The actual paper is by **Jeremias Bekierman and Hans Manner**, DOI **10.1016/j.ijforecast.2017.12.005**. It does provide a latent Gaussian state-space HAR precedent estimated through the Kalman filter, so the methodological characterization is broadly sound, but the frozen authors and DOI are not. The authorship and method are directly visible in the [authors’ working paper](https://static.uni-graz.at/fileadmin/_Persoenliche_Webseite/manner_hans/Publikationen/Bekierman_and_Manner_WP.pdf).

This repeats the exact citation-integrity class that previously blocked K1739.

### 5. The Xu citation misidentifies the authorship

Severity: **blocking**.

`README.md:42`, `K1745.py:474`, and `K1745_results.json:77-82` cite “Xu, G.” The actual authors are **Wen Xu, Pakorn Aschakulporn, and Jin E. Zhang**. The DOI and title are correct, and the description of local-linear TVP with bandwidth/smoothing-variable selection is accurate. The [official Wiley article](https://doi.org/10.1002/for.3260) confirms that it is not a Kalman random-walk model.

## Non-blocking findings

### Lookahead and common forecast seam

I found no end-to-end lookahead:

- Predictors are lagged at `K1745.py:123-134`.
- Static training uses only rows before origin `i` at `K1745.py:223-227`.
- TVP forecasts before observing `y[i]`, then updates afterward at `K1745.py:228-231`.
- Both forecasts use the same origin, target, initial-sample clipping bounds, and loss functions.
- Clipping is not an asymmetric driver: results record 0/0 clipped SPY forecasts and 2/2 for 0050.TW.

The runtime assertion at `K1745.py:225` is reachable, but it only checks date ordering; it does not mechanically prove that the training slice is `:i`. The source slice itself is correct.

Coefficient paths are stored after the same-day update at `K1745.py:231-251`. That is appropriate for a filtered descriptive path, but they are not forecast-origin coefficients. The README correctly avoids causal interpretation.

### q selection and boundary identification

Tuning is training-only. `main()` passes only the first 1,260 rows at `K1745.py:487`, while `tune_q()` fits on the first 1,008 and validates sequentially on the following 252 at `K1745.py:191-207`.

Both markets select the lower grid boundary, with extremely small validation-loss gaps. This is weak identification and makes the primary method close to static HAR. It is not wholly tautological: all three frozen q settings produce distinct forecasts, and every q setting worsens QLIKE in both markets. The honest conclusion is therefore limited to “none of these three small, training-selected q values improved QLIKE,” not a general rejection of TVP-HAR.

### Data proxy and flooring

The artifact is honest that Garman–Klass daily range variance is not intraday RV. The 0050.TW floor is potentially consequential for model fitting because it inserts `log(1e-12)`, but it does not create an exploding QLIKE *difference*: the common `−log(actual)` term cancels between forecasts.

Sixteen of the 19 floored observations occur OOS. Their combined QLIKE differential favours TVP and offsets about 22.7% of the otherwise positive 0050.TW QLIKE gap. Thus, the floor does not manufacture the NULL against TVP; if anything, it masks part of the unfavourable QLIKE result. The issue remains a proxy limitation, not a blocking directional distortion.

TX exclusion is credible rather than convenient. TAIFEX identifies free time-and-sales downloads as covering the previous 30 trading days and directs deeper historical requests to its data shop; its daily report is contract-month data. See the official [TAIFEX download page](https://www.taifex.com.tw/enl/eng3/futPrevious30DaysSalesData) and [historical-data guidance](https://www.taifex.com.tw/enl/eng3/hisAppForm).

### Sign conventions

The two signs refer to different quantities:

- loss differential = TVP minus static, so negative favours TVP;
- improvement percentage = `(static − TVP)/static`, so positive favours TVP.

They are coherent, but the table should explicitly label “positive favours TVP.” This is editorial, not blocking.

### Remaining citations

Corsi (2009), Giacomini–Rossi (2010), and Harvey–Leybourne–Newbold (1997) have correct authors, years, titles, venues, and DOIs. Their characterizations are accurate. See [Corsi](https://doi.org/10.1093/jjfinec/nbp001) and [Harvey–Leybourne–Newbold](https://doi.org/10.1016/S0169-2070(96)00719-4).

### Tests

`test_K1745.py` is not wholly decorative: it checks the daily feature seam, QLIKE orientation, Kalman updating, deterministic bootstrap behavior, and Holm monotonicity.

It would not catch the important integration failures considered here:

- no assertion that `forecast_path()` fits OLS on exactly `y[:i]`;
- no test that TVP forecasts before updating with `y[i]`;
- no weekly/monthly feature-seam test;
- no common-origin/target/clipping comparison;
- no q-validation containment test;
- no nested-inference gate;
- README consistency checks only QLIKE, which is precisely why the omitted MSE result passes.

That coverage gap is non-blocking because direct source inspection establishes the lookahead seam, but it should be repaired before a later certification round.

```json
{
  "kid": "K1745",
  "verdict": "FAIL",
  "reviewer": "Codex (GPT-5) / high",
  "reviewed_at": "2026-08-04T03:06:45Z",
  "reviewed_commit": "f4f045dd90363a302024ff879e572237ec16ca0a",
  "review_artifact": "storage/ops/codex_reviews/k1745_round1_verdict.md",
  "blocking_defects": [
    "K1745.py:267-290 and K1745.py:496-537 use raw DM/HLN and its p-values as primary claim evidence for a structurally nested TVP-versus-static comparison with an expanding OLS window, without Clark-West for MSE or a nested-appropriate general-loss design for QLIKE.",
    "K1745.py:305-337 labels a custom 499-draw centered circular-block bootstrap with data-dependent critical values as a formal Giacomini-Rossi fluctuation test, without theoretical or cited validation for its null, critical law, or nested/expanding estimation design.",
    "README.md:28-35 omits the declared primary-family 0050.TW/MSE cell even though K1745_results.json:498-541 reports a favourable 3.311% improvement and Holm p 0.000324, making the NULL presentation selectively incomplete.",
    "README.md:40 and K1745.py:472 contain a false bibliographic record for the state-space precedent: the cited paper is by Jeremias Bekierman and Hans Manner with DOI 10.1016/j.ijforecast.2017.12.005, not Manner, Türk, and Eichler with DOI 10.1016/j.ijforecast.2017.12.001.",
    "README.md:42 and K1745.py:474 misidentify the authorship of DOI 10.1002/for.3260 as Xu, G.; the paper is by Wen Xu, Pakorn Aschakulporn, and Jin E. Zhang."
  ],
  "reviewed_sha256": {
    "K1745.py": "1ddf9d84b09dbcc0a51fb7ee5b9f06ae901184dd94ae004f2a4bdc7473fde313",
    "K1745_paths_and_fluctuation.png": "14bed383f0d6eccf3281073e26a6ce47e2a9d6d594d32e55662b5b959b1202eb",
    "K1745_results.json": "51c4bb55edc2349bf04d0b89f0e29425083c2df500be1e6fec7f4923babefb13",
    "README.md": "956af17dbcc850734195eca6e1aeab0c66e02533741e10b55280e92353cc83bf",
    "gate_history/5462187d__K1745.py": "5462187d49e6f08e9ad7a374b9406eded082e429fb07b247f193b424fda02a95",
    "gate_history/bcd8e55f__K1745.py": "bcd8e55f97f2db6792b7d146f7945e5ecf1fcca726df8050e00edd5d9d6fb39c",
    "test_K1745.py": "5068c4d3c3f1f8e655880449c0a0c01bc04f399715f24f3ccc1433bfe4cc00ab"
  }
}
```
