"""Publication eligibility gate for K-experiment knowledge entries.

A reviewer can pass an experiment as *research* while explicitly withholding it
from *publication* — the verdict is `CONDITIONAL_PASS` and the condition is
"finish X before this goes to a feed article or a paper route". Nothing read
that condition. `build_publication_candidates._is_invalidated_artifact` only
catches artifacts that were outright invalidated (`codex review FAIL`,
`artifact 作廢`), so a conditionally-cleared K looked identical to a clean PASS
and flowed straight into the uncovered-K article pool.

Concrete incident (2026-07-14, hourly-08): K1684's README says 「因 gate 為 null,
**不得**據此寫 feed 或選論文路線,必須先完成 E2」 and its knowledge entry's
`codex_review` says "use limited to null and methodology knowledge; E2 required
before publication/paper routing". refill_task_pool still auto-created
`K1684_article_general`, which sat P3 in the pending pool waiting for a writer
agent. Had a fire picked it up, we would have shipped a reader-facing article
built on a result its own reviewer had ruled unpublishable — a research-honesty
breach, not merely a wasted dispatch.

Design notes
------------
Blanket-blocking every `CONDITIONAL_PASS` is not an option: 110 of 825 knowledge
entries carry that verdict and most conditions are minor (fix a caption, note a
limitation). Blocking them all would starve the article pool — the same content
black hole the arc-gate false-positive incident produced. So the gate keys on
what the reviewer actually *restricted*: a publication-scoped prohibition or
precondition, stated in the fields reviewers write (`codex_review`,
`review_notes`, `content`, `title`).

The phrase list is deliberately narrow. A false negative costs one wasted
dispatch that a human notices; a false positive silently deletes a publishable
result from the pool. When in doubt, do not add the phrase — make the reviewer
be explicit instead.
"""
from __future__ import annotations

# Phrases that scope a prohibition or a precondition to *publication*.
# Each entry must be unambiguous on its own: it may not fire on a sentence that
# merely mentions publication (e.g. "published in 2024", "publication bias").
_BLOCK_PHRASES: tuple[str, ...] = (
    # English — reviewer preconditions
    "before publication",
    "prior to publication",
    "required before publication",
    "not for publication",
    "must not publish",
    "do not publish",
    "no feed article",
    "publication blocked",
    "not publishable",
    "unpublishable",
    # 中文 — 禁令 / 前置條件
    "不得據此寫",
    "不得寫 feed",
    "不得寫feed",
    "不得發文",
    "不得發佈",
    "不得發布",
    "不得撰寫文章",
    "禁止發文",
    "禁止發佈",
    "禁止發布",
    "禁止寫 feed",
    "禁止寫feed",
    "不可發文",
    "不可發佈",
    "不可發布",
    "發佈前必須",
    "發布前必須",
)

# Fields a reviewer writes their disposition into. `evidence` and the numeric
# result fields are excluded — they quote experiment prose and would drag in
# phrases the reviewer never asserted.
_REVIEWER_FIELDS: tuple[str, ...] = (
    "title",
    "summary",
    "content",
    "codex_review",
    "review_notes",
    "reviewer",
    "disposition",
)


def publication_block_reason(entry: dict) -> str | None:
    """Return the reviewer's publication-blocking phrase, or None if clear.

    The return value is the matched phrase plus a short window of surrounding
    text, so every exclusion is auditable at the point it happens — a K that
    silently vanishes from the candidate pool is indistinguishable from a bug.
    """
    for field in _REVIEWER_FIELDS:
        raw = entry.get(field)
        if not raw:
            continue
        text = str(raw)
        lowered = text.lower()
        for phrase in _BLOCK_PHRASES:
            idx = lowered.find(phrase)
            if idx < 0:
                continue
            start = max(0, idx - 40)
            end = min(len(text), idx + len(phrase) + 60)
            excerpt = text[start:end].replace("\n", " ").strip()
            return f"{field}: …{excerpt}…"
    return None


def is_publication_blocked(entry: dict) -> bool:
    return publication_block_reason(entry) is not None


def article_ineligibility_reason(entry: dict) -> str | None:
    """Return a hard reason why a knowledge entry cannot seed an article.

    This is deliberately stricter than :func:`publication_block_reason`.
    Auto-discovery has no human in the loop to repair missing provenance, so a
    failed review, an empty evidence field, or an unresolved human-review flag
    must stop the task before it enters the reader-facing queue.
    """
    verdict = str(entry.get("verdict") or "").strip().upper()
    if verdict.startswith("FAIL_"):
        return f"knowledge verdict={verdict}"
    if not entry.get("evidence"):
        return "knowledge evidence is empty"
    if entry.get("needs_human") is True:
        return "knowledge needs_human=true"
    return publication_block_reason(entry)


def is_article_eligible(entry: dict) -> bool:
    """Whether an entry may automatically seed a reader-facing article."""
    return article_ineligibility_reason(entry) is None
