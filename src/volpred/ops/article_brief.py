"""Canonical audience-specific clauses for automatically generated article briefs.

The task generators used to say only "write a general-audience article".  That
left writers to combine two incompatible global rules: keep experiment
provenance visible and avoid the signals that make Publisher classify the copy
as research.  Keep the distinction here so every generator emits the same
contract: evidence remains exact, while internal experiment identity travels in
metadata rather than reader-visible prose.
"""

from __future__ import annotations


GENERAL_AUDIENCE_BRIEF_CONTRACT = (
    "General-audience delivery contract: keep exact figures, sample/as-of/window, "
    "data source, and statistical strength, but translate the evidence into plain "
    "reader language. Do not put K-ids or bare academic terms (for example QLIKE, "
    "Diebold-Mariano/DM test, Harvey, bootstrap, p-value, t-stat, or MLE) in the "
    "reader-visible title or body. Preserve experiment provenance in frontmatter/"
    "details.experiment_refs and evidence_source_paths instead. Before completing "
    "the task, run the canonical publisher audience inference against the final "
    "title/body/tags; success requires inferred audience=general."
)


def audience_brief_contract(audience: str) -> str:
    """Return the mandatory delivery clause for an auto-generated article task."""

    if str(audience or "").strip().lower() == "general":
        return GENERAL_AUDIENCE_BRIEF_CONTRACT
    return ""
