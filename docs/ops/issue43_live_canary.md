# Issue #43 — Live Canary: Enforced Mutating Isolation

**Task ID:** `issue43_live_canary_v2_20260727`

## Purpose

Production acceptance canary verifying that supervisor-enforced mutating
execution isolation works end to end. This worker was assigned a single
declared output path and must modify no other repo path, run no
`git add/commit/merge`, and leave integration to the machine finalizer.

## Scope of this file

- Written by the isolated worker inside its registered producer workspace.
- Contains the assigned task id above.
- Supervisor receipt identifiers (claim session, candidate commit, landing
  reference) will be appended by the owner after machine integration.

## Receipt identifiers (appended by owner post-integration)

- Dispatch job: `80f1563b6a1f4dd89d5e100e2e0f4005`
- Claim session: `dispatch-80f1563b-c0becdcf`
- Allocation: `751cdf01fd644e979b72cd1d1d50899d`
- Settlement pending: `e4c09b9db26c4c40b9c8c3e068204e9e`
- Gate passed: `dd8e3614d6724021af24b6fa087ecbdf`
- Terminal intent: `38b6fe70c29f47019635182c2496447a`
- Finalized: `0b19918aaf9141d8949ad011393386d7`
- Settlement completed: `c256addc427c4bf7b4131594fa8d3814`
- Candidate and main SHA: `296aabac03c73f484c8e6c8dfed9e4e46d707824`
