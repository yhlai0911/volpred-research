from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .common import project_path

CANONICAL_ROOT = project_path("agent-specs")
CANONICAL_GUIDE = CANONICAL_ROOT / "guide.md"
CANONICAL_SKILLS = CANONICAL_ROOT / "skills"
CANONICAL_REFERENCES = CANONICAL_ROOT / "references"
CANONICAL_CLAUDE_RULES = CANONICAL_ROOT / "claude_rules"
CANONICAL_CLAUDE_AGENTS = CANONICAL_ROOT / "claude_agents"
CANONICAL_CODEX_ROOT = CANONICAL_ROOT / "codex"
CANONICAL_CODEX_CONFIG = CANONICAL_CODEX_ROOT / "config.toml"
CANONICAL_CODEX_AGENTS = CANONICAL_CODEX_ROOT / "agents"

GENERATED_HEADER = "<!-- AUTO-GENERATED FROM agent-specs/. Edit canonical sources instead. -->\n\n"
COMMENT_GENERATED_HEADER = "# AUTO-GENERATED FROM agent-specs/. Edit canonical sources instead.\n\n"
PLACEHOLDERS = {
    "guide_file": "{{GUIDE_FILE}}",
    "skill_root": "{{SKILL_ROOT}}",
    "provider_dir": "{{PROVIDER_DIR}}",
}


@dataclass(frozen=True)
class AgentSpecTarget:
    key: str
    guide_path: Path
    skills_path: Path
    guide_name: str
    skill_root: str
    provider_dir: str
    rules_source_path: Path | None = None
    rules_path: Path | None = None
    agents_source_path: Path | None = None
    agents_path: Path | None = None
    config_source_path: Path | None = None
    config_path: Path | None = None


TARGETS = {
    "claude": AgentSpecTarget(
        key="claude",
        guide_path=project_path("CLAUDE.md"),
        skills_path=project_path(".claude", "skills"),
        guide_name="CLAUDE.md",
        skill_root=".claude/skills",
        provider_dir=".claude",
        rules_source_path=CANONICAL_CLAUDE_RULES,
        rules_path=project_path(".claude", "rules"),
        agents_source_path=CANONICAL_CLAUDE_AGENTS,
        agents_path=project_path(".claude", "agents"),
    ),
    "codex": AgentSpecTarget(
        key="codex",
        guide_path=project_path("AGENTS.md"),
        skills_path=project_path(".agents", "skills"),
        guide_name="AGENTS.md",
        skill_root=".agents/skills",
        provider_dir=".codex",
        agents_source_path=CANONICAL_CODEX_AGENTS,
        agents_path=project_path(".codex", "agents"),
        config_source_path=CANONICAL_CODEX_CONFIG,
        config_path=project_path(".codex", "config.toml"),
    ),
}


def ensure_agent_spec_dirs() -> None:
    CANONICAL_ROOT.mkdir(parents=True, exist_ok=True)
    CANONICAL_SKILLS.mkdir(parents=True, exist_ok=True)
    CANONICAL_REFERENCES.mkdir(parents=True, exist_ok=True)
    CANONICAL_CLAUDE_RULES.mkdir(parents=True, exist_ok=True)
    CANONICAL_CLAUDE_AGENTS.mkdir(parents=True, exist_ok=True)
    CANONICAL_CODEX_ROOT.mkdir(parents=True, exist_ok=True)
    CANONICAL_CODEX_AGENTS.mkdir(parents=True, exist_ok=True)
    readme = CANONICAL_REFERENCES / "README.md"
    if not readme.exists():
        readme.write_text("# Shared References\n\nProvider-neutral references live here when needed.\n")


def _strip_generated_header(text: str) -> str:
    if text.startswith(GENERATED_HEADER):
        return text[len(GENERATED_HEADER) :]
    if text.startswith(COMMENT_GENERATED_HEADER):
        return text[len(COMMENT_GENERATED_HEADER) :]
    return text


def _normalize_text(text: str) -> str:
    text = _strip_generated_header(text)
    replacements = (
        (".claude/skills", PLACEHOLDERS["skill_root"]),
        (".agents/skills", PLACEHOLDERS["skill_root"]),
        (".claude/", f"{PLACEHOLDERS['provider_dir']}/"),
        (".agents/", f"{PLACEHOLDERS['provider_dir']}/"),
        (".codex/", f"{PLACEHOLDERS['provider_dir']}/"),
        ("CLAUDE.md", PLACEHOLDERS["guide_file"]),
        ("AGENTS.md", PLACEHOLDERS["guide_file"]),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _generated_header_for(destination: Path) -> str:
    if destination.suffix.lower() in {".toml"}:
        return COMMENT_GENERATED_HEADER
    return GENERATED_HEADER


def _render_text(text: str, target: AgentSpecTarget, destination: Path) -> str:
    rendered = text
    replacements = (
        (PLACEHOLDERS["guide_file"], target.guide_name),
        (PLACEHOLDERS["skill_root"], target.skill_root),
        (PLACEHOLDERS["provider_dir"], target.provider_dir),
    )
    for old, new in replacements:
        rendered = rendered.replace(old, new)
    return _generated_header_for(destination) + rendered


def _iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if path.name in {".DS_Store"}:
            continue
        if "__pycache__" in path.parts:
            continue
        yield path


def _load_text(path: Path) -> str:
    return path.read_text()


def _display_path(path: Path) -> str:
    for base in (project_path(), CANONICAL_ROOT.parent):
        try:
            return str(path.relative_to(base))
        except ValueError:
            continue
    return str(path)


def _render_file(source: Path, destination: Path, target: AgentSpecTarget) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        destination.write_text(_render_text(_load_text(source), target, destination))
    except UnicodeDecodeError:
        shutil.copy2(source, destination)


def import_agent_specs(
    *,
    source: str,
    include_guide: bool = True,
    include_skills: bool = True,
) -> dict[str, object]:
    if source not in TARGETS:
        raise ValueError(f"Unknown source provider: {source}")
    ensure_agent_spec_dirs()
    target = TARGETS[source]
    copied_files: list[str] = []

    if include_guide:
        guide_text = _normalize_text(_load_text(target.guide_path))
        CANONICAL_GUIDE.write_text(guide_text)
        copied_files.append(_display_path(CANONICAL_GUIDE))

    if include_skills:
        if CANONICAL_SKILLS.exists():
            shutil.rmtree(CANONICAL_SKILLS)
        CANONICAL_SKILLS.mkdir(parents=True, exist_ok=True)
        for path in _iter_files(target.skills_path):
            relative = path.relative_to(target.skills_path)
            destination = CANONICAL_SKILLS / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                destination.write_text(_normalize_text(_load_text(path)))
            except UnicodeDecodeError:
                shutil.copy2(path, destination)
            copied_files.append(_display_path(destination))

    return {
        "source": source,
        "guide_imported": include_guide,
        "skills_imported": include_skills,
        "copied_files": copied_files,
    }


def _render_skills(target: AgentSpecTarget) -> list[str]:
    if target.skills_path.exists():
        shutil.rmtree(target.skills_path)
    target.skills_path.mkdir(parents=True, exist_ok=True)
    rendered_files: list[str] = []
    for path in _iter_files(CANONICAL_SKILLS):
        relative = path.relative_to(CANONICAL_SKILLS)
        destination = target.skills_path / relative
        _render_file(path, destination, target)
        rendered_files.append(_display_path(destination))
    return rendered_files


def _render_optional_tree(
    *,
    source_root: Path | None,
    destination_root: Path | None,
    target: AgentSpecTarget,
) -> list[str]:
    if source_root is None or destination_root is None:
        return []
    if destination_root.exists():
        shutil.rmtree(destination_root)
    destination_root.mkdir(parents=True, exist_ok=True)
    rendered_files: list[str] = []
    for path in _iter_files(source_root):
        relative = path.relative_to(source_root)
        destination = destination_root / relative
        _render_file(path, destination, target)
        rendered_files.append(_display_path(destination))
    return rendered_files


def _render_optional_file(
    *,
    source_path: Path | None,
    destination_path: Path | None,
    target: AgentSpecTarget,
) -> list[str]:
    if source_path is None or destination_path is None or not source_path.exists():
        return []
    _render_file(source_path, destination_path, target)
    return [_display_path(destination_path)]


def render_agent_specs(*, target_key: str | None = None) -> dict[str, object]:
    ensure_agent_spec_dirs()
    targets = [TARGETS[target_key]] if target_key else list(TARGETS.values())
    rendered: dict[str, list[str]] = {}
    for target in targets:
        target.guide_path.write_text(_render_text(_load_text(CANONICAL_GUIDE), target, target.guide_path))
        rendered_files = [_display_path(target.guide_path)]
        rendered_files.extend(_render_skills(target))
        rendered_files.extend(
            _render_optional_tree(
                source_root=target.rules_source_path,
                destination_root=target.rules_path,
                target=target,
            )
        )
        rendered_files.extend(
            _render_optional_tree(
                source_root=target.agents_source_path,
                destination_root=target.agents_path,
                target=target,
            )
        )
        rendered_files.extend(
            _render_optional_file(
                source_path=target.config_source_path,
                destination_path=target.config_path,
                target=target,
            )
        )
        rendered[target.key] = rendered_files
    return {"targets": rendered}


def _check_optional_tree(
    *,
    source_root: Path | None,
    destination_root: Path | None,
    target: AgentSpecTarget,
    issues: list[str],
) -> None:
    if source_root is None or destination_root is None:
        return

    expected_rel_paths = {
        path.relative_to(source_root)
        for path in _iter_files(source_root)
    }
    actual_rel_paths = {
        path.relative_to(destination_root)
        for path in _iter_files(destination_root)
    } if destination_root.exists() else set()

    for missing in sorted(expected_rel_paths - actual_rel_paths):
        issues.append(f"{_display_path(destination_root)}/{missing}: missing")
    for extra in sorted(actual_rel_paths - expected_rel_paths):
        issues.append(f"{_display_path(destination_root)}/{extra}: unexpected")

    for relative in sorted(expected_rel_paths & actual_rel_paths):
        expected_text = _render_text(_load_text(source_root / relative), target, destination_root / relative)
        actual_text = _load_text(destination_root / relative)
        if actual_text != expected_text:
            issues.append(f"{_display_path(destination_root)}/{relative}: drift")


def _check_optional_file(
    *,
    source_path: Path | None,
    destination_path: Path | None,
    target: AgentSpecTarget,
    issues: list[str],
) -> None:
    if source_path is None or destination_path is None or not source_path.exists():
        return
    expected_text = _render_text(_load_text(source_path), target, destination_path)
    actual_text = _load_text(destination_path) if destination_path.exists() else None
    if actual_text != expected_text:
        issues.append(f"{_display_path(destination_path)}: drift")


def check_agent_specs(*, target_key: str | None = None) -> dict[str, object]:
    ensure_agent_spec_dirs()
    targets = [TARGETS[target_key]] if target_key else list(TARGETS.values())
    issues: list[str] = []
    for target in targets:
        expected_guide = _render_text(_load_text(CANONICAL_GUIDE), target, target.guide_path)
        actual_guide = _load_text(target.guide_path) if target.guide_path.exists() else None
        if actual_guide != expected_guide:
            issues.append(f"{_display_path(target.guide_path)}: drift")

        expected_rel_paths = {
            path.relative_to(CANONICAL_SKILLS)
            for path in _iter_files(CANONICAL_SKILLS)
        }
        actual_rel_paths = {
            path.relative_to(target.skills_path)
            for path in _iter_files(target.skills_path)
        } if target.skills_path.exists() else set()

        for missing in sorted(expected_rel_paths - actual_rel_paths):
            issues.append(f"{_display_path(target.skills_path)}/{missing}: missing")
        for extra in sorted(actual_rel_paths - expected_rel_paths):
            issues.append(f"{_display_path(target.skills_path)}/{extra}: unexpected")

        for relative in sorted(expected_rel_paths & actual_rel_paths):
            expected_text = _render_text(_load_text(CANONICAL_SKILLS / relative), target, target.skills_path / relative)
            actual_text = _load_text(target.skills_path / relative)
            if actual_text != expected_text:
                issues.append(f"{_display_path(target.skills_path)}/{relative}: drift")

        _check_optional_tree(
            source_root=target.rules_source_path,
            destination_root=target.rules_path,
            target=target,
            issues=issues,
        )
        _check_optional_tree(
            source_root=target.agents_source_path,
            destination_root=target.agents_path,
            target=target,
            issues=issues,
        )
        _check_optional_file(
            source_path=target.config_source_path,
            destination_path=target.config_path,
            target=target,
            issues=issues,
        )

    return {
        "clean": not issues,
        "issues": issues,
        "targets": [target.key for target in targets],
    }
