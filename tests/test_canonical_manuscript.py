"""Which file is the paper is a declared fact, not an inferred one.

THREE-STRIKE class. Three times a stale ``main_v*`` artifact won the selection
and reached readers:

* 2026-06-11 leverage-direction -- a fixed suffix-priority list preferred
  main_v3.tex over the actively edited main.tex, publishing a superseded
  abstract.
* 2026-07-19 vt-trend-following -- the hardcoded v4/v3/v2 list uploaded a stale
  PDF the day main_v5 appeared.
* 2026-08-04 leverage-direction again -- the 2026-07-01 owner-authorised
  adjudication ruled main.tex canonical and git mv-ed the v3/v2 lines to
  _archived/, but moved only the **.tex** files. main_v3.pdf stayed behind, mtime
  selection kept choosing it, and the PDF readers downloaded was byte-identical
  to the explicitly-obsoleted v3 for 34 days -- across a scheduled refresh that
  re-picked it on 07-20.

Each earlier fix replaced one guess with a better guess. The fault is guessing:
an explicit adjudication sat in ``_archived/README.md`` and no resolver could see
it. Identity is now declared in ``paper/<id>/canonical.json``.

Two invariants carry the fix and are pinned here:

* only the tex is declared, and the PDF is derived from its stem -- so tex and
  pdf cannot name different versions (vt-insurance-cost was taking main_v1.tex
  for metrics while uploading main.pdf);
* an undeclared or unbuildable paper fails closed with the remedy printed, and
  never silently falls back to a guess.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from volpred.ops.papers import (  # noqa: E402
    CANONICAL_DECL_NAME,
    CanonicalManuscriptError,
    read_canonical_declaration,
    resolve_canonical_manuscript,
)


def _paper(tmp_path: Path, *, files: tuple[str, ...], decl: dict | None) -> Path:
    d = tmp_path / "somepaper"
    d.mkdir()
    for name in files:
        (d / name).write_text("x", encoding="utf-8")
    if decl is not None:
        (d / CANONICAL_DECL_NAME).write_text(json.dumps(decl), encoding="utf-8")
    return d


def test_declaration_wins_over_a_newer_stale_artifact(tmp_path: Path) -> None:
    """The 2026-08-04 shape: a newer v3 sitting beside the declared main."""
    d = _paper(
        tmp_path,
        files=("main.tex", "main.pdf", "main_v3.tex", "main_v3.pdf"),
        decl={"main_tex": "main.tex"},
    )
    # Make the stale pair unambiguously newer, which is what used to win.
    for name in ("main_v3.tex", "main_v3.pdf"):
        (d / name).touch()
    tex, pdf = resolve_canonical_manuscript(d)
    assert tex.name == "main.tex"
    assert pdf.name == "main.pdf"


def test_pdf_is_derived_from_the_declared_tex_stem(tmp_path: Path) -> None:
    """tex and pdf can never name different versions -- that split shipped once."""
    d = _paper(
        tmp_path,
        files=("main.tex", "main.pdf", "main_v5.tex", "main_v5.pdf"),
        decl={"main_tex": "main_v5.tex"},
    )
    tex, pdf = resolve_canonical_manuscript(d)
    assert (tex.name, pdf.name) == ("main_v5.tex", "main_v5.pdf")


def test_undeclared_paper_fails_closed_with_a_remedy(tmp_path: Path) -> None:
    """Silently guessing is what shipped the wrong manuscript three times."""
    d = _paper(tmp_path, files=("main.tex", "main.pdf", "main_v3.pdf"), decl=None)
    with pytest.raises(CanonicalManuscriptError) as err:
        resolve_canonical_manuscript(d)
    message = str(err.value)
    assert CANONICAL_DECL_NAME in message
    assert "main_tex" in message, "the error must show what to write"


def test_declared_but_unbuilt_pdf_fails_closed_with_the_build_command(tmp_path: Path) -> None:
    d = _paper(tmp_path, files=("main.tex",), decl={"main_tex": "main.tex"})
    with pytest.raises(CanonicalManuscriptError) as err:
        resolve_canonical_manuscript(d)
    assert "xelatex" in str(err.value), "the error must show how to build it"


def test_declaring_a_missing_file_is_an_error_not_a_fallback(tmp_path: Path) -> None:
    d = _paper(tmp_path, files=("main.tex", "main.pdf"), decl={"main_tex": "main_v9.tex"})
    with pytest.raises(CanonicalManuscriptError) as err:
        resolve_canonical_manuscript(d)
    assert "main_v9.tex" in str(err.value)


def test_corrupt_declaration_raises_rather_than_reverting_to_guessing(tmp_path: Path) -> None:
    """A broken declaration must be repaired, never guessed around."""
    d = _paper(tmp_path, files=("main.tex", "main.pdf"), decl=None)
    (d / CANONICAL_DECL_NAME).write_text("{not json", encoding="utf-8")
    with pytest.raises(CanonicalManuscriptError):
        read_canonical_declaration(d)


def test_empty_declaration_is_rejected(tmp_path: Path) -> None:
    d = _paper(tmp_path, files=("main.tex", "main.pdf"), decl={"reason": "forgot the file"})
    with pytest.raises(CanonicalManuscriptError):
        resolve_canonical_manuscript(d)


# --- live repo invariants -------------------------------------------------


def _declared_papers() -> list[Path]:
    return sorted(
        d for d in (ROOT / "paper").iterdir()
        if d.is_dir() and not d.name.startswith("_") and (d / CANONICAL_DECL_NAME).is_file()
    )


def test_every_declaration_in_the_repo_resolves() -> None:
    """A declaration that names a missing or unbuilt file is worse than none."""
    failures = []
    for d in _declared_papers():
        try:
            resolve_canonical_manuscript(d)
        except CanonicalManuscriptError as exc:
            failures.append(f"{d.name}: {str(exc).splitlines()[0]}")
    assert not failures, "declared papers that do not resolve:\n" + "\n".join(failures)


def test_declared_paper_folders_keep_no_rival_main_artifacts() -> None:
    """A rival main_v*.pdf beside the declared one is how v3 kept winning.

    The declaration alone would be enough for this repo's own code, but a stray
    rival is what any future tool, script or human still trips over -- the
    2026-07-01 adjudication left exactly one behind and it cost 34 days. Retire
    them to `_archived/` when the adjudication is made, not later.
    """
    strays = {}
    for d in _declared_papers():
        decl = read_canonical_declaration(d)
        keep = {Path(decl["main_tex"]).stem + ".tex", Path(decl["main_tex"]).stem + ".pdf"}
        rivals = sorted(
            p.name for p in d.glob("main_v[0-9]*.pdf") if p.name not in keep
        )
        if rivals:
            strays[d.name] = rivals
    assert not strays, (
        "rival main_v*.pdf files beside a declared manuscript: "
        f"{strays}. Move them into the paper's _archived/ folder."
    )
