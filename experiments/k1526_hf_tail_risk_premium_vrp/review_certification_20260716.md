# K1526 methodology repair review

Verdict: PASS

Reviewed frozen commit: `60052f4fbd4fac7418a43326645b27b73223cc06`

Checks performed:

1. The h=1-degenerate local DM helper is removed; the squared-error comparison between the historical-mean restriction and ES+VIX larger model uses canonical `clark_west_test`.
2. The 138-row OOS ledger recomputes the saved Clark-West record exactly when parsed with `float_precision="round_trip"`; HAC lag is 6, t=-0.212562, one-sided p=0.584166.
3. The ledger SHA-256 matches the result JSON. K1526 and K1525 core result payloads are identical after normalizing experiment-specific identifiers.
4. R2 OOS is -0.045704 and the 1,000-draw bootstrap interval [-0.135240, 0.098672] crosses zero. The corrected OOS NULL is supported; the in-sample RDSV t=3.343702 is reported separately and not promoted to an OOS claim.
5. Both DM/HAC and nested-DM ratchet suites pass (123 tests). Result JSON and ledger writes are atomic. No lookahead, strategy-return, or reader-facing claim issue was found in the repaired surface.

Blocking defects: none.
