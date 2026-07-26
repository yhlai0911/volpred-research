VERDICT: FAIL
REVIEWED_COMMIT: b2634ed41
BLOCKING_DEFECTS:
1. tests/test_nfp_official_release_dates.py:902-925,996-1005 — finite verb stems and the 24-character cutoff permit obvious synonyms/rephrasings; “the 237 NFP reports were issued on Fridays” and a natural longer-distance release phrase both return no offender.
2. tests/test_nfp_official_release_dates.py:985-1009 — bindings are OR-ed across an entire clause, so an unrelated second Friday-session exempts the actual misbinding; “237 Friday releases were used, and a Friday session was also analyzed” returns no offender.
3. tests/test_nfp_official_release_dates.py:909-914,1010 — clause splitting omits commas, colons, and ASCII periods while denial markers exempt the whole resulting unit; “The unrelated proxy statement is wrong, 237 Friday releases were used” returns no offender.
NON_BLOCKING_NOTES: OLD is a faithful reconstruction: replay produced OLD 1/7 versus NEW 7/7, with 4/4 legitimate cases passing. All 14 structural cases and the clean-tree scan passed by direct invocation; an in-memory offending file made the live scan assertion fail, so it is not a no-op. N2 is closed. N3 is explicitly a post-merge draft deferral, although summary.json:7 misleadingly says N3 is closed.
ONE_LINE: The published cases are honestly tested, but the detector remains trivially defeatable through ordinary synonym, binding, and denial rephrasings, so N1 has not earned a mergeable verdict.
