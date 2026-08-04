"""pytest plugin: record which repo paths under storage/ the suite really opens.

Static grep cannot answer "does any test read this file". A test reaches a repo
path through a module-level default (`report_sections.NEXT_TASKS_PATH`), a
config pointer, or a glob it never spells out — none of which grep sees. An
audit hook sees the syscall no matter how the path was spelled, so this is the
evidence `.github/workflows/pytest.yml`'s paths-ignore is checked against.

Relative paths resolve against the CURRENT working directory, so a test that
does `monkeypatch.chdir(tmp_path)` and opens "storage/x.json" correctly does
NOT count — only reads still rooted at the repo do.

Run it against a full suite, then freeze the result:

    VOLPRED_PROBE_REPO="$PWD" VOLPRED_PROBE_OUT=/tmp/hits.txt PYTHONPATH=scripts \\
      uv run --extra dev pytest -q -p no:randomly -p ci_storage_read_probe
    uv run python scripts/audit_ci_paths_ignore.py freeze --hits /tmp/hits.txt

`scripts/` is not a package, hence PYTHONPATH rather than a dotted -p name.

Output is one `<repo-relative path>\\t<test nodeid>` per line.
"""
from __future__ import annotations

import atexit
import os
import sys

_REPO = os.environ["VOLPRED_PROBE_REPO"].rstrip("/")
_OUT = os.environ["VOLPRED_PROBE_OUT"]
_PREFIX = _REPO + "/storage/"

_hits: set[str] = set()
_writing = False
_current = "<import/collection>"


def _record(raw) -> None:
    # This runs inside the syscall. Anything expensive or re-entrant here
    # (including another open) deadlocks or recurses — keep it to string work
    # and a set insert.
    if _writing or not isinstance(raw, str):
        return
    if raw.startswith("/"):
        path = raw
    elif raw.startswith("storage/") or raw.startswith("./storage/"):
        path = os.path.join(os.getcwd(), raw)
    else:
        return
    path = os.path.normpath(path)
    if path.startswith(_PREFIX):
        _hits.add(path[len(_REPO) + 1:] + "\t" + _current)


def _hook(event: str, args) -> None:
    if event == "open":
        _record(args[0])
    elif event in ("os.listdir", "os.scandir", "glob.glob"):
        if args:
            _record(args[0])


def _flush() -> None:
    global _writing
    _writing = True
    with open(_OUT, "w", encoding="utf-8") as fh:
        for line in sorted(_hits):
            fh.write(line + "\n")


def pytest_runtest_protocol(item, nextitem):  # noqa: ARG001
    global _current
    _current = item.nodeid
    return None


atexit.register(_flush)
sys.addaudithook(_hook)
