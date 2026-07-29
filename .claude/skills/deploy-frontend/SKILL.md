---
name: deploy-frontend
description: Deploy and verify the active VolPred frontend. Use when the user requests a production deployment, go-live, Zeabur release, or post-deploy frontend verification.
---

# Deploy the active frontend

Resolve the target from `config/project_targets.json` on every invocation. Read
`.claude/rules/frontend-and-deploy.md` and `docs/zeabur-safe-deploy.md` for the current safety
contract. Never copy project, environment, service IDs, URLs, or active paths into this skill.

## Workflow

1. Resolve `active_frontend`, its source path, deploy service, paper directory, and live URL.
2. Inspect both the parent repository and nested frontend repository for unrelated work.
3. Run the frontend's tests and build required by the deploy rule.
4. Resolve and execute the current safe deploy entrypoint; fail closed if the path or target does
   not match the active config.
5. Read the provider state back and require the target service to reach its expected terminal
   state.
6. Verify the live endpoint, route/version identity, expected assets, and the changed UI behavior.
7. For visual changes, complete the `web-ui-ux-review` post-deploy spot check.

Do not use a Git push as the deployment mechanism unless the active config explicitly changes the
contract. A successful upload without provider and live-site readback is incomplete.
