# Spec: mark a paper's blocker string stale automatically

**Origin**: governance ruling 2026-08-05 — *a narrative field carrying `*_verified_at` declares
its own expiry; if the verification timestamp precedes the landing of what it describes, the
field is void and may not be cited.* Governance also ruled that mechanising the detection is **not
a new gate** — it is one more field on the existing pipeline read model, so anti-stacking does not
apply.

**Owner of the code**: whoever holds `scripts/`. The publications department cannot write there;
this spec exists so that the judgement does not have to be made twice.

**Why it is worth doing**: three papers were misread from stale prose fields in a single session
(prg-periodic-garch, vix-sufficiency, taiwan-vt), and one of those misreads produced a departmental
ruling on evidence that had been void for a month.

## Where it goes

`scripts/paper_pipeline_check.py` — the existing read model. Add one field per paper; do not add a
checker, a cron, or an alert. Consumers decide what to do with it.

```json
"blocker_staleness": {
  "verified_at": "2026-07-05T19:20:00+08:00",
  "newest_canonical_artifact_at": "2026-07-13T11:04:12+08:00",
  "stale": true,
  "evidence": ["paper/taiwan-vt/body_v3.tex", "paper/taiwan-vt/reproduce.py"]
}
```

`stale = verified_at < newest_canonical_artifact_at`. Absent `blocker_verified_at`, fall back to
`last_update`, and set `"basis": "last_update"` so consumers know the signal is weaker.

## What counts as a canonical artifact

**Not** every commit touching `paper/<id>/`. A prototype using arbitrary commit dates flagged
12/13 papers, because portfolio-wide sweeps (compliance scrubs, the manuscript-declared refactor,
periodic snapshot refreshes, the repo migration) touch every paper directory. That version is a
sorter, not a detector.

Restrict to files whose modification means the blocker's subject may have moved:

- the declared manuscript (`canonical.json` → `main_tex`) and anything it `\input`s
- `reproduce.py`, `reproduce_report.json`, `experiments.md`, `data_sources.md`
- `review_history/*/` — a new round directory is the strongest signal of all

Use **git commit dates, not filesystem mtimes**: a checkout rewrites mtimes and would make every
paper look freshly modified.

## Known residual noise

Portfolio-wide sweeps do sometimes edit `main.tex` itself (the 2026-07-01 AI-footnote scrub is a
real example), so the restricted version still yields occasional false positives. That is
acceptable — a false positive costs one file read, a false negative cost a department a wrong
ruling. **Do not tune it toward silence.**

Do not attempt to classify commits by message keywords. The prototype tried; `paper(prg): v6 MINOR
9 mechanism citations` and `paper_ai_footnote_scrub_20260701 | 全 portfolio 論文清洗` are not
separable by pattern, and a wrong classifier is worse than an honest over-report.

## What this does not do

It does not decide whether a blocker is *correct* — only whether it has been verified since the
artifacts it describes last moved. Establishing correctness still means reading the source, which
is what the publications rotation now does once per round, recording the corrected string in the
round README for whoever holds write access.

## Related, same root cause, not covered here

`last_advance_at` has the same defect in a worse form: it has no verification stamp at all, so
staleness is undetectable rather than merely undetected. Nine papers carry the portfolio baseline
date, four of which had substantive advances afterwards. The fix there is different — derive the
value from `review_history/` and git rather than flag it — and belongs to the same work item.
