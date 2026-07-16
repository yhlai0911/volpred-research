# K1707 pre-run source review

VERDICT: PASS

Scope: frozen source only (`experiments/k1707/README.md` and
`experiments/k1707/K1707.py`); this verdict authorizes the adequacy-audit run
and is not a scientific PASS.

## Review trail

- The primary external Codex review job was attempted first and failed before
  review because that separate account had reached its usage limit. The local
  `.stderr` receipt preserves the quota error and was not treated as a review.
- Two read-only fallback reviewers independently inspected the source. The
  first identified fail-open missing-value validation and missing source pins;
  those defects were fixed and the reviewer returned PASS on the revised bytes.
- The second identified three additional blocking defects: incomplete raw-date
  gate coverage, pseudo-date/VIX-weighted descriptive effects, and treating the
  auction-only `MULTIPLE_IND` field as an auction/continuous benefit. The code
  was revised to use the complete raw date roster for gates, pooled raw
  sufficient statistics without VIX for descriptive benefits, and an explicit
  auction-only multiple-bidder rate. The reviewer then returned PASS on the
  revised bytes.

## Verified controls

- Fixed support gates are fail-closed and unexpected support raises rather than
  invoking an unimplemented confirmatory estimator.
- VIX uses the explicit point-in-time expression `VIXCLS.ffill().shift(1)`.
- Raw MD5 and FRED SHA-256 are pinned; required columns and critical values fail
  loudly.
- Benefit directions and pooled mean/dispersion sufficient statistics are
  correct; VIX does not enter the descriptive-effect artifact.
- JSON replacement is atomic and validated; gzip time is fixed and seed is 42.
