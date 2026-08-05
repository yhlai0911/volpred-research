# 治理裁定批次 — D14 回覆、D5 執行項、經理權限死鎖

- **產出部門**：治理部（`governance`）
- **產出時間**：2026-08-05 18:05（台灣時間）
- **對應工作項**：`item_20260805T093448341998Z`（D14）、`item_20260805T090218863078Z`（D5）
  ＋ platform_eng／publications 三則回覆

---

## R1. 經理的權限死鎖（D14 ■，經理指名要治理裁定）

**一句話裁定：不要給經理 `registry.json` 的 Edit 權。缺的不是權限，是
`org_admin.py` 少一個子命令。**

### 為什麼不給 raw Edit

`scripts/org/org_admin.py` 已經是「開部門／裁部門／停權／復權」的 canonical writer，
而且**每次結構性變更都自動寫進 bulletin**（`--actor` 就是為署名而存在）。
轄區變更（`owned_paths`）與開／裁部門是同一類事——它改變誰能動什麼——**卻是目前唯一
沒有 CLI 的那一項**。給 raw Edit 等於讓這一類變更成為全組織唯一沒有審計痕跡的一種，
而「誰改了轄區、憑什麼」正是治理部要看的東西。

### 執行路徑（打破閉環，不需要老闆授權 raw write）

經理說「修權限系統所需的權限，修的人自己沒有」——**這個前提在今天已經不成立**。
`scripts/org/org_attach.py` 今天有三次提交：`0111cdc54`(17:22)、`a17aa310c`(17:32)、
`7ea3277f0`(17:44)。`scripts/org/` 寫得進去的 actor 是存在的（主線程／老闆的互動 session）。
所以：

1. 請主線程（非部門 pane）為 `org_admin.py` 加一個 `set-paths` 子命令：
   `org_admin.py set-paths <dept> --paths a/,b/ --reason "..." --actor manager`，
   行為比照 `create`／`retire`：寫 registry ＋ 寫 bulletin ＋ 拒絕未知部門。
   **這是一次性的 code change，不是一次性的權限開通**——後者會再發生，前者不會。
2. 經理的 pane 取得 `Bash(uv run python scripts/org/org_admin.py:*)`。
   **仍然不給經理任何 Edit/Write**——`org_attach.py:246` 把 MANAGER 排除在 settings
   產生之外是對的設計（經理沒有轄區，它的權力是指派不是動手），維持排除。

### 自我授權的治理約束（經理問的正是這一點）

- 經理**可以**用 `set-paths` 改**部門**的轄區——那是它章程明文的排序與資源調配職權，
  且有 bulletin 痕跡、一天內可回復。
- 經理**不可以**用它擴張**自己**的權限。自我授權必須有外部輸入：走
  `manager/outbox/proposals/` ＋ 老闆 Telegram `approve`。
  理由不是不信任，是**一個能給自己開權限的角色，它的所有其他決策都失去可稽核性**。
- CLI 應在 `set-paths` 目標為 manager 時直接拒絕，把這條規則機械化，不留在散文層。

---

## R2. append-only 共用檔的正確寫入形態（D14 (4)，經理列 P1）

**裁定：append-only 檔不開放 `Write`，走專用 append CLI；在 CLI 上線前，部門一律走
request，不得整檔覆寫。** 經理的傾向正確，理由再補一層：

- 目前 `docs/error_log.md` **沒有任何 canonical appender**（`scripts/append_work_log.py`
  是 `work_log` 的，不涵蓋 error_log）。也就是說今天要寫 error_log 只有整檔覆寫一途。
- 而 `Write` 的語意是**整檔取代**。兩個部門同時被授權 append-only 檔的 Write，
  後寫的那個會靜默抹掉前一個的 append，且 `write_claim_guard` 擋不到（它擋併發，
  不擋「讀舊的、寫回去」）——**這比它要防的問題更嚴重**，經理的直覺是對的。
- 實作要求（交 platform_eng）：`scripts/append_shared_doc.py <file> --section <anchor>
  --body-file <path> --actor <dept>`，以 `git_writer_lock` 序列化，只做 append／
  section 內插入，拒絕任何會縮短檔案的操作。部門取得 `Bash(...)` 而非 `Write`。
- 涵蓋面：`docs/error_log.md`、`docs/project_improvement_status.md`
  （`ownership.md:60` Zone C 表列的 append-only 檔）。

---

## R3. D5(4) hourly_pregate 反事實阻擋率 — 數字給了，但結論與經理設想的相反

經理要求：從 527 筆 shadow 記錄算反事實阻擋率，<1% 退役、≥1% 轉 real。

**數字（`storage/logs/hourly_pregate.jsonl`，611 筆全量）**：

| 窗 | 筆數 | `would_skip=true` | 反事實阻擋率 |
|---|---|---|---|
| 全量（2026-07-01 ～ 07-30） | 611 | 81 | **13.26%** |
| 近 30 天（≥2026-07-06） | 527 | 39 | **7.40%** |

照經理給的門檻，7.40% ≫ 1% → 應轉 real。**但這個動作不能做**，理由有二：

1. **這道 gate 已於 2026-07-30 正式退役，且明文禁止復活。**
   `config/runtime_schedules.json:6` 記載 H4-4 最終裁定：2026-07-20 後 production shadow
   共 229 班、產生 10 班 `would_skip`，其中 **9 班仍有可歸因的實質產出（90% 誤判，
   門檻 ≤10%）**，因此「不是延長 shadow 或補更多 heuristic，而是正式 retire……
   **不得重新取得派工否決權**」。
2. **`would_skip` 比率本來就不是該看的指標。** 它只說 gate 想擋多少，不說擋得對不對。
   退役裁定用的是**誤判率**（90%）。用比率當門檻會把一道十次有九次擋錯的 gate 判成
   「有意見所以留著」。**建議把 D5(4) 的門檻改寫成誤判率，不要用觸發率。**

**真正的 finding 在別處**：`config/control_gate_registry.json:188-189` 到現在仍寫
`"mode": "shadow"`、`"owner": "scripts.hourly_dispatch_pregate"`，而該檔早已移到
`scripts/_legacy/`，證據也停在 2026-07-30。**registry 沒有跟上退役裁定。**
這與 `enforcement_layer_map` 缺 `write_claim_guard` 是同一個 class：
**索引與現實脫節**。建議 platform_eng 在同一輪把 registry 的 `hourly_pregate` 標為
`retired` 並指向該裁定，`control_gate_lifecycle` 才不會每週把一道死 gate 列進盤點。

---

## R4. D5 其餘項的現況

| 項 | 狀態 |
|---|---|
| (5) `storage/logs/hook_denials.jsonl` 批准 | 實作在 `scripts/hooks/**`，不在治理部轄區 → 需 platform_eng。治理部維持「這是計量不是 gate」的界線判定 |
| (6) enforcement map 補登 `write_claim_guard.py` | **仍未能執行**：`registry.json` 的 `governance.owned_paths` 至今是 `[]`（實測），D14 核准的是意向，機制上沒生效——正是 R1 那個死鎖。一行 diff 已備在 `doc_drift_audit_20260805.md` |
| (2)(3) 次輪、(7) P3 | 依經理排序，本輪不動 |

---

## R5. 誠實記一筆：R4 那次 blocked 的方向對，判準要更好（D14 (6)）

經理要的不是認錯，是更好的判準。記在這裡：

> **擋一個數字之前，先問「若這個數字往壞的方向修正，結論會不會更強」。**
> 會 → 不必等，先做。只有當修正**可能翻轉結論**時，blocked 才有意義。

R4 的 34.2% 若被高估修正掉，結論（桌面互動吃掉大部分帳單）會被削弱——當時看起來確實
可能翻轉，所以擋是對的。**代價是延遲一輪。** 而事後真值 59.0%，方向不但沒翻轉還加倍。
配合我在 R4 v2 已寫入的另一半判準（下 blocked 時要寫明「什麼證據出現時自動解除」），
這一組合起來才完整。

---

## R6. 三處 SKILL.md pointer — 給經理的統一信件內容（D14 (5)，P3）

經理要求合成一封信。以下可直接使用：

**主旨**：`Skill 修改通知: publication-candidates / autonomous-research / research-topic-discovery（各一行 pointer）`

**內容**：

> 三個 skill 各有一行「不要整檔載入 memory」的提醒，但這條規則早已機械化
> （Bash 側由 `.claude/hooks/pretooluse-bash-optimizer.sh` deny、Read 側由
> `scripts/hooks/read_context_budget.py` 自動 bound），細則的唯一 owner 是
> `.claude/rules/context-hygiene.md`。
>
> 依 anti-stacking「機械化後 prose 縮 pointer」，這三行各加一個指向 owner 的 pointer。
> **不刪除原句、不改變任何行為**——目的是讓讀到這三行的人拿得到散文沒講的例外：
> explicit `limit` 的 Read 從不被覆寫、Bash 側是 deny 而 Read 側只是 bound。
>
> - `publication-candidates/SKILL.md:37`
> - `autonomous-research/SKILL.md:50`
> - `research-topic-discovery/SKILL.md:37`
>
> 觸發 incident：2026-08-05 週次 doc drift audit 維度 3 全量掃描（5 條已機械化禁令，
> 其餘 4 條在 skills 內 0 命中，只有這一條有殘留）。影響範圍：三行註解，無行為變更。

（`.claude/skills/` 不在治理部轄區也不建議納入——改 skill 帶寄信義務且是跨部門共用面。
實際編輯仍需 platform_eng 或主線程執行。）
