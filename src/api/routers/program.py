from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

PROGRAM_PATH = Path("research_program.md")


class ProgramUpdate(BaseModel):
    content: str


@router.get("/")
def get_program():
    """Get the current research program."""
    if not PROGRAM_PATH.exists():
        raise HTTPException(status_code=404, detail="research_program.md not found")
    return {"content": PROGRAM_PATH.read_text(encoding="utf-8")}


@router.put("/")
def update_program(update: ProgramUpdate):
    """Update the research program."""
    PROGRAM_PATH.write_text(update.content, encoding="utf-8")
    return {"status": "updated", "length": len(update.content)}
