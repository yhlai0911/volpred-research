"""The bounded CLI wrappers embed python in a single-quoted bash -c block.

Regression for 2026-08-04: an apostrophe inside a python comment ("the
contract's forbidden auth variables") terminated the bash single-quoted string
in scripts/codex_exec_bounded.sh. The -c program was truncated mid-code, the
following words became argv, and every codex call died with
``ValueError: could not convert string to float: 'forbidden'`` — the entire
primary review path was broken while the wrapper's own unit tests (which read
the file as text) stayed green.

Locked property: the embedded block, extracted exactly as bash would delimit
it, must parse as python. Any un-escaped single quote inside the block breaks
extraction or parsing and fails here.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPERS = [
    REPO_ROOT / "scripts" / "codex_exec_bounded.sh",
    REPO_ROOT / "scripts" / "agy_exec_bounded.sh",
]

BLOCK_RE = re.compile(r"-c '\n(.*?)\n' \"\$TIMEOUT_S\"", re.S)


@pytest.mark.parametrize("wrapper", WRAPPERS, ids=lambda p: p.name)
def test_embedded_python_block_parses(wrapper: Path) -> None:
    text = wrapper.read_text(encoding="utf-8")
    match = BLOCK_RE.search(text)
    assert match, f"{wrapper.name}: embedded -c block not found (delimiter changed?)"
    block = match.group(1)
    assert "'" not in block, (
        f"{wrapper.name}: single quote inside the bash single-quoted -c block — "
        "this truncates the program exactly like the 2026-08-04 breakage"
    )
    ast.parse(block)  # raises SyntaxError on truncation or mangling
