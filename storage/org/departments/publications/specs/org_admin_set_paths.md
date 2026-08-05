# Spec: `org_admin.py set-paths` — the missing writer for territory changes

**Origin**: manager ruling D24 (2026-08-05), taking option 2 in the form governance specified —
a subcommand on the canonical writer, not a one-off registry edit and not a widened write gate.

**Who implements it**: the main thread / owner's interactive session. Per governance's audit, that
is the actor with write access to `scripts/org/`. Not platform engineering — the manager has
already issued a retraction on that point.

**Why it is blocking**: `owned_paths` is fixed at department creation. `org_admin.py` exposes
`init / create / retire / suspend / resume / list` and nothing that edits an existing department,
so a territory change has no writer at all — the manager cannot write the registry, platform
engineering owns only `frontend-v2-fix/`, and departments are forbidden by charter. Four roles,
no path. Publications currently holds `owned_paths: []` while being asked to edit `paper/`.

## Interface

```bash
uv run python scripts/org/org_admin.py set-paths <dept> \
    --paths paper/,storage/paper_pipeline_status.json \
    --reason "D24: publications owns manuscript revision" \
    --actor manager \
    [--cadence weekly] \
    [--task-types paper_review,paper_body,paper_decision]
```

`--paths` replaces the list rather than appending; passing `""` clears it. Say so in `--help`,
because "add one path" is what a caller will assume.

## Behaviour, in order

1. `validate_dept_name(dept)`; department must exist with `status == "active"`.
2. **Refuse `dept == "manager"`.** Governance's condition: a role that can widen its own access
   makes every other decision it takes unauditable. This is a hard check, not a warning.
3. `check_path_conflicts(registry, paths, exclude=dept)` — the function already exists and is used
   by `cmd_create`. Two departments owning the same path is the failure this prevents; refuse and
   print the conflicts, exactly as `cmd_create` does at `:95-100`.
4. If `--task-types` given, run the same duplicate check `cmd_create` performs at `:101-108`.
5. Update `registry["departments"][dept]`: `owned_paths`, and `min_cadence` / `owned_task_types`
   when supplied. `save_registry`.
6. **Rewrite the matching lines in `storage/org/departments/<dept>/charter.md`.** See below — this
   step is the one most likely to be skipped, and skipping it reintroduces the exact defect the
   department has spent today reporting.
7. `bulletin_append(root, args.actor, f"department {dept}: paths → {paths}; cadence → {cadence} — {reason}")`.
   `--reason` is required, matching `retire`.
8. Print a reminder that the change takes effect **after re-attach** (see below).

## Step 6 is not optional, and there is already a live example

`cmd_create` writes `owned_paths` and `min_cadence` into two places: the registry (`:139-140`) and
the rendered `charter.md` (`:121-122`). A `set-paths` that updates only the registry leaves the
charter describing the old territory — and the charter is what each department session reads at
startup to learn who it is.

This has already happened. The manager ruled on 2026-08-05 that publications moves to a weekly
cadence. With no writer available, the change went into `charter.md` alone, so right now:

```
charter.md:  min_cadence: weekly（2026-08-05 經理裁決二）
registry:    "min_cadence": null
```

The department believes one thing, the registry says another, and nothing detects the gap. That is
the same class as the stale `blocker` strings and the `data_sources.md` row naming a source nothing
reads — a hand-maintained description drifting from the thing it describes. Implementing
`set-paths` without step 6 institutionalises it.

Safest form: re-render the charter's metadata block from the registry entry, so the registry is the
single source and the charter is a projection. If a full re-render risks clobbering
department-authored sections (publications has added a rotation table to its own charter), then
rewrite only the four metadata lines and leave the body untouched.

## Re-attach

Governance's standing warning: `generate_dept_settings` produces a session's settings at attach
time. A registry change does not reach a running session, and a caller who tests immediately will
conclude the change failed and try to route around it. The command should print this, and the
manager's dispatch note should repeat it.

## Idempotence and verification

Calling twice with identical arguments must be a no-op that still prints what it verified — not an
error, and not a second bulletin line. Callers will re-run it to confirm.

Suggested tests, matching the shape of the existing org admin tests:

- sets `owned_paths` and reflects it in both registry and charter
- refuses `dept == "manager"`
- refuses a path already owned by another active department
- refuses an unknown or retired department
- `--cadence` updates registry and charter together
- second identical call changes nothing and appends no bulletin line

## First call, once it exists

```bash
uv run python scripts/org/org_admin.py set-paths publications \
    --paths paper/ \
    --cadence weekly \
    --reason "D24: manuscript revision belongs to the department that reviews it; cadence per decision 2" \
    --actor manager
```

That unblocks `APPLY_PATCH.md` (four MAJORs on prg-periodic-garch, MAJOR-1 carrying a live
submission risk), the F3/F10 nested Clark-West runs, and the pipeline blocker corrections — all of
which currently sit finished-but-unapplied.

Whether `storage/paper_pipeline_status.json` should come with it is a separate call: governance has
opinions about who owns cross-paper state, and this spec does not pre-empt them.
