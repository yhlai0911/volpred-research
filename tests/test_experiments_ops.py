from pathlib import Path

from volpred.ops.experiments import (
    adopt_experiment_files,
    build_experiment_migration_plan,
    build_experiments_report,
    migrate_experiment_files,
    scaffold_experiment,
)


def test_build_experiments_report_groups_loose_files(tmp_path: Path):
    experiments_dir = tmp_path / "experiments"
    experiments_dir.mkdir()
    (experiments_dir / "k100.py").write_text("print('x')\n", encoding="utf-8")
    (experiments_dir / "k100_results.json").write_text("{}\n", encoding="utf-8")
    (experiments_dir / "k100_plot.png").write_text("png", encoding="utf-8")
    (experiments_dir / "notes.txt").write_text("misc\n", encoding="utf-8")
    (experiments_dir / "k200").mkdir()
    (experiments_dir / "k200" / "README.md").write_text("# K200\n", encoding="utf-8")

    report = build_experiments_report(root_path=tmp_path, limit=10)

    assert report["loose_file_count"] == 4
    assert report["top_level_dir_count"] == 1
    assert report["candidate_count"] == 1
    assert report["grouped_candidates"][0]["experiment_id"] == "k100"
    assert report["grouped_candidates"][0]["loose_count"] == 3
    assert report["ungrouped_loose_files"] == ["experiments/notes.txt"]


def test_build_experiments_report_is_clean_for_canonical_layout(tmp_path: Path):
    experiments_dir = tmp_path / "experiments"
    (experiments_dir / "k910").mkdir(parents=True)
    (experiments_dir / "k910" / "README.md").write_text("# K910\n", encoding="utf-8")
    (experiments_dir / "k910" / "k910.py").write_text("print('k910')\n", encoding="utf-8")
    (experiments_dir / "k910" / "k910_results.json").write_text("{}\n", encoding="utf-8")
    (experiments_dir / "vol_surface_mapping").mkdir(parents=True)
    (experiments_dir / "vol_surface_mapping" / "README.md").write_text("# vol surface\n", encoding="utf-8")
    (experiments_dir / "vol_surface_mapping" / "vol_surface_mapping.py").write_text(
        "print('surface')\n",
        encoding="utf-8",
    )
    (experiments_dir / "vol_surface_mapping" / "vol_surface_mapping_results.json").write_text(
        "{}\n",
        encoding="utf-8",
    )

    report = build_experiments_report(root_path=tmp_path, limit=10)

    assert report["loose_file_count"] == 0
    assert report["candidate_count"] == 0
    assert report["top_level_dir_count"] == 2
    assert report["grouped_candidates"] == []
    assert report["ungrouped_loose_files"] == []


def test_scaffold_experiment_creates_canonical_layout(tmp_path: Path):
    result = scaffold_experiment("k321", title="My Experiment", root_path=tmp_path)
    experiment_dir = tmp_path / "experiments" / "k321"

    assert result["target_dir"] == "experiments/k321"
    assert (experiment_dir / "README.md").exists()
    assert (experiment_dir / "k321.py").exists()
    assert (experiment_dir / "k321_results.json").exists()
    assert (experiment_dir / "references" / ".gitkeep").exists()
    assert (experiment_dir / "data" / ".gitkeep").exists()


def test_migrate_experiment_files_moves_only_touched_group(tmp_path: Path):
    experiments_dir = tmp_path / "experiments"
    experiments_dir.mkdir()
    (experiments_dir / "k555.py").write_text("print('main')\n", encoding="utf-8")
    (experiments_dir / "k555_plots.py").write_text("print('plots')\n", encoding="utf-8")
    (experiments_dir / "k555_results.json").write_text("{}\n", encoding="utf-8")
    (experiments_dir / "k556.py").write_text("print('other')\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "notes.md").write_text(
        "See experiments/k555.py and experiments/k555_results.json\n",
        encoding="utf-8",
    )

    plan = build_experiment_migration_plan("k555", root_path=tmp_path)
    assert len(plan["moves"]) == 3
    assert plan["conflicts"] == []
    k555_move = next(item for item in plan["moves"] if item["source"] == "experiments/k555.py")
    assert k555_move["reference_hit_count"] >= 1

    result = migrate_experiment_files("k555", root_path=tmp_path, apply_changes=True)
    experiment_dir = tmp_path / "experiments" / "k555"

    assert result["dry_run"] is False
    assert sorted(item["source"] for item in result["moved"]) == [
        "experiments/k555.py",
        "experiments/k555_plots.py",
        "experiments/k555_results.json",
    ]
    assert (experiment_dir / "k555.py").exists()
    assert (experiment_dir / "k555_plots.py").exists()
    assert (experiment_dir / "k555_results.json").exists()
    assert (tmp_path / "experiments" / "k556.py").exists()
    assert not (tmp_path / "experiments" / "k555.py").exists()


def test_build_experiment_migration_plan_marks_existing_canonical_target_as_conflict(tmp_path: Path):
    experiments_dir = tmp_path / "experiments"
    experiments_dir.mkdir()
    (experiments_dir / "k901.py").write_text("print('loose')\n", encoding="utf-8")
    canonical_dir = experiments_dir / "k901"
    canonical_dir.mkdir()
    (canonical_dir / "k901.py").write_text("print('canonical')\n", encoding="utf-8")

    plan = build_experiment_migration_plan("k901", root_path=tmp_path)

    assert plan["moves"] == []
    assert len(plan["conflicts"]) == 1
    assert plan["conflicts"][0]["source"] == "experiments/k901.py"
    assert plan["conflicts"][0]["target"] == "experiments/k901/k901.py"


def test_migrate_dry_run_does_not_create_scaffold(tmp_path: Path):
    experiments_dir = tmp_path / "experiments"
    experiments_dir.mkdir()
    (experiments_dir / "k777.py").write_text("print('main')\n", encoding="utf-8")

    result = migrate_experiment_files("k777", root_path=tmp_path, apply_changes=False)

    assert result["dry_run"] is True
    assert "experiments/k777/README.md" in result["planned_created"]
    assert result["created"] == []
    assert not (tmp_path / "experiments" / "k777").exists()


def test_scaffold_plan_skips_gitkeep_for_non_empty_data_dir(tmp_path: Path):
    experiment_dir = tmp_path / "experiments" / "k888"
    data_dir = experiment_dir / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "panel.parquet").write_text("data", encoding="utf-8")

    result = migrate_experiment_files("k888", root_path=tmp_path, apply_changes=False)

    assert "experiments/k888/README.md" in result["planned_created"]
    assert "experiments/k888/references/.gitkeep" in result["planned_created"]
    assert "experiments/k888/data/.gitkeep" not in result["planned_created"]


def test_migrate_overwrite_replaces_existing_canonical_target_and_rewrites_refs(tmp_path: Path):
    experiments_dir = tmp_path / "experiments"
    experiments_dir.mkdir()
    loose_script = experiments_dir / "k930.py"
    loose_script.write_text("print('new body')\n", encoding="utf-8")
    canonical_dir = experiments_dir / "k930"
    canonical_dir.mkdir()
    canonical_script = canonical_dir / "k930.py"
    canonical_script.write_text("print('old body')\n", encoding="utf-8")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    notes = docs_dir / "notes.md"
    notes.write_text("Use experiments/k930.py\n", encoding="utf-8")

    result = migrate_experiment_files(
        "k930",
        root_path=tmp_path,
        apply_changes=True,
        rewrite_references=True,
        overwrite=True,
    )

    assert result["conflicts"] == []
    assert len(result["moved"]) == 1
    assert result["moved"][0]["source"] == "experiments/k930.py"
    assert result["moved"][0]["target"] == "experiments/k930/k930.py"
    assert not loose_script.exists()
    assert canonical_script.read_text(encoding="utf-8") == "print('new body')\n"
    assert "experiments/k930/k930.py" in notes.read_text(encoding="utf-8")
    assert any(update["files"] for update in result["reference_updates"])


def test_migrate_can_rewrite_repo_references(tmp_path: Path):
    experiments_dir = tmp_path / "experiments"
    experiments_dir.mkdir()
    source_script = experiments_dir / "k625_hurst_volatility.py"
    source_results = experiments_dir / "k625_hurst_volatility_results.json"
    legacy_script_ref = "experiments/" + "k625_hurst_volatility.py"
    legacy_results_ref = "experiments/" + "k625_hurst_volatility_results.json"
    source_script.write_text(
        f'results_path = "{legacy_results_ref}"\n',
        encoding="utf-8",
    )
    source_results.write_text(
        '{"script":"' + legacy_script_ref + '"}\n',
        encoding="utf-8",
    )
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    notes = docs_dir / "notes.md"
    notes.write_text(
        f"See {legacy_script_ref} and {legacy_results_ref}\n",
        encoding="utf-8",
    )

    result = migrate_experiment_files(
        "k625",
        root_path=tmp_path,
        apply_changes=True,
        rewrite_references=True,
    )

    moved_script = tmp_path / "experiments" / "k625" / "k625_hurst_volatility.py"
    moved_results = tmp_path / "experiments" / "k625" / "k625_hurst_volatility_results.json"
    assert moved_script.exists()
    assert moved_results.exists()
    assert "experiments/k625/k625_hurst_volatility_results.json" in moved_script.read_text(encoding="utf-8")
    assert "experiments/k625/k625_hurst_volatility.py" in moved_results.read_text(encoding="utf-8")
    assert "experiments/k625/k625_hurst_volatility.py" in notes.read_text(encoding="utf-8")
    assert any(update["files"] for update in result["reference_updates"])


def test_adopt_experiment_files_can_rename_results_and_rewrite_refs(tmp_path: Path):
    experiments_dir = tmp_path / "experiments"
    experiments_dir.mkdir()
    source_script = experiments_dir / "legacy_drawdown_duration_script.py"
    source_results = experiments_dir / "legacy_drawdown_duration_results.json"
    legacy_script_ref = "experiments/legacy_drawdown_duration_script.py"
    legacy_results_ref = "experiments/legacy_drawdown_duration_results.json"
    source_script.write_text(
        f'results_path = "{legacy_results_ref}"\n',
        encoding="utf-8",
    )
    source_results.write_text(
        '{"script":"' + legacy_script_ref + '"}\n',
        encoding="utf-8",
    )
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    notes = docs_dir / "notes.md"
    notes.write_text(
        f"See {legacy_script_ref} and {legacy_results_ref}\n",
        encoding="utf-8",
    )

    result = adopt_experiment_files(
        "drawdown_duration_analysis",
        source_files=[
            legacy_script_ref,
            legacy_results_ref,
        ],
        root_path=tmp_path,
        apply_changes=True,
        rewrite_references=True,
    )

    moved_script = tmp_path / "experiments" / "drawdown_duration_analysis" / "drawdown_duration_analysis.py"
    moved_results = tmp_path / "experiments" / "drawdown_duration_analysis" / "drawdown_duration_analysis_results.json"
    assert moved_script.exists()
    assert moved_results.exists()
    assert "experiments/drawdown_duration_analysis/drawdown_duration_analysis_results.json" in moved_script.read_text(encoding="utf-8")
    assert "experiments/drawdown_duration_analysis/drawdown_duration_analysis.py" in moved_results.read_text(encoding="utf-8")
    assert "experiments/drawdown_duration_analysis/drawdown_duration_analysis_results.json" in notes.read_text(encoding="utf-8")
    assert "experiments/drawdown_duration_analysis/README.md" in result["created"]


def test_adopt_experiment_files_creates_placeholder_script_for_json_only(tmp_path: Path):
    experiments_dir = tmp_path / "experiments"
    experiments_dir.mkdir()
    source_results = experiments_dir / "legacy_rough_vol_pilot_results.json"
    source_results.write_text('{"experiment":"rough_vol_pilot"}\n', encoding="utf-8")

    result = adopt_experiment_files(
        "rough_vol_pilot",
        source_files=["experiments/legacy_rough_vol_pilot_results.json"],
        root_path=tmp_path,
        apply_changes=True,
    )

    experiment_dir = tmp_path / "experiments" / "rough_vol_pilot"
    assert (experiment_dir / "rough_vol_pilot.py").exists()
    assert (experiment_dir / "rough_vol_pilot_results.json").exists()
    assert "experiments/rough_vol_pilot/rough_vol_pilot.py" in result["created"]


def test_adopt_experiment_files_creates_placeholder_results_for_py_only(tmp_path: Path):
    experiments_dir = tmp_path / "experiments"
    experiments_dir.mkdir()
    source_script = experiments_dir / "legacy_term_structure_signal.py"
    source_script.write_text("print('term structure')\n", encoding="utf-8")

    result = adopt_experiment_files(
        "term_structure_signal",
        source_files=["experiments/legacy_term_structure_signal.py"],
        root_path=tmp_path,
        apply_changes=True,
    )

    experiment_dir = tmp_path / "experiments" / "term_structure_signal"
    assert (experiment_dir / "term_structure_signal.py").exists()
    assert (experiment_dir / "term_structure_signal_results.json").exists()
    assert "experiments/term_structure_signal/term_structure_signal_results.json" in result["created"]


def test_adopt_experiment_files_overwrite_replaces_existing_canonical_target(tmp_path: Path):
    experiments_dir = tmp_path / "experiments"
    experiments_dir.mkdir()
    source_script = experiments_dir / "legacy_vol_surface_signal.py"
    source_script.write_text("print('new source')\n", encoding="utf-8")
    canonical_dir = experiments_dir / "vol_surface_signal"
    canonical_dir.mkdir()
    canonical_script = canonical_dir / "vol_surface_signal.py"
    canonical_script.write_text("print('old canonical')\n", encoding="utf-8")

    result = adopt_experiment_files(
        "vol_surface_signal",
        source_files=["experiments/legacy_vol_surface_signal.py"],
        root_path=tmp_path,
        apply_changes=True,
        overwrite=True,
    )

    assert result["conflicts"] == []
    assert result["moved"] == [
        {
            "source": "experiments/legacy_vol_surface_signal.py",
            "target": "experiments/vol_surface_signal/vol_surface_signal.py",
        }
    ]
    assert canonical_script.read_text(encoding="utf-8") == "print('new source')\n"
