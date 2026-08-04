"""Every sanctioned provider CLI wrapper must strip paid-auth variables itself.

Owner principle (2026-08-04): claude, codex and agy all run on subscription
OAuth quota, never a metered API key.

The registry denies a spawn when the parent environment carries any forbidden
API-key or alternate-endpoint variable. Inside a Claude Code session
ANTHROPIC_BASE_URL is always present -- harness-injected, pointing at the
official default endpoint -- so the check denied every sanctioned spawn while
granting the child nothing. Worse, denying only stopped the sanctioned path: a
raw `codex exec` or `subprocess.run(["agy", ...])` inherited the entire
environment. Three experiment reviews (K1746, K1747, K1735) went out that way
before a wrapper existed for agy at all.

The wrappers now strip first, attest the stripped environment, and spawn with
that same environment, so what is attested is what the child actually gets.
These tests pin that shape so it cannot regress into "attest clean, spawn
dirty", which would be worse than the original deny.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "provider_registry.json"
WRAPPERS = {
    "codex-cli": ROOT / "scripts" / "codex_exec_bounded.sh",
    "agy-cli": ROOT / "scripts" / "agy_exec_bounded.sh",
}


def _registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


@pytest.mark.parametrize("provider_id", sorted(WRAPPERS))
def test_wrapper_exists_and_is_the_sanctioned_entry(provider_id: str) -> None:
    """A provider without a bounded wrapper is a provider people will call raw."""
    path = WRAPPERS[provider_id]
    assert path.exists(), f"{provider_id} has no bounded wrapper at {path}"


@pytest.mark.parametrize("provider_id", sorted(WRAPPERS))
def test_wrapper_strips_forbidden_env_before_authorising(provider_id: str) -> None:
    text = WRAPPERS[provider_id].read_text(encoding="utf-8")
    # Delegates to the canonical sanitizer instead of reimplementing stripping.
    # One owner per concern: registry.sanitize_provider_spawn_environment landed
    # 2026-08-04 for the daemon spawn path, and these wrappers briefly carried a
    # parallel copy. A second implementation is how the two drift apart.
    # Must actually CALL it, not merely import it. An earlier version of this
    # test matched the bare name and so stayed green when the call was replaced
    # with a hand-rolled dict while the import lingered.
    assert re.search(
        r"clean_env,\s*stripped\s*=\s*sanitize_provider_spawn_environment\s*\(",
        text,
    ), (
        f"{provider_id} wrapper does not call the canonical sanitizer "
        "(importing it is not using it)"
    )
    assert 'provider["auth"]["forbidden_env"]' not in text, (
        f"{provider_id} wrapper reimplements the forbidden-set lookup instead of "
        "delegating to registry.sanitize_provider_spawn_environment"
    )
    # Passing os.environ INTO the sanitizer is correct; what must never happen is
    # handing the raw environment to authorize_provider_spawn. Scope the check to
    # the authorize call rather than substring-matching the whole file, which is
    # what an earlier version of this test got wrong.
    authorize_call = re.search(
        r"authorize_provider_spawn\((.*?)\)", text, re.S
    )
    assert authorize_call, f"{provider_id} wrapper never calls authorize_provider_spawn"
    args = authorize_call.group(1)
    assert "environment=clean_env" in args, (
        f"{provider_id} wrapper attests something other than the sanitized "
        f"environment: {args.strip()[:120]}"
    )
    assert "environment=os.environ" not in args, (
        f"{provider_id} wrapper hands the raw parent environment to authorize"
    )


@pytest.mark.parametrize("provider_id", sorted(WRAPPERS))
def test_wrapper_spawns_with_the_environment_it_attested(provider_id: str) -> None:
    """Attesting a clean env and spawning a dirty one would be the worst outcome."""
    text = WRAPPERS[provider_id].read_text(encoding="utf-8")
    assert re.search(r"child_env\s*=\s*\{\*\*clean_env", text), (
        f"{provider_id} wrapper spawns from an environment other than the one "
        "it attested"
    )
    assert not re.search(r"child_env\s*=\s*\{\*\*os\.environ", text), (
        f"{provider_id} wrapper spawns with the raw parent environment"
    )


@pytest.mark.parametrize("provider_id", sorted(WRAPPERS))
def test_wrapper_reports_what_it_stripped(provider_id: str) -> None:
    """Silent stripping is unauditable; the operator must see what was removed."""
    text = WRAPPERS[provider_id].read_text(encoding="utf-8")
    assert "stripped from child env" in text, (
        f"{provider_id} wrapper strips variables without saying which"
    )


def test_every_registered_provider_still_requires_subscription_auth() -> None:
    """The stripping must never become an excuse to allow an api-key surface."""
    allowed = {"subscription_oauth", "desktop_subscription"}
    for provider in _registry()["providers"]:
        auth = provider["auth"]
        assert auth["surface"] in allowed, (
            f"{provider['provider_id']} auth surface {auth['surface']!r} is not "
            "a subscription surface"
        )
        assert not auth.get("api_key_env"), (
            f"{provider['provider_id']} declares an api_key_env, which the owner "
            "principle forbids"
        )


def test_forbidden_sets_stay_aligned_across_providers() -> None:
    """One provider quietly shrinking its forbidden set is the drift to catch."""
    sets = {
        p["provider_id"]: frozenset(p["auth"]["forbidden_env"])
        for p in _registry()["providers"]
    }
    reference = max(sets.values(), key=len)
    for provider_id, forbidden in sets.items():
        missing = sorted(reference - forbidden)
        assert not missing, (
            f"{provider_id} omits forbidden variables the other providers "
            f"block: {missing}"
        )
