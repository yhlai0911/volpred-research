#!/usr/bin/env python3
from pathlib import Path

path = Path("src/volpred/ops/control_gate_lifecycle.py")
text = path.read_text(encoding="utf-8")
old = """        gate_verdicts.append(verdict)\n        if materialize_reviews and due:\n            stored, created = _materialize_review_task(\n"""
new = """        gate_verdicts.append(verdict)\n        # A due decision is not actionable when any required evidence source is\n        # unhealthy.  Missing or malformed inputs mean \"unknown\", not zero\n        # observations; materializing a PDCA review in that state fabricates a\n        # clean review window and can flood the canonical task pool.  The\n        # audit-health breach remains visible below, while actuation fails\n        # closed until the evidence graph is readable again.\n        gate_sources_healthy = all(\n            source.get(\"ok\") is True for source in source_health\n        )\n        if materialize_reviews and due and gate_sources_healthy:\n            stored, created = _materialize_review_task(\n"""
if old not in text:
    raise SystemExit("target block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
