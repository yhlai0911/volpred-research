# K1340 Codex Review

**Review date:** 2026-06-15
**Reviewer:** Codex
**Implementation verdict:** PASS_WITH_CAVEATS
**Research verdict:** NULL_INVERSE_VOL_COMPRESSION

## Checks

1. **Lookahead:** PASS. Raw pressure is observed on shock date t, then
   `positive_raw_event.shift(1)` / `negative_raw_event.shift(1)` defines the
   tradable event date. Forward windows start from the shifted event date, so
   same-day pressure is not used to explain same-day returns.

2. **Proxy validity:** CAVEAT. `return * prior-only volume_z` is a transparent
   signed price-pressure proxy, not true dealer gamma, option customer flow, or
   market-maker inventory. Conclusions must say "retail/gamma candidate
   pressure proxy", not "dealer gamma exposure".

3. **Multiple testing:** PASS. The primary family is fixed at 12 tests
   (2 event types x 3 horizons x 2 metrics). The reported Bonferroni alpha is
   0.10 / 12 = 0.00833.

4. **Event independence:** CONDITIONAL. Same-date cross-ticker episodes are
   common. The main p-values average same-date events into event-date clusters
   before sign-flip testing. This is better than event-level iid bootstrap, but
   it still cannot fully remove broad market retail-episode dependence.

5. **Seed reproducibility:** PASS. Bootstrap uses `np.random.default_rng` with
   deterministic stable seeds and does not depend on Python `hash()`.

6. **Bootstrap p-value:** PASS_WITH_CAVEATS. Paired event/control differences
   are tested with two-sided sign-flip bootstrap. This is appropriate for the
   matched-difference null, but inference remains approximate because matched
   controls are constructed from overlapping daily windows.

## Result Review

The ex-ante primary positive-pressure H=21 CAR test is not significant:

- Date-clustered matched CAR difference: +1.88%.
- p=0.5322.
- 85 event-date clusters, 103 events.

No direction-supportive test has raw p<0.10 or Bonferroni significance.

Three Bonferroni-significant cells exist, but all are inverse RV-compression
results:

- Positive-pressure H=5 matched RV-jump difference: -0.3413, p=0.0000.
- Negative-pressure H=5 matched RV-jump difference: -0.4868, p=0.0000.
- Negative-pressure H=10 matched RV-jump difference: -0.2254, p=0.0026.

These do not support the elevated-volatility/gamma-squeeze continuation
hypothesis. They indicate that once the observed shock day is excluded, short
forward realized volatility tends to cool down relative to matched non-event
windows.

## Final

K1340 is reproducible and lookahead-clean, but the empirical conclusion is NULL
for the stated hypothesis. Do not promote it as gamma-squeeze prediction
evidence. It is a useful negative result about the limits of daily yfinance
price-volume proxies.
