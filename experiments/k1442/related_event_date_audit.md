# Related event-date contamination audit

Audit date: 2026-07-12. This scan was triggered by the K1442 CPI-date correction and was read-only with respect to the four related studies.

## Findings and disposition

| Study | Finding | Reader impact | Follow-up |
|---|---|---|---|
| `storage/event_articles/us_cpi_2026_06_11_t0` | The current 2026-06-10 window is correct, but the historical comparison contains seven wrong dates and one phantom event. Its claim that the current `+11.827%` VIX move ranked fourth is inconsistent with the official 13-event sample, where it ranks first. | No feed article was published. Internal evidence and prose are contaminated. | `task_b3b91831f5a3` |
| `storage/event_articles/us_cpi_2026_06_11_t2` | Three of the displayed recent-four dates are not CPI release dates. The recent-event statistics, pre-event run-up, variance comparison, and IV-crush narrative therefore require a full rerun. | Published as `mile_0fa9c7f5`; formal in-place correction is required. | `task_4751e8957898` |
| `storage/event_articles/us_cpi_2026_06_13_t7` | Seven of 13 hard-coded dates are wrong. With official dates, the event-day VIX mean changes from `+2.184%` to about `-0.847%`; the direction reverses. The old review also found unsupported CPI-surprise and predictability claims. | Published as `mile_ebb5d6f5`; statistics, figures, prose, and errata must all be replaced. | `task_4751e8957898` |
| `experiments/event_article_nfp_2026_07_03_t1` | A first-Friday proxy produces at least seven wrong dates in the 13-event historical sample. The July 2026 release was 2026-07-02, not 2026-07-03. | Live article `mile_35eef830` already uses the correct date and primarily relies on K528/K513, but its event metadata remains wrong; internal historical artifacts are contaminated. | `task_7ef956506564` |

## Shared process defect

- All three CPI scripts hard-code an obsolete `/Users/yhlai0911/Desktop/volpred-research` output root. They must use `Path(__file__).resolve().parent`.
- CPI repairs must use `volpred.data.event_dates.cpi_release_dates()`; the NFP repair must use `nfp_release_dates()`.
- Official-calendar retrieval must fail closed. No monthly heuristic or first-Friday proxy may silently substitute for a missing calendar.
- Published corrections must preserve old evidence as audit history, update through the formal publisher, sync the projection, and verify the live URL.

Primary calendar references: [BLS CPI schedule](https://www.bls.gov/schedule/news_release/cpi.htm), [ALFRED CPI release calendar](https://alfred.stlouisfed.org/release?rid=10), and [BLS Employment Situation schedule](https://www.bls.gov/schedule/news_release/empsit.htm).
