"""Conclusion-field linter for experiment results.json.

Background
----------
2026-05-09 K947 incident: results.json 的 ``conclusion`` 欄位寫了
"Harvey-Yes" 但同句沒指明哪一對 model。下游讀者把這當成 "K947 通過 Harvey
門檻"，但實際上對應的 DM 表 t-stat 不夠強。

P5 audit 在 846 個 results.json 內找到 14 個 AMBIGUOUS conclusion。為了
避免再寫進 knowledge.json / 文章 / 論文，這個 linter 在 results.json 落地
時掃 conclusion 欄位、抓 trigger word、要求同句要有 numeric 或 model-pair
作 backing，否則 WARN（或 strict mode 直接 raise）。

設計原則
---------
- 純文字 linter，無 lookahead 風險（spec 已標 N/A）。
- WARN-only by default；``VOLPRED_LINT_STRICT=1`` 或 ``strict=True`` 才
  raise。
- 規則 R1-R4 對應 K947 / audit 14 cases 的 failure modes。
- 同時支援中文（勝過/超越/主導/通過/明顯/顯著/大幅/明確）與英文 trigger word。

Public API
----------
- ``lint_conclusion(text, dm_tests=None) -> list[str]``
- ``extract_conclusion_text(payload) -> str | None``
- ``lint_results_payload(payload, *, strict=False) -> list[str]``
"""

from __future__ import annotations

import os
import re
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

# R1 trigger words: 出現代表「下了強結論」，必須有 numeric or pair backing
TRIGGER_WORDS_EN: tuple[str, ...] = (
    "Yes",
    "PASS",
    "significant",
    "dominates",
    "outperforms",
    "beats",
)

TRIGGER_WORDS_ZH: tuple[str, ...] = (
    "勝過",
    "超越",
    "主導",
    "通過",
)

# R4 vague qualifiers: 不算強 trigger，但若孤獨出現（無 numeric / pair）也要 WARN
VAGUE_QUALIFIERS_ZH: tuple[str, ...] = (
    "明顯",
    "顯著",
    "大幅",
    "明確",
)

# R3: Harvey / 嚴格統計 必須有 pair specifier
HARVEY_TRIGGERS: tuple[str, ...] = (
    "Harvey",
    "harvey",
    "嚴格統計",
)

# Numeric backing patterns (any of these in same sentence counts as backing)
_NUMERIC_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bt\s*=\s*-?\d", re.IGNORECASE),
    re.compile(r"\bt[-_]?stat\s*=\s*-?\d", re.IGNORECASE),
    re.compile(r"\bp\s*=\s*-?\d", re.IGNORECASE),
    re.compile(r"\bp[-_]?value\s*=\s*-?\d", re.IGNORECASE),
    re.compile(r"\bdm[-_ ]?(stat|t)\s*=\s*-?\d", re.IGNORECASE),
    re.compile(r"\bSharpe\s*=\s*-?\d", re.IGNORECASE),
    re.compile(r"\bQLIKE\s*=\s*-?\d", re.IGNORECASE),
    # percentage like "+13.7%" or "-2.06%"
    re.compile(r"-?\d+(\.\d+)?\s*%"),
    # ratio like "7.86x"
    re.compile(r"\b\d+(\.\d+)?\s*x\b", re.IGNORECASE),
    # explicit number followed by stat-like unit
    re.compile(r"\b\d+(\.\d+)?\s*bp\b", re.IGNORECASE),
)

# Pair patterns: explicit "<A>_vs_<B>" or "<A> vs <B>" or "K123 vs K456"
_PAIR_PATTERNS: tuple[re.Pattern[str], ...] = (
    # K123_vs_K456 or KNNN_vs_KMMM
    re.compile(r"\bK\d+[a-z0-9]*[ _]?vs[ _]?K\d+[a-z0-9]*\b", re.IGNORECASE),
    # ModelA_vs_ModelB / ModelA vs ModelB (alphanumeric, hyphen, paren etc.)
    re.compile(
        r"\b[A-Za-z][A-Za-z0-9_\-\(\)]{1,40}\s*(?:_vs_|\s+vs\.?\s+)\s*[A-Za-z][A-Za-z0-9_\-\(\)]{1,40}\b",
    ),
)


# ---------------------------------------------------------------------------
# Sentence splitting
# ---------------------------------------------------------------------------

_SENT_SPLIT_RE = re.compile(r"(?<=[\.\!\?。！？])\s+|[\r\n]+")


def _split_sentences(text: str) -> list[str]:
    """Split into sentence-ish chunks. Mixed Chinese/English friendly."""
    if not text:
        return []
    parts = [s.strip() for s in _SENT_SPLIT_RE.split(text) if s and s.strip()]
    return parts


def _has_numeric_backing(sentence: str) -> bool:
    return any(p.search(sentence) for p in _NUMERIC_PATTERNS)


def _has_pair_backing(sentence: str) -> bool:
    return any(p.search(sentence) for p in _PAIR_PATTERNS)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def _check_r1_triggers(sentences: list[str]) -> list[str]:
    """R1: trigger word ⇒ same sentence needs numeric OR pair."""
    warnings: list[str] = []
    triggers = TRIGGER_WORDS_EN + TRIGGER_WORDS_ZH
    for sent in sentences:
        for word in triggers:
            # English: word boundary ; Chinese: substring
            if word in TRIGGER_WORDS_EN:
                # case-sensitive for Yes/PASS to avoid noise on "yes" in prose
                if word in ("Yes", "PASS"):
                    if not re.search(rf"\b{re.escape(word)}\b", sent):
                        continue
                else:
                    if not re.search(rf"\b{re.escape(word)}\b", sent, re.IGNORECASE):
                        continue
            else:
                if word not in sent:
                    continue
            if _has_numeric_backing(sent) or _has_pair_backing(sent):
                continue
            warnings.append(
                f"[R1] Trigger word '{word}' lacks pair-or-numeric context: "
                f"{_truncate(sent)}"
            )
            # one warning per sentence per word is enough
            break
    return warnings


def _check_r2_dm_consistency(text: str, dm_tests: dict | None) -> list[str]:
    """R2: cross-check 'X dominates/beats Y' against dm_tests entries."""
    if not dm_tests or not isinstance(dm_tests, dict):
        return []
    warnings: list[str] = []

    # Find dominates/beats/outperforms claims with explicit pair
    claim_re = re.compile(
        r"\b([A-Za-z][A-Za-z0-9_\-\(\)]{1,40})\s+(?:dominates|beats|outperforms)\s+([A-Za-z][A-Za-z0-9_\-\(\)]{1,40})\b",
        re.IGNORECASE,
    )
    for m in claim_re.finditer(text):
        a, b = m.group(1), m.group(2)
        # Look up dm_tests for either direction
        forward_keys = (f"{a}_vs_{b}", f"{a} vs {b}")
        reverse_keys = (f"{b}_vs_{a}", f"{b} vs {a}")
        forward = _lookup_dm(dm_tests, forward_keys)
        reverse = _lookup_dm(dm_tests, reverse_keys)
        if forward is None and reverse is None:
            continue  # no entry, nothing to cross-check
        # DM stats in this repo are loss differentials (loss1 - loss2).
        # For "A_vs_B": negative t → loss_A < loss_B → A wins.
        # For reverse "B_vs_A": positive t → loss_B > loss_A → A wins.
        t_stat = None
        a_wins_per_dm: bool | None = None
        if forward is not None:
            t_stat = _extract_t_stat(forward)
            if t_stat is not None:
                # loss_A - loss_B: negative t → A has lower loss → A wins
                a_wins_per_dm = t_stat < 0
        elif reverse is not None:
            t_stat = _extract_t_stat(reverse)
            if t_stat is not None:
                a_wins_per_dm = t_stat > 0  # key is B_vs_A: loss_B - loss_A; positive → A wins
        if a_wins_per_dm is False:
            warnings.append(
                f"[R2] Claim '{a} dominates/beats {b}' but DM table favors {b} "
                f"(t_stat={t_stat})"
            )
    return warnings


def _check_r3_harvey_pair(sentences: list[str]) -> list[str]:
    """R3: Harvey / 嚴格統計 mention must qualify which pair."""
    warnings: list[str] = []
    for sent in sentences:
        if not any(trig in sent for trig in HARVEY_TRIGGERS):
            continue
        if _has_pair_backing(sent):
            continue
        warnings.append(
            f"[R3] Harvey/嚴格統計 claim lacks pair specifier: {_truncate(sent)}"
        )
    return warnings


def _check_r4_vague(sentences: list[str]) -> list[str]:
    """R4: vague qualifier alone (no numeric, no pair)."""
    warnings: list[str] = []
    for sent in sentences:
        for word in VAGUE_QUALIFIERS_ZH:
            if word not in sent:
                continue
            if _has_numeric_backing(sent) or _has_pair_backing(sent):
                continue
            warnings.append(
                f"[R4] Vague qualifier '{word}' without numeric backing: "
                f"{_truncate(sent)}"
            )
            break
    return warnings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truncate(s: str, n: int = 120) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _lookup_dm(dm_tests: dict, keys: Iterable[str]) -> Any:
    for k in keys:
        if k in dm_tests:
            return dm_tests[k]
        # case-insensitive fallback
        for actual in dm_tests:
            if actual.lower() == k.lower():
                return dm_tests[actual]
    return None


def _extract_t_stat(entry: Any) -> float | None:
    if isinstance(entry, dict):
        for k in ("t_stat", "dm_stat", "t", "stat", "tstat"):
            if k in entry:
                try:
                    return float(entry[k])
                except (TypeError, ValueError):
                    return None
    if isinstance(entry, (int, float)):
        return float(entry)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def lint_conclusion(
    conclusion: str | None,
    dm_tests: dict | None = None,
) -> list[str]:
    """Lint a conclusion string. Returns list of warnings (empty = clean).

    Parameters
    ----------
    conclusion:
        The conclusion text. May be ``None`` (treated as empty → no warnings).
    dm_tests:
        Optional dict keyed by ``"<A>_vs_<B>"`` with ``t_stat`` / ``dm_stat``
        fields. Used by R2 cross-check.
    """
    if conclusion is None:
        return []
    if not isinstance(conclusion, str):
        # tolerate dict-style conclusion accidentally passed in
        try:
            import json as _json

            conclusion = _json.dumps(conclusion, ensure_ascii=False)
        except Exception:
            return []
    text = conclusion
    sentences = _split_sentences(text)

    warnings: list[str] = []
    warnings.extend(_check_r1_triggers(sentences))
    warnings.extend(_check_r2_dm_consistency(text, dm_tests))
    warnings.extend(_check_r3_harvey_pair(sentences))
    warnings.extend(_check_r4_vague(sentences))
    return warnings


def extract_conclusion_text(payload: Any) -> str | None:
    """Extract a string conclusion from a results.json payload.

    Looks at common fields: ``conclusion``, ``conclusions``, ``main_finding``,
    ``interpretation``, ``verdict``. If the value is a dict, its values are
    flattened and joined; if a list, joined by newlines.
    """
    if not isinstance(payload, dict):
        return None
    pieces: list[str] = []
    for key in ("conclusion", "conclusions", "main_finding", "interpretation", "verdict"):
        if key in payload:
            pieces.append(_flatten_to_text(payload[key]))
    text = "\n".join(p for p in pieces if p).strip()
    return text or None


def _flatten_to_text(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, (int, float, bool)):
        return str(val)
    if isinstance(val, list):
        return "\n".join(_flatten_to_text(v) for v in val if v is not None)
    if isinstance(val, dict):
        return "\n".join(_flatten_to_text(v) for v in val.values() if v is not None)
    return str(val)


def lint_results_payload(payload: Any, *, strict: bool | None = None) -> list[str]:
    """Lint a full results.json payload.

    If ``strict=True`` (or env var ``VOLPRED_LINT_STRICT=1``) and warnings ≥ 1,
    raises ``ValueError``. Otherwise returns warnings list.
    """
    if strict is None:
        strict = os.environ.get("VOLPRED_LINT_STRICT", "").strip() in ("1", "true", "True", "yes")

    text = extract_conclusion_text(payload)
    if text is None:
        return []

    dm_tests: dict | None = None
    if isinstance(payload, dict):
        candidate = payload.get("dm_tests") or payload.get("dm_table")
        if isinstance(candidate, dict):
            dm_tests = candidate

    warnings = lint_conclusion(text, dm_tests)
    if strict and warnings:
        raise ValueError(
            "conclusion_lint strict mode: "
            f"{len(warnings)} warning(s) found:\n  - "
            + "\n  - ".join(warnings)
        )
    return warnings
