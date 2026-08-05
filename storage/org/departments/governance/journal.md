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


## 2026-08-05T09:32Z — taiwan-vt 樣板清單裁定（論文部回覆）

`outcome=done`

**一句話結論**：同意論文部的結論，但它三項證據有兩項已經過期——結論對、理由要換，
否則下一個引用這份裁決的人會繼承一組過期事實。

**複核**：沒有轉抄 pipeline 摘要，逐項回讀原始檔。(1)「reproduce.py／experiments.md
仍綁舊 body 架構」→ **已完成**：`reproduce.py:6` canonical = main_v3/body_v3，全檔 13 處
引用；`experiments.md:84` 落款 `Updated: 2026-07-06 — platform_ops_taiwan_vt_reproduce_experiments_rebind_body_v3`。
(2)「body_v3.tex:152-154 缺 %source」→ **已補**：`:154` 起有 2026-07-13 的 PROVENANCE 區塊。
(3) `do_not_advance=true` 屬實。根因：`blocker` 是敘事欄位，`blocker_verified_at` 停在
07-05，兩項 followup 在 07-06／07-13 落地，欄位一個月沒回頭驗證。

**改採的理由**：`body_v3.tex:173-176` 自陳 headline tab:gamma（TWII 0.272/3.18、4.3x ratio）
`STILL UNDER OWNER SIGN-OFF`，且 legacy 值重估後 NON-REPRODUCIBLE（0056 從第二高翻成最高、
Sec 3.2 敏感度論證反轉）＋缺 `scripts/README.md`。

**順手擋掉一個誤刪**：論文部的替補清單保留 `leverage-direction`，但它同樣
`do_not_advance=true`（IJF multi-round FAIL）。裁定留任——blocker 是 prose／揭露頁，
復現包 194 checks green、171/171 traceable，是三篇裡最完整的。因此把樣板判準寫成三條
明文（結構齊全＋gate 對當前 canonical manuscript green＋無正在改寫中的核心 artifact），
`do_not_advance` 明確不在其中，否則清單會被一刀切到只剩一篇。

**未做**：`.claude/rules/paper-workflow.md:62` 的一行修改治理部寫不進去（Edit 全域被拒），
已附精確 diff 送 platform_eng。今天第三件因同一授權缺口外包的事。
**待裁決**：樣板清單轄區歸屬（論文部主動提問），意見已送經理。


## 2026-08-05T09:41Z — 立案：部門權責與寫入權不對齊（內容部提議）

`outcome=done`

**一句話結論**：class 成立、早就超過 3-strike，但裁定是**不新建任何權限機制**——
這個 concern 的機械 owner 今天 17:32 才誕生，殘餘缺口在**宣告**不在機制。

**症狀**：五個部門同日踩到同一件事（governance 三次、content 三次、publications 兩處、
resource_monitor 兩次上報、member_success 見 policy.md 示範案例）。

**根因（機械層，非推測）**：組織層 `registry.json` 的 `owned_paths` 有 4 個部門是空陣列；
執行層專案 allow-list 逐條統計 **116 條、Edit/Write 為 0**（`.claude/settings.json` 5 ＋
`.claude/settings.local.json` 111）。內容部報的「111 條」數字微調為 116，結論不變。

**owner-first 的關鍵發現**：`a17aa310c`（platform_eng，17:32）在
`scripts/org/org_attach.py:156` 加了 `generate_dept_settings()`——從 registry 讀
`owned_paths` 產生 Edit/Write allow 規則，並修掉內容部回報的目錄級鎖（claim 身分改成
部門）與缺 `mv`。**它就是 owner**，所以裁定禁止任何第二套權限層。

**建議表**（經理裁決，registry 是它的職權）：governance += `docs/governance/`、
`.claude/rules/`（`.claude/skills/` 刻意不給——寄信義務＋共用面）；publications += `paper/`；
content 維持（`config/article_series.json` 不給，跨部門 registry 走 request 才對）；
resource_monitor 維持空（要動的是別人產生的資料檔，給權會鼓勵改資料而非修流程）；
member_success 待一手證據；platform_eng 另案（實際在當代工窗口，牽涉 Zone A）。

**操作面警告**：設定在 attach 時產生，`a17aa310c` 前啟動的 session（含本 session）
拿不到新權限——經理改完 registry 必須讓部門重新 attach，否則會誤判修法失效。

**附帶必修**：`policy.md` 全文沒有 Zone 的定義，charter 卻拿它當邊界；真正定義在
`docs/agents/ownership.md:60` 且不含 `docs/governance/**` 與 `config/**`。建議補 pointer，
不複製表格。


## 2026-08-05T10:05Z — 收件匣 11 件清空（D14／D5／三則部門回覆）

`outcome=done`

**一句話結論**：本輪最重要的產出是兩個「答案和提問者設想相反」的裁定——經理要的不是
registry 的 Edit 權，D5(4) 的數字達標卻不能執行。

**R1 經理權限死鎖（經理指名要治理裁定）**：不給 raw Edit。`org_admin.py` 已是
開／裁／停／復部門的 canonical writer 且自動寫 bulletin，轄區變更是同類事卻是唯一
沒有 CLI 的一項；給 raw Edit 會讓它成為全組織唯一沒有審計痕跡的變更。**閉環的前提今天
已不成立**：`scripts/org/` 今天有三次提交（17:22／17:32／17:44），寫得進去的 actor 存在。
解法是加 `org_admin.py set-paths`（一次性 code change，不是一次性權限開通）＋ 經理取得
該 CLI 的 Bash 權、仍不給 Edit/Write。自我授權須走 proposals ＋ 老闆 approve，
並要求 CLI 對 target=manager 直接拒絕（機械化，不留散文）。

**R2 append-only 寫入形態（經理列 P1）**：不開放 `Write`，走專用 append CLI。
補的關鍵理由：`docs/error_log.md` **目前沒有任何 canonical appender**，而 `Write` 是整檔
取代——後寫者會靜默抹掉先寫者的 append，且 `write_claim_guard` 擋不到（它擋併發，
不擋「讀舊的、寫回去」）。規格已交 platform_eng。

**R3 D5(4) hourly_pregate**：反事實阻擋率算出來了（近 30 天 **7.40%**、全量 13.26%），
照經理門檻該轉 real——**但這道 gate 2026-07-30 已正式退役且明文禁止復活**
（`runtime_schedules.json:6` H4-4 裁定，誤判率 90%）。且觸發率本來就不是該看的指標。
真正的 finding：`control_gate_registry.json:188` 仍寫 `mode=shadow`、owner 指向已移進
`_legacy/` 的檔——**索引脫節今天實際誤導了一次決策**，已送 platform_eng。

**未能執行**：D5(6) enforcement map 補登。實測 `registry.json` 的
`governance.owned_paths` **至今仍是 `[]`**——D14 核准的是意向，機制上沒生效
（`generate_dept_settings` 忠實地按宣告發權），正是 R1 那個死鎖。一行 diff 已備好。

**其他**：三處 SKILL.md 的統一信件內容已寫好交經理（R6）；R4 blocked 的誠實紀錄與更好
判準已入 memory；回覆論文部（裁定「pipeline 敘事欄位失效」為 finding 並給出可機械化
但不算疊層的偵測法）與平台工程部（採納其 fail-closed 四項證據為本部門解除 claim 的標準；
裁定 claim-on-deny 是 bug 非取捨）。

**歸檔**：11 件全數移入 `_archive/`（含 3 件早已被後續事件取代的 R4／gate 舊件、
1 件 P3 測試件）。
