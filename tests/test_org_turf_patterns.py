"""Declared ownership must survive the trip into permissions.

`generate_dept_settings` turns a department's registry `owned_paths` into the
Edit/Write patterns that make the declaration real. Twice on 2026-08-05 a grant
that read as correct denied every write:

* Everything was treated as a directory and given `/**`, so a declaration that
  names a file — `scripts/gen_*_article_charts.py`, `storage/org/policy.md` —
  became `...py/**`, a pattern that matches nothing. The registry said the
  department owned the file; the settings said it owned a directory that does
  not exist; the department was told "denied" with nothing to go on.
* `**` does not cross a segment beginning with a dot in most glob
  implementations, so owning `frontend-v2-fix/` still did not permit
  `frontend-v2-fix/.claude/no-session-lock` — a file inside that department's
  own turf which the manager had just approved (D51).

Both failures share a shape worth naming: **the grant existed and looked right**.
Nothing was missing from the registry, no rule denied anything, and no error was
raised. Only the translation was wrong, and a translation bug in a permission
system presents as "you do not have permission" — which sends the reader to
argue about policy instead of to read the pattern.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ORG_DIR = Path(__file__).resolve().parents[1] / "scripts" / "org"


@pytest.fixture(scope="module")
def attach():
    sys.path.insert(0, str(ORG_DIR))
    spec = importlib.util.spec_from_file_location(
        "org_attach_under_test", ORG_DIR / "org_attach.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_a_declared_file_stays_a_file(attach):
    patterns = attach.turf_patterns(["scripts/gen_*_article_charts.py"])

    assert patterns == ["scripts/gen_*_article_charts.py"], (
        "appending /** to a filename produces a pattern that matches nothing, "
        "which reads as a policy refusal instead of the translation bug it is"
    )


def test_a_declared_file_without_a_glob_too(attach):
    assert attach.turf_patterns(["storage/org/policy.md"]) == ["storage/org/policy.md"]


def test_a_directory_still_covers_its_whole_tree(attach):
    patterns = attach.turf_patterns(["config/"])

    assert "config/**" in patterns


def test_a_directory_also_covers_its_dot_entries(attach):
    patterns = attach.turf_patterns(["frontend-v2-fix/"])

    assert "frontend-v2-fix/.*" in patterns, "a dot file inside owned turf is owned"
    assert "frontend-v2-fix/.*/**" in patterns, (
        "and so is everything under a dot directory — D51's no-session-lock lives "
        "at frontend-v2-fix/.claude/no-session-lock"
    )


def test_a_trailing_slash_is_not_required(attach):
    with_slash = attach.turf_patterns(["scripts/"])
    without = attach.turf_patterns(["scripts"])

    assert with_slash == without, (
        "registry entries are hand-written; the two spellings must not grant "
        "different things"
    )


def test_blank_declarations_are_dropped_not_turned_into_root_access(attach):
    assert attach.turf_patterns(["", "   "]) == []


def test_the_real_registry_still_yields_usable_patterns(attach):
    """A guard against the whole thing degenerating into empty or root patterns."""
    patterns = attach.turf_patterns(["storage/org/departments/content/", "storage/drafts/"])

    assert patterns, "a department with declared turf must end up with patterns"
    assert all(p and not p.startswith("/") for p in patterns), (
        "patterns are joined onto REPO_ROOT by the caller; a leading slash here "
        "would silently widen the grant to the filesystem root"
    )
