"""Semantic duplicate detection for storage/next_tasks.json.

Why this exists
---------------
``scripts/dedupe_next_tasks.py`` only groups by **exact task id**, so it reported
``before=3242 / after=3242 / dropped=0`` on a queue that visibly contained the
same bug filed twice:

- ``assign_614e70ee`` 13:38 「修 check_alerts NameError：_ci_incident_store_sync 未定義」
- ``assign_1d936f52`` 13:53 「[P1 回歸] check_alerts.py 呼叫 _ci_incident_store_sync 但該函式不存在」

Same file, same symbol, same failure class, 15 minutes apart, two ids.

Algorithm (one sentence)
------------------------
Extract a normalized signature — ``{files, symbols, failure_class, rare_ids,
topics}`` — from title+description, then declare two tasks duplicates only when
their **titles** share an anchor (a file / symbol / topic that both titles name)
**and** their bodies corroborate it with enough shared evidence.

The title anchor is the false-positive brake. Without it, a meta-task that merely
*quotes* another ticket (e.g. ``assign_de13fd1b`` quotes ``_ci_incident_store_sync``
as an example of duplication) would be merged into the ticket it quotes. Boss rule:
寧可漏報不可誤報 — a wrong merge costs far more than a missed pair.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable

__all__ = [
    "TaskSignature",
    "extract_signature",
    "signature_key",
    "duplicate_verdict",
    "is_duplicate",
    "find_duplicate_groups",
    "find_semantic_duplicate",
    "is_dedupe_exempt",
    "OPEN_STATUSES",
    "DUP_SCORE_THRESHOLD",
]

#: only open work can be a duplicate target — a closed ticket is history, and
#: re-filing the same failure after it was closed is a legitimate new report.
OPEN_STATUSES = frozenset({"pending", "pending_main_thread", "claimed", "in_progress"})

# ---------------------------------------------------------------------------
# normalization
# ---------------------------------------------------------------------------

#: tag prefixes that carry no semantics: "[P1 回歸]", "[老闆直令 立即]", "【1】"
_TAG_PREFIX_RE = re.compile(r"^\s*(?:[\[【(（]\s*[^\]】)）]{0,24}\s*[\]】)）]\s*)+")
#: ISO dates / times / compact dates that differ between two filings of one bug
_DATE_RE = re.compile(
    r"\b(?:20\d{2}[-/]\d{1,2}[-/]\d{1,2}|20\d{6}|\d{1,2}:\d{2}(?::\d{2})?)\b"
)

_FILE_EXTS = (
    "py|sh|ts|tsx|js|jsx|json|jsonl|md|tex|bib|yml|yaml|toml|ini|cfg|sql|csv|html|css"
)
_FILE_RE = re.compile(rf"\b([\w][\w./+-]*\.(?:{_FILE_EXTS}))\b", re.IGNORECASE)

#: `_snake_case` private helpers and multi-underscore identifiers
_SNAKE_RE = re.compile(r"\b(_[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+|[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+){2,})\b")
#: CamelCase class-ish names (>=2 humps, avoids ordinary capitalized words)
_CAMEL_RE = re.compile(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b")
#: anything the author bothered to backtick
_BACKTICK_RE = re.compile(r"`([^`\n]{2,80})`")

#: long hyphen/underscore separated identifiers, worktree/branch names, hex blobs.
#: These are the "rare id" evidence class: two tickets naming the same
#: ``dispatch-slot-1-20b291d5-snapdup`` are almost certainly about the same thing.
_RARE_ID_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+){2,})\b")
_HEXID_RE = re.compile(r"\b([0-9a-f]{7,40})\b")

#: task-id self references — never evidence (a ticket quoting another ticket's id
#: is discussing it, not duplicating it)
_TASK_ID_RE = re.compile(r"\b(?:assign|task|telegram|wsb|phase)[-_][A-Za-z0-9_-]+\b", re.IGNORECASE)

#: failure classes, in priority order — first hit wins
_FAILURE_CLASSES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("nameerror", ("nameerror", "未定義", "not defined", "沒有定義", "該函式不存在", "函式不存在", "undefined symbol")),
    ("importerror", ("importerror", "modulenotfounderror", "import error", "無法 import", "匯入失敗")),
    ("attributeerror", ("attributeerror", "has no attribute")),
    ("typeerror", ("typeerror",)),
    ("keyerror", ("keyerror",)),
    ("valueerror", ("valueerror",)),
    ("filenotfound", ("filenotfounderror", "no such file", "檔案不存在", "找不到檔案")),
    ("timeout", ("timeout", "timed out", "逾時", "超時", "卡住不動")),
    ("permission", ("permissionerror", "permission denied", "權限不足")),
    ("crash", ("traceback", "exit 1", "crash", "崩掉", "崩潰", "停擺", "整條掛")),
    ("regression", ("regression", "回歸", "退化", "本來會現在不會")),
    ("test_failure", ("測試全紅", "全紅", "test failure", "pytest 失敗", "測試失敗", "紅燈")),
    ("data_stale", ("資料落後", "沒更新", "stale", "陳舊", "卡在舊日期")),
    ("duplicate", ("重複單", "語意重複", "duplicate task", "去重")),
    ("leak", ("memory leak", "洩漏", "膨脹")),
)

#: domain topics — the CJK-friendly anchor vocabulary. CJK has no word
#: boundaries, so a curated keyword list beats naive tokenization.
_TOPICS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("worktree", ("worktree", "工作樹", "wt/")),
    ("merge", ("merge_worktree", "合併", "收割", "merge")),
    ("commit", ("commit", "提交", "git push", "推送")),
    ("alert", ("alert", "警報", "check_alerts", "告警")),
    ("dedupe", ("dedupe", "去重", "重複單", "語意重複", "duplicate")),
    ("dispatch", ("dispatch", "派工", "排班", "認領", "claim")),
    ("task_pool", ("task_pool", "任務池", "next_tasks", "佇列", "queue")),
    ("paper", ("論文", "paper", "投稿", "arxiv", "期刊")),
    ("feed", ("feed", "發佈", "文章", "publish", "貼文")),
    ("incident", ("incident", "事故", "故障")),
    ("cron", ("cron", "排程", "schedule")),
    ("ci", ("ci ", "ci-", "ci_", "持續整合")),
    ("memory", ("knowledge.json", "記憶", "memory", "thinking_journal")),
    ("experiment", ("實驗", "experiment", "qlike", "garch", "har-rv", "波動率")),
    ("telegram", ("telegram", "電報")),
    ("email", ("gmail", "email", "郵件", "寄信")),
    ("frontend", ("frontend", "ui", "ux", "前端", "頁面")),
    ("deploy", ("deploy", "zeabur", "部署")),
    ("test", ("pytest", "測試", "test")),
    ("worktree_gc", ("gc job", "回收", "清理", "cleanup")),
)

#: score needed to call two tasks duplicates (see duplicate_verdict)
DUP_SCORE_THRESHOLD = 5


#: CJK chars are word characters to `re`, so `\b` never fires between "ai" and
#: "變現" — which silently truncated identifiers like
#: `trending_repost_2026_07_17_ai變現` and made template siblings look identical.
_CJK_RUN_RE = re.compile(r"([　-〿㐀-䶿一-鿿豈-﫿]+)")


def _normalize_text(text: str, *, strip_tags: bool = True) -> str:
    """Lowercase, NFKC-fold, strip tag prefixes and dates, isolate CJK runs.

    ``strip_tags=False`` keeps the leading ``[...]`` tag. Callers scoring token
    similarity want the tag gone (it is template boilerplate); callers mining
    *discriminators* must not, because the tag is where a whole family of titles
    keeps its only distinguishing id — see ``_extract_targets``.
    """
    text = unicodedata.normalize("NFKC", str(text or ""))
    if strip_tags:
        text = _TAG_PREFIX_RE.sub("", text)
    text = _DATE_RE.sub(" ", text)
    text = _CJK_RUN_RE.sub(r" \1 ", text)
    return text.lower()


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _extract_files(text: str) -> set[str]:
    # basename only: "scripts/check_alerts.py" ≡ "check_alerts.py"
    return {_basename(m.group(1)) for m in _FILE_RE.finditer(text)}


def _extract_symbols(text: str) -> set[str]:
    out: set[str] = set()
    for m in _BACKTICK_RE.finditer(text):
        inner = m.group(1).strip()
        # backticked code spans often contain a symbol; mine them recursively
        out |= {s.lower() for s in _SNAKE_RE.findall(inner)}
        out |= {s.lower() for s in _CAMEL_RE.findall(inner)}
    out |= {s.lower() for s in _SNAKE_RE.findall(text)}
    out |= {s.lower() for s in _CAMEL_RE.findall(text)}
    # a bare filename stem is a file, not a symbol
    files = {_basename(f).split(".")[0] for f in _extract_files(text)}
    return {s for s in out if s not in files and len(s) >= 5}


def _extract_rare_ids(text: str) -> set[str]:
    out: set[str] = {m.group(1).lower() for m in _RARE_ID_RE.finditer(text) if len(m.group(1)) >= 12}
    out |= {m.group(1).lower() for m in _HEXID_RE.finditer(text) if len(m.group(1)) >= 7}
    # drop ticket-id self references and file-ish tokens
    out = {t for t in out if not _TASK_ID_RE.fullmatch(t)}
    out -= {_basename(f).split(".")[0] for f in _extract_files(text)}
    return out


#: knowledge-entry / experiment target ids: K1319, k1592, paper9, mile_903fd2cf
#: The optional ``_v<n>`` is load-bearing, not cosmetic: ``_`` is a word char to
#: ``re``, so a bare ``k\d{3,5}\b`` never fires inside ``k1095_v3`` and the
#: versioned remediation of an experiment extracted NO target at all — the same
#: blind spot as the stripped tag prefix, one level down.
_TARGET_RE = re.compile(r"\b(k\d{3,5}(?:_v\d+)?|paper\d{1,2}|mile_[0-9a-f]{6,})\b")


def _extract_targets(text: str) -> set[str]:
    """Concrete things a title points at — the template-collision discriminator.

    A generator that emits one ticket per knowledge entry produces titles that
    differ only here (``[snapshot-dup 修正/HIGH] k1319`` vs ``... k1592``) while
    their bodies share every file, symbol and failure class. Without this,
    template siblings score as duplicates of each other.
    """
    out = _extract_files(text) | _extract_symbols(text) | _extract_rare_ids(text)
    out |= {m.group(1) for m in _TARGET_RE.finditer(text)}
    out |= {m.group(0) for m in _GLUED_IDENT_RE.finditer(text)}
    return out


#: identifiers whose slot value is CJK glued on by underscore
#: (``trending_repost_2026_07_17_債市波動度``). Must run on text where CJK runs
#: have NOT been split out, hence the separate pass.
_GLUED_IDENT_RE = re.compile(r"[A-Za-z]\w*(?:_\w+){2,}", re.UNICODE)


def _title_slots(raw_title: str) -> set[str]:
    """Slot values of a machine-generated ``prefix:slot:slot`` title.

    ``[dreaming] repeated_tool_failure:release_settings_audit.log:exit1`` and
    ``...:dispatch_supervisor:killed_timeout:exit143`` share the generator prefix
    and nothing else. Comparing everything after the first colon separates the
    template from the subject — including CJK slot values, which no ASCII
    identifier regex can see.
    """
    text = unicodedata.normalize("NFKC", str(raw_title or ""))
    text = _TAG_PREFIX_RE.sub("", text).lower()
    if ":" not in text:
        return set()
    tail = text.split(":", 1)[1]
    return {tok for tok in re.split(r"[\s:,;、，。()（）\[\]【】]+", tail) if len(tok) >= 3}


def _extract_failure_class(text: str) -> str:
    for name, needles in _FAILURE_CLASSES:
        if any(n in text for n in needles):
            return name
    return ""


def _extract_topics(text: str) -> set[str]:
    return {name for name, needles in _TOPICS if any(n in text for n in needles)}


@dataclass(frozen=True)
class TaskSignature:
    """Normalized semantic fingerprint of one task."""

    task_id: str = ""
    files: frozenset[str] = field(default_factory=frozenset)
    symbols: frozenset[str] = field(default_factory=frozenset)
    failure_class: str = ""
    rare_ids: frozenset[str] = field(default_factory=frozenset)
    topics: frozenset[str] = field(default_factory=frozenset)
    #: same components restricted to the **title** — the anti-false-positive anchor
    title_files: frozenset[str] = field(default_factory=frozenset)
    title_symbols: frozenset[str] = field(default_factory=frozenset)
    title_topics: frozenset[str] = field(default_factory=frozenset)
    title_tokens: frozenset[str] = field(default_factory=frozenset)
    #: concrete targets named in the title (files/symbols/rare ids/K-numbers).
    #: Two titles with non-empty but **disjoint** target sets are about different
    #: things even when a template makes their bodies read alike.
    title_targets: frozenset[str] = field(default_factory=frozenset)
    #: for machine-generated ``prefix:slot1:slot2`` titles, the slot values —
    #: the part a generator varies per item.
    title_slots: frozenset[str] = field(default_factory=frozenset)

    @property
    def key(self) -> str:
        """Coarse ``file+symbol+failure_class`` key, for grouping/reporting."""
        return signature_key(self)

    @property
    def is_empty(self) -> bool:
        return not (self.files or self.symbols or self.rare_ids or self.topics)


def _title_tokens(norm_title: str) -> frozenset[str]:
    latin = re.findall(r"[a-z0-9_./-]{3,}", norm_title)
    cjk = re.findall(r"[一-鿿]{2,}", norm_title)
    # CJK: 2-gram shingles so "收割並清理" and "清理收割" overlap
    grams: list[str] = []
    for run in cjk:
        grams.extend(run[i : i + 2] for i in range(len(run) - 1))
    return frozenset(latin) | frozenset(grams)


def extract_signature(task: dict[str, Any] | Any) -> TaskSignature:
    """Build a :class:`TaskSignature` from a task record (or a title string)."""
    if isinstance(task, str):
        title, description, task_id = task, "", ""
    else:
        title = str(task.get("title") or "")
        description = str(task.get("description") or "")
        task_id = str(task.get("id") or task.get("task_id") or "")

    n_title = _normalize_text(title)
    # Same title, tag prefix intact. Only ever read for `title_targets`: the tag
    # is boilerplate for token similarity but load-bearing for discrimination,
    # because `[K1749 collection] ...` / `[K1750 collection] ...` carry their
    # only distinguishing id there. Stripping it first made every collection
    # ticket's `title_targets` empty, so veto 1 could never fire and two
    # unrelated experiments collapsed onto their shared toolchain vocabulary
    # (check_experiment_artifacts.py, experiment_gates.py, merge_worktree.sh,
    # git_writer_lock, ...) — the better the write-up, the likelier the refusal.
    n_title_tagged = _normalize_text(title, strip_tags=False)
    n_body = f"{n_title}\n{_normalize_text(description)}"
    # CJK-glued variant of the title: identifiers whose slot value is CJK
    # (`trending_repost_2026_07_17_債市波動度`) only survive without CJK splitting.
    glued_title = unicodedata.normalize("NFKC", _TAG_PREFIX_RE.sub("", title)).lower()

    return TaskSignature(
        task_id=task_id,
        files=frozenset(_extract_files(n_body)),
        symbols=frozenset(_extract_symbols(n_body)),
        failure_class=_extract_failure_class(n_body),
        rare_ids=frozenset(_extract_rare_ids(n_body)),
        topics=frozenset(_extract_topics(n_body)),
        title_files=frozenset(_extract_files(n_title)),
        title_symbols=frozenset(_extract_symbols(n_title)),
        title_topics=frozenset(_extract_topics(n_title)),
        title_tokens=_title_tokens(n_title),
        title_targets=frozenset(_extract_targets(n_title))
        | frozenset(_extract_targets(n_title_tagged))
        | frozenset(m.group(0) for m in _GLUED_IDENT_RE.finditer(glued_title)),
        title_slots=frozenset(_title_slots(title)),
    )


def signature_key(sig: TaskSignature) -> str:
    """Human-readable ``file+symbol+failure_class`` key (report/debug aid)."""
    files = "|".join(sorted(sig.files)[:3]) or "-"
    symbols = "|".join(sorted(sig.symbols)[:3]) or "-"
    topics = "|".join(sorted(sig.topics)[:3]) or "-"
    return f"{files}::{symbols}::{sig.failure_class or '-'}::{topics}"


def _jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def duplicate_verdict(
    a: TaskSignature | dict[str, Any],
    b: TaskSignature | dict[str, Any],
    *,
    threshold: int = DUP_SCORE_THRESHOLD,
) -> dict[str, Any]:
    """Decide whether two tasks are semantic duplicates.

    Returns ``{"duplicate": bool, "score": int, "anchor": [...], "reasons": [...]}``.

    Two gates, both must pass:

    1. **Title anchor** — both *titles* must name the same file, symbol, or topic.
       This is what stops a meta/umbrella ticket that merely quotes another
       ticket's symbol from being merged into it. A *topic-only* anchor is weak
       (two tickets both mentioning "worktree" prove little), so it additionally
       requires >=2 shared rare ids or a title-token Jaccard >= 0.5.
    2. **Evidence score >= threshold** — shared symbols (3 each), shared files (2),
       shared rare ids (2 each), identical non-empty failure class (2), plus a
       title-token Jaccard fallback for tickets with no extractable file/symbol.

    And one veto: **disjoint title targets**. If both titles name concrete targets
    (files/symbols/K-numbers) and share none, they are template siblings pointing
    at different work, not duplicates — no score can override this.
    """
    if not isinstance(a, TaskSignature):
        a = extract_signature(a)
    if not isinstance(b, TaskSignature):
        b = extract_signature(b)

    shared_title_files = a.title_files & b.title_files
    shared_title_symbols = a.title_symbols & b.title_symbols
    shared_title_topics = a.title_topics & b.title_topics
    anchor = sorted(shared_title_files | shared_title_symbols | shared_title_topics)

    reasons: list[str] = []
    score = 0

    shared_symbols = a.symbols & b.symbols
    if shared_symbols:
        score += 3 * min(len(shared_symbols), 2)
        reasons.append(f"shared symbols: {sorted(shared_symbols)[:4]}")

    shared_files = a.files & b.files
    if shared_files:
        score += 2
        reasons.append(f"shared files: {sorted(shared_files)[:4]}")

    shared_rare = a.rare_ids & b.rare_ids
    if shared_rare:
        score += 2 * min(len(shared_rare), 3)
        reasons.append(f"shared rare ids: {sorted(shared_rare)[:4]}")

    if a.failure_class and a.failure_class == b.failure_class:
        score += 2
        reasons.append(f"same failure_class: {a.failure_class}")

    title_j = _jaccard(a.title_tokens, b.title_tokens)
    if title_j >= 0.60:
        # secondary criterion for tickets with no extractable file/symbol
        score += 5
        reasons.append(f"title token jaccard={title_j:.2f}")
    elif title_j >= 0.40:
        score += 2
        reasons.append(f"title token jaccard={title_j:.2f}")

    # veto 1: each title names a concrete target the other does not.
    #
    # Compare the *distinguishing* targets, not raw disjointness: a generator
    # emits "[dreaming] missing_retry_strategy:<X>" per item, so every sibling
    # shares the template prefix `missing_retry_strategy` while <X> is the real
    # subject. Shared prefix + different subject = different work.
    only_a = a.title_targets - b.title_targets
    only_b = b.title_targets - a.title_targets
    target_veto = bool(only_a) and bool(only_b)

    # veto 1b: machine-generated `prefix:slot` titles whose slot values are
    # entirely different subjects (catches CJK-only slots that no ASCII
    # identifier regex can see).
    slot_veto = (
        bool(a.title_slots)
        and bool(b.title_slots)
        and not (a.title_slots & b.title_slots)
    )
    if slot_veto:
        target_veto = True
        reasons.append(
            f"VETO disjoint title slots: {sorted(a.title_slots)[:3]} vs "
            f"{sorted(b.title_slots)[:3]}"
        )
    # veto 2: the only thing the titles share is a topic — too weak alone
    strong_anchor = bool(shared_title_files | shared_title_symbols)
    weak_anchor_ok = (
        strong_anchor or len(shared_rare) >= 2 or title_j >= 0.50
    )

    duplicate = (
        bool(anchor)
        and score >= threshold
        and not (a.is_empty or b.is_empty)
        and not target_veto
        and weak_anchor_ok
    )
    if not anchor:
        reasons.append("no shared title anchor -> not duplicate (false-positive brake)")
    if target_veto and not slot_veto:
        reasons.append(
            f"VETO distinguishing title targets: {sorted(only_a)[:3]} vs "
            f"{sorted(only_b)[:3]} (template siblings, different work)"
        )
    elif not weak_anchor_ok:
        reasons.append(
            f"VETO topic-only anchor {anchor} with weak corroboration "
            f"(shared_rare={len(shared_rare)}, title_jaccard={title_j:.2f})"
        )

    return {
        "duplicate": duplicate,
        "score": score,
        "threshold": threshold,
        "anchor": anchor,
        "reasons": reasons,
        "a_key": a.key,
        "b_key": b.key,
        "a_id": a.task_id,
        "b_id": b.task_id,
    }


def is_duplicate(a, b, *, threshold: int = DUP_SCORE_THRESHOLD) -> bool:
    return bool(duplicate_verdict(a, b, threshold=threshold)["duplicate"])


#: date / timestamp components inside a task id
_ID_DATE_RE = re.compile(r"(20\d{6}t?\d*z?|\d{4}[-_]\d{2}[-_]\d{2})", re.IGNORECASE)


def is_recurrence_pair(id_a: str, id_b: str) -> bool:
    """True when two ids are the *same* scheduled job on different dates.

    ``daily_digest_20260719`` / ``daily_digest_20260721`` and
    ``alert_host_cron_fail_20260719`` / ``..._20260720`` normalize to identical
    text once the date is removed. Signature comparison deliberately strips dates
    (so one bug filed on two days still matches), which makes every recurrence of
    a scheduled job look like a duplicate of the previous one. It is not: today's
    digest is not yesterday's digest.
    """
    a, b = str(id_a or ""), str(id_b or "")
    if not a or not b or a == b:
        return False
    sa, sb = _ID_DATE_RE.sub("", a.lower()), _ID_DATE_RE.sub("", b.lower())
    return sa == sb and (sa != a.lower() or sb != b.lower())


def is_dedupe_exempt(record: dict[str, Any]) -> bool:
    """Records the semantic gate must never block.

    Reuses ``task_urgency``'s existing owner lists rather than starting a second
    source-of-truth: dedicated-owner ingress (telegram_reply / email_reply) and
    time-critical types legitimately re-file near-identical text (the same boss
    asking the same thing twice is two obligations, not one duplicate), and they
    already carry their own external-contract dedupe ids. ``dedupe_exempt: true``
    is the explicit caller escape hatch.
    """
    if record.get("dedupe_exempt"):
        return True
    try:
        from volpred.ops import task_urgency
    except Exception:  # pragma: no cover - silent-ok: defensive import probe; absent module means "no exemption list", fail-closed to False
        return False
    task_type = record.get("task_type")
    return bool(
        task_type in getattr(task_urgency, "DEDICATED_OWNER_TASK_TYPES", ())
        or task_type in getattr(task_urgency, "TIME_CRITICAL_TASK_TYPES", ())
    )


def find_semantic_duplicate(
    record: dict[str, Any],
    tasks: list[Any],
    *,
    threshold: int = DUP_SCORE_THRESHOLD,
) -> dict[str, Any] | None:
    """Return the verdict against the first *open* task ``record`` duplicates.

    Admission-gate entry point used by ``append_task_record``. Returns ``None``
    when the record is exempt, has no extractable signature, or matches nothing.
    """
    if is_dedupe_exempt(record):
        return None
    sig = extract_signature(record)
    if sig.is_empty:
        return None
    record_id = str(record.get("id") or "")
    best: dict[str, Any] | None = None
    for existing in tasks:
        if not isinstance(existing, dict):
            continue
        existing_id = str(existing.get("id") or existing.get("task_id") or "")
        if existing_id == record_id:
            continue
        if str(existing.get("status") or "").lower() not in OPEN_STATUSES:
            continue
        if is_dedupe_exempt(existing) or is_recurrence_pair(record_id, existing_id):
            continue
        verdict = duplicate_verdict(sig, extract_signature(existing), threshold=threshold)
        if verdict["duplicate"] and (best is None or verdict["score"] > best["score"]):
            best = verdict
            best["existing_id"] = str(existing.get("id") or "")
            best["existing_title"] = str(existing.get("title") or "")
            best["existing_status"] = str(existing.get("status") or "")
    return best


def find_duplicate_groups(
    tasks: list[dict[str, Any]],
    *,
    threshold: int = DUP_SCORE_THRESHOLD,
) -> list[dict[str, Any]]:
    """Cluster ``tasks`` into semantic-duplicate groups (greedy cliques).

    Clustering is **clique-based, not transitive**. Union-find would let one
    vague ticket that matches two mutually-vetoed tickets chain them into a
    single bogus group (observed: a 7-ticket "group" whose members were seven
    different subjects sharing a generator prefix). Here a ticket joins a group
    only if it is judged duplicate against *every* current member.

    Returns one dict per group of size >= 2: ``{"keep", "merge", "members",
    "pairs"}``. ``keep`` is the earliest-created member (the original filing).
    """
    sigs = [extract_signature(t) for t in tasks]
    # same exemptions the admission gate honours — otherwise every boss Telegram
    # reply ticket looks like a duplicate of every other one
    skip = [
        sigs[i].is_empty or is_dedupe_exempt(tasks[i]) for i in range(len(tasks))
    ]

    pairs: list[dict[str, Any]] = []
    adj: dict[int, set[int]] = {i: set() for i in range(len(tasks))}
    for i in range(len(tasks)):
        if skip[i]:
            continue
        for j in range(i + 1, len(tasks)):
            if skip[j] or is_recurrence_pair(sigs[i].task_id, sigs[j].task_id):
                continue
            verdict = duplicate_verdict(sigs[i], sigs[j], threshold=threshold)
            if verdict["duplicate"]:
                pairs.append(verdict)
                adj[i].add(j)
                adj[j].add(i)

    # greedy cliques, strongest pair first
    ordered_pairs = sorted(pairs, key=lambda p: -p["score"])
    assigned: set[int] = set()
    id_to_index = {str(tasks[i].get("id") or ""): i for i in range(len(tasks))}
    clusters: list[list[int]] = []
    for p in ordered_pairs:
        i, j = id_to_index.get(p["a_id"], -1), id_to_index.get(p["b_id"], -1)
        if i < 0 or j < 0 or i in assigned or j in assigned:
            continue
        clique = [i, j]
        assigned.update(clique)
        for k in sorted(adj[i] & adj[j]):
            if k in assigned:
                continue
            if all(k in adj[m] for m in clique):
                clique.append(k)
                assigned.add(k)
        clusters.append(clique)

    groups: list[dict[str, Any]] = []
    for members in clusters:
        if len(members) < 2:
            continue
        members.sort(key=lambda i: str(tasks[i].get("created_at") or ""))
        keep = members[0]
        member_ids = {str(tasks[i].get("id") or "") for i in members}
        groups.append(
            {
                "keep": tasks[keep],
                "keep_id": str(tasks[keep].get("id") or ""),
                "merge": [tasks[i] for i in members[1:]],
                "merge_ids": [str(tasks[i].get("id") or "") for i in members[1:]],
                "members": [tasks[i] for i in members],
                "signature": sigs[keep].key,
                "pairs": [p for p in pairs if p["a_id"] in member_ids and p["b_id"] in member_ids],
            }
        )
    groups.sort(key=lambda g: -len(g["members"]))
    return groups
