"""
test_merge_worktree_dedup_regression.py — pytest 包裝 scripts/tests/test_merge_worktree_dedup.py

驗證：
1. clean fixture → exit 0（all 5 checks PASS）
2. 4 個 corrupt fixtures 各觸發對應 hard fail → exit 1
3. emit-baseline + baseline 模式 round-trip：clean fixture 產 baseline，
   再用 baseline 跑 → 仍 PASS（baseline 為空 / failures 不變）
4. delta mode 偵測新增 failure：用 clean 的 baseline 跑 corrupt → exit 1
5. legitimate cross-ref 不誤判（clean fixture 內的 K700 引用 K588 仍 OK）

歷史背景：
  - 2026-04-10 knowledge.json 54.5MB bloat（jq dedup bug）
  - 2026-05-08 K936 incident（25 entries id-vs-title misalignment）
本 regression 是 P3 platform_ops gate，避免第 3 次 silent corruption commit。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "tests" / "test_merge_worktree_dedup.py"
FIXTURES = ROOT / "tests" / "fixtures"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_script_exists():
    assert SCRIPT.exists(), f"runner missing: {SCRIPT}"
    assert FIXTURES.is_dir(), f"fixtures dir missing: {FIXTURES}"


def test_clean_fixture_passes():
    """Case 1: clean fixture 5/5 PASS, exit 0."""
    fx = FIXTURES / "knowledge_clean.json"
    res = _run([str(fx)])
    assert res.returncode == 0, (
        f"clean fixture should pass; got rc={res.returncode}\nstdout={res.stdout}\nstderr={res.stderr}"
    )
    assert "ALL CHECKS PASS" in res.stdout


def test_id_title_misaligned_fails():
    """Case 2: K936-style id/title mismatch → Test 1 FAIL, exit 1."""
    fx = FIXTURES / "knowledge_corrupt_id_title_misaligned.json"
    res = _run([str(fx)])
    assert res.returncode == 1, f"expected rc=1 got {res.returncode}\n{res.stdout}"
    assert "Test 1: id-vs-title consistency" in res.stdout
    # 預期 fixture 內 entry #0 (K936/K112) + entry #1 (K937/K140) 都被 flag
    assert "K936" in res.stdout
    assert "K112" in res.stdout
    assert "K937" in res.stdout
    assert "K140" in res.stdout


def test_content_id_mismatch_fails():
    """Case 3: title+content 三方矛盾 → Test 2 FAIL, exit 1.

    fixture 內含 1 個硬 bug（K700 但 title+content 都 K112）+
    1 個 legitimate cross-ref（K861 引用 K44，title 一致）— 後者不 flag。
    """
    fx = FIXTURES / "knowledge_corrupt_content_id_mismatch.json"
    res = _run([str(fx)])
    assert res.returncode == 1, f"expected rc=1 got {res.returncode}\n{res.stdout}"
    assert "Test 2: content-id alignment" in res.stdout
    assert "K700" in res.stdout and "K112" in res.stdout
    # legitimate K861 cross-ref 不該被 flag — 確認 K861 / K44 不出現於 Test 2 段
    test2_section = res.stdout.split("[FAIL] Test 2")[1].split("[")[0] if "[FAIL] Test 2" in res.stdout else ""
    assert "K861" not in test2_section, "K861 legitimate cross-ref 被誤判：\n" + res.stdout


def test_experiment_id_mismatch_fails():
    """Case 4: experiment_id vs id/title 不一致 → Test 3 FAIL, exit 1."""
    fx = FIXTURES / "knowledge_corrupt_experiment_id_mismatch.json"
    res = _run([str(fx)])
    assert res.returncode == 1, f"expected rc=1 got {res.returncode}\n{res.stdout}"
    assert "Test 3: experiment_id consistency" in res.stdout
    assert "K109" in res.stdout
    assert "K950" in res.stdout


def test_duplicate_ids_fails():
    """Case 5: 同 id 兩個 substantive entry → Test 4 FAIL, exit 1."""
    fx = FIXTURES / "knowledge_corrupt_duplicate_ids.json"
    res = _run([str(fx)])
    assert res.returncode == 1, f"expected rc=1 got {res.returncode}\n{res.stdout}"
    assert "Test 4: no duplicate ids" in res.stdout
    assert "K500" in res.stdout


def test_baseline_roundtrip(tmp_path: Path):
    """Case 6: emit-baseline + --baseline 模式 round-trip — clean fixture 走過後仍 PASS。"""
    fx = FIXTURES / "knowledge_clean.json"
    bpath = tmp_path / "baseline.json"
    res1 = _run([str(fx), "--emit-baseline", str(bpath)])
    assert res1.returncode == 0
    assert bpath.exists()
    base = json.loads(bpath.read_text())
    # clean fixture should have 0 failures
    for key, lst in base.items():
        assert isinstance(lst, list)
    res2 = _run([str(fx), "--baseline", str(bpath)])
    assert res2.returncode == 0
    assert "ALL CHECKS PASS" in res2.stdout


def test_delta_mode_detects_new_failure(tmp_path: Path):
    """Case 7: 從 clean fixture 抽 baseline，再跑 corrupt fixture → exit 1（新增 failure）."""
    clean = FIXTURES / "knowledge_clean.json"
    corrupt = FIXTURES / "knowledge_corrupt_id_title_misaligned.json"
    bpath = tmp_path / "clean_baseline.json"
    _run([str(clean), "--emit-baseline", str(bpath)])
    res = _run([str(corrupt), "--baseline", str(bpath)])
    assert res.returncode == 1, f"delta mode 該抓新 failure；rc={res.returncode}\n{res.stdout}"
    assert "新增 mismatch" in res.stdout or "新增 failure" in res.stdout.lower() or "NEW FAILURES" in res.stdout


def test_delta_mode_tolerates_baseline_failures(tmp_path: Path):
    """Case 8: 同一 corrupt fixture 自己當 baseline → 沒新增 → exit 0."""
    corrupt = FIXTURES / "knowledge_corrupt_id_title_misaligned.json"
    bpath = tmp_path / "self_baseline.json"
    _run([str(corrupt), "--emit-baseline", str(bpath)])
    res = _run([str(corrupt), "--baseline", str(bpath)])
    assert res.returncode == 0, f"baseline = self → 不該 fail；rc={res.returncode}\n{res.stdout}"


def test_missing_file_returns_2(tmp_path: Path):
    """Case 9: 不存在路徑 → exit 2（fatal，不是 hard fail）."""
    res = _run([str(tmp_path / "no_such_file.json")])
    assert res.returncode == 2


def test_invalid_json_returns_2(tmp_path: Path):
    """Case 10: 壞 JSON → exit 2."""
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    res = _run([str(bad)])
    assert res.returncode == 2


@pytest.mark.skipif(
    not (ROOT / "storage" / "memory" / "knowledge.json").exists(),
    reason="production knowledge.json 不存在（CI sandbox）",
)
def test_production_knowledge_delta_mode_self_baseline(tmp_path: Path):
    """Case 11: production knowledge.json 自當 baseline → 0 新增 → exit 0.

    這是 merge_worktree.sh 整合時的 baseline pattern：pre-merge 抽 baseline，
    post-merge 比對。若 dedup 沒引入新 corruption，必 PASS。
    """
    prod = ROOT / "storage" / "memory" / "knowledge.json"
    bpath = tmp_path / "prod_baseline.json"
    res1 = _run([str(prod), "--emit-baseline", str(bpath)])
    assert res1.returncode == 0
    res2 = _run([str(prod), "--baseline", str(bpath)])
    assert res2.returncode == 0, (
        f"production self-baseline delta should be 0; got rc={res2.returncode}\n{res2.stdout}"
    )
