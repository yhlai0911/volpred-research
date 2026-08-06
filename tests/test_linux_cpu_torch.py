"""Linux CI must never resolve PyTorch's CUDA runtime by accident."""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CPU_INDEX = "https://download.pytorch.org/whl/cpu"


def test_pyproject_routes_only_linux_torch_to_explicit_cpu_index() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    uv = project["tool"]["uv"]

    torch_sources = uv["sources"]["torch"]
    assert torch_sources == [
        {"index": "pytorch-cpu", "marker": "sys_platform == 'linux'"}
    ]

    cpu_indexes = [
        entry for entry in uv["index"] if entry.get("name") == "pytorch-cpu"
    ]
    assert cpu_indexes == [
        {"name": "pytorch-cpu", "url": CPU_INDEX, "explicit": True}
    ]


def test_lock_has_distinct_linux_cpu_and_non_linux_torch_sources() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    torch_packages = [package for package in lock["package"] if package["name"] == "torch"]

    linux_cpu = [
        package
        for package in torch_packages
        if package.get("source", {}).get("registry") == CPU_INDEX
    ]
    non_linux_pypi = [
        package
        for package in torch_packages
        if package.get("source", {}).get("registry") == "https://pypi.org/simple"
    ]

    assert len(linux_cpu) == 1
    assert "+cpu" in linux_cpu[0]["version"]
    assert any("sys_platform == 'linux'" in marker for marker in linux_cpu[0]["resolution-markers"])
    assert len(non_linux_pypi) == 1
    assert any("sys_platform != 'linux'" in marker for marker in non_linux_pypi[0]["resolution-markers"])


@pytest.mark.skipif(sys.platform != "linux", reason="Linux CI accelerator contract")
def test_installed_linux_torch_is_cpu_only() -> None:
    import torch

    assert "+cpu" in torch.__version__
    assert torch.version.cuda is None
    assert not torch.cuda.is_available()
