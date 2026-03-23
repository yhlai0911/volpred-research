from __future__ import annotations

import os
import sys

from fastapi import APIRouter, Depends, HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from .common import get_storage_dir, require_research_mirror_token

router = APIRouter(dependencies=[Depends(require_research_mirror_token)])


def _get_memory():
    from volpred.memory.system import MemorySystem

    return MemorySystem(storage_dir=get_storage_dir())


@router.get("/experiments")
def list_experiments(asset: str | None = None):
    """List all experiments, optionally filtered by asset."""
    memory = _get_memory()
    return memory.list_experiments(asset=asset)


@router.get("/experiments/{experiment_id}")
def get_experiment(experiment_id: str):
    """Get details of a single experiment."""
    memory = _get_memory()
    exp = memory.load_experiment(experiment_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return exp


@router.get("/log")
def get_research_log():
    """Get the full research log."""
    memory = _get_memory()
    return memory.get_research_log()


@router.get("/knowledge")
def get_knowledge(category: str | None = None):
    """Get knowledge base items."""
    memory = _get_memory()
    return memory.get_knowledge(category=category)


@router.get("/summary")
def get_summary():
    """Get research summary."""
    memory = _get_memory()
    return memory.get_summary()


@router.get("/thinking")
def get_thinking_journal():
    """Get the researcher's real-time thinking journal."""
    memory = _get_memory()
    return memory.get_thinking_journal()


@router.get("/questions")
def get_open_questions(status: str | None = None):
    """Get open research questions."""
    memory = _get_memory()
    return memory.get_open_questions(status=status)


@router.get("/paper-trading")
def get_paper_trading():
    """Get paper trading log."""
    import json
    from pathlib import Path
    pt_file = Path(get_storage_dir()) / "paper_trading.json"
    if pt_file.exists():
        return json.loads(pt_file.read_text())
    return []
