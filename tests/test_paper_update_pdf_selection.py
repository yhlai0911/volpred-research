"""Paper artifact selection, under the declared-identity contract.

Rewritten 2026-08-04. These tests used to pin mtime-based selection ("newest
main_v<N> wins"), which was the third incarnation of the bug that shipped a stale
manuscript to readers three times. Identity is now declared in
`paper/<id>/canonical.json` and resolved by `resolve_canonical_manuscript`; the
selection invariants that were always real -- metrics come from the *current*
tex/pdf, page-count failure is reported, author parsing spans the \and form --
are kept here and re-expressed against the declaration.

The old mtime assertions are deliberately not kept alongside. Two live selection
rules is how the versions diverged in the first place.
"""

from __future__ import annotations

import json
import subprocess

from PyPDF2 import PdfWriter

from volpred.ops.papers import CANONICAL_DECL_NAME
from volpred.ops.papers import PAPER_FRONTEND_SLUGS
from volpred.ops.papers import _count_tex_metrics
from volpred.ops.papers import _select_current_main_artifact


def _declare(paper_dir, main_tex: str) -> None:
    (paper_dir / CANONICAL_DECL_NAME).write_text(
        json.dumps({"main_tex": main_tex}), encoding="utf-8"
    )


def test_garch_x_vix_has_configured_frontend_slug():
    assert PAPER_FRONTEND_SLUGS["garch-x-vix"] == "garch-x-vix.pdf"


def _write_blank_pdf(path, pages):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    with path.open("wb") as f:
        writer.write(f)


def test_declaration_beats_a_stale_version_even_when_the_stale_one_is_newer(tmp_path):
    """The 2026-08-04 shape: main_v3.pdf left behind by an archive that moved
    only the .tex, then winning on mtime for 34 days."""
    (tmp_path / "main.tex").write_text("x")
    (tmp_path / "main_v3.tex").write_text("x")
    (tmp_path / "main.pdf").write_bytes(b"canonical")
    stale = tmp_path / "main_v3.pdf"
    stale.write_bytes(b"stale")
    _declare(tmp_path, "main.tex")

    stale.touch()  # newest by mtime, which is exactly what used to win

    assert _select_current_main_artifact(tmp_path, ".pdf") == tmp_path / "main.pdf"


def test_select_current_main_artifact_returns_none_when_missing(tmp_path):
    assert _select_current_main_artifact(tmp_path, ".pdf") is None


def test_count_tex_metrics_counts_pages_from_the_declared_main_pdf(tmp_path):
    """Title and page count must come from the same version -- Supabase showing
    one version's abstract beside another version's PDF is the reader-visible
    symptom of the split."""
    (tmp_path / "main_v3.tex").write_text(r"\title{Old}\begin{abstract}Old\end{abstract}")
    (tmp_path / "main.tex").write_text(r"\title{Current}\begin{abstract}Current\end{abstract}")
    _write_blank_pdf(tmp_path / "main_v3.pdf", 5)
    _write_blank_pdf(tmp_path / "main.pdf", 2)
    _declare(tmp_path, "main.tex")

    metrics = _count_tex_metrics(tmp_path)

    assert metrics["title"] == "Current"
    assert metrics["pages"] == 2


def test_count_tex_metrics_warns_when_page_count_fails(tmp_path, monkeypatch, capsys):
    (tmp_path / "main.tex").write_text(r"\title{Current}\begin{abstract}Current\end{abstract}")
    (tmp_path / "main.pdf").write_bytes(b"not a pdf")
    _declare(tmp_path, "main.tex")

    def fail_run(*args, **kwargs):
        raise RuntimeError("fitz missing")

    monkeypatch.setattr(subprocess, "run", fail_run)

    metrics = _count_tex_metrics(tmp_path)

    out = capsys.readouterr().out
    assert metrics["title"] == "Current"
    assert "pages" not in metrics
    assert "[papers] WARN page count failed" in out
    assert "fitz missing" in out


def test_count_tex_metrics_extracts_author_from_current_main_tex(tmp_path):
    (tmp_path / "main_v3.tex").write_text(
        r"""
        \title{Old}
        \author{Stale Author}
        \begin{abstract}Old\end{abstract}
        """
    )
    (tmp_path / "main.tex").write_text(
        r"""
        \title{Current}
        \author{
          Yi-Hao Lai\thanks{Department of Finance, example@example.com}%
          \and
          VolPred Research System\footnote{Operational research system}\\[0.25em]
        }
        \begin{abstract}Current\end{abstract}
        """
    )
    _write_blank_pdf(tmp_path / "main.pdf", 1)
    _declare(tmp_path, "main.tex")

    metrics = _count_tex_metrics(tmp_path)

    assert metrics["title"] == "Current"
    assert metrics["authors"] == "Yi-Hao Lai, VolPred Research System"


def test_any_version_number_can_be_declared(tmp_path):
    """2026-07-19 vt-trend incident: a hardcoded v2-v4 list uploaded a stale
    main_v4.pdf the day main_v5 appeared. The declaration carries no version
    vocabulary at all, so a new suffix needs no code change -- and a decoy that
    is not the declared file can never be selected however new it is."""
    for name in ("main_v4", "main_v5"):
        (tmp_path / f"{name}.tex").write_text("x")
        (tmp_path / f"{name}.pdf").write_bytes(name.encode())
    _declare(tmp_path, "main_v5.tex")

    assert _select_current_main_artifact(tmp_path, ".pdf") == tmp_path / "main_v5.pdf"

    decoy = tmp_path / "main_backup.pdf"
    decoy.write_bytes(b"decoy")
    decoy.touch()
    assert _select_current_main_artifact(tmp_path, ".pdf") == tmp_path / "main_v5.pdf"
