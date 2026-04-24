#!/usr/bin/env python3
"""Host-cron fallback for continue_task session cron.

Session cron `b604e1af continue_task 13 */12` 只在此 Claude Code session 活著時 fire。
Session 關閉後，此 host-cron stub 會在預定時間寫入 pending_continue.json；
下次 session 開啟時由 scripts/session_startup.md 的 replay 機制補跑 continue_task。

用意：確保「自動繼續研究」在 session 斷線時不完全靜默。

Schedule：host crontab `30 */12 * * *`（與 session cron `13 */12` 錯開 17 分鐘，
避免同 session 活著時雙路徑同時觸發）。

Replay 規則（session 啟動時）：
- 讀 storage/ops/pending_continue.json
- 若 last_fire_at 在 session 最近 continue_task work_log entry 之後 → 補跑 continue_task
- 跑完 clear last_fire_at → next_session_replay=false
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "storage" / "ops" / "pending_continue.json"


def main() -> int:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    now_iso = datetime.now(timezone.utc).isoformat()

    if STATE_PATH.exists():
        with STATE_PATH.open() as fh:
            state = json.load(fh)
    else:
        state = {
            "schema_version": 1,
            "description": "continue_task host-cron fallback stub",
            "last_fire_at": None,
            "fire_count": 0,
            "next_session_replay": False,
            "history": [],
        }

    state["last_fire_at"] = now_iso
    state["fire_count"] = int(state.get("fire_count", 0)) + 1
    state["next_session_replay"] = True
    history = state.get("history") or []
    history.append({"at": now_iso, "source": "host_cron_stub"})
    state["history"] = history[-50:]

    with STATE_PATH.open("w") as fh:
        json.dump(state, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"[continue_task_stub] wrote pending_continue.json at={now_iso} fire_count={state['fire_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
