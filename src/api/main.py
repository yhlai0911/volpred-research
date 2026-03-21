from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routers import publications, program, research

app = FastAPI(
    title="Volpred Research API",
    description="API for the Autonomous Volatility Prediction Research System",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes (must be before static mount)
app.include_router(research.router, prefix="/api/research", tags=["research"])
app.include_router(publications.router, prefix="/api/publications", tags=["publications"])
app.include_router(program.router, prefix="/api/program", tags=["program"])


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


# Serve static frontend as fallback (for Zeabur: single-service deployment)
# API routes at /api/* are matched first, everything else falls through to static
frontend_out = Path(__file__).parent.parent.parent / "frontend" / "out"
if frontend_out.exists():
    app.mount("/", StaticFiles(directory=str(frontend_out), html=True), name="frontend")
