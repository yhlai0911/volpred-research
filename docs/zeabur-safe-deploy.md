# Zeabur Safe Frontend Deploy

## Why this exists

`frontend-v2-fix` is a Next.js Docker deploy. Two things make raw `npx zeabur deploy` risky here:

1. `NEXT_PUBLIC_*` values are needed at **build time**, not only runtime.
2. Zeabur CLI upload can effectively exclude `.env.production` when it follows ignore rules, which can produce a "successful" deploy whose API responses are all empty.

That exact failure mode happened on `volpred.zeabur.app` on 2026-03-24.

## Safe workflow

Use:

```bash
cd frontend-v2-fix
./scripts/deploy-zeabur-safe.sh
```

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
