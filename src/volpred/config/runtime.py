from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROJECT_TARGETS_PATH = PROJECT_ROOT / "config" / "project_targets.json"


def get_project_root() -> Path:
    return PROJECT_ROOT


def get_project_targets_path() -> Path:
    return PROJECT_TARGETS_PATH


@lru_cache(maxsize=1)
def load_project_targets() -> dict[str, Any]:
    if not PROJECT_TARGETS_PATH.exists():
        raise RuntimeError(f"Missing project targets config: {PROJECT_TARGETS_PATH}")
    data = json.loads(PROJECT_TARGETS_PATH.read_text())
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid project targets config: {PROJECT_TARGETS_PATH}")
    return data


def _frontends() -> dict[str, dict[str, Any]]:
    frontends = load_project_targets().get("frontends")
    if not isinstance(frontends, dict) or not frontends:
        raise RuntimeError("project_targets.json must define a non-empty 'frontends' object")
    return frontends


def get_active_frontend_name() -> str:
    name = load_project_targets().get("active_frontend")
    if not isinstance(name, str) or name not in _frontends():
        raise RuntimeError("project_targets.json has an invalid 'active_frontend'")
    return name


def get_frontend_names(*, active_first: bool = True) -> list[str]:
    names = list(_frontends().keys())
    active = get_active_frontend_name()
    if active_first and active in names:
        return [active] + [name for name in names if name != active]
    return names


def get_frontend_config(name: str | None = None) -> dict[str, Any]:
    frontend_name = name or get_active_frontend_name()
    config = _frontends().get(frontend_name)
    if not isinstance(config, dict):
        raise RuntimeError(f"Unknown frontend target: {frontend_name}")
    return config


def get_frontend_path(name: str | None = None) -> Path:
    frontend_name = name or get_active_frontend_name()
    rel_path = get_frontend_config(frontend_name).get("path")
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise RuntimeError(f"Frontend '{frontend_name}' is missing a valid 'path'")
    return PROJECT_ROOT / rel_path


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def _resolve_frontend_path_list(
    field: str,
    *,
    active_only: bool = True,
    active_first: bool = True,
) -> list[Path]:
    names = [get_active_frontend_name()] if active_only else get_frontend_names(active_first=active_first)
    resolved: list[Path] = []
    for name in names:
        values = get_frontend_config(name).get(field) or []
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            continue
        base = get_frontend_path(name)
        for rel_path in values:
            if isinstance(rel_path, str) and rel_path.strip():
                resolved.append(base / rel_path)
    return _unique_paths(resolved)


def _resolve_single_frontend_path(field: str, name: str | None = None) -> Path | None:
    frontend_name = name or get_active_frontend_name()
    rel_path = get_frontend_config(frontend_name).get(field)
    if not isinstance(rel_path, str) or not rel_path.strip():
        return None
    return get_frontend_path(frontend_name) / rel_path


def get_local_data_sync_dirs(*, active_only: bool = True) -> list[Path]:
    return _resolve_frontend_path_list("local_data_sync_dirs", active_only=active_only)


def get_strategy_metrics_sync_paths(*, active_only: bool = True) -> list[Path]:
    return _resolve_frontend_path_list("strategy_metrics_targets", active_only=active_only)


def get_active_frontend_paper_dir() -> Path | None:
    return _resolve_single_frontend_path("paper_public_dir")


def iter_frontend_paper_public_dirs(*, active_first: bool = True) -> list[Path]:
    return _resolve_frontend_path_list(
        "paper_public_dir",
        active_only=False,
        active_first=active_first,
    )


def get_deploy_project_id() -> str | None:
    deploy = load_project_targets().get("deploy")
    if not isinstance(deploy, dict):
        return None
    value = deploy.get("zeabur_project_id")
    return value.strip() if isinstance(value, str) and value.strip() else None


def get_active_service_name() -> str | None:
    deploy = load_project_targets().get("deploy")
    if not isinstance(deploy, dict):
        return None
    value = deploy.get("active_service")
    return value.strip() if isinstance(value, str) and value.strip() else None


def get_active_service_id() -> str | None:
    deploy = load_project_targets().get("deploy")
    if not isinstance(deploy, dict):
        return None
    services = deploy.get("services")
    active_service = get_active_service_name()
    if not isinstance(services, dict) or not active_service:
        return None
    service_id = services.get(active_service)
    return service_id.strip() if isinstance(service_id, str) and service_id.strip() else None


def get_default_mirror_url() -> str:
    mirror = load_project_targets().get("mirror")
    if not isinstance(mirror, dict):
        return ""
    url = mirror.get("default_url")
    return url.strip() if isinstance(url, str) and url.strip() else ""


def get_default_remote_url() -> str:
    site = load_project_targets().get("site")
    if not isinstance(site, dict):
        return ""
    url = site.get("default_remote_url")
    return url.strip() if isinstance(url, str) and url.strip() else ""
