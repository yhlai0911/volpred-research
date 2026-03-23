from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from volpred.core.types import ExperimentResult
from volpred.memory.schemas import ExperimentRecord, KnowledgeItem, ResearchLogEntry


class MemorySystem:
    REMOTE_URL = os.environ.get("VOLPRED_REMOTE_URL", "https://volpred.zeabur.app")

    def __init__(self, storage_dir: str = "storage"):
        self.storage_dir = Path(storage_dir)
        self.memory_dir = self.storage_dir / "memory"
        self.results_dir = self.storage_dir / "results"
        for d in [self.memory_dir, self.results_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def _sync_to_remote(self, filename: str) -> None:
        """Sync a memory file to Zeabur via PUT."""
        if not self.REMOTE_URL:
            return
        filepath = self.memory_dir / filename
        if not filepath.exists():
            return
        try:
            import urllib.request
            data = filepath.read_bytes()
            req = urllib.request.Request(
                f"{self.REMOTE_URL}/api/sync/{filename}",
                data=data,
                headers={"Content-Type": "application/json"},
                method="PUT",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass  # Don't fail research for sync issues

    # --- Experiment Records ---
    def save_experiment(self, result: ExperimentResult, metrics: dict, notes: str = "") -> str:
        """Save experiment result and return experiment_id."""
        record = {
            "experiment_id": result.experiment_id,
            "model_name": result.config.model_name,
            "asset": result.config.asset,
            "config": {
                "model_params": result.config.model_params,
                "window_size": result.config.window_size,
                "oos_start": result.config.oos_start,
                "oos_end": result.config.oos_end,
            },
            "metrics": metrics,
            "fit_time": result.fit_time,
            "n_forecasts": len(result.forecasts),
            "timestamp": datetime.now().isoformat(),
            "notes": notes,
        }

        # Save individual result
        result_file = self.results_dir / f"{result.experiment_id}.json"
        with open(result_file, "w") as f:
            json.dump(record, f, indent=2, default=str)

        # Append to experiment index
        self._append_to_index("experiments.json", record)
        self._sync_to_remote("experiments.json")

        return result.experiment_id

    def load_experiment(self, experiment_id: str) -> dict | None:
        result_file = self.results_dir / f"{experiment_id}.json"
        if result_file.exists():
            with open(result_file) as f:
                return json.load(f)
        return None

    def list_experiments(self, asset: str | None = None) -> list[dict]:
        index = self._load_index("experiments.json")
        if asset:
            index = [e for e in index if e.get("asset") == asset]
        return index

    # --- Research Log (structured entries, kept for API compatibility) ---
    def add_log_entry(
        self,
        phase: str,
        action: str,
        observation: str,
        decision: str,
        experiment_ids: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> str:
        entry = {
            "entry_id": uuid.uuid4().hex[:8],
            "timestamp": datetime.now().isoformat(),
            "phase": phase,
            "action": action,
            "observation": observation,
            "decision": decision,
            "experiment_ids": experiment_ids or [],
            "tags": tags or [],
        }
        self._append_to_index("research_log.json", entry)
        self._sync_to_remote("research_log.json")
        return entry["entry_id"]

    def get_research_log(self) -> list[dict]:
        return self._load_index("research_log.json")

    # --- Thinking Journal (freeform, real-time research thinking) ---
    def think(self, thought: str, context: str = "", experiment_ids: list[str] | None = None) -> str:
        """Record a real-time thinking entry — what the researcher is noticing,
        questioning, hypothesizing, or deciding RIGHT NOW.

        This is NOT a summary. It's stream-of-consciousness reasoning:
        'I just saw X. That's weird because Y. Maybe Z is happening.
         Let me try W to test this hypothesis.'
        """
        entry = {
            "id": uuid.uuid4().hex[:8],
            "timestamp": datetime.now().isoformat(),
            "thought": thought,
            "context": context,
            "experiment_ids": experiment_ids or [],
        }
        self._append_to_index("thinking_journal.json", entry)
        self._sync_to_remote("thinking_journal.json")
        return entry["id"]

    def get_thinking_journal(self) -> list[dict]:
        return self._load_index("thinking_journal.json")

    # --- Open Questions (things the researcher is puzzled about) ---
    def add_question(self, question: str, priority: str = "medium",
                     related_experiments: list[str] | None = None) -> str:
        """Record an open research question that needs investigation."""
        entry = {
            "id": uuid.uuid4().hex[:8],
            "timestamp": datetime.now().isoformat(),
            "question": question,
            "priority": priority,  # low, medium, high, critical
            "status": "open",  # open, investigating, answered
            "answer": "",
            "related_experiments": related_experiments or [],
        }
        self._append_to_index("open_questions.json", entry)
        self._sync_to_remote("open_questions.json")
        return entry["id"]

    def answer_question(self, question_id: str, answer: str) -> None:
        """Mark a question as answered."""
        questions = self._load_index("open_questions.json")
        for q in questions:
            if q["id"] == question_id:
                q["status"] = "answered"
                q["answer"] = answer
                q["answered_at"] = datetime.now().isoformat()
                break
        filepath = self.memory_dir / "open_questions.json"
        with open(filepath, "w") as f:
            json.dump(questions, f, indent=2, default=str)
        self._sync_to_remote("open_questions.json")

    def get_open_questions(self, status: str | None = None) -> list[dict]:
        questions = self._load_index("open_questions.json")
        if status:
            questions = [q for q in questions if q.get("status") == status]
        return questions

    # --- Knowledge Base ---
    def add_knowledge(
        self,
        category: str,
        content: str,
        evidence: list[str] | None = None,
        confidence: float = 0.5,
    ) -> str:
        item = {
            "item_id": uuid.uuid4().hex[:8],
            "category": category,
            "content": content,
            "evidence": evidence or [],
            "confidence": confidence,
            "created_at": datetime.now().isoformat(),
        }
        self._append_to_index("knowledge.json", item)
        self._sync_to_remote("knowledge.json")
        return item["item_id"]

    def get_knowledge(self, category: str | None = None) -> list[dict]:
        items = self._load_index("knowledge.json")
        if category:
            items = [i for i in items if i.get("category") == category]
        return items

    # --- Forecasts (save actual forecast values for later analysis) ---
    def save_forecasts(self, experiment_id: str, forecasts: list) -> None:
        """Save forecast details for an experiment."""
        data = []
        for f in forecasts:
            data.append(
                {
                    "date": f.date.isoformat() if hasattr(f.date, "isoformat") else str(f.date),
                    "point_forecast": f.point_forecast,
                    "variance_forecast": f.variance_forecast,
                    "model_name": f.model_name,
                }
            )
        fcast_file = self.results_dir / f"{experiment_id}_forecasts.json"
        with open(fcast_file, "w") as f:
            json.dump(data, f, indent=2)

    # --- Internal helpers ---
    def _append_to_index(self, filename: str, record: dict) -> None:
        filepath = self.memory_dir / filename
        data = self._load_index(filename)
        data.append(record)
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def _load_index(self, filename: str) -> list[dict]:
        filepath = self.memory_dir / filename
        if filepath.exists():
            with open(filepath) as f:
                return json.load(f)
        return []

    def get_summary(self) -> dict:
        """Get summary of all stored data."""
        experiments = self.list_experiments()
        log = self.get_research_log()
        knowledge = self.get_knowledge()
        return {
            "n_experiments": len(experiments),
            "n_log_entries": len(log),
            "n_knowledge_items": len(knowledge),
            "assets_studied": list(set(e.get("asset", "") for e in experiments)),
            "best_models": self._get_best_models(experiments),
        }

    def _get_best_models(
        self, experiments: list[dict], metric: str = "qlike", top_n: int = 5
    ) -> list[dict]:
        """Get top N models by metric (lower is better for qlike)."""
        scored = []
        for e in experiments:
            if metric in e.get("metrics", {}):
                scored.append(
                    {
                        "experiment_id": e["experiment_id"],
                        "model_name": e["model_name"],
                        "asset": e.get("asset", ""),
                        metric: e["metrics"][metric],
                    }
                )
        scored.sort(key=lambda x: x[metric])
        return scored[:top_n]
