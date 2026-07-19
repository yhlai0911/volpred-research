"""Hermetic tests for the orphan-reaper namespace registry（2026-07-19，msg 963）.

回歸目標不是「再補一個目錄」，而是**補一個目錄不必再寫程式**。

原本的形狀是「每種產物一個 recognizer 函式」。新增一種產物目錄就要有人記得再寫一支
函式；沒寫 = 那個目錄的檔案沒有任何出口（PHASE-Z by design 只 commit 自己那班產的檔）
→ 永久 held → alert 永遠解不掉。這個坑踩了三次：paper/(07-14)、storage/drafts/(07-15，
07-17 才反轉預設)、experiments/(07-19)。07-17 的反轉只做在 drafts recognizer 內部，沒有
升級成全域規則，所以下一個目錄照樣中招。

所以這裡釘住四件事：
  (a) 新增一個受管目錄**只加一筆 config** 就有出口 —— 沒有新的 recognizer 函式；
  (b) held 不是永久狀態：超過 TTL 自動變成一張指名路徑的任務，且不再重複噴同一句 alert；
  (c) 垃圾檔仍然被擋、且帶可讀 reason（預設反轉沒有把防線一起反轉掉）；
  (d) 出貨的 registry 真的宣告了 drafts / paper / experiments，預設是 adopt。

每個測試都跑在拋棄式 git repo（monkeypatch ROOT）上。這裡不得碰到真 repo —— 那是
fixture 的目的，不是禮貌。
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GRACE = 2 * 3600
OLD = time.time() - (GRACE + 600)


def _load_module():
    script = REPO_ROOT / "scripts" / "reap_orphan_deliverables.py"
    spec = importlib.util.spec_from_file_location("reap_orphan_registry_under_test", script)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)


def _write(path: Path, text: str, *, mtime: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Disposable repo + a fake registry the test owns end to end."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "test")
    (tmp_path / "storage" / "ops").mkdir(parents=True)
    (tmp_path / "storage" / "next_tasks.json").write_text("[]", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")

    mod = _load_module()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "TASKS_PATH", tmp_path / "storage" / "next_tasks.json")
    monkeypatch.setattr(mod, "HELD_STATE_PATH", tmp_path / "storage" / "ops" / "held.json")
    monkeypatch.setattr(mod, "REGISTRY_PATH", tmp_path / "config" / "orphan_namespaces.json")
    return mod, tmp_path


def _install_registry(mod, root: Path, payload: dict) -> None:
    path = root / "config" / "orphan_namespaces.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    mod.load_registry(refresh=True)


# ── (a) 新目錄只加 config 即有出口 ───────────────────────────────────────────


def test_a_new_managed_directory_needs_only_a_config_row(env):
    """核心驗收：加一筆 config，那個目錄的檔案立刻有出口。

    這裡刻意沒有 import 任何 `widgets` 專用的東西 —— 因為根本不存在。若有人日後把
    引擎改回「要有對應函式才認得」，這個測試會紅，那正是它的工作。
    """
    mod, root = env
    _install_registry(mod, root, {
        "namespaces": [{"id": "widgets", "path": "storage/widgets",
                        "owner_source": "widget_producer"}],
    })
    _write(root / "storage" / "widgets" / "w1.bin", "bytes", mtime=OLD)
    _write(root / "storage" / "widgets" / "nested" / "w2.weirdext", "x", mtime=OLD)

    scan = mod.scan_namespace("widgets")
    assert {e["path"] for e in scan["collectable"]} == {
        "storage/widgets/w1.bin",
        "storage/widgets/nested/w2.weirdext",
    }
    assert scan["held"] == []

    out = mod.collect_namespace("widgets", scan["collectable"])
    assert out[0]["committed"] is True, out
    assert _git(root, "status", "--porcelain", "--", "storage/widgets/").stdout.strip() == ""


def test_a_registry_drives_the_sweep_without_per_directory_code(env):
    """scan_all_namespaces 掃的是 registry，不是寫死的清單。"""
    mod, root = env
    _install_registry(mod, root, {
        "namespaces": [
            {"id": "alpha", "path": "storage/alpha"},
            {"id": "beta", "path": "storage/beta"},
        ],
    })
    _write(root / "storage" / "alpha" / "a.txt", "a", mtime=OLD)
    _write(root / "storage" / "beta" / "b.txt", "b", mtime=OLD)

    scans = mod.scan_all_namespaces()
    assert set(scans) == {"alpha", "beta"}
    assert scans["alpha"]["collectable"][0]["path"] == "storage/alpha/a.txt"
    assert scans["beta"]["collectable"][0]["path"] == "storage/beta/b.txt"


# ── (d) 垃圾仍被擋，且帶 reason —— 在一個全新的 namespace 裡 ────────────────


def test_d_junk_is_held_with_a_reason_in_any_namespace(env):
    """預設反轉是全域規則，防線也是：這些 reason 不是 drafts 的特例。"""
    mod, root = env
    _install_registry(mod, root, {"namespaces": [{"id": "widgets", "path": "storage/widgets"}]})
    base = root / "storage" / "widgets"
    _write(base / "scratch.tmp", "junk", mtime=OLD)
    _write(base / ".DS_Store", "x", mtime=OLD)
    _write(base / "notes.md~", "x", mtime=OLD)
    _write(base / "__pycache__" / "m.cpython-312.pyc", "x", mtime=OLD)
    big = base / "dump.csv"
    big.write_bytes(b"0" * (mod.get_namespace("widgets")["max_file_bytes"] + 1))
    os.utime(big, (OLD, OLD))
    real = root / "outside.csv"
    real.write_text("a,b\n", encoding="utf-8")
    (base / "link.csv").symlink_to(real)

    scan = mod.scan_namespace("widgets")
    assert scan["collectable"] == []
    reasons = {e["path"]: e["reason"] for e in scan["held"]}
    assert reasons["storage/widgets/scratch.tmp"] == "excluded_suffix:.tmp"
    assert reasons["storage/widgets/.DS_Store"] == "excluded_dotfile"
    assert reasons["storage/widgets/notes.md~"] == "excluded_editor_backup"
    assert reasons["storage/widgets/__pycache__/m.cpython-312.pyc"] == "excluded_suffix:.pyc"
    assert reasons["storage/widgets/dump.csv"].startswith("excluded_oversize:")
    assert reasons["storage/widgets/link.csv"] == "excluded_symlink"
    # 不變量：held 就是留著，不是刪掉。
    assert big.exists() and (base / "scratch.tmp").exists()


def test_d_paired_deletion_is_held_not_half_committed(env):
    """k1380 形狀：刻意的 invalidation rename（舊檔 deleted、`*_INVALID_*` untracked）。

    reaper 永不 commit 刪除，所以只收另一半 = 落地一個做到一半的 rename，並且把已作廢
    的資料默默複製一份進版控。held + 指名，讓 TTL 升級去處理，不盲收。

    2026-07-19（assign_c0ad1962）：held 仍在，但改成「每個目錄一列」。原本兩半各一列、
    各帶一個「not owned」理由，八個檔案就是八列無主產物 —— 而真實狀態是「一個目錄正在
    改名、等 commit」。列出成員即可，理由只需要一個。
    """
    mod, root = env
    _install_registry(mod, root, {"namespaces": [{"id": "experiments", "path": "experiments"}]})
    tracked = root / "experiments" / "k1380" / "k1380_results.json"
    _write(tracked, "{}")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "k1380")
    tracked.unlink()
    _write(root / "experiments" / "k1380" / "k1380_results_INVALID_20260716.json",
           "{}", mtime=OLD)

    scan = mod.scan_namespace("experiments")
    assert scan["collectable"] == []
    assert len(scan["held"]) == 1
    entry = scan["held"][0]
    assert entry["path"] == "experiments/k1380"
    assert entry["reason"] == "pending_rename"
    assert set(entry["members"]) == {
        "experiments/k1380/k1380_results.json",
        "experiments/k1380/k1380_results_INVALID_20260716.json",
    }
    # 刪除從來沒有被批准過：HEAD 裡的原檔還在。
    assert _git(root, "cat-file", "-e",
                "HEAD:experiments/k1380/k1380_results.json").returncode == 0


# ── (b) held 超過 TTL → escalation 任務，且不再重複噴 alert ──────────────────


def _tasks(root: Path) -> list[dict]:
    return json.loads((root / "storage" / "next_tasks.json").read_text(encoding="utf-8"))


def test_b_held_escalates_into_a_named_task_after_ttl(env):
    """held 帶 first_seen，超過 N 班變成一張**指名該路徑**的任務。"""
    mod, root = env
    _install_registry(mod, root, {
        "held_escalation_shifts": 3,
        "namespaces": [{"id": "widgets", "path": "storage/widgets"}],
    })
    held = [{"path": "storage/widgets/mystery.tmp", "reason": "excluded_suffix:.tmp",
             "namespace": "widgets"}]

    first = mod.track_held(held)
    assert first["escalations"] == []
    assert first["suppressed"] == []
    assert _tasks(root) == []

    second = mod.track_held(held)
    assert second["escalations"] == []
    assert second["state"]["storage/widgets/mystery.tmp"]["shifts"] == 2
    # 時間軸存在，才可能有 TTL：這正是原本缺的欄位。
    assert second["state"]["storage/widgets/mystery.tmp"]["first_seen"] == \
        first["state"]["storage/widgets/mystery.tmp"]["first_seen"]

    third = mod.track_held(held)
    assert len(third["escalations"]) == 1
    assert third["escalations"][0]["paths"] == ["storage/widgets/mystery.tmp"]

    tasks = _tasks(root)
    assert len(tasks) == 1
    task = tasks[0]
    assert task["status"] == "pending"
    assert task["task_type"] == "platform_ops"
    assert task["source"] == "reap_orphan_deliverables_held_ttl"
    # 走 append_next_task（佇列的唯一 canonical gateway），不是自己開一個 writer。
    assert task["payload"]["held_paths"] == ["storage/widgets/mystery.tmp"]
    # 出口必須由系統指派，不能寄望作者回來：任務指名了路徑本身。
    assert "storage/widgets/mystery.tmp" in task["description"]


def test_b_escalated_path_stops_re_alerting_and_is_not_re_escalated(env):
    """升級之後就有人owns它了；每班再噴同一句 alert 只是噪音。"""
    mod, root = env
    _install_registry(mod, root, {
        "held_escalation_shifts": 1,
        "namespaces": [{"id": "widgets", "path": "storage/widgets"}],
    })
    held = [{"path": "storage/widgets/mystery.tmp", "reason": "excluded_suffix:.tmp",
             "namespace": "widgets"}]

    first = mod.track_held(held)
    assert len(first["escalations"]) == 1
    assert first["suppressed"] == ["storage/widgets/mystery.tmp"]

    for _ in range(5):
        again = mod.track_held(held)
        assert again["escalations"] == []          # 不重複開任務
        assert again["suppressed"] == ["storage/widgets/mystery.tmp"]  # 持續靜音
    assert len(_tasks(root)) == 1


def test_b_dry_run_never_writes_state_or_tasks(env):
    """掃描是純讀。dry-run 不得開任務、不得推進班次計數。"""
    mod, root = env
    _install_registry(mod, root, {
        "held_escalation_shifts": 1,
        "namespaces": [{"id": "widgets", "path": "storage/widgets"}],
    })
    held = [{"path": "storage/widgets/mystery.tmp", "reason": "excluded_suffix:.tmp",
             "namespace": "widgets"}]

    out = mod.track_held(held, persist=False)
    assert out["escalations"] == []
    assert _tasks(root) == []
    assert not (root / "storage" / "ops" / "held.json").exists()


def test_b_resolved_held_entry_drops_off_the_clock(env):
    """一筆 held 消失 = 那個路徑已經有出口了，狀態檔不該把它留成殭屍。"""
    mod, root = env
    _install_registry(mod, root, {
        "held_escalation_shifts": 9,
        "namespaces": [{"id": "widgets", "path": "storage/widgets"}],
    })
    mod.track_held([{"path": "a", "reason": "r", "namespace": "widgets"}])
    after = mod.track_held([{"path": "b", "reason": "r", "namespace": "widgets"}])
    assert set(after["state"]) == {"b"}


# ── (c) 出貨的 registry 本身 ────────────────────────────────────────────────


def test_c_shipped_registry_declares_the_three_managed_directories():
    """既有三條路徑仍然受管，且 experiments/ 靠同一條預設規則取得出口。

    行為不變的部分由 tests/test_reap_draft_artifacts.py 與
    scripts/tests/test_reap_paper_artifacts.py 覆蓋（兩者現在直接打泛型引擎）。
    這裡只釘住 config 沒有漂移。
    """
    raw = json.loads((REPO_ROOT / "config" / "orphan_namespaces.json").read_text(encoding="utf-8"))
    by_id = {ns["id"]: ns for ns in raw["namespaces"]}
    assert {"drafts", "paper", "experiments"} <= set(by_id)
    assert raw["defaults"]["default"] == "adopt", "全域預設必須是收編，不是白名單"
    assert by_id["drafts"]["path"] == "storage/drafts"
    assert by_id["experiments"]["path"] == "experiments"
    # experiments/ 沒有任何專屬程式碼 —— 它只是套用了全域預設。
    assert by_id["experiments"].get("content_gates", []) == []
    # paper/ 是唯一的 hold-by-default：那裡的 dirty 檔可能是真的內容變動。
    assert by_id["paper"]["default"] == "hold"
    assert by_id["paper"]["content_gates"] == [
        "volatile_json_only", "pdf_requires_clean_sources"]


def test_c_registry_has_no_per_directory_recognizer_functions():
    """驗收條件的 source-level ratchet：新增目錄不得再長出 scan_*_artifacts。"""
    src = (REPO_ROOT / "scripts" / "reap_orphan_deliverables.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))
    for banned in ("def scan_draft_artifacts", "def scan_paper_build_artifacts",
                   "def collect_draft_artifacts", "def collect_paper_artifacts"):
        assert banned not in code, f"per-directory recognizer 回來了: {banned}"
    assert "def scan_namespace(" in code
    assert "def collect_namespace(" in code
