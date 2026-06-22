from __future__ import annotations

import os
import subprocess

from PyPDF2 import PdfWriter

from volpred.ops.papers import _count_tex_metrics
from volpred.ops.papers import _select_current_main_artifact


def _write_blank_pdf(path, pages):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    with path.open("wb") as f:
        writer.write(f)


def test_select_current_main_artifact_prefers_fresh_main_over_stale_version(tmp_path):
    old_pdf = tmp_path / "main_v3.pdf"
    new_pdf = tmp_path / "main.pdf"
    old_pdf.write_bytes(b"old")
    new_pdf.write_bytes(b"new")

    os.utime(old_pdf, (100, 100))
    os.utime(new_pdf, (200, 200))

    assert _select_current_main_artifact(tmp_path, ".pdf") == new_pdf


def test_select_current_main_artifact_returns_none_when_missing(tmp_path):
    assert _select_current_main_artifact(tmp_path, ".pdf") is None


def test_count_tex_metrics_counts_pages_from_current_main_pdf(tmp_path):
    (tmp_path / "main_v3.tex").write_text(r"\title{Old}\begin{abstract}Old\end{abstract}")
    (tmp_path / "main.tex").write_text(r"\title{Current}\begin{abstract}Current\end{abstract}")
    _write_blank_pdf(tmp_path / "main_v3.pdf", 5)
    _write_blank_pdf(tmp_path / "main.pdf", 2)

    os.utime(tmp_path / "main_v3.tex", (100, 100))
    os.utime(tmp_path / "main.tex", (200, 200))
    os.utime(tmp_path / "main_v3.pdf", (100, 100))
    os.utime(tmp_path / "main.pdf", (200, 200))

    metrics = _count_tex_metrics(tmp_path)

    assert metrics["title"] == "Current"
    assert metrics["pages"] == 2


def test_count_tex_metrics_warns_when_page_count_fails(tmp_path, monkeypatch, capsys):
    (tmp_path / "main.tex").write_text(r"\title{Current}\begin{abstract}Current\end{abstract}")
    (tmp_path / "main.pdf").write_bytes(b"not a pdf")

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

    os.utime(tmp_path / "main_v3.tex", (100, 100))
    os.utime(tmp_path / "main.tex", (200, 200))

    metrics = _count_tex_metrics(tmp_path)

    assert metrics["title"] == "Current"
    assert metrics["authors"] == "Yi-Hao Lai, VolPred Research System"
