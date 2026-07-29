"""Environment boundary for processes launched by the pinned supervisor.

The immutable supervisor release identity belongs to the daemon process only.
If those markers reach a canonical-repository CLI or a provider process, the
child can mistake mutable checkout code for the pinned release.  That changes
import provenance and capability behavior even when the child happens to
start successfully.

Every canonical-repository CLI/gate and provider process that leaves the pinned
supervisor execution context must build its environment through
:func:`external_child_environment`.  Pure OS probes such as ``git``, ``ps``,
``du``, and ``sandbox-exec /usr/bin/true`` do not interpret this identity and
remain outside this semantic boundary.  The deliberate
stage0 -> bootstrap -> supervisor chain does not call this helper because that
chain is the sole owner of the release identity.
"""
from __future__ import annotations

import os
from collections.abc import Mapping

_PRIVATE_PREFIXES = (
    "VOLPRED_SUPERVISOR_",
    "VOLPRED_DEFERRED_RELOAD_",
)
_PRIVATE_EXACT_KEYS = frozenset({
    "VOLPRED_CANONICAL_REPO_ROOT",
})


def _is_supervisor_private(key: str) -> bool:
    return key in _PRIVATE_EXACT_KEYS or key.startswith(_PRIVATE_PREFIXES)


def external_child_environment(
    base: Mapping[str, str] | None = None,
    *,
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return an external-child environment without supervisor identity.

    ``base`` defaults to the live process environment and is never mutated.
    Overrides are applied before the private-key filter, so no caller can
    accidentally reintroduce a daemon-only identity at the spawn boundary.
    Ordinary attribution, provider receipts, OAuth material, PATH, and HOME
    remain intact.
    """
    environment = dict(os.environ if base is None else base)
    if overrides:
        environment.update(overrides)
    return {
        key: value
        for key, value in environment.items()
        if not _is_supervisor_private(key)
    }
