"""Emit ``reproduce_spec.json`` AT RUN TIME, from the process that wrote the results.

THE BUG CLASS
-------------
K1708 (2026-07) failed Codex primary-path review three rounds running. One of the
two root causes was not a bug in the experiment at all -- it was a process hole:

  ``reproduce_spec.json`` only became a convention in 2026-07, so specs were
  written by hand, *after* the run, sometimes weeks after. By then the script had
  moved. ``K1708_results.json`` records ``code_trace`` sha ``43bffdd...`` at
  91,752 bytes; ``experiments/k1708/K1708.py`` on disk is 126,998 bytes. The spec
  therefore describes a program that did not produce the results it claims to pin.

A spec written after the fact can always be wrong, and nobody can tell from the
artifact alone. A spec written by the run itself cannot: the bytes it hashes are
the bytes the interpreter is executing. That is the whole idea here. The fix is
not "remember to write the spec" -- it is "the spec is a side effect of running".

HOW TO USE IT
-------------
At the end of an experiment script, replace the hand-rolled ``json.dump`` of the
results with one call::

    from volpred.research.reproduce_spec import finalize_experiment

    finalize_experiment(
        results=payload,                     # the dict you were about to dump
        entrypoint=__file__,
        canonical_result="K1750_results.json",
        inputs=["experiments/k1750/data/spy.csv"],
        seeds=[("numpy", 1750)],
        started_at=T0,                       # time.time() taken at import
    )

That writes ``K1750_results.json`` and ``reproduce_spec.json`` side by side, from
a SINGLE ``trace_file()`` call. ``results["code_trace"]`` and
``spec["entrypoint"]`` take their sha and byte size from that same snapshot, so
the K1708 identity divergence is not merely discouraged, it is unrepresentable.
Their ``path`` fields intentionally use different schemas: repo-relative in the
result trace, experiment-relative in the runnable spec.

If a script must keep its own results writer, use :func:`write_reproduce_spec`
and take ``code_trace`` from its return value -- never recompute the hash.

WHAT THE GATE DOES WITH IT
--------------------------
``entrypoint.sha256`` / ``entrypoint.size_bytes`` are additions to the v1 schema
(``scripts/reproduce_check.py:load_spec`` ignores unknown keys, so old specs stay
valid). Their presence is also the forward-ratchet marker used by
``scripts/check_experiment_artifacts.py``: a spec that carries a sha is a spec a
run produced, so the gate may hold it to the drift and gate-preservation rules.
A spec without one is pre-convention and is left alone -- see that module's
``_drift_violation``.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "SPEC_NAME",
    "SPEC_SCHEMA",
    "trace_file",
    "runtime_environment",
    "build_reproduce_spec",
    "write_reproduce_spec",
    "finalize_experiment",
]

SPEC_NAME = "reproduce_spec.json"
SPEC_SCHEMA = "volpred.reproduce_spec.v1"

# reproduce_check.MAX_TIMEOUT_SECONDS (24h — raised 2026-07-22 so K1730's honest
# 13448s run could declare a timeout it does not blow through). Duplicated rather
# than imported because scripts/ is not importable from an experiment's sys.path;
# a test asserts the two stay equal, so the duplication cannot drift silently.
MAX_TIMEOUT_SECONDS = 86_400

# Runtime x this = declared timeout. A spec that pins the timeout to the exact
# observed runtime turns any slower machine into a false reproduction failure.
_TIMEOUT_SLACK = 3.0
_MIN_TIMEOUT = 60


def _repo_root() -> Path:
    """Repository root, found by walking up from this file."""
    return Path(__file__).resolve().parents[3]


def trace_file(path: str | os.PathLike[str], *, root: Path | None = None) -> dict[str, Any]:
    """``{path, sha256, size_bytes}`` for one file, repo-relative where possible.

    THE one place a file identity is computed. ``code_trace`` in results and
    ``entrypoint`` in the spec both come from here, called once, so they cannot
    describe different bytes -- the K1708 failure.

    ``size_bytes`` is taken from the bytes that were hashed, not from ``stat()``:
    a stat() taken separately can observe a different revision of a file being
    rewritten underneath us, and then the pair silently disagrees.
    """
    target = Path(path).resolve()
    data = target.read_bytes()
    root = (root or _repo_root()).resolve()
    try:
        rel = target.relative_to(root).as_posix()
    except ValueError:
        # Outside the checkout (a scratch copy, /tmp probe). Honest absolute path
        # beats a fabricated relative one -- the reader must see it is off-tree.
        rel = target.as_posix()
    return {
        "path": rel,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


def _version(module_name: str) -> str | None:
    try:
        module = __import__(module_name)
    except Exception:  # noqa: BLE001  # silent-ok: an absent optional dep is data, not an error —
        # the caller records ``None`` in the spec, which is the honest answer to "which numpy
        # produced this?" when numpy was never installed. Warning here would fire on every spec.
        return None
    return str(getattr(module, "__version__", "unknown"))


def runtime_environment(seeds: Sequence[tuple[str, int | str]] | None = None) -> dict[str, Any]:
    """Interpreter / library versions and declared seeds, as observed right now."""
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "numpy": _version("numpy"),
        "pandas": _version("pandas"),
        "scipy": _version("scipy"),
        "seeds": [{"library": lib, "value": val} for lib, val in (seeds or [])],
    }


def _randomness_block(seeds: Sequence[tuple[str, int | str]] | None) -> dict[str, Any]:
    if not seeds:
        # 'not_applicable' is a claim about the science, so it is only made when the
        # caller declared no seeds at all. Guessing either way would put a false
        # reproducibility statement into a machine-checked artifact.
        return {"status": "not_applicable", "seeds": []}
    return {
        "status": "declared",
        "seeds": [{"library": lib, "value": val} for lib, val in seeds],
    }


def _timeout_seconds(runtime_seconds: float | None) -> int:
    if runtime_seconds is None or runtime_seconds <= 0:
        return 900
    bound = int(runtime_seconds * _TIMEOUT_SLACK) + _MIN_TIMEOUT
    return max(_MIN_TIMEOUT, min(bound, MAX_TIMEOUT_SECONDS))


def build_reproduce_spec(
    *,
    exp_dir: str | os.PathLike[str],
    entrypoint: str | os.PathLike[str],
    canonical_result: str,
    inputs: Iterable[str | os.PathLike[str]] = (),
    outputs: Iterable[str] = (),
    seeds: Sequence[tuple[str, int | str]] | None = None,
    runtime_seconds: float | None = None,
    timeout_seconds: int | None = None,
    args: Sequence[str] = (),
    network: str = "deny",
    comparison: Mapping[str, Any] | None = None,
    entrypoint_trace: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the spec dict. Pure; :func:`write_reproduce_spec` persists it.

    ``entrypoint_trace`` lets a caller that already traced the entrypoint (for the
    results' ``code_trace``) hand the SAME snapshot in rather than recompute it.
    """
    exp_path = Path(exp_dir).resolve()
    # reproduce_check resolves inputs against ``exp_dir.parents[1]``; derive the root
    # the same way rather than from this file's location, or an emitted spec is only
    # loadable when the experiment happens to live in the same checkout as the helper.
    root = exp_path.parents[1] if len(exp_path.parents) >= 2 else _repo_root()
    trace = dict(entrypoint_trace) if entrypoint_trace else trace_file(entrypoint, root=root)

    entry_abs = Path(entrypoint).resolve()
    try:
        entry_rel = entry_abs.relative_to(exp_path).as_posix()
    except ValueError:
        # The v1 schema requires entrypoint.path to sit inside the experiment dir.
        # Refuse rather than emit a spec that reproduce_check will reject anyway --
        # a spec that exists but never validates is worse than a loud failure.
        raise ValueError(
            f"entrypoint {entry_abs} is not inside experiment dir {exp_path}; "
            "the v1 schema requires entrypoint.path to be experiment-relative"
        ) from None

    default_ignore = ["/created_at", "/runtime_seconds", "/run_utc", "/runtime_env"]
    ignore_reasons = {
        "/created_at": "Execution timestamp; written after every scientific value is computed.",
        "/runtime_seconds": "Wall-clock performance metadata; not an input to any estimate or verdict.",
        "/run_utc": "Execution timestamp; not an input to any estimate or verdict.",
        "/runtime_env": "Interpreter and library versions of the recording host; machine-dependent by construction.",
    }
    cmp_block: dict[str, Any] = {
        "rtol": 1e-9,
        "atol": 1e-12,
        "ignore_pointers": default_ignore,
        "ignore_reasons": ignore_reasons,
    }
    if comparison:
        cmp_block.update(comparison)
        # ignore_reasons must document exactly the ignored pointers (load_spec
        # enforces set equality); an override of one half silently breaks the other.
        pointers = cmp_block.get("ignore_pointers", [])
        reasons = cmp_block.get("ignore_reasons", {})
        if set(pointers) != set(reasons):
            raise ValueError(
                "comparison.ignore_reasons must document exactly the ignored pointers; "
                f"got pointers={sorted(pointers)} reasons={sorted(reasons)}"
            )

    input_traces = [trace_file(p, root=root) for p in inputs]

    return {
        "schema_version": SPEC_SCHEMA,
        "generated_by": "volpred.research.reproduce_spec",
        "generated_at_runtime": True,
        "entrypoint": {
            "path": entry_rel,
            "args": list(args),
            "sha256": trace["sha256"],
            "size_bytes": trace["size_bytes"],
        },
        "canonical_result": canonical_result,
        "inputs": input_traces,
        "outputs": sorted(outputs),
        "timeout_seconds": (
            timeout_seconds if timeout_seconds is not None else _timeout_seconds(runtime_seconds)
        ),
        "network": network,
        "randomness": _randomness_block(seeds),
        "runtime": {
            "runtime_seconds": round(float(runtime_seconds), 3) if runtime_seconds else None,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "environment": runtime_environment(seeds),
        "comparison": cmp_block,
    }


def write_reproduce_spec(
    *,
    exp_dir: str | os.PathLike[str] | None = None,
    entrypoint: str | os.PathLike[str],
    canonical_result: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build and write ``<exp_dir>/reproduce_spec.json``. Returns the spec dict.

    ``exp_dir`` defaults to the entrypoint's directory, which is the layout every
    experiment already uses.
    """
    entry = Path(entrypoint).resolve()
    exp_path = Path(exp_dir).resolve() if exp_dir is not None else entry.parent
    spec = build_reproduce_spec(
        exp_dir=exp_path,
        entrypoint=entry,
        canonical_result=canonical_result,
        **kwargs,
    )
    out = exp_path / SPEC_NAME
    out.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return spec


def finalize_experiment(
    *,
    results: dict[str, Any],
    entrypoint: str | os.PathLike[str],
    canonical_result: str,
    exp_dir: str | os.PathLike[str] | None = None,
    inputs: Iterable[str | os.PathLike[str]] = (),
    outputs: Iterable[str] = (),
    seeds: Sequence[tuple[str, int | str]] | None = None,
    started_at: float | None = None,
    runtime_seconds: float | None = None,
    **spec_kwargs: Any,
) -> tuple[Path, dict[str, Any]]:
    """Write the results JSON and its spec together. The recommended entry point.

    Both artifacts take their file identity from ONE :func:`trace_file` call, so
    ``results["code_trace"]`` and ``spec["entrypoint"]`` describe the same bytes
    by construction rather than by discipline. Returns ``(results_path, spec)``.

    An existing ``results["code_trace"]`` is overwritten deliberately: a
    hand-written trace is exactly the artifact that drifted in K1708, and silently
    preferring it would reintroduce the bug this function exists to remove.
    """
    entry = Path(entrypoint).resolve()
    exp_path = Path(exp_dir).resolve() if exp_dir is not None else entry.parent
    elapsed = runtime_seconds
    if elapsed is None and started_at is not None:
        elapsed = max(0.0, time.time() - started_at)

    root = exp_path.parents[1] if len(exp_path.parents) >= 2 else _repo_root()
    trace = trace_file(entry, root=root)

    payload = dict(results)
    payload["code_trace"] = trace
    if elapsed is not None:
        payload.setdefault("runtime_seconds", round(float(elapsed), 3))
    payload.setdefault("runtime_env", runtime_environment(seeds))

    exp_path.mkdir(parents=True, exist_ok=True)
    results_path = exp_path / canonical_result
    results_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )

    spec = build_reproduce_spec(
        exp_dir=exp_path,
        entrypoint=entry,
        canonical_result=canonical_result,
        inputs=inputs,
        outputs=sorted({*outputs, canonical_result}),
        seeds=seeds,
        runtime_seconds=elapsed,
        entrypoint_trace=trace,
        **spec_kwargs,
    )
    (exp_path / SPEC_NAME).write_text(
        json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"[reproduce_spec] wrote {results_path.name} + {SPEC_NAME} "
        f"(entrypoint {trace['sha256'][:12]}, {trace['size_bytes']} bytes)",
        file=sys.stderr,
    )
    return results_path, spec
