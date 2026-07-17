#!/usr/bin/env python3
"""Stop hook: a dispatch fire that produced output must not end without a receipt.

## 為什麼需要這個 hook

PHASE-Z 已經是 commit 的唯一 owner，agent 只剩一件事：交代**為什麼**改
（`scripts/fire_receipt.py`）。2026-07-13 的重構認為漏 receipt 是「cosmetic、
rare by design」，因此沒有任何 gate。

實測打臉（老闆 2026-07-16 Telegram msg 886「為什麼沒有理由？為什麼總是會有
這樣的情形？」）：近 14 天 dispatch commit 中 **186/266（有產出的 fire 約 70%）
沒有 receipt**。於是那則「agent 沒交代原因」的 warn 每小時都響，變成噪音。

根因不是 agent 特別懶，而是**責任結構**：
  - 做完事 → 直接結束 = 預設路徑（零成本）
  - 跑 receipt = 需要額外自律（且 prompt 第 252 行還明寫「漏跑不會掉工作」）
一個「每個 agent 都必須記得、但沒有任何東西會檢查」的步驟，不是罕見失誤，
就是預設行為。這與 `enforce_final_text.py` 是同一種病（prose 自律 → 3-strike →
升級為 Stop hook 硬攔），所以用同一種藥。

## 行為

- stdin 收 Claude Code Stop hook JSON（`stop_hook_active`）
- `stop_hook_active=true` → 放行（已 block 過一次，絕不無窮迴圈）
- 問 `phase_z.fire_output_needs_receipt()`：這班有沒有產出、有沒有 receipt
  （唯讀，絕不 consume receipt / snapshot —— 那兩個屬於稍後才跑的 PHASE-Z）
- 有產出且無 receipt → `{"decision":"block"}`，agent 補跑 `fire_receipt.py` 再結束
- 其餘一律放行（非 dispatch fire、工作區乾淨、只有 machine churn、已有 receipt）

## Fail-open 是刻意的

任何解析 / import / 探測失敗一律放行 + stderr 留 trace（no-silent-fallback）。
這個 gate 的最壞情況必須是「commit message 變醜」，永遠不能是「fire 被卡死」。
漏擋一次的代價是一行難看的 subject；擋錯一次的代價是整班 fire 燒 cap 被 SIGKILL。
兩者不對稱，所以偏向放行。

Regression test: scripts/tests/test_enforce_fire_receipt.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

REASON = (
    "PHASE Z 未完成：這班 fire 有產出，但沒有留下 fire receipt。\n"
    "\n"
    "PHASE-Z 會照常 commit（工作不會遺失），但 commit message 只能從 diff 自動生成 —— "
    "看得出動到哪些檔，看不出為什麼。git log 是這個系統唯一的 audit trail，"
    "「為什麼」只有你知道，機器補不出來。\n"
    "\n"
    "請立刻補跑（然後才結束這個 turn）：\n"
    "  uv run python scripts/fire_receipt.py \\\n"
    "    --task-id <task_id> \\\n"
    "    --subject \"<一句話 what changed | why>\" \\\n"
    "    --body \"<掃了什麼 / 改了什麼 / 怎麼驗證的>\"\n"
    "\n"
    "subject 禁止寫 'ops update' / 'wip' / 'save progress'（等於沒交代）。\n"
    "中文多行 body 用 --body-file，不要用 shell heredoc（會寫出壞掉的 CJK 位元組）。\n"
    "\n"
    "這班產出的檔案："
)


def _emit_allow(note: str = "") -> None:
    if note:
        print(f"[enforce_fire_receipt] allow: {note}", file=sys.stderr)
    sys.exit(0)


def main(argv: list[str] | None = None) -> None:
    # `--repo-root` is a test seam only (same convention as scripts/fire_receipt.py).
    # The registered hook passes nothing and probes the checkout it lives in, so a
    # stray flag cannot point the gate at a clean tree to talk itself out of blocking.
    args = sys.argv[1:] if argv is None else argv
    probe_root = REPO_ROOT
    if len(args) == 2 and args[0] == "--repo-root":
        probe_root = Path(args[1])

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except (ValueError, OSError) as exc:  # silent-ok: not silent — _emit_allow traces to stderr; deliberate fail-open (see module docstring)
        _emit_allow(f"unparsable stop payload ({exc}) — fail open")
        return

    # Already blocked once this turn. The agent got its nudge; a second block would
    # be a loop, and a fire trapped in a loop burns the 3000s cap. One nudge only.
    if payload.get("stop_hook_active"):
        _emit_allow("stop_hook_active — nudge already delivered")
        return

    try:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from dispatch_supervisor.phase_z import fire_output_needs_receipt
    except Exception as exc:  # noqa: BLE001  # silent-ok: not silent — _emit_allow traces to stderr; hook runs under bare python3 (no venv), so any import failure must fail open rather than trap the fire
        _emit_allow(f"cannot import phase_z ({exc}) — fail open")
        return

    try:
        verdict = fire_output_needs_receipt(probe_root)
    except Exception as exc:  # noqa: BLE001  # silent-ok: not silent — _emit_allow traces to stderr; a probe must never trap the agent (blocking costs a whole fire, missing one costs an ugly subject)
        _emit_allow(f"probe failed ({exc}) — fail open")
        return

    if not verdict.get("needs_receipt"):
        _emit_allow(verdict.get("reason", "no receipt needed"))
        return

    owned = verdict.get("owned") or []
    listing = "\n".join(f"  - {p}" for p in owned[:30])
    if len(owned) > 30:
        listing += f"\n  - …（共 {len(owned)} 個）"
    print(json.dumps({"decision": "block", "reason": f"{REASON}\n{listing}"}, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
