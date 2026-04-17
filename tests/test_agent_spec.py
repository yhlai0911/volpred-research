from pathlib import Path

from volpred.ops import agent_spec


def _retarget_agent_spec(monkeypatch, root: Path):
    canonical_root = root / "agent-specs"
    monkeypatch.setattr(agent_spec, "CANONICAL_ROOT", canonical_root)
    monkeypatch.setattr(agent_spec, "CANONICAL_GUIDE", canonical_root / "guide.md")
    monkeypatch.setattr(agent_spec, "CANONICAL_SKILLS", canonical_root / "skills")
    monkeypatch.setattr(agent_spec, "CANONICAL_REFERENCES", canonical_root / "references")
    monkeypatch.setattr(agent_spec, "CANONICAL_CLAUDE_RULES", canonical_root / "claude_rules")
    monkeypatch.setattr(agent_spec, "CANONICAL_CLAUDE_AGENTS", canonical_root / "claude_agents")
    monkeypatch.setattr(agent_spec, "CANONICAL_CODEX_ROOT", canonical_root / "codex")
    monkeypatch.setattr(agent_spec, "CANONICAL_CODEX_CONFIG", canonical_root / "codex" / "config.toml")
    monkeypatch.setattr(agent_spec, "CANONICAL_CODEX_AGENTS", canonical_root / "codex" / "agents")
    monkeypatch.setattr(
        agent_spec,
        "TARGETS",
        {
            "claude": agent_spec.AgentSpecTarget(
                key="claude",
                guide_path=root / "CLAUDE.md",
                skills_path=root / ".claude" / "skills",
                guide_name="CLAUDE.md",
                skill_root=".claude/skills",
                provider_dir=".claude",
                rules_source_path=canonical_root / "claude_rules",
                rules_path=root / ".claude" / "rules",
                agents_source_path=canonical_root / "claude_agents",
                agents_path=root / ".claude" / "agents",
            ),
            "codex": agent_spec.AgentSpecTarget(
                key="codex",
                guide_path=root / "AGENTS.md",
                skills_path=root / ".agents" / "skills",
                guide_name="AGENTS.md",
                skill_root=".agents/skills",
                provider_dir=".codex",
                agents_source_path=canonical_root / "codex" / "agents",
                agents_path=root / ".codex" / "agents",
                config_source_path=canonical_root / "codex" / "config.toml",
                config_path=root / ".codex" / "config.toml",
            ),
        },
    )
    return canonical_root


def test_render_and_check_detect_drift(tmp_path: Path, monkeypatch):
    canonical_root = _retarget_agent_spec(monkeypatch, tmp_path)
    (canonical_root / "skills").mkdir(parents=True, exist_ok=True)
    (canonical_root / "claude_rules").mkdir(parents=True, exist_ok=True)
    (canonical_root / "claude_agents").mkdir(parents=True, exist_ok=True)
    (canonical_root / "codex" / "agents").mkdir(parents=True, exist_ok=True)
    (canonical_root / "guide.md").write_text(
        "Shared guide -> {{GUIDE_FILE}} and {{SKILL_ROOT}} and {{PROVIDER_DIR}}\n",
        encoding="utf-8",
    )
    (canonical_root / "skills" / "demo" / "SKILL.md").parent.mkdir(parents=True, exist_ok=True)
    (canonical_root / "skills" / "demo" / "SKILL.md").write_text(
        "Use {{GUIDE_FILE}} with {{SKILL_ROOT}} from {{PROVIDER_DIR}}\n",
        encoding="utf-8",
    )
    (canonical_root / "claude_rules" / "frontend.md").write_text(
        "---\npaths:\n  - \"frontend-v2-fix/**/*\"\n---\n\nUse {{GUIDE_FILE}} from {{PROVIDER_DIR}}\n",
        encoding="utf-8",
    )
    (canonical_root / "claude_agents" / "fresh-context-worker.md").write_text(
        "---\nname: fresh-context-worker\ndescription: Keep the main thread clean\ntools: Read, Grep, Glob, Bash\nmodel: sonnet\n---\n\nUse {{GUIDE_FILE}} and {{SKILL_ROOT}}.\n",
        encoding="utf-8",
    )
    (canonical_root / "codex" / "config.toml").write_text(
        "project_doc_max_bytes = 65536\n\n[agents]\nmax_threads = 4\n",
        encoding="utf-8",
    )
    (canonical_root / "codex" / "agents" / "fresh_context_worker.toml").write_text(
        'name = "fresh_context_worker"\ndescription = "Use for unrelated work."\ndeveloper_instructions = """Use {{GUIDE_FILE}} and {{SKILL_ROOT}} from {{PROVIDER_DIR}}."""\n',
        encoding="utf-8",
    )

    rendered = agent_spec.render_agent_specs()
    assert "claude" in rendered["targets"]
    assert "codex" in rendered["targets"]

    claude_guide = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    codex_guide = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert agent_spec.GENERATED_HEADER in claude_guide
    assert "CLAUDE.md" in claude_guide
    assert ".claude/skills" in claude_guide
    assert "AGENTS.md" in codex_guide
    assert ".agents/skills" in codex_guide
    assert ".codex" in codex_guide

    claude_rule = (tmp_path / ".claude" / "rules" / "frontend.md").read_text(encoding="utf-8")
    codex_config = (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8")
    codex_agent = (tmp_path / ".codex" / "agents" / "fresh_context_worker.toml").read_text(encoding="utf-8")
    assert agent_spec.GENERATED_HEADER in claude_rule
    assert agent_spec.COMMENT_GENERATED_HEADER in codex_config
    assert agent_spec.COMMENT_GENERATED_HEADER in codex_agent

    clean = agent_spec.check_agent_specs()
    assert clean["clean"] is True

    agent_path = tmp_path / ".codex" / "agents" / "fresh_context_worker.toml"
    agent_path.write_text(agent_path.read_text(encoding="utf-8") + "\nmanual drift\n", encoding="utf-8")
    dirty = agent_spec.check_agent_specs()
    assert dirty["clean"] is False
    assert any(".codex/agents/fresh_context_worker.toml: drift" in issue for issue in dirty["issues"])


def test_import_normalizes_provider_specific_paths(tmp_path: Path, monkeypatch):
    canonical_root = _retarget_agent_spec(monkeypatch, tmp_path)
    (tmp_path / ".claude" / "skills" / "demo").mkdir(parents=True, exist_ok=True)
    (tmp_path / "CLAUDE.md").write_text(
        agent_spec.GENERATED_HEADER + "Read CLAUDE.md and .claude/skills/demo/SKILL.md and .claude/agents/fresh-context-worker.md\n",
        encoding="utf-8",
    )
    (tmp_path / ".claude" / "skills" / "demo" / "SKILL.md").write_text(
        agent_spec.GENERATED_HEADER + "Use .claude/skills/demo/SKILL.md from .claude/ and watch .claude/worktrees/\n",
        encoding="utf-8",
    )

    result = agent_spec.import_agent_specs(source="claude")
    assert result["guide_imported"] is True
    assert result["skills_imported"] is True

    imported_guide = (canonical_root / "guide.md").read_text(encoding="utf-8")
    imported_skill = (canonical_root / "skills" / "demo" / "SKILL.md").read_text(encoding="utf-8")
    assert "{{GUIDE_FILE}}" in imported_guide
    assert "{{SKILL_ROOT}}" in imported_guide
    assert "{{SKILL_ROOT}}" in imported_skill
    assert "{{PROVIDER_DIR}}" in imported_skill
