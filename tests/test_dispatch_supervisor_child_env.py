from __future__ import annotations

from scripts.dispatch_supervisor.child_env import external_child_environment


def test_external_child_environment_removes_process_scoped_release_identity() -> None:
    base = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/tmp/home",
        "CLAUDE_CODE_OAUTH_TOKEN": "subscription",
        "VOLPRED_ACTOR": "dispatch-supervisor",
        "VOLPRED_TASK_CLAIM_OWNER": "hourly-slot-1-job",
        "VOLPRED_SUPERVISOR_RELEASE_ID": "release-id",
        "VOLPRED_SUPERVISOR_RELEASE_SHA256": "a" * 64,
        "VOLPRED_SUPERVISOR_BOOTSTRAP_SHA256": "b" * 64,
        "VOLPRED_SUPERVISOR_FUTURE_MARKER": "future",
        "VOLPRED_DEFERRED_RELOAD_ROOT": "/tmp/reload",
        "VOLPRED_DEFERRED_RELOAD_FUTURE_MARKER": "future",
        "VOLPRED_CANONICAL_REPO_ROOT": "/repo",
    }

    child = external_child_environment(
        base,
        overrides={
            "VOLPRED_PROVIDER_ID": "claude-cli",
            "VOLPRED_SUPERVISOR_RELEASE_ID": "must-still-be-removed",
        },
    )

    assert base["VOLPRED_SUPERVISOR_RELEASE_ID"] == "release-id"
    assert child == {
        "PATH": "/usr/bin:/bin",
        "HOME": "/tmp/home",
        "CLAUDE_CODE_OAUTH_TOKEN": "subscription",
        "VOLPRED_ACTOR": "dispatch-supervisor",
        "VOLPRED_TASK_CLAIM_OWNER": "hourly-slot-1-job",
        "VOLPRED_PROVIDER_ID": "claude-cli",
    }
