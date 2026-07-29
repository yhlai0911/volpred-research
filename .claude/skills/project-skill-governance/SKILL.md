---
name: project-skill-governance
description: Audit, add, update, merge, or retire VolPred project skills. Use for skill architecture reviews, monthly skill hygiene, registry/router drift, overlapping triggers, or any change under .claude/skills/.
---

# Govern project skills

Treat a skill as an executable workflow contract, not a place to archive platform history.

## Resolve the current architecture first

Read these sources at invocation time:

1. `storage/ops/task_pool_mode.json` for the live work-admission mode.
2. `config/runtime_schedules.json` for active schedule ownership.
3. `config/project_targets.json` for frontend, deploy, paper, and remote targets.
4. `config/skill_registry.json` for roles, routes, workflow usage, dispatch expectations, and
   canonical contracts.
5. `config/supervisor_rules.json` for the live task-family/context/seed dispatch projection.
6. `config/models.json` and `scripts/model_router.py` for runtime model and effort routing.
7. `docs/agents/ownership.md` for path ownership and writer boundaries.

Machine-readable state outranks dated prose. Never copy a current mode, cadence, service ID,
model choice, or queue snapshot into a skill.

## Audit the full population

1. Inventory every `.claude/skills/*/SKILL.md`.
2. Compare the inventory, workflow trigger text, and routes with `config/skill_registry.json`,
   `docs/skill-registry.md`, and `docs/workflow-index.md`.
3. Verify `config/supervisor_rules.json` task-family, context, and skill-backed seed dispatch
   exactly match the registry's required keys, route sequence, and owners; membership-only
   validation is insufficient.
4. Classify each skill as `orchestrator`, `leaf`, `cross-cutting`, or `compatibility`.
5. Verify one leading action and one unambiguous trigger domain per skill.
6. Identify duplicated owners, unreachable support skills, phantom entries, stale commands,
   direct state writes, and copied runtime values.
7. Move detailed variants to directly linked references; keep the main workflow concise.
8. Run `python3 scripts/check_skill_architecture.py` and
   `bash scripts/check_skills_complete.sh --json`.

## Change safely

- Preserve canonical policy in config, code, and path-scoped rules; skills point to it.
- Verify every documented command with its current `--help` before publishing the instruction.
- Do not invent a missing writer or transition CLI. Mark the workflow blocked and create a
  canonical implementation task instead.
- Update the registry and workflow projection in the same change.
- When modifying an existing skill, send the owner notification required by `AGENTS.md`.

## Completion

Finish only when the actual skill set matches the registry, every support route resolves, all
architecture checks pass, the affected workflow has an observable completion criterion, and the
required owner notification has been sent. A green mtime or dead-link scan alone is insufficient.
