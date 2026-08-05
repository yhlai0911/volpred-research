# governance 工作日誌（append-only）

## 2026-08-05 16:38–16:45（台灣時間）

**處理項**：
- `item_20260805T074441696044Z_r4-codex-desktop-session-codex`（P2，R4 長壽 Codex Desktop session 輪替政策）→ **outcome=done**
- `item_20260805T075043421203Z_2-a-...`（P2，經理投遞確認）→ outcome=done（本次即為要求的實際執行）
- `item_20260805T074138321044Z_item`（P3 測試件）→ outcome=noop，直接歸檔

**結論**：R4 裁定為「不新建機制、且政策案 blocked-on-R2」。owner-first 拆成三個 concern：
C1 backbone session 壽命已有 owner（codex_loop.sh 每 tick 新 exec + 禁裸跑 deny 規則）；
C2 rollout 磁碟占用應收編進既有 `log_rotate` job，不另建 cleanup；C3 老闆桌面對話壽命
無 owner 也無執行面，只能是建議、不進 layer map。政策本身擋在來源報告自承的 F2 會計
缺陷上——34.2% 這個數字的誤差上界足以翻轉結論，R2 未修前不得驅動行為政策。

**產出**：`reports/2026-08-05_r4_desktop_session_rotation_ruling.md`（含可直接貼給老闆的
一段白話說明，交由經理走 proposals 流程）、`memory/notes.md` 新增兩條可複用判準。

**未做**：C2 的收編實作（`scripts/` 不在本部門 owned_paths，已列為建議交 platform_eng）。

## 2026-08-05 16:41–16:50（台灣時間）

**處理項**：`item_20260805T084204237050Z_gate-gate-1-deny-block-pre-comm`（P1，老闆點名
「gate 太多、動不動被鎖」全量盤點）→ **outcome=done**

**結論**：病因不是 gate 數量，是同一候選被同一 gate 反覆擋。7 日窗 663 次阻擋只落在
30 個候選上（均 22 次/候選）；`event_reaction_coverage` 對單一 task 擋 246 次且其資料源
被 audit_health 標為 malformed = 活鎖。真正該收斂的是 4 道，不是 29 道。

**盤點覆蓋**：五層——control-plane 29 道（引用既有 canonical registry，未另建清單）、
Claude Code hook 6 個 owner + 8 條 Bash deny、git hook 5 個、CI 6 個 workflow、
merge_worktree.sh 8 個 ABORT 點。

**關鍵缺口**：後四層**完全無 deny telemetry**，「30 天擋幾次」在該層無法回答。
提案補 `storage/logs/hook_denials.jsonl`（唯一建議新增之物，且是計量不是新 gate）。

**anti-stacking**：artifact gate 與併發寫入判定為正確設計（同 script 雙入口／不同時點）；
arc dedup、digest、silent-fallback 三組疑似疊層已登記待複核。另發現
`enforcement_layer_map.md` 已過期（缺 `write_claim_guard.py`）——索引過期正是疊層溫床。

**產出**：`reports/2026-08-05_gate_inventory_and_convergence_proposal.md`（含 7 項裁決
清單）、`memory/notes.md` 新增三條判準。

**未做（依指令）**：未退役、未關閉、未放寬任何一道 gate，七項提案全數等經理裁決。
**取不到**：CI 觸發統計（`gh` 在本 session don't-ask mode 下被擋）；窗口是工具定義的
7 天而非任務要求的 30 天，未改口徑湊數。
