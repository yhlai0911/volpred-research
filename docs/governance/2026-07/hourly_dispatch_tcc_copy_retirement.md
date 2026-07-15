# Hourly dispatch Desktop-TCC alert retirement

Date: 2026-07-16

## Problem

The rollback-only `scripts/cron_hourly_dispatch.sh` treated `Operation not permitted`, `getcwd`, and `EINTR` output as proof that a Claude CLI update had lost Desktop TCC access. That diagnosis was supported during the 2026-07-02 10:55 incident, when the repository still lived under `~/Desktop`. The repository moved to `~/volpred-research` later that day, so the causal premise no longer applies.

The stale branch would still send a CRITICAL alert and instruct the operator to open an interactive Claude session under Desktop. The syscall strings alone establish only a runtime/filesystem-context failure; they do not identify TCC, a CLI update, or any single remediation.

## Correction

- Preserve the signature branch so it remains distinct from explicit credential rejection.
- Report only a neutral runtime/filesystem failure and list cwd, repository path, WorkingDirectory, filesystem/mount state, and system load as follow-up checks.
- Remove the Claude symlink-age heuristic and all Desktop-TCC causal language.
- Do not suggest keychain repair without explicit authentication-rejection text.
- Downgrade this branch to WARN because Codex failover still owns the slot and the next schedule naturally retries.

## Verification

`tests/test_cron_auth_preflight.py` reproduces the exact `getcwd`/`Operation not permitted` signature and asserts the neutral WARN path, Codex failover wording, and absence of the retired TCC/interactive-session copy. `bash -n scripts/cron_hourly_dispatch.sh` and the portable-stat regression suite also pass.
