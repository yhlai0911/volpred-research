# K1442 Codex review

- Date: 2026-07-12
- Reviewer: Codex（source-level audit + independent result verification）
- Verdict: PASS
- Scope: official event-date integration, window construction, statistical claims, reproducibility, and published-claim correction

## Source-level checks

- `cpi_release_dates()` is the only source of the corrected event calendar; a missing API key, empty response, or upstream request error fails closed.
- The exact legacy-to-official date difference is asserted: seven legacy dates removed, six official dates added, and the event count changes from 29 to 28.
- Official dates must exist in the shared MOVE/VIX trading index; the code does not silently roll a missing date.
- `true_pre` is `T-6 close → T-1 close` and `post` is `T0 close → T+5 close`, so both contain five returns. The release-day return is isolated as `T-1 close → T0 close`.
- The primary family tests MOVE and VIX release-day changes directly against zero. Bonferroni `alpha=0.025` and 97.5% bootstrap intervals are applied consistently.
- All bootstrap procedures use fixed seeds. Market and legacy inputs are SHA-256 pinned. Outputs are staged and read back before the canonical results JSON is replaced last.
- Interpretation is restricted to descriptive release-date association. The code and README make no CPI-specific causal, mispricing, mechanism, or directional trading claim.

## Post-run verification

- `uv run pytest -q tests/test_event_dates.py`: 5 passed.
- The corrected script completed successfully from the pinned 5,794-row market snapshot.
- Legacy-row reproduction maximum absolute difference: `4.44e-14`.
- Independent recomputation from `k1442_cpi_events.csv` matched the JSON event count, means, frequencies, Wilcoxon tests, and bootstrap intervals.
- Two consecutive runs from identical inputs produced identical SHA-256 values for the canonical JSON, CSV, and both figures, as recorded in `README.md`.
- Figure and corrected lazypack PNGs were visually inspected for readability and clipping.

## Claim verdict

- MOVE release day: descriptive decline gate PASS (`22/28` negative, one-sided Wilcoxon `p=0.000236`, 97.5% bootstrap mean interval `[-5.47%, -1.35%]`).
- VIX release day: gate FAIL because the 97.5% bootstrap interval crosses zero (`[-4.89%, +1.19%]`).
- True-pre versus post and post-five-day results remain exploratory and do not support the prior mechanism or trading-timing claims.
- Published article `mile_166eda01` required a formal erratum; the old claims were not eligible to remain live.

No blocking defect remained after rerun and independent verification.
