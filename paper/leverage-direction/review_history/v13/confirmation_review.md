# latex-academic-reviewer — v13 Confirmation Round

- **Paper**: `paper/leverage-direction/` (`main.tex` → `body.tex` + `tables_main.tex`)
- **Review date**: 2026-06-15
- **Round type**: focused confirmation of v12 H5 final blocker
- **Verification basis**: current tracked sources after commit `02c91001`, K903 table values in `experiments/k903/tables/k903_table3.csv`, stale-literal grep, `reproduce.py`, and a fresh two-pass XeLaTeX compile.

## Verdict: READY_FOR_SUBMISSION_CHECKPOINT

The v12 HIGH blocker is closed. No HIGH-severity numerical contradiction remains in the TLT/BTC QLIKE discussion.

## 1. H5 Status

`body.tex:187-188` now reports the K903 canonical values:

- TLT: GARCH marginally ahead in 2023--2024 (`Delta = +0.20%`, `p = 0.238`) and GJR marginally ahead in 2025 (`Delta = -0.33%`, `p = 0.133`), with both periods statistically indistinguishable.
- BTC-USD: `gamma = +0.072`, `Delta = -0.06%`, `p = 0.848`, and cross-window instability `std = 0.105`.

This matches the internally consistent BTC discussion in the model-selection paragraph and removes the prior same-document contradiction.

## 2. Table 3 Status

`tables_main.tex:51-61` now has eleven K903 QLIKE rows:

- SPY 2023--2024 and 2025
- QQQ 2023--2024 and 2025
- GLD 2023--2024 and 2025
- TLT 2023--2024 and 2025
- EEM 2023--2024 and 2025
- BTC 2023--2024

The paper consistently refers to "eleven Diebold-Mariano comparisons." BTC 2025 is not added because there is no canonical K903 source row.

## 3. Stale-Literal Sweep

The blocking stale literals from v12 H5 were searched in `main.tex`, `body.tex`, and `tables_main.tex`:

- `0.293`
- `+0.14%`
- `approx +0.12`
- `std = 0.14`
- `-0.54%`
- `-0.01%`
- `GARCH slightly outperforms GJR`

No uncorrected H5 stale prose remains. The only nearby `+0.12` occurrence is QQQ's current gamma summary, not the stale BTC value.

## 4. Gate Results

`uv run python reproduce.py`:

- Total checks: 194
- MATCH: 171
- MISMATCH: 0
- NOTE: 23
- Traceable match rate: 100.00% (171/171)
- Alert level: GREEN

XeLaTeX was run twice:

- `Output written on main.pdf (49 pages).`
- No fatal errors.
- No unresolved-reference warnings observed.

`uv run volpred ops paper-update --paper-id leverage-direction` was rerun after fixing the PDF-selection/page-count path. Final sync output reports `storage_path = leverage-direction/main.pdf` and `pages = 49`. The paper status was then promoted through the formal CLI with `uv run volpred ops paper-upsert --paper-id leverage-direction --status ready_for_submission`.

Known residual layout warnings remain low-severity production cleanup items, chiefly the pre-existing 262pt overfull boxes in the conclusions/table area. They do not reopen the v12 H5 numerical-integrity blocker.

## 5. Conclusion

The v12 H5 final blocker is closed, the reproduce gate is green, and the compiled PDF reflects the current sources. From this confirmation scope, the leverage-direction paper can proceed from frozen review state to submission-prep state.
