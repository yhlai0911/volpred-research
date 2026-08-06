"""Linux CI must use CPU-only ML distributions without version drift."""
from __future__ import annotations

from importlib import metadata
import sys
import tomllib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CPU_INDEX = "https://download.pytorch.org/whl/cpu"
PYPI_INDEX = "https://pypi.org/simple"
EXPECTED_TORCH_VERSION = "2.10.0"
EXPECTED_XGBOOST_VERSION = "3.2.0"


def _read_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _lock_packages(lock: dict, name: str) -> list[dict]:
    return [package for package in lock["package"] if package["name"] == name]


def test_pyproject_routes_linux_ml_to_cpu_distributions() -> None:
    project = _read_toml(ROOT / "pyproject.toml")
    dependencies = set(project["project"]["dependencies"])
    uv = project["tool"]["uv"]

    assert f"torch=={EXPECTED_TORCH_VERSION}" in dependencies
    assert (
        f"xgboost-cpu=={EXPECTED_XGBOOST_VERSION}; sys_platform == 'linux'"
        in dependencies
    )
    assert (
        f"xgboost=={EXPECTED_XGBOOST_VERSION}; sys_platform != 'linux'"
        in dependencies
    )

    assert uv["sources"]["torch"] == [
        {"index": "pytorch-cpu", "marker": "sys_platform == 'linux'"}
    ]
    cpu_indexes = [
        entry for entry in uv["index"] if entry.get("name") == "pytorch-cpu"
    ]
    assert cpu_indexes == [
        {"name": "pytorch-cpu", "url": CPU_INDEX, "explicit": True}
    ]


def test_lock_keeps_cpu_and_non_linux_ml_versions_aligned() -> None:
    lock = _read_toml(ROOT / "uv.lock")
    torch_packages = _lock_packages(lock, "torch")
    linux_cpu = [
        package
        for package in torch_packages
        if package.get("source", {}).get("registry") == CPU_INDEX
    ]
    non_linux_pypi = [
        package
        for package in torch_packages
        if package.get("source", {}).get("registry") == PYPI_INDEX
    ]

    assert len(linux_cpu) == 1
    assert len(non_linux_pypi) == 1
    assert linux_cpu[0]["version"] == f"{EXPECTED_TORCH_VERSION}+cpu"
    assert non_linux_pypi[0]["version"] == EXPECTED_TORCH_VERSION
    assert any(
        "sys_platform == 'linux'" in marker
        for marker in linux_cpu[0]["resolution-markers"]
    )
    assert any(
        "sys_platform != 'linux'" in marker
        for marker in non_linux_pypi[0]["resolution-markers"]
    )

    xgboost_cpu = _lock_packages(lock, "xgboost-cpu")
    xgboost_full = _lock_packages(lock, "xgboost")
    assert [package["version"] for package in xgboost_cpu] == [
        EXPECTED_XGBOOST_VERSION
    ]
    assert [package["version"] for package in xgboost_full] == [
        EXPECTED_XGBOOST_VERSION
    ]

    project_package = next(
        package for package in lock["package"] if package["name"] == "volpred"
    )
    project_dependencies = project_package["dependencies"]
    assert {
        dependency.get("marker")
        for dependency in project_dependencies
        if dependency["name"] == "xgboost-cpu"
    } == {"sys_platform == 'linux'"}
    assert {
        dependency.get("marker")
        for dependency in project_dependencies
        if dependency["name"] == "xgboost"
    } == {"sys_platform != 'linux'"}

    package_names = {package["name"] for package in lock["package"]}
    accelerator_packages = {
        name
        for name in package_names
        if name.startswith("nvidia-")
        or name in {"cuda-bindings", "cuda-pathfinder", "triton"}
    }
    assert not accelerator_packages


@pytest.mark.skipif(sys.platform != "linux", reason="Linux CI accelerator contract")
def test_installed_linux_ml_stack_is_cpu_only() -> None:
    import torch
    import xgboost

    assert torch.__version__ == f"{EXPECTED_TORCH_VERSION}+cpu"
    assert torch.version.cuda is None
    assert not torch.cuda.is_available()
    assert xgboost.__version__ == EXPECTED_XGBOOST_VERSION
    assert metadata.version("xgboost-cpu") == EXPECTED_XGBOOST_VERSION
    with pytest.raises(metadata.PackageNotFoundError):
        metadata.version("xgboost")
