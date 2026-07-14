"""Regression tests for the canonical-writer inventory/ratchet."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
AUDITOR = REPO / "scripts" / "audit_canonical_writers.py"


def _load_auditor():
    spec = importlib.util.spec_from_file_location("audit_canonical_writers", AUDITOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def auditor():
    return _load_auditor()


def _fixture_tree(root: Path, source: str) -> Path:
    target = root / "src" / "volpred" / "writer.py"
    target.parent.mkdir(parents=True)
    target.write_text(source, encoding="utf-8")
    return root


def test_new_unguarded_storage_writer_fails(auditor, tmp_path: Path) -> None:
    _fixture_tree(
        tmp_path,
        """from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "storage" / "next_tasks.json"

def save(payload):
    OUT.write_text(payload)
""",
    )
    result = auditor.audit(tmp_path)
    assert not result.ok
    assert [(item.path, item.line, item.operation) for item in result.violations] == [
        ("src/volpred/writer.py", 6, "write_text")
    ]
    rendered = auditor._render_text(result)
    assert "src/volpred/writer.py:6: unguarded-direct: save -> write_text" in rendered


def test_guarded_registered_storage_writer_passes(
    auditor, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fixture_tree(
        tmp_path,
        """from pathlib import Path
from volpred.canonical_write import guard_canonical_write
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "storage" / "next_tasks.json"

def save(payload):
    guard_canonical_write(OUT)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(payload)
""",
    )
    monkeypatch.setitem(
        auditor.LOW_LEVEL_OWNERS,
        "src/volpred/writer.py:save",
        {"mkdir": 1, "write_text": 1},
    )
    result = auditor.audit(tmp_path)
    assert result.ok
    assert len(result.inventory) == 2
    assert {item.classification for item in result.inventory} == {"guarded-owner"}


def test_tmp_writer_is_outside_canonical_inventory(auditor, tmp_path: Path) -> None:
    _fixture_tree(
        tmp_path,
        """def save(tmp_path, payload):
    out = tmp_path / "state.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(payload)
""",
    )
    result = auditor.audit(tmp_path)
    assert result.ok
    assert result.inventory == ()


def test_registered_owner_operation_count_is_a_fixed_ratchet(
    auditor, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fixture_tree(
        tmp_path,
        """from pathlib import Path
from volpred.canonical_write import guard_canonical_write
OUT = Path("storage") / "next_tasks.json"

def save(payload):
    guard_canonical_write(OUT)
    OUT.write_text(payload)
    OUT.write_text(payload)
""",
    )
    monkeypatch.setitem(
        auditor.LOW_LEVEL_OWNERS,
        "src/volpred/writer.py:save",
        {"write_text": 1},
    )
    result = auditor.audit(tmp_path)
    assert not result.ok
    assert result.violations == ()  # guarded, but the owner grew a new mutation
    assert "expected {'write_text': 1}, observed {'write_text': 2}" in result.owner_count_mismatches[0]


def test_new_parameter_alias_called_with_canonical_path_fails(
    auditor, tmp_path: Path
) -> None:
    _fixture_tree(
        tmp_path,
        """from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

def save(path):
    path.write_text("[]")

save(ROOT / "storage" / "next_tasks.json")
""",
    )
    result = auditor.audit(tmp_path)
    assert not result.ok
    assert [(item.scope, item.operation) for item in result.violations] == [
        ("save", "write_text")
    ]


@pytest.mark.parametrize(
    ("body", "imports_guard"),
    [
        (
            """if False:
        guard_canonical_write(OUT)
    OUT.write_text("[]")""",
            True,
        ),
        (
            """guard_canonical_write(OTHER)
    OUT.write_text("[]")""",
            True,
        ),
        (
            """try:
        guard_canonical_write(OUT)
    except Exception:
        pass
    OUT.write_text("[]")""",
            True,
        ),
        (
            """if apply:
        guard_canonical_write(OUT)
    if apply:
        pass
    else:
        OUT.write_text("[]")""",
            True,
        ),
        (
            """guard_canonical_write(OUT)
    OUT.write_text("[]")""",
            False,
        ),
    ],
    ids=(
        "dead_branch",
        "wrong_target",
        "swallowed",
        "opposite_branch",
        "fake_same_name",
    ),
)
def test_non_dominating_or_noncanonical_guard_fails(
    auditor,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    body: str,
    imports_guard: bool,
) -> None:
    guard_setup = (
        "from volpred.canonical_write import guard_canonical_write\n"
        if imports_guard
        else "def guard_canonical_write(path):\n    pass\n"
    )
    _fixture_tree(
        tmp_path,
        "from pathlib import Path\n"
        + guard_setup
        + 'OUT = Path("storage") / "next_tasks.json"\n'
        + 'OTHER = Path("storage") / "work_log.json"\n\n'
        + "def save():\n    "
        + body
        + "\n",
    )
    monkeypatch.setitem(
        auditor.LOW_LEVEL_OWNERS,
        "src/volpred/writer.py:save",
        {"write_text": 1},
    )
    result = auditor.audit(tmp_path)
    assert not result.ok
    assert [(item.operation, item.guarded) for item in result.violations] == [
        ("write_text", False)
    ]


def test_string_replace_named_path_is_not_a_filesystem_mutation(
    auditor, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fixture_tree(
        tmp_path,
        """from pathlib import Path
from volpred.canonical_write import guard_canonical_write
OUT = Path("storage") / "next_tasks.json"

def save(path="hello"):
    guard_canonical_write(OUT)
    path.replace("h", "H")
    OUT.write_text("[]")
""",
    )
    monkeypatch.setitem(
        auditor.LOW_LEVEL_OWNERS,
        "src/volpred/writer.py:save",
        {"write_text": 1},
    )
    result = auditor.audit(tmp_path)
    assert result.ok
    assert [item.operation for item in result.inventory] == ["write_text"]


def test_write_open_and_atomic_replace_are_detected(auditor, tmp_path: Path) -> None:
    _fixture_tree(
        tmp_path,
        """from pathlib import Path
STORAGE = Path("storage")

def save():
    target = STORAGE / "next_tasks.json"
    with target.open("a+") as handle:
        handle.write("x")
    tmp = STORAGE / ".state.tmp"
    tmp.replace(target)
""",
    )
    result = auditor.audit(tmp_path)
    assert not result.ok
    assert [item.operation for item in result.violations] == ["open-write", "replace"]


@pytest.mark.parametrize(
    ("guard_predicate", "mode_predicate", "expected_ok"),
    [
        ("apply", "apply", True),
        ("apply", "force", False),
    ],
    ids=("same_predicate", "mismatched_predicate"),
)
def test_conditional_guard_must_select_the_write_mode(
    auditor,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    guard_predicate: str,
    mode_predicate: str,
    expected_ok: bool,
) -> None:
    _fixture_tree(
        tmp_path,
        f'''from pathlib import Path
from volpred.canonical_write import guard_canonical_write
OUT = Path("storage") / "next_tasks.json"

def save(apply, force):
    if {guard_predicate}:
        guard_canonical_write(OUT)
    mode = "r+" if {mode_predicate} else "r"
    with OUT.open(mode) as handle:
        pass
''',
    )
    monkeypatch.setitem(
        auditor.LOW_LEVEL_OWNERS,
        "src/volpred/writer.py:save",
        {"open-write": 1},
    )
    result = auditor.audit(tmp_path)
    assert result.ok is expected_ok, auditor._render_text(result)
    assert [(item.operation, item.guarded) for item in result.inventory] == [
        ("open-write", expected_ok)
    ]


def test_real_active_tree_matches_frozen_owner_inventory(auditor) -> None:
    result = auditor.audit(REPO)
    assert result.ok, auditor._render_text(result)
    assert result.inventory, "coverage canary: audit inventoried zero canonical mutations"
    inventoried_owners = {item.owner for item in result.inventory}
    formerly_missed_alias_writers = {
        "scripts/check_alerts.py:_append_next_task_locked",
        "scripts/check_alerts.py:_ci_close_pending_repair_tasks",
        "scripts/extract_base64_images.py:main",
        "scripts/slim_feed_description.py:main",
        "src/api/routers/mirror.py:append_memory_file",
        "src/api/routers/mirror.py:put_memory_file",
        "src/volpred/ops/event_jobs.py:_ensure_next_task",
        "src/volpred/ops/event_jobs.py:_expire_next_tasks",
        "src/volpred/ops/event_jobs.py:_suppress_canonical_for_legacy_conflict",
        "src/volpred/ops/feed_sync.py:reconcile_content_from_singles",
    }
    assert formerly_missed_alias_writers <= inventoried_owners
