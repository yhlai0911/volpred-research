"""Agent completion monitor.

Checks if background agents have completed and triggers follow-up actions.
Run periodically via CronCreate or loop.

Usage: uv run python scripts/agent_monitor.py
"""
import json
import os
from pathlib import Path
from datetime import datetime

TASK_DIR = Path("/private/tmp/claude-501") 

def check_agents():
    """Check for completed agents and report."""
    # This is a placeholder — actual agent monitoring needs Claude Code's internal API
    # For now, just check if output files have grown since last check
    
    status_file = Path("storage/agent_status.json")
    if status_file.exists():
        prev = json.loads(status_file.read_text())
    else:
        prev = {}
    
    current = {}
    task_dir = list(TASK_DIR.rglob("tasks/*.output"))
    
    for f in task_dir:
        agent_id = f.stem
        size = f.stat().st_size
        current[agent_id] = size
        
        if agent_id in prev and prev[agent_id] == size and size > 0:
            print(f"  ✓ Agent {agent_id}: completed ({size} bytes, unchanged)")
        elif size > 0:
            print(f"  ⏳ Agent {agent_id}: working ({size} bytes)")
        else:
            print(f"  ⏸ Agent {agent_id}: not started")
    
    status_file.parent.mkdir(parents=True, exist_ok=True)
    status_file.write_text(json.dumps(current, indent=2))
    print(f"\n  Checked {len(current)} agents at {datetime.now().strftime('%H:%M:%S')}")

if __name__ == "__main__":
    check_agents()
