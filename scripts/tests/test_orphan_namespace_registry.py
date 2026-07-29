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

import hashlib
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
    _git(root, "add", "config/orphan_namespaces.json")
    committed = _git(root, "commit", "-q", "-m", "registry fixture")
    assert committed.returncode == 0, committed.stderr
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


def test_b_a_task_closes_when_the_held_condition_that_spawned_it_disappears(env):
    """反向對帳。`state` 每輪從當前 scan 重建，所以路徑不再 held 時記錄就消失了 ——
    連同那個 task_id。沒有這一步就沒有任何人去關那張單，於是**任務活得比它的成因
    更久**：experiments/k1380 早已不在 state，單子卻還躺在 pending。"""
    mod, root = env
    _install_registry(mod, root, {
        "held_escalation_shifts": 1,
        "namespaces": [{"id": "widgets", "path": "storage/widgets"}],
    })
    held = [{"path": "storage/widgets/mystery.tmp", "reason": "excluded_suffix:.tmp",
             "namespace": "widgets"}]
    assert len(mod.track_held(held)["escalations"]) == 1
    task_id = _tasks(root)[0]["id"]

    out = mod.track_held([])  # 路徑找到出口，不再 held

    assert out["resolved_tasks"] == [task_id]
    closed = _tasks(root)[0]
    assert closed["status"] == "succeeded"
    assert "不再被 reaper held" in closed["result"]


def test_b_a_task_stays_open_while_any_of_its_paths_is_still_held(env):
    """部分解決不是解決。一張單點名 N 個路徑，剩一個卡著就還沒完 —— 否則「大部分
    處理完了」會變成關單理由，那正是這個 class 反覆栽的地方。"""
    mod, root = env
    _install_registry(mod, root, {
        "held_escalation_shifts": 1,
        "namespaces": [{"id": "widgets", "path": "storage/widgets"}],
    })
    both = [{"path": "storage/widgets/a.tmp", "reason": "r", "namespace": "widgets"},
            {"path": "storage/widgets/b.tmp", "reason": "r", "namespace": "widgets"}]
    assert len(mod.track_held(both)["escalations"]) == 1

    out = mod.track_held(both[:1])  # b 有出口了，a 還卡著

    assert out["resolved_tasks"] == []
    assert _tasks(root)[0]["status"] == "pending"


def test_b_a_single_path_escalation_names_it_in_the_title(env):
    """只編碼份數的標題，讓每個單路徑逃逸都渲染成同一串字：7/19、7/20、7/20 三張
    不同 held key 在池子裡長得一模一樣，看起來像同一張單開了三次。分不出來的標題
    讓真重複與假重複都看不見。"""
    mod, root = env
    _install_registry(mod, root, {
        "held_escalation_shifts": 1,
        "namespaces": [{"id": "widgets", "path": "storage/widgets"}],
    })
    mod.track_held([{"path": "storage/widgets/mystery.tmp", "reason": "r",
                     "namespace": "widgets"}])

    assert "storage/widgets/mystery.tmp" in _tasks(root)[0]["title"]


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
    assert by_id["experiments"]["atomic_unit"] == "first_child_directory"
    # experiments/ 仍走泛型 namespace engine，但收編前必須委派既有的
    # review-certification + artifact-completeness owners；否則 reaper 會像
    # K1694 一樣把 Codex FAIL、無 knowledge 的結果直接 commit 進 main。
    assert by_id["experiments"]["content_gates"] == [
        "experiment_ready_for_main"
    ]
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


def test_experiment_file_limit_never_splits_one_directory(env):
    """A 41-file experiment crosses max_files=40 as one atomic unit."""
    mod, _root = env
    namespace = {
        "path": "experiments",
        "atomic_unit": "first_child_directory",
    }
    entries = [
        {"path": f"experiments/K2000/artifact_{index:02d}.json"}
        for index in range(41)
    ] + [{"path": "experiments/K2001/result.json"}]

    batch = mod._namespace_batch(namespace, entries, 40)

    assert len(batch) == 41
    assert {
        str(Path(row["path"]).parent)
        for row in batch
    } == {"experiments/K2000"}


def test_uncertified_experiment_outputs_are_held_not_auto_committed(env):
    """K1694 regression: orphan adoption may not bypass experiment admission.

    The producer can leave perfectly ordinary result files in ``experiments/``;
    their location proves ownership, not scientific admissibility.  A missing
    byte-bound PASS review and missing knowledge/spec must therefore hold the
    whole experiment for its normal review/merge owner.
    """
    mod, root = env
    _install_registry(mod, root, {
        "namespaces": [{
            "id": "experiments",
            "path": "experiments",
            "content_gates": ["experiment_ready_for_main"],
        }],
    })
    _write(root / "storage" / "memory" / "knowledge.json", "[]")
    exp = root / "experiments" / "K1694"
    _write(exp / "K1694.py", "print('invalid pending review')\n", mtime=OLD)
    _write(exp / "README.md", "# REVIEW_FAILED\n", mtime=OLD)
    _write(
        exp / "K1694_results.json",
        json.dumps({"experiment_id": "K1694", "verdict": "NULL"}),
        mtime=OLD,
    )

    scan = mod.scan_namespace("experiments")

    assert scan["collectable"] == []
    assert {entry["path"] for entry in scan["held"]} == {
        "experiments/K1694/K1694.py",
        "experiments/K1694/K1694_results.json",
        "experiments/K1694/README.md",
    }
    assert all(
        entry["kind"] == "experiment_admission"
        and "review-certification" in entry["reason"]
        and "knowledge" in entry["reason"]
        for entry in scan["held"]
    )


def _reviewed_k1694(root: Path) -> Path:
    exp = root / "experiments" / "K1694"
    claim_files = {
        "K1694.py": "print('reviewed')\n",
        "README.md": "# reviewed\n",
        "K1694_results.json": json.dumps(
            {"experiment_id": "K1694", "verdict": "NULL"}
        ),
    }
    for name, payload in claim_files.items():
        _write(exp / name, payload, mtime=OLD)
    _write(exp / "reproduce_spec.json", json.dumps({
        "schema_version": "volpred.reproduce_spec.v1",
        "entrypoint": {"path": "K1694.py", "args": []},
        "canonical_result": "K1694_results.json",
        "inputs": [],
        "timeout_seconds": 900,
        "network": "deny",
        "randomness": {"status": "not_applicable"},
        "comparison": {
            "rtol": 1e-9,
            "atol": 1e-12,
            "ignore_pointers": [],
            "ignore_reasons": {},
        },
    }), mtime=OLD)
    reviewed = {
        name: hashlib.sha256((exp / name).read_bytes()).hexdigest()
        for name in claim_files
    }
    _write(exp / "review_verdict.json", json.dumps({
        "kid": "K1694",
        "verdict": "PASS",
        "reviewer": "test",
        "reviewed_at": "2026-07-29T00:00:00+00:00",
        "reviewed_commit": "fixture",
        "review_artifact": "fixture",
        "blocking_defects": [],
        "reviewed_sha256": reviewed,
    }), mtime=OLD)
    return exp


def _commit_k1694_evidence(root: Path, *, tracked_input: bool = False) -> Path:
    _write(
        root / "storage" / "memory" / "knowledge.json",
        json.dumps([{"content": "K1694 recorded"}]),
    )
    _write(
        root / "config" / "experiment_artifact_exclusions.json",
        json.dumps({"exclusions": []}),
    )
    paths = [
        "storage/memory/knowledge.json",
        "config/experiment_artifact_exclusions.json",
    ]
    tracked = root / "experiments" / "K1694" / "tracked_input.csv"
    if tracked_input:
        _write(tracked, "x\n")
        paths.append("experiments/K1694/tracked_input.csv")
    _git(root, "add", *paths)
    committed = _git(root, "commit", "-q", "-m", "admission evidence")
    assert committed.returncode == 0, committed.stderr
    return tracked


def test_atomic_experiment_with_tracked_deletion_is_entirely_held(env):
    """A deleted sibling blocks even when current claim-surface bytes PASS."""
    mod, root = env
    _install_registry(mod, root, {
        "namespaces": [{
            "id": "experiments",
            "path": "experiments",
            "atomic_unit": "first_child_directory",
            "content_gates": ["experiment_ready_for_main"],
        }],
    })
    tracked = _commit_k1694_evidence(root, tracked_input=True)
    tracked.unlink()
    _reviewed_k1694(root)

    scan = mod.scan_namespace("experiments")

    assert scan["collectable"] == []
    assert len(scan["held"]) == 1
    held = scan["held"][0]
    assert held["path"] == "experiments/K1694"
    assert held["kind"] == held["reason"] == "pending_rename"
    assert "experiments/K1694/tracked_input.csv" in held["members"]
    assert "experiments/K1694/K1694_results.json" in held["members"]


def test_atomic_experiment_with_41_ready_and_one_recent_member_commits_nothing(
    env,
):
    """max_files cannot hide a held/grace member outside the collectable slice."""
    mod, root = env
    _install_registry(mod, root, {
        "namespaces": [{
            "id": "experiments",
            "path": "experiments",
            "atomic_unit": "first_child_directory",
            "content_gates": ["experiment_ready_for_main"],
            "max_files": 40,
        }],
    })
    _commit_k1694_evidence(root)
    exp = _reviewed_k1694(root)
    for index in range(41):
        _write(exp / f"input_{index:02d}.bin", "ready", mtime=OLD)
    _write(exp / "input_recent.bin", "still writing")

    scan = mod.scan_namespace("experiments")

    assert scan["collectable"] == []
    assert len(scan["held"]) == 1
    held = scan["held"][0]
    assert held["path"] == "experiments/K1694"
    assert held["reason"] == "atomic_unit_incomplete"
    assert "experiments/K1694/input_recent.bin" in held["members"]
    assert len([p for p in held["members"] if p.endswith(".bin")]) == 42


def test_dirty_only_knowledge_cannot_authorize_experiment_collection(env):
    """The reaper commits only experiment paths, so evidence must come from HEAD."""
    mod, root = env
    _install_registry(mod, root, {
        "namespaces": [{
            "id": "experiments",
            "path": "experiments",
            "content_gates": ["experiment_ready_for_main"],
        }],
    })
    knowledge = root / "storage" / "memory" / "knowledge.json"
    _write(knowledge, "[]")
    _git(root, "add", "storage/memory/knowledge.json")
    _git(root, "commit", "-q", "-m", "empty knowledge")
    # The working tree claims K1694 is recorded, but collect_namespace would
    # leave this dirty byte behind while committing only experiments/K1694/*.
    _write(knowledge, json.dumps([{"content": "K1694 dirty-only"}]))
    exp = _reviewed_k1694(root)
    (exp / "reproduce_spec.json").unlink()

    scan = mod.scan_namespace("experiments")

    assert scan["collectable"] == []
    assert scan["held"]
    assert all("knowledge.json" in row["reason"] for row in scan["held"])


def test_dirty_only_artifact_exclusion_cannot_authorize_collection(env):
    """A working-tree-only exclusion is evidence outside the commit boundary."""
    mod, root = env
    _install_registry(mod, root, {
        "namespaces": [{
            "id": "experiments",
            "path": "experiments",
            "content_gates": ["experiment_ready_for_main"],
        }],
    })
    _write(
        root / "storage" / "memory" / "knowledge.json",
        json.dumps([{"content": "K1694 recorded"}]),
    )
    exclusion = root / "config" / "experiment_artifact_exclusions.json"
    _write(exclusion, json.dumps({"exclusions": []}))
    baseline = root / "storage" / "ops" / "mdd_scale_artifact_baseline.json"
    _write(baseline, "{}")
    _git(root, "add", "storage/memory/knowledge.json", str(exclusion), str(baseline))
    _git(root, "commit", "-q", "-m", "admission evidence")
    _write(exclusion, json.dumps({
        "exclusions": [{
            "experiment": "K1694",
            "reason": "dirty-only bypass",
        }],
    }))
    exp = _reviewed_k1694(root)
    (exp / "reproduce_spec.json").unlink()

    scan = mod.scan_namespace("experiments")

    assert scan["collectable"] == []
    assert scan["held"]
    assert all(
        "missing reproduce_spec.json" in row["reason"]
        for row in scan["held"]
    )


def test_evidence_mutation_between_snapshot_and_checker_cannot_authorize(
    env, monkeypatch
):
    """Delegated checkers receive the immutable HEAD snapshot, not a later read."""
    mod, root = env
    _install_registry(mod, root, {
        "namespaces": [{
            "id": "experiments",
            "path": "experiments",
            "content_gates": ["experiment_ready_for_main"],
        }],
    })
    _write(
        root / "storage" / "memory" / "knowledge.json",
        json.dumps([{"content": "K1694 recorded"}]),
    )
    exclusion = root / "config" / "experiment_artifact_exclusions.json"
    _write(exclusion, json.dumps({"exclusions": []}))
    _git(root, "add", "storage/memory/knowledge.json", str(exclusion))
    _git(root, "commit", "-q", "-m", "immutable admission evidence")
    exp = _reviewed_k1694(root)
    (exp / "reproduce_spec.json").unlink()

    import check_experiment_artifacts as artifacts

    original = artifacts.audit_experiment

    def mutate_then_audit(*args, **kwargs):
        _write(exclusion, json.dumps({
            "exclusions": [{
                "experiment": "K1694",
                "reason": "TOCTOU dirty-only bypass",
            }],
        }))
        return original(*args, **kwargs)

    monkeypatch.setattr(artifacts, "audit_experiment", mutate_then_audit)

    scan = mod.scan_namespace("experiments")

    assert scan["collectable"] == []
    assert scan["held"]
    assert all("missing reproduce_spec.json" in row["reason"] for row in scan["held"])


def test_dirty_registry_cannot_remove_an_admission_gate(env):
    """A working-tree registry edit is policy outside the commit boundary."""
    mod, root = env
    _install_registry(mod, root, {
        "namespaces": [{
            "id": "experiments",
            "path": "experiments",
            "content_gates": ["experiment_ready_for_main"],
        }],
    })
    _write(
        root / "config" / "orphan_namespaces.json",
        json.dumps({
            "namespaces": [{
                "id": "experiments",
                "path": "experiments",
                "content_gates": [],
            }],
        }),
    )
    _write(
        root / "experiments" / "K1694" / "K1694_results.json",
        "{}",
        mtime=OLD,
    )

    scan = mod.scan_namespace("experiments")

    assert scan["collectable"] == []
    assert scan["held"] == [{
        "path": "experiments/K1694/K1694_results.json",
        "kind": "namespace_configuration",
        "reason": "registry_worktree_differs_head",
    }]


def test_reviewed_experiment_mutated_after_scan_is_not_committed(env):
    """The writer lease revalidates admission and the exact staged blob."""
    mod, root = env
    _install_registry(mod, root, {
        "namespaces": [{
            "id": "experiments",
            "path": "experiments",
            "content_gates": ["experiment_ready_for_main"],
        }],
    })
    _write(
        root / "storage" / "memory" / "knowledge.json",
        json.dumps([{"content": "K1694 recorded"}]),
    )
    _write(
        root / "config" / "experiment_artifact_exclusions.json",
        json.dumps({"exclusions": []}),
    )
    _git(
        root,
        "add",
        "storage/memory/knowledge.json",
        "config/experiment_artifact_exclusions.json",
    )
    _git(root, "commit", "-q", "-m", "admission evidence")
    exp = _reviewed_k1694(root)
    scan = mod.scan_namespace("experiments")
    assert scan["collectable"], scan

    # This byte was never reviewed. The old implementation would still stage
    # and commit it using the earlier scan decision.
    _write(exp / "K1694.py", "print('mutated after review')\n", mtime=OLD)

    out = mod.collect_namespace("experiments", scan["collectable"])

    assert out == [{
        "namespace": "experiments",
        "paths": [row["path"] for row in scan["collectable"]],
        "committed": False,
        "err": "admission_snapshot_changed",
        "mismatches": [row["path"] for row in scan["collectable"]],
    }]
    assert _git(
        root, "status", "--porcelain", "--", "experiments/K1694"
    ).stdout


def test_foreign_staged_path_blocks_the_whole_tree_commit(env):
    """A detached commit may not inherit any staged path outside its namespace."""
    mod, root = env
    _install_registry(mod, root, {
        "namespaces": [{
            "id": "experiments",
            "path": "experiments",
            "content_gates": ["experiment_ready_for_main"],
        }],
    })
    _write(
        root / "storage" / "memory" / "knowledge.json",
        json.dumps([{"content": "K1694 recorded"}]),
    )
    _write(
        root / "config" / "experiment_artifact_exclusions.json",
        json.dumps({"exclusions": []}),
    )
    _git(
        root,
        "add",
        "storage/memory/knowledge.json",
        "config/experiment_artifact_exclusions.json",
    )
    _git(root, "commit", "-q", "-m", "admission evidence")
    _reviewed_k1694(root)
    scan = mod.scan_namespace("experiments")
    foreign = root / "foreign-owner.txt"
    _write(foreign, "not the reaper's change\n")
    _git(root, "add", "foreign-owner.txt")

    out = mod.collect_namespace("experiments", scan["collectable"])

    assert out == [{
        "namespace": "experiments",
        "paths": [row["path"] for row in scan["collectable"]],
        "committed": False,
        "err": "pre_staged_collision",
        "collisions": ["foreign-owner.txt"],
    }]
    assert _git(
        root, "diff", "--cached", "--name-only"
    ).stdout.splitlines() == ["foreign-owner.txt"]


def test_worktree_mutation_after_staged_check_cannot_replace_verified_blob(env):
    """The final commit consumes an isolated index, never pathspec worktree bytes."""
    mod, root = env
    _install_registry(mod, root, {
        "namespaces": [{
            "id": "experiments",
            "path": "experiments",
            "content_gates": ["experiment_ready_for_main"],
        }],
    })
    _write(
        root / "storage" / "memory" / "knowledge.json",
        json.dumps([{"content": "K1694 recorded"}]),
    )
    _write(
        root / "config" / "experiment_artifact_exclusions.json",
        json.dumps({"exclusions": []}),
    )
    _git(
        root,
        "add",
        "storage/memory/knowledge.json",
        "config/experiment_artifact_exclusions.json",
    )
    _git(root, "commit", "-q", "-m", "admission evidence")
    exp = _reviewed_k1694(root)
    reviewed_bytes = (exp / "K1694.py").read_text(encoding="utf-8")
    scan = mod.scan_namespace("experiments")
    assert scan["collectable"], scan

    hook = root / ".git" / "hooks" / "pre-commit"
    _write(
        hook,
        "#!/bin/sh\n"
        "printf \"%s\\\\n\" \"print('mutated inside pre-commit')\" "
        "> experiments/K1694/K1694.py\n",
    )
    hook.chmod(0o755)

    out = mod.collect_namespace("experiments", scan["collectable"])

    assert out[0]["committed"] is True, out
    committed = _git(
        root, "show", "HEAD:experiments/K1694/K1694.py"
    ).stdout
    assert committed == reviewed_bytes
    assert (exp / "K1694.py").read_text(encoding="utf-8") == (
        "print('mutated inside pre-commit')\n"
    )
    # The later bytes are preserved as an ordinary dirty edit for the next
    # admission cycle; they were neither lost nor smuggled into this commit.
    assert "experiments/K1694/K1694.py" in _git(
        root, "status", "--porcelain"
    ).stdout


def test_head_advance_during_hook_is_preserved_and_reaper_fails_closed(env):
    """A foreign HEAD advance must win; reaper may never roll it back."""
    mod, root = env
    _install_registry(mod, root, {
        "namespaces": [{
            "id": "experiments",
            "path": "experiments",
            "content_gates": ["experiment_ready_for_main"],
        }],
    })
    _write(
        root / "storage" / "memory" / "knowledge.json",
        json.dumps([{"content": "K1694 recorded"}]),
    )
    _write(
        root / "config" / "experiment_artifact_exclusions.json",
        json.dumps({"exclusions": []}),
    )
    _git(
        root,
        "add",
        "storage/memory/knowledge.json",
        "config/experiment_artifact_exclusions.json",
    )
    _git(root, "commit", "-q", "-m", "admission evidence")
    _reviewed_k1694(root)
    scan = mod.scan_namespace("experiments")
    original_head = _git(root, "rev-parse", "HEAD").stdout.strip()
    external_receipt = root / "external-head.txt"

    hook = root / ".git" / "hooks" / "pre-commit"
    _write(
        hook,
        "#!/bin/sh\n"
        "original=$(git rev-parse HEAD)\n"
        "tree=$(git rev-parse \"$original^{tree}\")\n"
        "external=$(printf 'external writer\\n' | "
        "git commit-tree \"$tree\" -p \"$original\")\n"
        "git update-ref HEAD \"$external\" \"$original\"\n"
        f"printf '%s\\n' \"$external\" > {external_receipt}\n",
    )
    hook.chmod(0o755)

    out = mod.collect_namespace("experiments", scan["collectable"])

    external_head = external_receipt.read_text(encoding="utf-8").strip()
    assert external_head != original_head
    assert _git(root, "rev-parse", "HEAD").stdout.strip() == external_head
    assert out[0]["committed"] is False
    assert "experiments/" in _git(
        root, "status", "--porcelain"
    ).stdout


def test_foreign_staged_during_hook_survives_reaper_failure(env):
    """Failure cleanup may never replace the checkout's shared index."""
    mod, root = env
    _install_registry(mod, root, {
        "namespaces": [{
            "id": "experiments",
            "path": "experiments",
            "content_gates": ["experiment_ready_for_main"],
        }],
    })
    _write(
        root / "storage" / "memory" / "knowledge.json",
        json.dumps([{"content": "K1694 recorded"}]),
    )
    _write(
        root / "config" / "experiment_artifact_exclusions.json",
        json.dumps({"exclusions": []}),
    )
    _git(
        root,
        "add",
        "storage/memory/knowledge.json",
        "config/experiment_artifact_exclusions.json",
    )
    _git(root, "commit", "-q", "-m", "admission evidence")
    _reviewed_k1694(root)
    scan = mod.scan_namespace("experiments")
    original_head = _git(root, "rev-parse", "HEAD").stdout.strip()
    _write(root / "foreign-owner.txt", "staged by external writer\n")

    hook = root / ".git" / "hooks" / "pre-commit"
    _write(
        hook,
        "#!/bin/sh\n"
        "env -u GIT_INDEX_FILE git add foreign-owner.txt\n"
        "exit 1\n",
    )
    hook.chmod(0o755)

    out = mod.collect_namespace("experiments", scan["collectable"])

    assert out[0]["committed"] is False
    assert _git(root, "rev-parse", "HEAD").stdout.strip() == original_head
    assert _git(
        root, "diff", "--cached", "--name-only"
    ).stdout.splitlines() == ["foreign-owner.txt"]
    assert _git(
        root, "show", ":foreign-owner.txt"
    ).stdout == "staged by external writer\n"


def test_head_advance_after_commit_is_not_rolled_back(env):
    """A post-commit ref race must fail its CAS without deleting either commit."""
    mod, root = env
    _install_registry(mod, root, {
        "namespaces": [{
            "id": "experiments",
            "path": "experiments",
            "content_gates": ["experiment_ready_for_main"],
        }],
    })
    _write(
        root / "storage" / "memory" / "knowledge.json",
        json.dumps([{"content": "K1694 recorded"}]),
    )
    _write(
        root / "config" / "experiment_artifact_exclusions.json",
        json.dumps({"exclusions": []}),
    )
    _git(
        root,
        "add",
        "storage/memory/knowledge.json",
        "config/experiment_artifact_exclusions.json",
    )
    _git(root, "commit", "-q", "-m", "admission evidence")
    _reviewed_k1694(root)
    scan = mod.scan_namespace("experiments")
    original_head = _git(root, "rev-parse", "HEAD").stdout.strip()
    race_receipt = root / "post-commit-race.txt"
    hook = root / ".git" / "hooks" / "post-commit"
    _write(
        hook,
        "#!/bin/sh\n"
        "reaper=$(git rev-parse HEAD)\n"
        "tree=$(git rev-parse \"$reaper^{tree}\")\n"
        "external=$(printf 'external writer\\n' | "
        "git commit-tree \"$tree\" -p \"$reaper\")\n"
        "git update-ref HEAD \"$external\" \"$reaper\"\n"
        f"printf '%s %s\\n' \"$reaper\" \"$external\" > {race_receipt}\n",
    )
    hook.chmod(0o755)

    out = mod.collect_namespace("experiments", scan["collectable"])

    reaper_head, external_head = race_receipt.read_text(
        encoding="utf-8"
    ).split()
    assert reaper_head != original_head
    assert external_head != reaper_head
    assert _git(root, "rev-parse", "HEAD").stdout.strip() == external_head
    assert _git(
        root, "cat-file", "-e", f"{reaper_head}^{{commit}}"
    ).returncode == 0
    assert _git(root, "rev-parse", f"{external_head}^").stdout.strip() == reaper_head
    assert out[0]["committed"] is True


def test_unknown_content_gate_fails_closed(env):
    mod, root = env
    _install_registry(mod, root, {
        "namespaces": [{
            "id": "widgets",
            "path": "storage/widgets",
            "content_gates": ["typo_gate"],
        }],
    })
    _write(root / "storage" / "widgets" / "output.json", "{}", mtime=OLD)

    scan = mod.scan_namespace("widgets")

    assert scan["collectable"] == []
    assert scan["held"] == [{
        "path": "storage/widgets/output.json",
        "kind": "namespace_configuration",
        "reason": "unknown_content_gate:typo_gate",
    }]
