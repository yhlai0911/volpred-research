# Zeabur Safe Frontend Deploy

## Why this exists

`frontend-v2-fix` is a Next.js Docker deploy. Two things make raw `npx zeabur deploy` risky here:

1. `NEXT_PUBLIC_*` values are needed at **build time**, not only runtime.
2. Zeabur CLI upload can effectively exclude `.env.production` when it follows ignore rules, which can produce a "successful" deploy whose API responses are all empty.

That exact failure mode happened on `volpred.zeabur.app` on 2026-03-24.

A second failure mode happened on 2026-06-02: after a server move, the deploy
target IDs in config/script were stale (and env-id was hardcoded), so every
deploy hit the **wrong service** — build succeeded but the deployment ended
`REMOVED` (never promoted), and the live site silently kept serving the old
version for weeks. See "Deploy target & architecture" and "Server move" below.

## Safe workflow

Use:

```bash
cd frontend-v2-fix
./scripts/deploy-zeabur-safe.sh
```

## Deploy target & architecture (current, 2026-06-02)

**Method = Zeabur CLI upload (the script above). NOT git push.** The script uploads
the working dir → builds on Zeabur → deploys to the **`volpred-v3`** service. The
live site `volpred.zeabur.app` is served by **`volpred-v3`** only.

**Single source of truth for IDs = `config/project_targets.json` → `.deploy`**
(`zeabur_project_id`, `zeabur_environment_id`, `services.volpred-v3`). The deploy
script reads all three from there. Never hardcode IDs in scripts/docs.

Current project (new Tencent-Tokyo machine, after the 2026-06-02 server move):

| Service | Service ID | Role | Domain | Deploy via |
|---|---|---|---|---|
| **volpred-v3** | `…6854117` | **LIVE frontend (serves volpred.zeabur.app)** | ✅ volpred.zeabur.app | this CLI script |
| volpred-web | `…6854116` | NOT in use (diff repo, no domain) | ❌ | GitHub yhlai0911/volpred-web |
| volpred-v2 | `69b8ed89…` | legacy | ❌ | — |
| volpred-mirror | `69c105e1…` | research-memory Mirror API | — | — |

(Old pre-move machine IDs preserved in `config .deploy._legacy_pre_20260602`.)
Frontend source repo (for reference only; deploy does NOT use git push):
`github.com/yhlai0911/volpred-v2`.

## Server move (changing machines)

**A server move is ONLY a change of 3 IDs.** Steps:

1. Edit `config/project_targets.json` → `.deploy`: set `zeabur_project_id`,
   `zeabur_environment_id`, and `services.volpred-v3` to the new machine's values
   (read them off the Zeabur console URL of the live volpred-v3 service:
   `zeabur.com/projects/<PROJECT>/services/<SERVICE>?envID=<ENV>`).
2. Deploy normally (`./scripts/deploy-zeabur-safe.sh`). Method does not change.
3. Verify the live render (see below).

Do **not** invent a new method, and do **not** confuse `volpred-web` with
`volpred-v3` — only `volpred-v3` binds the domain.

## Verification is mandatory

After deploy, **always confirm the live render**, not just the CLI message:

```bash
curl -sI -o /dev/null -w "%{http_code}\n" https://volpred.zeabur.app/   # expect 200
# then open https://volpred.zeabur.app/admin and confirm strategy-card numbers are sane
```

`"Service deployed successfully"` only means the **upload** succeeded. And do
**not** run the deploy through `| tail` — it masks the script's real exit code.

## What the script does

1. Verifies local `frontend-v2-fix/.env.production` exists and contains required keys.
2. Creates a temporary staging directory that does **not** inherit the repo `.gitignore` exclusion for `.env.production`.
3. Syncs the Zeabur service variables from the same local `.env.production`.
4. Deploys the staged frontend to the live Zeabur service.
5. Polls Zeabur until the deployment is `RUNNING`.
6. Verifies:
   - `/api/publications/feed` has non-zero data
   - `/api/strategy-overview` has non-empty strategies
7. Deletes the temporary staging directory.

## Why this is safer

- Avoids the silent "0-byte `.env.production`" production image problem.
- Uses one source of truth for build-time and runtime config.
- Fails closed if required env keys are missing.
- Verifies live data before declaring success.

## Important note

Do **not** go back to raw:

```bash
npx zeabur@latest deploy --project-id ... --service-id ... --json
```

for this frontend unless you are certain the build context already includes a valid `.env.production`.
