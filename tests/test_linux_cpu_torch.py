"""CI may use CPU wheels, but research hosts must keep accelerator choice."""
from __future__ import annotations

from importlib import metadata
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[1]
CPU_INDEX = "https://download.pytorch.org/whl/cpu"
PYPI_INDEX = "https://pypi.org/simple"
EXPECTED_TORCH_VERSION = "2.10.0"
EXPECTED_XGBOOST_VERSION = "3.2.0"
EXPECTED_SB3_VERSION = "2.9.0"


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
    cpu = [
        package
        for package in torch_packages
        if package.get("source", {}).get("registry") == CPU_INDEX
    ]
    accelerator_capable = [
        package
        for package in torch_packages
        if package.get("source", {}).get("registry") == PYPI_INDEX
    ]

    assert [package["version"] for package in cpu] == [
        f"{EXPECTED_TORCH_VERSION}+cpu"
    ]
    assert [package["version"] for package in accelerator_capable] == [
        EXPECTED_TORCH_VERSION
    ]
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


def test_default_profile_exports_accelerator_capable_research_distributions() -> None:
    names, lines = _exported_requirements()

    assert any(line.startswith(f"torch=={EXPECTED_TORCH_VERSION}") for line in lines)
    assert not any(
        line.startswith(f"torch=={EXPECTED_TORCH_VERSION}+cpu") for line in lines
    )
    assert any(line.startswith(f"xgboost=={EXPECTED_XGBOOST_VERSION}") for line in lines)
    assert any(
        line.startswith(f"stable-baselines3=={EXPECTED_SB3_VERSION}") for line in lines
    )
    assert "xgboost-cpu" not in names


@pytest.mark.skipif(sys.platform != "linux", reason="Linux CI profile export")
def test_linux_ci_profile_exports_no_accelerator_runtime() -> None:
    names, lines = _exported_requirements(
        "--no-default-groups",
        "--group",
        "dev",
        "--group",
        "ci-ml",
        "--extra",
        "dev",
    )

    assert any(line.startswith(f"torch=={EXPECTED_TORCH_VERSION}+cpu") for line in lines)
    assert any(
        line.startswith(f"xgboost-cpu=={EXPECTED_XGBOOST_VERSION}") for line in lines
    )
    assert any(
        line.startswith(f"stable-baselines3=={EXPECTED_SB3_VERSION}") for line in lines
    )
    assert "xgboost" not in names
    accelerator_packages = {
        name
        for name in names
        if name.startswith("nvidia-")
        or name.startswith("cuda-")
        or name in {"triton", "pytorch-triton"}
    }
    assert not accelerator_packages


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
