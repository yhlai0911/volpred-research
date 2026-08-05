# governance 部門私有記憶

## 判準：帶已知會計缺陷的成本證據，不得直接驅動行為政策（附 v2 修正：誤差上界 ≠ 誤差）

（2026-08-05 立，同日 v2 修正 — R4 桌面 session 輪替案）

**v2（同日 17:10）**：本案的 blocked 只活了半小時。資源監控部用 fork root 收斂實測，
重複量只有 **4.07M**（不到當初 60.1M 上界的 7%），而 34.2% 之所以失真是因為 fork 把
一個對話拆成 76 個 rollout 檔造成的**低估** —— 真值 **59.0%**，方向與擔心的相反。
三條教訓：(a) **誤差上界不等於誤差**，列了上界不代表窮舉了偏誤方向；(b) 下 blocked 時
就要寫明「什麼證據出現時自動解除」，否則嚴謹會變成拖延；(c) **口徑修好要回頭解除自己
下的 blocked**，上游不會替你收。下面的原判準本身仍然成立，只是要配這半條一起用。

資源監控部報告同時給出「桌面互動佔 34.2%」與「fork 重複計算上界 60.1M」。兩者相衝：
若重複落在上界，結論反轉。**證據自帶誤差上界且上界足以翻轉結論時，五步 Gate 的第 1 步
（證據化症狀）就還沒過**，不得進第 3 步做底層修正，更不得驚動老闆改變工作方式。
處置：把政策案排在口徑修正案之後，標 blocked-on-<修正案>。

## 判準：無執行面的 concern 不算「缺 owner」

同案 C3。老闆桌面 Codex.app 的 session 壽命，平台沒有任何 hook / cron / deny 能干預。
這種 concern 就算沒有 owner，也不該為它新建機制——能寫出來的只會是 prose 提醒，
依 CLAUDE.md 升級路徑那是 strike 1 層級，不進 `docs/governance/enforcement_layer_map.md`。
正確出口是「對老闆的建議」，走經理的 proposals 流程。

## Owner-first 查法（本部門標準動作）

1. `docs/governance/enforcement_layer_map.md` 四張表（hooks / deny / CI / git hooks）
2. `config/runtime_schedules.json` 找語意最接近的既有 retention / cleanup job
3. 對疑似 owner 的 script 直接 `rg` 關鍵詞驗證它真的管這件事，不憑檔名推斷

## 判準：gate 是否過度封鎖，看 block/候選 比值，不看 gate 數量

（2026-08-05，老闆點名「gate 太多」案）

7 日內 663 次阻擋只落在 30 個候選上。數量不是問題，**同一候選被同一 gate 反覆擋**才是。
比值 ≈ 1 = 健康（擋一次、修好就過）；≫ 1 = deny 訊息沒給出可走的出路。
極端案例 `event_reaction_coverage` 對單一 task 擋 246 次，且該 gate 的資料源同時被
`audit_health` 標記 malformed —— 活鎖，不是防護。

推論：**零觸發的 contract gate 不是老闆體感的來源**（沒擋到人就感覺不到），
不該因「看起來沒用」被列入收斂範圍。

## 缺口：Claude Code hook / git hook / merge gate 層完全沒有 deny telemetry

`pretooluse-bash-optimizer.sh` 不寫 deny log，其餘 hook 只回 permissionDecision 不落盤，
merge_worktree.sh 的 8 個 ABORT 點無拒絕 receipt。**無法計數的 gate 無法被評估、
也就無法被收斂。** 下次做 gate 盤點前，先確認這層是否已補上
`storage/logs/hook_denials.jsonl`（提案編號 5，2026-08-05 送經理）。

## 資料來源：control-plane gate 已有 canonical registry，不要另建清單

`config/control_gate_registry.json`（registry）＋ `src/volpred/ops/control_gate_lifecycle.py`
（lifecycle owner）＋ `storage/ops/control_gate_lifecycle_latest.json`（7 日 inventory，
含 per-gate trigger_count / blocking_count / distinct_candidates / audit_health）。
registry 強制每道 gate 帶 `incident_refs`，是全平台立項紀律最好的一層。
另一半（hook / git hook / CI）的 owner 是 `docs/governance/enforcement_layer_map.md`，
用 `scripts/audit_enforcement_map.py` 驗它有沒有過期——2026-08-05 當下是過期的。


## 判準：治理部有職責、沒轄區——動手前先確認寫得進去

（2026-08-05，週次 doc drift audit）

治理部 `owned_paths = []`，charter 只授權部門子樹＋「Zone C 共用區」，而 Zone C 的真正
定義在 `docs/agents/ownership.md:60` 是一張 **7 列具名表**，不含 `docs/governance/**`、
不含 `config/**`。`policy.md` 全文沒有 Zone 的定義。實測：`Write docs/governance/2026-08/...`
被拒。**所以治理部的標準產出（audit 報告、enforcement layer map 維護）目前寫不進 canonical
位置。** 在做任何「我來修一下」的判斷前，先確認目標路徑寫得進去，寫不進去就走 request，
不要把一整班的分析做完才發現交不出去。

## 陷阱：被 deny 的寫入仍然會留下 45 分鐘 path claim

同班實證。PreToolUse claim guard 在權限判定**之前** auto-claim，所以嘗試過就算數。
兩個後果：(a) 自己會在 `path_claims.py list` 上看到一堆自己根本沒寫成的 scope；
(b) 別人被擋時收到的訊息會說「持有者正在寫」，而事實是持有者一個 byte 都沒寫。
已送平台工程部。**判準：claim 清單不是「誰在寫」的證據，只是「誰試過」。**

## 判準：staleness 時間戳不是 drift，要用實質檢查取代

上週列的 7 個 stale_skills，本週全部在 2026-07-29 被動過——觸發條件自己消失了，
但那不代表它們曾經有問題。改用**引用路徑存在性**做實質檢查（24 條引用、0 失效）才有結論。
`check_skills_complete.sh` 的 `stale_skills` 欄位只能當「看一下」的提示，不能當 finding。

## 讀規則要讀上下文：`scripts/README.md` 是 paper-scoped

`.claude/rules/paper-workflow.md:42` 的 `scripts/README.md` 指的是 `paper/<name>/scripts/README.md`。
上週 audit 按 repo root 去 stat，判成「檔案不存在」的 finding，是偽陽性。
**規則裡的相對路徑，先找它的「此處」是哪裡。**


## 判準：引用敘事欄位前，先看它的 `*_verified_at`

（2026-08-05，taiwan-vt 樣板清單案）

論文部拿 `paper_pipeline_status.json` 的 `taiwan-vt.blocker` 當現況證據下裁決，
三項理由有兩項在一個月前就已經被做完了——欄位的 `blocker_verified_at` 停在 07-05，
followup 在 07-06 與 07-13 落地，沒人回頭改欄位。

**帶時間戳的欄位，時間戳就是它的有效期聲明；沒回頭驗證的敘事欄位不是證據，是留言。**
本部門複核他部門結論時的標準動作：把敘事欄位講的每一件事回讀到原始檔（tex / py / md
的實際行），對得上才採用。這次三項有兩項對不上，而結論方向仍然正確——**理由錯了但
結論對，仍然要換理由**，否則下一個引用這份裁決的人會繼承一組過期事實。

## 判準：樣板／範例清單不能用 pipeline 狀態欄位一刀切

同案。`do_not_advance=true` 對 `taiwan-vt` 與 `leverage-direction` 同時成立，但前者是
headline 數字未簽核（該移出），後者是 prose 與揭露頁草稿、復現包本身 171/171 traceable
（該留任）。**樣板示範的是結構與 provenance 慣例，不是結論已定案。**
判準寫成明文放在 `reports/2026-08-05_paper_exemplar_list_ruling.md` §3，
下次有人要動清單時引用它，不要重新發明標準。


## 判準：看到「沒有權限」的回報，先找產生器，不要建機制

（2026-08-05，部門權責與寫入權不對齊立案）

五個部門同日踩到同一件事，看起來像是該建一套權限管理。**不是。** 正解是
`scripts/org/org_attach.py:156 generate_dept_settings()`（platform_eng 當日 17:32 落地，
`a17aa310c`）：它從 `registry.json` 的 `owned_paths` 產生 `Edit`/`Write` allow 規則，
範圍是部門子樹＋owned_paths，不多給一寸。

**宣告與權限是同一件事的兩半，中間不該有人工翻譯。** 所以：
- 要更多權限 → 改 registry 的**宣告**（經理職權），讓既有產生器去發
- **不得**手寫 `departments/<dept>/settings.json`、不得放寬全域 allow-list、
  不得把 `VOLPRED_ALLOW_CONCURRENT_WRITE` 當日常出路 —— 那都是繞過產生器＝第二份真相

**操作面陷阱（會讓人誤判修法失效）**：設定是在 **attach 時**產生的。改完 registry 若
不重新 attach，舊 session 一樣寫不進去。回報「修了沒用」之前先確認這一點。

**數字備查**：專案 allow-list 共 116 條（`.claude/settings.json` 5 ＋
`.claude/settings.local.json` 111），其中 Edit/Write **0 條**——這是 don't-ask 模式下
所有部門寫入被拒的機械解釋。
