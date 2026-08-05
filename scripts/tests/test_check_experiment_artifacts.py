"""The artifact-completeness gate must block, and must block only what it should.

2026-07-19 CI went red three dispatch hours in a row because experiments reached
main while their knowledge entry / reproduce_spec did not (k1732, then k1719).
``scripts/check_experiment_artifacts.py`` freezes that class at both doors
(``merge_worktree.sh`` and ``.github/workflows/experiment-artifacts.yml``).

Two failure modes are tested here, and the second matters as much as the first:
a gate that blocks a result-less directory forces someone to invent a knowledge
entry for a run that produced no finding — fabricated history is the exact thing
this gate exists to prevent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import check_experiment_artifacts as gate

from volpred.research import reproduce_spec as rs


def _experiment(root: Path, name: str, *, results: bool = True, spec: bool = True) -> Path:
    exp = root / "experiments" / name
    exp.mkdir(parents=True)
    if results:
        (exp / f"{name}_results.json").write_text(
            json.dumps({"qlike": 0.42}), encoding="utf-8"
        )
    if spec:
        (exp / "run.py").write_text("print('ok')\n", encoding="utf-8")
        # Shape copied from experiments/k1719 — the gate validates through
        # reproduce_check.load_spec when it can import it, so a spec that only
        # satisfies the structural fallback would pass here and fail in CI.
        (exp / gate.SPEC_NAME).write_text(json.dumps({
            "schema_version": gate.SPEC_SCHEMA,
            "entrypoint": {"path": "run.py", "args": []},
            "canonical_result": f"{name}_results.json",
            "inputs": [],
            "timeout_seconds": 900,
            "network": "deny",
            "randomness": {"status": "not_applicable"},
            "comparison": {"rtol": 1e-9, "atol": 1e-12,
                           "ignore_pointers": [], "ignore_reasons": {}},
        }), encoding="utf-8")
    return exp


def test_experiment_with_results_but_no_knowledge_entry_is_blocked(tmp_path: Path) -> None:
    exp = _experiment(tmp_path, "k9001", spec=True)
    record = gate.audit_experiment(exp, knowledge_ids=set(), exclusions={})
    assert record["gated"] is True
    assert record["has_knowledge_entry"] is False
    assert any("knowledge.json" in v for v in record["violations"])


def test_experiment_without_reproduce_spec_is_blocked(tmp_path: Path) -> None:
    exp = _experiment(tmp_path, "k9002", spec=False)
    record = gate.audit_experiment(exp, knowledge_ids={"k9002"}, exclusions={})
    assert record["gated"] is True
    assert any(gate.SPEC_NAME in v for v in record["violations"])


def test_complete_experiment_passes(tmp_path: Path) -> None:
    exp = _experiment(tmp_path, "k9003")
    record = gate.audit_experiment(exp, knowledge_ids={"k9003"}, exclusions={})
    assert record["gated"] is True
    assert record["violations"] == []


def test_runtime_result_number_tamper_is_blocked(tmp_path: Path) -> None:
    """K1708-class edits must fail even when the producing code is unchanged."""
    exp = tmp_path / "experiments" / "k9010"
    exp.mkdir(parents=True)
    entry = exp / "k9010.py"
    entry.write_text("print('science')\n", encoding="utf-8")
    results_path, _spec = rs.finalize_experiment(
        results={
            "cw": {"t_stat": 1.968775},
            "qlike": 0.42,
            "verdict": {"label": "NULL"},
        },
        entrypoint=entry,
        canonical_result="k9010_results.json",
        exp_dir=exp,
    )
    before = gate.audit_experiment(
        exp,
        knowledge_ids={"k9010"},
        exclusions={},
    )
    assert before["violations"] == []
    assert before["canonical_result_identity"] == "clean"

    tampered = json.loads(results_path.read_text(encoding="utf-8"))
    tampered["cw"]["t_stat"] = 3.5
    results_path.write_text(
        json.dumps(tampered, indent=2) + "\n",
        encoding="utf-8",
    )

    record = gate.audit_experiment(
        exp,
        knowledge_ids={"k9010"},
        exclusions={},
    )

    assert any(
        "canonical result identity" in violation
        for violation in record["violations"]
    )


def test_runtime_declared_output_tamper_is_blocked(tmp_path: Path) -> None:
    exp = tmp_path / "experiments" / "k9011"
    exp.mkdir(parents=True)
    entry = exp / "k9011.py"
    entry.write_text("print('science')\n", encoding="utf-8")
    chart = exp / "chart.png"
    chart.write_bytes(b"chart-v1")
    rs.finalize_experiment(
        results={"verdict": "NULL"},
        entrypoint=entry,
        canonical_result="k9011_results.json",
        exp_dir=exp,
        outputs=["chart.png"],
    )
    chart.write_bytes(b"chart-v2")

    record = gate.audit_experiment(exp, knowledge_ids={"k9011"}, exclusions={})
    assert record["artifact_generation"] == "output-mismatch"
    assert any("declared output identity mismatch" in v for v in record["violations"])


def test_runtime_partial_generation_is_blocked_by_completion_receipt(
    tmp_path: Path,
) -> None:
    exp = tmp_path / "experiments" / "k9012"
    exp.mkdir(parents=True)
    entry = exp / "k9012.py"
    entry.write_text("print('science')\n", encoding="utf-8")
    results_path, _ = rs.finalize_experiment(
        results={"stage": 1},
        entrypoint=entry,
        canonical_result="k9012_results.json",
        exp_dir=exp,
    )
    # Simulate termination after a new result became visible but before the
    # completion receipt was promoted.
    results_path.write_text('{"stage": 2}\n', encoding="utf-8")

    record = gate.audit_experiment(exp, knowledge_ids={"k9012"}, exclusions={})
    assert record["artifact_generation"] in {"result-mismatch", "commit-mismatch"}
    assert record["violations"]


def test_directory_with_no_results_is_not_gated(tmp_path: Path) -> None:
    """No archived result = no finding to record and no output to pin.

    Gating these would demand a knowledge entry for a run that produced nothing —
    the 2026-07-19 sweep found 232 such directories (paper-writing sessions,
    ``.gitkeep`` placeholders, abandoned stubs).
    """
    exp = _experiment(tmp_path, "k9004", results=False, spec=False)
    record = gate.audit_experiment(exp, knowledge_ids=set(), exclusions={})
    assert record["gated"] is False
    assert record["violations"] == []


def test_documented_exclusion_is_skipped(tmp_path: Path) -> None:
    exp = _experiment(tmp_path, "k9005", spec=False)
    record = gate.audit_experiment(
        exp, knowledge_ids=set(), exclusions={"k9005": "archived legacy run"}
    )
    assert record["excluded"] is True
    assert record["violations"] == []


def test_directory_without_a_k_id_still_needs_a_spec_but_not_a_knowledge_entry(
    tmp_path: Path,
) -> None:
    """``paper2_taiwan_indiv_rolling_gamma`` has results but no K-id.

    knowledge.json is keyed by K-id, so "an entry mentioning paper2_..." is a demand
    the gate's own lookup could never satisfy — and an unsatisfiable gate gets
    bypassed rather than obeyed. The reproduce_spec half still applies: the run
    produced real output that must stay pinnable.
    """
    complete = _experiment(tmp_path, "paper2_rolling_gamma")
    record = gate.audit_experiment(complete, knowledge_ids=set(), exclusions={})
    assert record["k_id"] is None
    assert record["violations"] == []

    specless = _experiment(tmp_path, "paper2_other_analysis", spec=False)
    record = gate.audit_experiment(specless, knowledge_ids=set(), exclusions={})
    assert [v for v in record["violations"] if gate.SPEC_NAME in v]
    assert not [v for v in record["violations"] if "knowledge.json" in v]


def test_unreadable_knowledge_base_blocks_rather_than_waves_through(tmp_path: Path) -> None:
    """A gate that cannot read its evidence must not approve the merge."""
    exp = _experiment(tmp_path, "k9006")
    record = gate.audit_experiment(exp, knowledge_ids=None, exclusions={})
    assert record["violations"], "unreadable knowledge.json must block"


def test_cmd_check_exits_nonzero_and_prints_a_runnable_remedy(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """End-to-end: the CLI both callers invoke fails, and says how to fix it."""
    exp = _experiment(tmp_path, "k9007", spec=False)
    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(gate, "load_knowledge_ids", lambda root=None: set())
    monkeypatch.setattr(gate, "load_exclusions", lambda root=None: {})

    # Built through the real parser, not a hand-rolled Namespace: a copy of the
    # CLI signature drifts the moment a flag is added, and asserts on an args
    # object no caller ever produces.
    args = gate.build_parser().parse_args(["check", "--path", str(exp)])
    assert gate.cmd_check(args) == 1
    err = capsys.readouterr().err
    assert "BLOCKED" in err
    assert "k9007" in err
    assert gate.EXCLUSIONS_REL.as_posix() in err, "the exemption path must be offered"


def test_cmd_check_passes_when_nothing_was_touched(monkeypatch, capsys) -> None:
    args = gate.build_parser().parse_args(["check"])
    assert gate.cmd_check(args) == 0
    assert "PASS" in capsys.readouterr().out


@pytest.mark.parametrize("name,expected", [
    ("k1719", "k1719"),
    ("K1538_bond_fund_contagion", "k1538"),
    ("paper_notes", None),
])
def test_k_id_extraction(name: str, expected: str | None) -> None:
    assert gate.k_id(name) == expected


# --------------------------------------------------------------------------
# Repo-wide ratchet for the bug class this file's own tests fell into.
#
# 2026-08-04, run 30884267057: 0e8e3391e added --knowledge-ref to this gate,
# cmd_check started reading args.knowledge_ref, and the two tests above — which
# then built argparse.Namespace by hand — went red with
#   AttributeError: 'Namespace' object has no attribute 'knowledge_ref'
# e0d6509da fixed those two by parsing through build_parser(), and its message
# named the class ("a test pinned a copy of the implementation instead of the
# contract", second instance that morning) but swept nothing else. A sweep on
# 2026-08-05 found 158 more hand-rolled namespaces feeding argparse-wired
# handlers — 73 against scripts/task_pool_claim.py, 67 against
# scripts/compute_queue.py. None is broken today; every one of them arms the
# same trap for the next flag. Neither of those two scripts exposes a parser
# builder, which is why their tests had no honest alternative.
#
# So this lives here — where the class was born — rather than staying prose in
# a commit message. It enforces two things, and deliberately not a third:
#   * no site is ALREADY broken (the exact CI-red condition), and
#   * the number of hand-rolled sites per file does not GROW.
# It does not demand the existing 158 be rewritten: that touches twelve test
# files this fire has no write claim on, and a mass rewrite unreviewed is a
# worse trade than a frozen ceiling. The baseline only ever ratchets down.
#
# KNOWN GAP, stated rather than implied. The scan follows handlers wired into
# a parser via set_defaults(func=/fn=/handler=). Scripts with a single command
# and no subparser reach their handler straight out of main(), so their tests
# are invisible here — and the sweep found the class's one live defect in
# exactly that blind spot: tests/test_repend_claim_ownership.py:155 builds a
# namespace with gate=/incident= for mark_task_blocked._mutate_tasks, whose
# real dests are unblock_gate/unblock_incident_id. It passes today only
# because unblock=True returns before those reads. Same shape at
# publish_draft.apply_update and progress_report.build. Widening to those
# needs write access to files outside this fire's declared paths; it is
# recorded in the fire result, not silently absorbed here.
# --------------------------------------------------------------------------

import ast  # noqa: E402  (kept beside the ratchet it serves)
import functools  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
_TEST_DIRS = ("tests", "scripts/tests")
# "" is the repo root itself: tests reach these two ways —
# `import compute_queue` (after a sys.path insert of scripts/) and
# `from scripts import compute_queue` (scripts/ as a package). Resolving only
# the first silently dropped all 68 compute_queue sites from the scan.
_SEARCH_ROOTS = ("", "scripts", "src")

# Hand-rolled namespaces per test file, frozen 2026-08-05. Lower is better;
# the way to lower an entry is to build the args through the script's own
# parser (see build_parser() above and its two callers), not to delete a test.
_HANDROLLED_BASELINE = {
    "tests/test_task_pool_claim.py": 73,
    "tests/test_compute_queue.py": 27,
    "tests/test_compute_queue_binding_settlement.py": 13,
    "scripts/tests/test_compute_queue_amend.py": 11,
    "scripts/tests/test_compute_queue_quota_requeue.py": 10,
    "tests/test_lazypack_async_pipeline.py": 7,
    "scripts/tests/test_compute_queue_model_retirement.py": 6,
    "tests/test_dispatch_supervisor.py": 5,
    "tests/test_ci_paths_ignore.py": 2,
    "tests/test_gates_fail_closed_when_blind.py": 2,
    "scripts/tests/test_gate_blob_preservation.py": 1,
    "scripts/tests/test_release_blocking_priority.py": 1,
}


@functools.lru_cache(maxsize=None)
def _parse(path: Path) -> ast.Module | None:
    # Cached: the production modules are re-consulted once per call site, and
    # scripts/compute_queue.py alone is reached ~67 times. Uncached, the scan
    # cost 60s of CI per test; cached it is a couple of seconds.
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return None


def _resolve_module(name: str) -> Path | None:
    """Map a name a test imported onto a file under scripts/ or src/.

    Only explicit imports are followed. Guessing would make the ratchet's
    verdict depend on filesystem coincidence, and a gate whose scope drifts
    with the checkout is not a gate.
    """
    if not name:
        return None
    rel = name.replace(".", "/")
    for base in _SEARCH_ROOTS:
        root = REPO_ROOT / base
        for cand in (root / f"{rel}.py", root / rel / "__init__.py"):
            if cand.is_file():
                return cand
    return None


def _namespace_keys(call: ast.Call) -> set[str] | None:
    """Keywords of an argparse.Namespace(...) / SimpleNamespace(...) literal."""
    fn = call.func
    name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
    if name not in {"Namespace", "SimpleNamespace"}:
        return None
    if any(kw.arg is None for kw in call.keywords):
        return None  # **spread — the key set is not knowable statically
    return {kw.arg for kw in call.keywords if kw.arg}


def _is_argparse_handler(module: ast.Module, name: str) -> bool:
    """Wired into a parser via set_defaults(func=name) — or fn=, or handler=.

    The keyword is not standardised: task_pool_claim.py dispatches on ``fn=``
    and guided_host_migration.py on ``handler=``. Matching only ``func=`` would
    have put the single largest cluster of hand-rolled sites in the repo
    (~85 in tests/test_task_pool_claim.py) outside this ratchet's field of view.
    """
    for node in ast.walk(module):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "set_defaults":
            continue
        for kw in node.keywords:
            if kw.arg not in {"func", "fn", "handler"}:
                continue
            wired = kw.value.id if isinstance(kw.value, ast.Name) else (
                kw.value.attr if isinstance(kw.value, ast.Attribute) else "")
            if wired == name:
                return True
    return False


def _attrs_read(fn: ast.FunctionDef, param: str) -> set[str]:
    return {
        node.attr for node in ast.walk(fn)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == param
        and isinstance(node.ctx, ast.Load)
    }


@functools.lru_cache(maxsize=1)
def _scan_handrolled_args() -> tuple[dict, ...]:
    """Every hand-rolled namespace handed to an argparse-wired handler."""
    sites: list[dict] = []
    for test_dir in _TEST_DIRS:
        for test_path in sorted((REPO_ROOT / test_dir).rglob("test_*.py")):
            tree = _parse(test_path)
            if tree is None:
                continue
            aliases: dict[str, str] = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        aliases[a.asname or a.name.split(".")[0]] = a.name
                elif isinstance(node, ast.ImportFrom) and node.module:
                    for a in node.names:
                        aliases[a.asname or a.name] = f"{node.module}.{a.name}"

            for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
                local: dict[str, tuple[set[str], int]] = {}
                for node in ast.walk(fn):
                    if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                        keys = _namespace_keys(node.value)
                        if keys is None:
                            continue
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                local[target.id] = (keys, node.lineno)

                for node in ast.walk(fn):
                    if not isinstance(node, ast.Call):
                        continue
                    callee = node.func
                    if isinstance(callee, ast.Attribute) and isinstance(callee.value, ast.Name):
                        alias, handler_name = callee.value.id, callee.attr
                    else:
                        continue
                    module_path = _resolve_module(aliases.get(alias, alias))
                    if module_path is None:
                        continue
                    module = _parse(module_path)
                    if module is None or not _is_argparse_handler(module, handler_name):
                        continue
                    handler = next(
                        (n for n in module.body
                         if isinstance(n, ast.FunctionDef) and n.name == handler_name),
                        None,
                    )
                    if handler is None or not handler.args.args:
                        continue

                    for arg in node.args:
                        if isinstance(arg, ast.Call):
                            keys, lineno = _namespace_keys(arg), arg.lineno
                        elif isinstance(arg, ast.Name) and arg.id in local:
                            keys, lineno = local[arg.id]
                        else:
                            continue
                        if keys is None:
                            continue
                        reads = _attrs_read(handler, handler.args.args[0].arg)
                        sites.append({
                            "test": test_path.relative_to(REPO_ROOT).as_posix(),
                            "line": lineno,
                            "handler": f"{module_path.name}:{handler_name}",
                            "missing": tuple(sorted(reads - keys)),
                        })
    return tuple(sites)


def test_no_handrolled_args_object_is_missing_an_attribute_its_handler_reads() -> None:
    """The exact 2026-08-04 red, checked statically instead of at runtime.

    A hand-rolled namespace only raises AttributeError if the test happens to
    reach the branch that reads the new flag. This asserts the whole attribute
    set up front, so a flag added behind a rarely-exercised branch cannot ship
    green here and go red somewhere else later.
    """
    broken = [s for s in _scan_handrolled_args() if s["missing"]]
    assert not broken, "\n".join(
        [
            "A test hands a hand-rolled args object to an argparse handler that "
            "reads attributes it does not supply.",
            "This is run 30884267057's failure, statically: "
            "AttributeError: 'Namespace' object has no attribute 'knowledge_ref'.",
            "Fix at the source — build the args through the script's own parser "
            "(add a build_parser() there if it has none, as e0d6509da did here), "
            "rather than adding the missing key to the copy:",
        ]
        + [
            f"  {s['test']}:{s['line']} -> {s['handler']} missing {s['missing']}"
            for s in broken
        ]
    )


def test_handrolled_args_objects_do_not_multiply() -> None:
    """Downward ratchet on the 158 sites inherited on 2026-08-05.

    Each entry is a test asserting on an args object no caller ever produces.
    They are allowed to stay while they are correct; they are not allowed to
    breed. Reducing a number here is always right — raising one means a new
    copy of a CLI signature was written after the class was already known.
    """
    counts: dict[str, int] = {}
    for site in _scan_handrolled_args():
        counts[site["test"]] = counts.get(site["test"], 0) + 1

    regressions = [
        f"  {test}: {count} hand-rolled (baseline {_HANDROLLED_BASELINE.get(test, 0)})"
        for test, count in sorted(counts.items())
        if count > _HANDROLLED_BASELINE.get(test, 0)
    ]
    assert not regressions, "\n".join(
        [
            "New hand-rolled args object(s) for an argparse handler:",
            *regressions,
            "Build them through the script's own parser instead — "
            "parser.parse_args(['subcmd', '--flag', value]) — so a new flag "
            "arrives with its default rather than as an AttributeError.",
        ]
    )

    stale = [
        f"  {test}: baseline {baseline}, actual {counts.get(test, 0)}"
        for test, baseline in sorted(_HANDROLLED_BASELINE.items())
        if counts.get(test, 0) < baseline
    ]
    assert not stale, "\n".join(
        [
            "Sites were cleaned up — lower the baseline so the ratchet holds "
            "the new ground (that is the whole point of it):",
            *stale,
        ]
    )
