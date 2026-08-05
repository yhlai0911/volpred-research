# taiwan-vt — one wording edit now that the k892 repoint is actually in canonical

**Target**: `paper/taiwan-vt/body_v3.tex:53` (the `% source:` provenance comment on the 0050.TW row)
**Executed by**: main thread — `paper/` is a reserved area.
**Trigger**: research department landed the k892 pinned repoint at `77b1884fc` (2026-08-05).

## The situation this fixes

The provenance comment already claims the repoint:

> *"2026-07-27 reproducibility repoint — analysis input is now the pinned snapshot
> data/0050\_tw\_...\_2008-2026.csv column 0050\_tw\_adj\_close, verified to reproduce these values
> byte-for-byte, no live yfinance dependency"*

Until today that sentence was **false in canonical main**. The repoint was written and verified on
2026-07-27, but it never landed — the quarantine mechanism intercepted it six times and it survived
only in `6349aec58`. Canonical's `k892_verify_tw_gamma.py` went on calling `yf.download` for
0050.TW. A referee reproducing from the repository would not have been reading a pinned snapshot at
all.

As of `77b1884fc` it is true. Verified independently, from canonical HEAD rather than from the
research department's report:

- `git cat-file -e HEAD:experiments/k892/k892_verify_tw_gamma.py` → present
- `experiments/k892/k892_verify_tw_gamma.py:54` defines `PINNED_SOURCES`; `:82-83` route 0050.TW
  through `_load_pinned` before any `yf.download` call
- `experiments/k892/k892_verify_tw_gamma_results.json .assets["0050.TW"].full_sample`:
  `gamma = 0.09704215871857629`, `gamma_t = 3.5965275718364866`, `n_obs = 4219` — matching the
  comment's `0.0970 / 3.5965 / 4219` and the table's rounded `0.097 / 3.60`

## Why it still needs one edit

**The claim is now true for the 0050.TW leg and false for the script as a whole.** The
cross-check tickers (`^TWII`, `2330.TW`, `SPY`) still go to live yfinance. The research department
ran it end to end: 0050.TW loads from the snapshot, then `^TWII` returns `None` and the script
raises `ValueError` — **before writing `results.json`**. So a referee who runs the package gets the
correct pinned input for the paper's cited statistic and then a crash.

"No live yfinance dependency" reads as a property of the reproduction path. It is a property of one
leg of it.

## The edit

**FIND** (inside the `% source:` comment on line 53)

```
verified to reproduce these values byte-for-byte, no live yfinance dependency
```

**REPLACE**

```
verified to reproduce these values byte-for-byte; the cited statistic has no live-data dependency, though the script's cross-check tickers still fetch live and currently halt it before completion
```

Nothing else on line 53 changes. The numbers, the D3 errata note and the source path stay as they
are — all three verified above.

## What must not be claimed until the cross-check is fixed

- ❌ "the replication package runs end to end"
- ❌ "reproducible from a clean clone"
- ✅ "the statistic cited in the paper is determined by a pinned snapshot and reproduces
  byte-for-byte"

`experiments/k892` also still lacks `reproduce_spec.json`, so the artifact gate is BLOCKED. Per the
K1708 rule the spec must be produced *during* a run — a spec written afterwards drifts from the run
it claims to describe — so this is blocked behind the same `^TWII` failure. Research has proposed
making the cross-check tickers optional (`K892_CROSSCHECK=0`) or pinning them too; the manager is
deciding who takes that.

## Separately — a number to check in the W4 taiwan-vt round, not now

`body_v3.tex:33` states the 0050.TW sample as *"January 2009 to March 2026 (4,217 trading days)"*,
while the estimation reports `n_obs = 4219` over 2009-01-02 to 2026-04-02. Two discrepancies: the
count differs by 2, and the end month differs by one.

Both could be legitimate — `n_obs` may count returns while the prose counts price observations, and
`:33` documents dropping the 2014 split date — but no combination obviously reconciles to 4,217, and
the endpoint difference is not explained by either. **Recorded, not adjudicated**: it needs the
script read rather than a guess, which belongs to the W4 round. Flagging it here so it is not lost,
and so nobody edits `:33` on the assumption that the estimation output is wrong.
