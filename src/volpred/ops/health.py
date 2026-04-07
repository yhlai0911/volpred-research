from __future__ import annotations

from .common import load_json, project_path


def _check_paper_consistency(project_root) -> dict:
    """Check paper/ directories vs research_program.md mentions."""
    paper_dir = project_root / "paper"
    rp_path = project_root / "research_program.md"

    # Papers on disk (directories with main.tex)
    on_disk = set()
    if paper_dir.exists():
        for d in paper_dir.iterdir():
            if d.is_dir() and any(d.glob("main*.tex")):
                on_disk.add(d.name)

    # Papers mentioned in research_program.md
    in_rp = set()
    if rp_path.exists():
        text = rp_path.read_text()
        for name in on_disk:
            if f"paper/{name}/" in text or f"paper/{name}/main" in text:
                in_rp.add(name)

    missing_from_rp = sorted(on_disk - in_rp)
    return {
        "papers_on_disk": sorted(on_disk),
        "papers_in_research_program": sorted(in_rp),
        "missing_from_research_program": missing_from_rp,
    }


def health_snapshot(storage_dir: str = "storage") -> dict:
    storage = project_path(storage_dir)
    feed = load_json(storage / "reports" / "feed.json", [])
    open_questions = load_json(storage / "memory" / "open_questions.json", [])
    paper_trading = load_json(storage / "paper_trading.json", {})
    failed_syncs = load_json(storage / ".failed_supabase_syncs.json", [])
    sync_state = load_json(storage / ".supabase_sync_state.json", {})

    total_entries = sum(len((strategy or {}).get("entries", [])) for strategy in paper_trading.values())

    project_root = storage.parent
    paper_check = _check_paper_consistency(project_root)

    result = {
        "storage_dir": str(storage),
        "feed_items": len(feed),
        "reports": len(list((storage / "reports").glob("*.json"))) if (storage / "reports").exists() else 0,
        "open_questions": len(open_questions),
        "paper_trading_strategies": len(paper_trading),
        "paper_trading_entries": total_entries,
        "risk_forecast_exists": (storage / "risk_forecast.json").exists(),
        "failed_supabase_syncs": len(failed_syncs),
        "has_incremental_sync_state": bool(sync_state),
        "papers_on_disk": len(paper_check["papers_on_disk"]),
    }

    if paper_check["missing_from_research_program"]:
        result["papers_missing_from_research_program"] = paper_check["missing_from_research_program"]

    return result
