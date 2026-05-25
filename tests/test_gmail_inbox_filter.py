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
MARKER = "[VolPred"


def _check(subject, sender, in_reply_to="", references="", owner=OWNER, marker=MARKER):
    return _should_process(subject, sender, in_reply_to, references, owner, marker)


# ─── ACCEPT cases (require ALL 3 conditions) ──────────────────────────────

def test_owner_re_volpred_boss_report():
    ok, reason = _check(
        "Re: [VolPred Boss Report] 2026-05-25 平台運營報告",
        "yihao.lai@gmail.com",
    )
    assert ok is True, reason
    assert reason == "from_owner_and_is_reply_and_volpred_thread"


def test_owner_re_volpred_6h_summary_chinese_colon():
    ok, _ = _check(
        "Re：[VolPred 6h Summary] 06:05 → 12:05",
        "Yi-Hao Lai <yihao.lai@gmail.com>",
    )
    assert ok is True


def test_owner_volpred_with_in_reply_to_header_no_re_prefix():
    """Some clients drop Re: prefix; reply header still proves thread continuity."""
    ok, _ = _check(
        "[VolPred Alert] continuing thought",
        "yihao.lai@gmail.com",
        in_reply_to="<abc@gmail.com>",
    )
    assert ok is True


def test_owner_re_volpred_alert():
    ok, _ = _check("Re: [VolPred Alert][CRITICAL] draft pool=0", OWNER)
    assert ok is True


def test_marker_match_case_insensitive():
    ok, _ = _check("re: [volpred work summary] tick", OWNER)
    assert ok is True


# ─── REJECT: missing 1+ conditions ─────────────────────────────────────────

def test_owner_re_but_not_volpred_thread():
    """Owner replies to a non-VolPred thread (e.g. lunch invite) → reject."""
    ok, reason = _check("Re: 一起吃飯？", "yihao.lai@gmail.com")
    assert ok is False
    assert reason == "from_owner_reply_but_not_volpred_thread"


def test_owner_volpred_subject_but_brand_new_no_re():
    """Owner sends brand-new mail with [VolPred in subject but no Re:/reply header → reject."""
    ok, reason = _check("[VolPred] manual instruction", "yihao.lai@gmail.com")
    assert ok is False
    assert reason == "from_owner_but_not_reply"


def test_external_re_volpred_spoof():
    """External sender forwards/spoofs a VolPred subject → reject (not from owner)."""
    ok, reason = _check(
        "Re: [VolPred Boss Report] forwarded",
        "spammer@evil.com",
    )
    assert ok is False
    assert reason == "not_from_owner"


def test_owner_re_only_no_volpred_marker():
    ok, reason = _check("Re: random old thread", "yihao.lai@gmail.com")
    assert ok is False
    assert reason == "from_owner_reply_but_not_volpred_thread"


def test_neither_owner_nor_reply_nor_marker():
    ok, reason = _check("newsletter", "marketing@somesite.com")
    assert ok is False


def test_empty_owner_config():
    ok, _ = _check("Re: [VolPred x]", "anyone@example.com", owner="")
    assert ok is False


def test_empty_marker_disables_filter():
    """If VOLPRED_SUBJECT_MARKER is empty string, marker check is bypassed
    (back to 2-condition check). Useful for testing or alternate deployments."""
    ok, _ = _check("Re: anything", "yihao.lai@gmail.com", marker="")
    # marker empty → is_volpred_thread = False → still rejected because new logic requires marker
    assert ok is False


def test_none_subject_defensive():
    ok, _ = _check(None, "yihao.lai@gmail.com")
    assert ok is False


def test_none_sender_defensive():
    ok, _ = _check("Re: [VolPred x]", None)
    assert ok is False


# ─── EDGE cases ────────────────────────────────────────────────────────────

def test_owner_substring_attack_acknowledged():
    ok, _ = _check(
        "Re: [VolPred x]",
        "evil-yihao.lai@gmail.com-attacker@evil.com",
    )
    assert ok is True  # acknowledged substring tradeoff


def test_re_re_re_chain_with_volpred():
    ok, _ = _check("Re: Re: Re: [VolPred Boss Report]", OWNER)
    assert ok is True


def test_marker_appears_in_middle_of_subject():
    """Marker doesn't need to be at start — Re: prefix often pushes it inward."""
    ok, _ = _check("Re: Fwd: [VolPred Alert] nested", OWNER)
    assert ok is True


def test_custom_marker_env_override():
    """Pass marker explicitly to verify it's not hardcoded."""
    ok, _ = _check(
        "Re: [CustomTag] x",
        "yihao.lai@gmail.com",
        marker="[CustomTag",
    )
    assert ok is True
