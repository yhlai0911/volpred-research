"""Single owner for files whose bytes an experiment review must certify.

Claims reach readers through code, prose, frozen result records, and rendered
figures.  Keeping this predicate in one stdlib-only module lets both the merge
certification gate and the nested-DM third-role receipt discover exactly the
same surface without importing one another.
"""

from __future__ import annotations

from pathlib import Path


READER_FACING_FIGURE_SUFFIXES = frozenset(
    {".gif", ".jpeg", ".jpg", ".pdf", ".png", ".svg", ".webp"}
)


def is_experiment_claim_surface_file(path: Path) -> bool:
    """Return whether ``path`` can carry a reader-facing experiment claim."""
    return (
        path.suffix == ".py"
        or path.name == "README.md"
        or path.name.endswith("_results.json")
        or path.suffix.lower() in READER_FACING_FIGURE_SUFFIXES
    )
