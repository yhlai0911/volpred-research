---
name: reference_unified_memory_one_brain
description: Telegram 與本機互動 session 是同一個大腦 — 共用同一份 auto-memory；headless claude -p 預設自動載入（2026-07-10 實測確認）；平行的 telegram_memory.md/py 已廢棄
metadata: 
  node_type: memory
  type: reference
  originSessionId: 257d8984-a4d3-475c-aa28-1eebcd51e6f1
---

**Telegram 與本機互動 session = 同一個運營經理、同一個大腦**（2026-07-10 統一，老闆 Telegram 指示「你的記憶跟我 telegram 互動的記憶是同一份、同一個大腦」）。

**唯一大腦 = auto-memory**：`~/.claude/projects/-Users-yhlai0911-volpred-research/memory/`（MEMORY.md 索引 + 各 memory 檔）。兩個管道共讀共寫同一份，無平行記憶、無同步。

**機制（實測依據）**：互動 session 的 auto-memory 綁 git repo；`telegram_responder` 則刻意從 repo 外 scratch cwd 啟動，故不能靠 `--add-dir`（它只授權工具存取）。Responder runtime settings 以 `autoMemoryDirectory` 明確指向本 canonical memory，確保仍是同一大腦；只有 `--bare` 才跳過。2026-07-10 的 repo-cwd headless 實測證明預設載入，2026-07-16 再補 scratch-cwd namespace override。

**已廢棄的平行記憶**（原基於「headless 沒有記憶注入」的錯誤假設，該假設 2026-07-10 被實測推翻）：
- `storage/ops/telegram_memory.md` → tombstone（內容已 migrate 進 auto-memory）
- `scripts/telegram_memory.py` → tombstone stub（fail-loud；殘留 add 落 deprecation log）
- `telegram_responder.sh` prompt 第 0 步已改：用內建 memory 系統寫 auto-memory，不再用 telegram_memory.py

**How to apply**：老闆經任一管道（Telegram / VS Code）交代長期指示 → 寫進 auto-memory（一檔一事實 + MEMORY.md pointer），下次任一管道都記得。**不要再建 channel-專屬的平行記憶**（那會退回「兩個大腦」）。回滾點 tag `snapshot-pre-memory-unify-20260710`。
