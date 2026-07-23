"""The paid-Gemini kill switch must cover embeddings, not just chat.

Boss msg936 (2026-07-17) turned off the PAID Gemini API; headless Gemini chat
moved to the free `agy` CLI and `gemini_ask.py` got a break-glass guard. That
left one paid surface uncovered: `build_knowledge_index.py`'s
`EMBED_PROVIDER=gemini` branch (`gemini-embedding-001`, $0.15/1M tokens). agy is
a chat CLI — it cannot serve embeddings — so the branch had no free substitute
and no guard, meaning one env var away from billing again.

Two things are pinned here, and the second is the one that bites:

  1. The guard fires at the provider boundary, before any billable request.
  2. It RAISES rather than `sys.exit()`. `get_client()` is library code —
     `volpred.ops.topic_similarity._real_embedder` calls it from the publisher's
     deliberately fail-open semantic-duplicate path, which catches `Exception`.
     `SystemExit` derives from `BaseException` and would escape that catch,
     killing a publish mid-run. That exact bug already happened once here with
     `MissingEmbeddingCredentials` (2026-07-10); this test stops the repeat.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_knowledge_index as bki  # noqa: E402


def test_gemini_provider_blocked_by_default(monkeypatch):
    monkeypatch.setattr(bki, "EMBED_PROVIDER", "gemini")
    monkeypatch.delenv("VOLPRED_ALLOW_PAID_GEMINI", raising=False)

    with pytest.raises(bki.PaidGeminiDisabled) as exc:
        bki.get_client()

    # The message must name the override, or the break-glass is undiscoverable.
    assert "VOLPRED_ALLOW_PAID_GEMINI=1" in str(exc.value)


def test_guard_raises_not_exits():
    """`except Exception` must be able to catch it — see module docstring."""
    assert issubclass(bki.PaidGeminiDisabled, Exception)
    assert not issubclass(bki.PaidGeminiDisabled, SystemExit)


def test_break_glass_override_lets_gemini_through(monkeypatch):
    monkeypatch.setenv("VOLPRED_ALLOW_PAID_GEMINI", "1")
    # Guard alone must not raise; client construction beyond it is out of scope
    # (it needs a real key and the google-genai package).
    bki._guard_paid_gemini_embeddings()


def test_openai_default_path_untouched(monkeypatch):
    """The guard must not fire on the default provider."""
    monkeypatch.setattr(bki, "EMBED_PROVIDER", "openai")
    monkeypatch.delenv("VOLPRED_ALLOW_PAID_GEMINI", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")

    # Constructing the OpenAI client makes no network call.
    client = bki.get_client()
    assert client is not None
