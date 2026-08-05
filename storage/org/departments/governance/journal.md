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


## 2026-08-05T09:00Z — 兩張 canonical 任務（alert 系列漂移 ＋ 週次 doc drift audit）

`outcome=done`（audit）／`outcome=blocked`（alert，卡在轄區不在治理部）

**一句話結論**：本班最有價值的產出不是修好文件，而是證明了改組把治理部設計成
「有職責、沒轄區」——`audit_enforcement_map.py` 紅燈只差一行就能修，而治理部在章程與
權限層兩處都被擋住，連本週報告都寫不進 `docs/governance/2026-08/`。

**任務 1 alert_series_registry_20260805**：先用原 detector 複驗（`series_registry.py --json`
→ drift=1，仍 breached，非照舊快照執行）。根因：`mile_63e0e1ff` 帶權威 marker
`details.event_series_slot='T-2'` 且已 published、標題已掛前綴，卻不在 registry members。
remediation 要寫 `config/article_series.json`（不在轄區）→ request 送內容部執行、
送平台工程部處理結構性根因（members 應由 marker 推導，這是 §M class 第 4 次漂移，
且方向與 2026-07-15 相反：那次是有文章沒 marker，這次是有 marker 沒註冊）。

**任務 2 週次 doc drift audit**：報告 `reports/doc_drift_audit_20260805.md`。上週 4 條
追蹤全數結案（1 撤回為偽陽性、1 觸發條件消失、1 維持原決策、1 補完）。新開 3 條 finding。
`enforcement_layer_map.md` 缺 `write_claim_guard.py` 是本部門**連續第二班**指出同一件事
（前一班 2026-08-05 gate 盤點已記），仍未修，因為修不了——這已不是遺漏而是授權缺口。

**未做**：未新增／退役任何 enforcement；未修改任何 `.claude/skills/*`（故未觸發寄信）；
未動 `config/`、`docs/`、`scripts/` 任何一個字。
**取不到**：`check_skills_complete.sh` 在本 session 被權限層擋（shell script 直呼），
改以逐檔 `git log` ＋ 路徑 stat 做實質檢查，未用舊快照冒充。


## 2026-08-05T09:15Z — R4 裁決數字更正（34.2% → 59.0%，fork root 口徑）

`outcome=done`

**一句話結論**：更正後我自己下的 blocked 站不住了，所以一併解除——數字不是只換一個
百分比，它推翻了 v1 停手的理由。

**複核**：沒有從資源監控部的摘要轉抄。直接回讀
`resource_monitor/memory/token_breakdown_2026-08-04_7d.json` 的 `codex_duplicate_audit`：
`worst_roots[0]` = root `019f8e4d`，76 個 rollout 檔，去重後 106,410,266；全體重複量
4,067,614；`totals.billable_total` 184,380,508 → 去重後 180,312,894。
106,410,266 ÷ 180,312,894 = **59.01%**，與 request 一致。

**裁決變更**：v1 把 R4 標 blocked-on-R2，理由是「重複量若落在 60.1M 上界，34.2% 會腰斬、
結論反轉」。實測重複量 4.07M（上界的 7% 不到），而失真的真正機制是 fork 拆檔造成的
**低估**——不在 v1 列出的偏誤方向裡。阻塞理由消滅 → **解除 blocked**，A 項改為
「C3 是否上呈老闆由經理裁決，治理部意見是值得上呈」。§1 anti-stacking 三列**一字未改**
（它從不依賴這個數字；嚴重度提高不會憑空長出平台能執行的介面）。

**口徑**：R3 的 103.76h 與給老闆段落的 238h 都是分身值，全部改為「≥ 下界，root 層級待
重算」；34.2% 保留在 §2.1 標明為已被取代的舊值，不刪改。給老闆的白話段落整段重寫
（v1 說「先不建議改變習慣」，方向已相反）。

**制度化**：`memory/notes.md` 原判準補上另一半——誤差上界不等於誤差；下 blocked 要寫明
自動解除條件；口徑修好要回頭收自己的 blocked。
