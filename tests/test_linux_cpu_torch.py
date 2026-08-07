"""CI may use CPU wheels, but research hosts must keep accelerator choice."""
from __future__ import annotations

from importlib import metadata
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib

from packaging.markers import default_environment
from packaging.requirements import Requirement
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
CPU_INDEX = "https://download.pytorch.org/whl/cpu"
PYPI_INDEX = "https://pypi.org/simple"
EXPECTED_TORCH_VERSION = "2.10.0"
EXPECTED_XGBOOST_VERSION = "3.2.0"
EXPECTED_SB3_VERSION = "2.9.0"
CI_SYNC_COMMAND = (
    "uv sync --frozen --no-default-groups "
    "--group dev --group ci-ml --extra dev"
)


def _read_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _lock_packages(lock: dict, name: str) -> list[dict]:
    return [package for package in lock["package"] if package["name"] == name]


def _requirement_name(requirement: str) -> str:
    match = re.match(r"\s*([A-Za-z0-9_.-]+)", requirement)
    assert match, f"cannot parse requirement name: {requirement!r}"
    return match.group(1).lower().replace("_", "-")


def _conflict_pair(*entries: tuple[str, str]) -> frozenset[tuple[str, str]]:
    return frozenset(entries)


def _exported_requirements(*args: str) -> tuple[set[str], list[str]]:
    completed = subprocess.run(
        [
            "uv",
            "export",
            "--frozen",
            "--no-hashes",
            "--no-header",
            "--no-annotate",
            *args,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    names: set[str] = set()
    for line in lines:
        if line.startswith(("#", "--", ".", "-e ")):
            continue
        names.add(_requirement_name(line))
    return names, lines


def _active_requirement_lines(lines: list[str], *, sys_platform: str) -> list[str]:
    """Evaluate universal-export markers for one concrete target platform."""
    environment = default_environment()
    if sys_platform == "linux":
        environment.update(
            {
                "sys_platform": "linux",
                "os_name": "posix",
                "platform_system": "Linux",
                "platform_machine": "x86_64",
            }
        )
    elif sys_platform == "win32":
        environment.update(
            {
                "sys_platform": "win32",
                "os_name": "nt",
                "platform_system": "Windows",
                "platform_machine": "AMD64",
            }
        )
    else:
        raise ValueError(f"unsupported test platform: {sys_platform}")

    active: list[str] = []
    for line in lines:
        if line.startswith(("#", "--", ".", "-e ")):
            continue
        requirement = Requirement(line)
        if requirement.marker is None or requirement.marker.evaluate(environment):
            active.append(line)
    return active


def _normalized_command(command: str) -> str:
    return " ".join(command.split())


def _command_invocations(command: str, executable: str) -> list[str]:
    """Extract direct shell commands, not quoted prose that names a command."""
    invocations: list[str] = []
    prefix = re.compile(
        rf"^(?:(?:if|then|do|time|command|exec)\s+|!\s+)*"
        rf"(?P<command>{re.escape(executable)}(?:\s+.*)?$)"
    )
    for raw_line in command.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        for segment in re.split(r"\s*(?:&&|\|\||;)\s*", line):
            match = prefix.match(segment.strip())
            if match:
                invocations.append(_normalized_command(match.group("command")))
    return invocations


def test_pyproject_separates_research_and_ci_ml_profiles() -> None:
    project = _read_toml(ROOT / "pyproject.toml")
    base_dependencies = set(project["project"]["dependencies"])
    optional = project["project"]["optional-dependencies"]
    groups = project["dependency-groups"]
    uv = project["tool"]["uv"]

    forbidden_base_names = {
        "stable-baselines3",
        "torch",
        "xgboost",
        "xgboost-cpu",
    }
    assert not ({_requirement_name(item) for item in base_dependencies} & forbidden_base_names)

    assert set(optional["research-ml"]) == {
        f"stable-baselines3=={EXPECTED_SB3_VERSION}",
        f"torch=={EXPECTED_TORCH_VERSION}",
        f"xgboost=={EXPECTED_XGBOOST_VERSION}",
    }
    assert set(optional["ci-ml-cpu"]) == {
        f"stable-baselines3=={EXPECTED_SB3_VERSION}",
        f"torch=={EXPECTED_TORCH_VERSION}",
        f"xgboost-cpu=={EXPECTED_XGBOOST_VERSION}; sys_platform == 'linux'",
        f"xgboost=={EXPECTED_XGBOOST_VERSION}; sys_platform != 'linux'",
    }
    assert set(optional["dev"]) >= {"packaging>=24.0", "pytest>=8.0"}
    assert groups["runtime-ml"] == ["volpred[research-ml]"]
    assert groups["ci-ml"] == ["volpred[ci-ml-cpu]"]
    assert uv["default-groups"] == ["dev", "runtime-ml"]

    conflicts = {
        frozenset((kind, value) for entry in conflict for kind, value in entry.items())
        for conflict in uv["conflicts"]
    }
    assert conflicts == {
        _conflict_pair(("extra", "research-ml"), ("extra", "ci-ml-cpu")),
        _conflict_pair(("group", "runtime-ml"), ("group", "ci-ml")),
        _conflict_pair(("group", "runtime-ml"), ("extra", "ci-ml-cpu")),
        _conflict_pair(("group", "ci-ml"), ("extra", "research-ml")),
    }

    assert uv["sources"]["torch"] == [
        {"index": "pytorch-cpu", "extra": "ci-ml-cpu"}
    ]
    cpu_indexes = [
        entry for entry in uv["index"] if entry.get("name") == "pytorch-cpu"
    ]
    assert cpu_indexes == [
        {"name": "pytorch-cpu", "url": CPU_INDEX, "explicit": True}
    ]


def test_lock_keeps_cpu_and_accelerator_profiles_version_aligned() -> None:
    lock = _read_toml(ROOT / "uv.lock")
    torch_packages = _lock_packages(lock, "torch")
    source_versions = {
        (
            package["version"],
            package.get("source", {}).get("registry"),
        )
        for package in torch_packages
    }

    # The explicit CPU index uses `+cpu` for Linux wheels but may
    # expose the same public version without a local suffix on other
    # platforms. A universal lock can legitimately contain both.
    assert (
        f"{EXPECTED_TORCH_VERSION}+cpu",
        CPU_INDEX,
    ) in source_versions
    assert (
        EXPECTED_TORCH_VERSION,
        PYPI_INDEX,
    ) in source_versions
    assert all(
        version in {EXPECTED_TORCH_VERSION, f"{EXPECTED_TORCH_VERSION}+cpu"}
        for version, _ in source_versions
    )
    assert all(
        registry == CPU_INDEX
        for version, registry in source_versions
        if version == f"{EXPECTED_TORCH_VERSION}+cpu"
    )
    assert [package["version"] for package in _lock_packages(lock, "xgboost-cpu")] == [
        EXPECTED_XGBOOST_VERSION
    ]
    assert [package["version"] for package in _lock_packages(lock, "xgboost")] == [
        EXPECTED_XGBOOST_VERSION
    ]
    assert [
        package["version"] for package in _lock_packages(lock, "stable-baselines3")
    ] == [EXPECTED_SB3_VERSION]

    project_package = next(
        package for package in lock["package"] if package["name"] == "volpred"
    )
    assert set(project_package["optional-dependencies"]) >= {
        "research-ml",
        "ci-ml-cpu",
    }
    assert set(project_package["dev-dependencies"]) >= {
        "runtime-ml",
        "ci-ml",
    }


def test_default_profile_exports_linux_accelerator_research_stack() -> None:
    _, lines = _exported_requirements()
    linux_lines = _active_requirement_lines(lines, sys_platform="linux")
    linux_names = {_requirement_name(line) for line in linux_lines}

    assert any(
        re.match(
            rf"^torch=={re.escape(EXPECTED_TORCH_VERSION)}(?:\s*;|$)",
            line,
        )
        for line in linux_lines
    )
    assert not any(
        line.startswith(f"torch=={EXPECTED_TORCH_VERSION}+cpu")
        for line in linux_lines
    )
    assert any(
        line.startswith(f"xgboost=={EXPECTED_XGBOOST_VERSION}")
        for line in linux_lines
    )
    assert any(
        line.startswith(f"stable-baselines3=={EXPECTED_SB3_VERSION}")
        for line in linux_lines
    )
    assert "xgboost" in linux_names
    assert "xgboost-cpu" not in linux_names
    assert any(
        name.startswith("nvidia-") or name in {"cuda-bindings", "triton"}
        for name in linux_names
    ), "standard Linux research profile lost its accelerator runtime"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux CI profile export")
def test_linux_ci_profile_exports_no_accelerator_runtime() -> None:
    _, lines = _exported_requirements(
        "--no-default-groups",
        "--group",
        "dev",
        "--group",
        "ci-ml",
        "--extra",
        "dev",
    )
    linux_lines = _active_requirement_lines(lines, sys_platform="linux")
    linux_names = {_requirement_name(line) for line in linux_lines}

    assert any(
        line.startswith(f"torch=={EXPECTED_TORCH_VERSION}+cpu")
        for line in linux_lines
    )
    assert not any(
        re.match(
            rf"^torch=={re.escape(EXPECTED_TORCH_VERSION)}(?:\s*;|$)",
            line,
        )
        for line in linux_lines
    )
    assert any(
        line.startswith(f"xgboost-cpu=={EXPECTED_XGBOOST_VERSION}")
        for line in linux_lines
    )
    assert any(
        line.startswith(f"stable-baselines3=={EXPECTED_SB3_VERSION}")
        for line in linux_lines
    )
    assert "xgboost-cpu" in linux_names
    assert "xgboost" not in linux_names
    accelerator_packages = {
        name
        for name in linux_names
        if name.startswith("nvidia-")
        or name.startswith("cuda-")
        or name in {"triton", "pytorch-triton"}
    }
    assert not accelerator_packages


def test_every_uv_workflow_is_bound_to_the_cpu_profile() -> None:
    covered_uv_run_jobs: set[tuple[str, str]] = set()

    workflow_paths = sorted(WORKFLOWS.glob("*.yml")) + sorted(
        WORKFLOWS.glob("*.yaml")
    )
    assert workflow_paths, "workflow inventory unexpectedly empty"

    for path in workflow_paths:
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in workflow.get("jobs", {}).items():
            steps = job.get("steps", [])
            sync_steps: list[tuple[int, str]] = []
            uv_run_steps: list[tuple[int, str]] = []

            for index, step in enumerate(steps):
                command = str(step.get("run", ""))
                sync_steps.extend(
                    (index, invocation)
                    for invocation in _command_invocations(command, "uv sync")
                )
                uv_run_steps.extend(
                    (index, invocation)
                    for invocation in _command_invocations(command, "uv run")
                )

            if not sync_steps and not uv_run_steps:
                continue

            assert job.get("env", {}).get("VOLPRED_EXPECT_CPU_ML") == "1", (
                f"{path.name}:{job_name} uses the project uv environment "
                "without declaring the CPU-only CI runtime contract"
            )
            canonical_sync_indexes = [
                index
                for index, step in enumerate(steps)
                if step.get("name") == "Sync explicit Linux CPU CI profile"
            ]
            assert len(canonical_sync_indexes) == 1, (
                f"{path.name}:{job_name} must own exactly one named CPU sync step"
            )
            assert sync_steps == [
                (canonical_sync_indexes[0], CI_SYNC_COMMAND)
            ], f"{path.name}:{job_name} must perform exactly one canonical CPU sync"

            sync_index = sync_steps[0][0]
            for run_index, invocation in uv_run_steps:
                assert run_index > sync_index, (
                    f"{path.name}:{job_name} runs {invocation!r} before CPU sync"
                )
                assert invocation.startswith("uv run --no-sync "), (
                    f"{path.name}:{job_name} may reselect default research ML: "
                    f"{invocation!r}"
                )

            if uv_run_steps:
                covered_uv_run_jobs.add((path.name, job_name))

    assert {
        ("pytest.yml", "pytest"),
        ("queue-invariants.yml", "real-queue"),
    } <= covered_uv_run_jobs


@pytest.mark.skipif(
    sys.platform != "linux" or os.environ.get("VOLPRED_EXPECT_CPU_ML") != "1",
    reason="only the explicit Linux CPU CI environment promises this runtime",
)
def test_installed_linux_ci_ml_stack_is_cpu_only() -> None:
    import torch
    import xgboost

    assert torch.__version__ == f"{EXPECTED_TORCH_VERSION}+cpu"
    assert torch.version.cuda is None
    assert not torch.cuda.is_available()
    assert xgboost.__version__ == EXPECTED_XGBOOST_VERSION
    assert metadata.version("xgboost-cpu") == EXPECTED_XGBOOST_VERSION
    with pytest.raises(metadata.PackageNotFoundError):
        metadata.version("xgboost")
