#!/usr/bin/env python3
"""Record WHY a dispatch fire acted; never use the receipt as ownership proof.

The dispatched agent does not run ``git add`` / ``git commit``. Since Issue #43,
repo-byte ownership comes from the isolated workspace's declared output paths and
durable settlement receipt; the machine finalizer alone gates and lands them.
PHASE-Z may still commit explicitly classified machine state and drain finite
legacy recovery receipts, but it may not infer agent authorship from timing.

This receipt carries explanatory metadata — *why* the fire acted — for the audit
trail and any cohort machine-state commit caption. It cannot add a path to the
owned set and cannot authorize the retired manifest Stage 3:

    uv run python scripts/fire_receipt.py \
        --task-id k1702_followup \
        --subject "K1702 收件：raw-MDD 改善是 scale artifact，降級 R3 措辭" \
        --body "全量掃 knowledge.json 命中 12 筆；K1265b 補跑 vol-normalized MDD。"

The Stop hook (``scripts/hooks/enforce_fire_receipt.py``) asks for it when the
legacy PHASE-Z caption seam sees attributable output. A missing receipt can reduce
explanatory quality, but it cannot lose or transfer workspace ownership.

That gate is here because the 2026-07-13 refactor left this step to agent
self-discipline on the theory that skipping it was merely cosmetic. The theory held;
the discipline did not. Over the following 14 days, 186 of 266 dispatch commits
(~70% of fires with output) carried a generated message, the accompanying warn became
hourly noise, and the boss read it as the system misfiring (msg 886, 2026-07-16).
A step everyone must remember, with nothing checking, is not a rare miss — it is the
default path.

Skipping cannot lose work: isolated workspace settlement is independent of this
file. The failure mode is an audit-caption gap, never an ownership fallback.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dispatch_supervisor.phase_z import write_fire_receipt  # noqa: E402
from volpred.ops import fire_manifest  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--subject", required=True,
                    help="一句話 what changed | why（legacy/machine-state caption）")
    ap.add_argument("--body", default="",
                    help="細節：掃了什麼、改了什麼、驗證方式（稽核說明）")
    ap.add_argument("--body-file", default="",
                    help="從檔案讀 body（UTF-8）。多行 / 中文 body 用這個，"
                         "不要在 shell 裡 heredoc 出暫存檔再 --body \"$(cat ...)\" —— "
                         "agent shell 的 heredoc 會寫出壞掉的 CJK 位元組，"
                         "receipt 端讀到就炸 UnicodeDecodeError（2026-07-13 實際踩到）")
    ap.add_argument("--task-id", default="",
                    help="next_tasks.json 的 task id，用於反查")
    ap.add_argument("--repo-root", default=str(REPO_ROOT))
    args = ap.parse_args(argv)

    body = args.body
    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")

    # A CJK --subject/--body handed in as a shell argument can arrive as surrogates:
    # the agent shell emits bytes that are not valid UTF-8, and Python's argv decoder
    # parks them as lone \udc80-\udcff. Nothing complains until the receipt is written,
    # where f.write() dies with "surrogates not allowed" — an error that says nothing
    # about the actual fix. Same family as the 2026-07-13 --body-file note above.
    # Say it at the boundary instead, in the one place the caller can act on.
    for flag, value in (("--subject", args.subject), ("--body", args.body)):
        if any("\ud800" <= ch <= "\udfff" for ch in value):
            print(
                f"[fire_receipt] {flag} 的位元組不是合法 UTF-8（經過 shell 時壞掉了）。\n"
                f"[fire_receipt] 改法：用 Write 工具把文字寫成 /tmp/receipt.txt，再 --body-file /tmp/receipt.txt。\n"
                f"[fire_receipt] --subject 若含中文，用 SUBJ=$(cat /tmp/subject.txt) 再帶入。",
                file=sys.stderr,
            )
            return 2

    ok = write_fire_receipt(
        Path(args.repo_root),
        subject=args.subject,
        body=body,
        task_id=args.task_id,
    )
    if not ok:
        # Non-fatal by design: a failed receipt must never fail the agent's task.
        # Workspace settlement is independent; only explanatory metadata is lost.
        print("[fire_receipt] 無法寫入 receipt — workspace settlement 不受影響，但缺少稽核說明",
              file=sys.stderr)
        return 1
    fire_id = os.environ.get("VOLPRED_FIRE_ID", "").strip()
    if fire_id:
        try:
            fire_manifest.seal(Path(args.repo_root), fire_id)
        except Exception as exc:  # noqa: BLE001 — receipt/commit remains fail-open
            print(f"[fire_receipt] manifest seal 失敗（仍保留 receipt）：{exc}", file=sys.stderr)
            return 1
    print(f"[fire_receipt] 已記錄：{args.subject}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
