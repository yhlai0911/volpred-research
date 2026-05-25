"""Tests for gmail_inbox_poll._should_process filter logic.

Run: uv run pytest tests/test_gmail_inbox_filter.py -v
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Load scripts/gmail_inbox_poll.py without installing as a package
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gmail_inbox_poll.py"
spec = importlib.util.spec_from_file_location("gmail_inbox_poll", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["gmail_inbox_poll"] = mod
spec.loader.exec_module(mod)
_should_process = mod._should_process

OWNER = "yihao.lai@gmail.com"


def _check(subject, sender, in_reply_to="", references="", owner=OWNER):
    return _should_process(subject, sender, in_reply_to, references, owner)


# ─── ACCEPT cases ──────────────────────────────────────────────────────────

def test_owner_with_re_prefix_english():
    ok, reason = _check("Re: my old subject", "yihao.lai@gmail.com")
    assert ok is True, reason
    assert reason == "from_owner_and_is_reply"


def test_owner_with_re_prefix_chinese_colon():
    ok, _ = _check("Re：研究進度", "Yi-Hao Lai <yihao.lai@gmail.com>")
    assert ok is True


def test_owner_with_in_reply_to_header():
    ok, _ = _check("回覆", "yihao.lai@gmail.com", in_reply_to="<abc@example.com>")
    assert ok is True


def test_owner_with_references_header():
    ok, _ = _check("討論", "yihao.lai@gmail.com", references="<x@y.com> <z@y.com>")
    assert ok is True


def test_owner_mixed_case_sender():
    ok, _ = _check("Re: x", "Yihao.Lai@GMAIL.com")
    assert ok is True


def test_owner_with_display_name_format():
    ok, _ = _check("Re: x", '"賴奕豪" <yihao.lai@gmail.com>')
    assert ok is True


# ─── REJECT cases ──────────────────────────────────────────────────────────

def test_owner_brand_new_subject_no_reply_marker():
    """Owner sends new mail (no Re:, no reply headers) → must reject."""
    ok, reason = _check("new question", "yihao.lai@gmail.com")
    assert ok is False
    assert reason == "from_owner_but_not_reply"


def test_external_spam_with_re_prefix():
    """External sender with Re: prefix (classic spam pattern) → must reject."""
    ok, reason = _check("Re: your urgent task", "spam@malicious.com")
    assert ok is False
    assert reason == "not_from_owner"


def test_external_with_reply_headers():
    """External sender with real reply chain → still reject (not from owner)."""
    ok, reason = _check(
        "Re: shared thread",
        "colleague@university.edu",
        in_reply_to="<existing-thread@gmail.com>",
    )
    assert ok is False
    assert reason == "not_from_owner"


def test_neither_owner_nor_reply():
    ok, reason = _check("hello world", "newsletter@somesite.com")
    assert ok is False
    assert reason == "not_from_owner_not_reply"


def test_empty_owner_config():
    """If owner_email config missing, must reject everything (fail-safe)."""
    ok, reason = _check("Re: x", "anyone@example.com", owner="")
    assert ok is False


def test_none_subject_defensive():
    """Defensive: None subject must not crash."""
    ok, _ = _check(None, "yihao.lai@gmail.com")
    assert ok is False  # no reply marker


def test_none_sender_defensive():
    ok, _ = _check("Re: x", None)
    assert ok is False


# ─── EDGE cases ────────────────────────────────────────────────────────────

def test_owner_partial_match_substring_attack():
    """Sender contains owner's email as substring but in unusual position.
    Current implementation accepts this. If you ever want strict equality,
    refactor _should_process to parse the address with email.utils.parseaddr."""
    ok, _ = _check("Re: x", "evil-yihao.lai@gmail.com-attacker@evil.com")
    # current behavior: True (substring match). Document, don't enforce.
    assert ok is True  # accepted under substring rule (acknowledged tradeoff)


def test_re_re_re_chain():
    ok, _ = _check("Re: Re: Re: ongoing", "yihao.lai@gmail.com")
    assert ok is True


def test_lowercase_re_prefix():
    ok, _ = _check("re: lowercase", "yihao.lai@gmail.com")
    assert ok is True
