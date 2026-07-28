Frozen-byte verification failed, so I stopped before reading claims or running gates.

Mismatches:

- `experiments/k1731/README.md` — expected `2f9efd…`, actual `38bedc…`
- `experiments/k1731/k1731_armB_traceability_rows.json` — expected `bb08cf…`, actual `234f56…`
- `experiments/k1731/k1731_armB_verification.py` — expected `6ee4fa…`, actual `e301ed…`

All 35 entries were checked; 3 mismatched. Line numbers are inapplicable because these are whole-file byte-identity failures.

Minimal remediation: restore these three files to the frozen bytes, or intentionally freeze the new complete claim surface and request a fresh review. No substantive round-10 verdict is valid against the current moved bytes.

VERDICT: FAIL
