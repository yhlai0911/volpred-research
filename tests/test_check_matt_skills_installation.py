from __future__ import annotations

import json
from pathlib import Path

from scripts.check_matt_skills_installation import (
    REQUIRED_MATT_SKILLS,
    audit,
    main,
)


REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_skill(root: Path, skill: str, *, declared_name: str | None = None) -> None:
    skill_dir = root / skill
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "\n".join(
            (
                "---",
                f"name: {declared_name or skill}",
                f"description: Test manifest for {skill}.",
                "---",
                "",
                f"# {skill}",
                "",
            )
        ),
        encoding="utf-8",
    )


def test_audit_accepts_complete_matt_skill_suite(tmp_path: Path) -> None:
    for skill in REQUIRED_MATT_SKILLS:
        _write_skill(tmp_path, skill)

    result = audit(tmp_path)

    assert result["ok"] is True
    assert result["missing"] == []
    assert result["invalid_manifests"] == []
    assert result["installed"] == list(REQUIRED_MATT_SKILLS)


def test_audit_reports_missing_manifest_and_wrong_frontmatter_name(
    tmp_path: Path,
) -> None:
    for skill in REQUIRED_MATT_SKILLS:
        _write_skill(tmp_path, skill)

    missing = REQUIRED_MATT_SKILLS[0]
    wrong_name = REQUIRED_MATT_SKILLS[1]
    (tmp_path / missing / "SKILL.md").unlink()
    _write_skill(
        tmp_path,
        wrong_name,
        declared_name="not-the-directory-name",
    )

    result = audit(tmp_path)

    assert result["ok"] is False
    assert result["missing"] == [missing]
    assert result["invalid_manifests"] == [
        {
            "skill": wrong_name,
            "declared_name": "not-the-directory-name",
            "reason": "frontmatter_name_mismatch",
        }
    ]


def test_cli_returns_nonzero_and_machine_readable_json_for_incomplete_suite(
    tmp_path: Path,
    capsys,
) -> None:
    exit_code = main(["--skill-root", str(tmp_path), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["skill_root"] == str(tmp_path.resolve())
    assert payload["missing"] == list(REQUIRED_MATT_SKILLS)


def test_agents_living_doc_records_current_matt_flow() -> None:
    agents = REPO_ROOT.joinpath("AGENTS.md").read_text(encoding="utf-8")

    stale_claims = (
        "讀到本節不要去找 `ask-matt` router",
        "它不存在，會撲空",
        "以下原文保留，待 owner 裁決",
    )
    assert not any(claim in agents for claim in stale_claims)
    assert "$HOME/.agents/skills/" in agents
    assert "scripts/check_matt_skills_installation.py" in agents
    assert "GitHub Issue #3" in agents
    assert "docs/refactor_plan_ops_master_2026_07.md" in agents
    assert "GitHub Issues #5~#36" in agents
    assert "`implement` → `tdd` → `code-review`" in agents
