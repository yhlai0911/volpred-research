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


## 判準：觸發率不是 gate 的健康指標，誤判率才是

（2026-08-05，D5(4) hourly_pregate 案）

經理給的門檻是「反事實阻擋率 <1% 退役、≥1% 轉 real」。實測 7.40%（近 30 天 39/527），
照門檻該轉 real——**但這道 gate 早在 2026-07-30 就正式退役了**，退役用的指標是
**誤判率 90%**（229 班 10 班 would_skip，其中 9 班仍有可歸因的實質產出）。

**`would_skip` 只說 gate 想擋多少，不說擋得對不對。** 用觸發率當門檻，會把一道十次
有九次擋錯的 gate 判成「它有意見所以留著」。要留要退，看的是它擋對的比例。

## 陷阱：退役裁定寫在 runtime_schedules，registry 沒跟上

同案。`config/runtime_schedules.json:6` 記著完整的退役裁定與「不得重新取得派工否決權」，
而 `config/control_gate_registry.json:188` 仍寫 `mode=shadow`、owner 指向已移進
`scripts/_legacy/` 的檔。**索引脫節今天實際誤導了一次決策**（經理差點下令轉 real）。

與 `enforcement_layer_map` 缺 `write_claim_guard` 同一 class：**索引與現實脫節**。
本部門的標準動作：引用任何 registry 的 `mode`／`owner` 欄位前，先確認 owner 檔案
還在原處、evidence 的 newest 時間戳還在窗內。

## 判準：擋一個數字之前，先問它往壞的方向修正會怎樣

（2026-08-05，經理 D14(6) 要求的更好判準）

**若這個數字往壞的方向修正、結論會更強 → 不必等，先做。**
只有當修正**可能翻轉結論**時，blocked 才有意義。R4 那次擋的方向是對的
（當時看起來可能翻轉），但代價是延遲一輪。配合 [[R4 v2 那條]]「下 blocked 要寫明
什麼證據出現時自動解除」，兩條合起來才完整。

## 操作標準：解除別人的 path claim，要用 fail-closed 四項證據

平台工程部處理 `.git/index.lock` 的做法立為本部門標準：**0 bytes ＋ 滯留秒數 ＋
`lsof` 無持有者 ＋ `ps` 無存活行程，四項缺一即中止；且改名保留不刪除**。
我今天解除同事的 `state.json` claim 時只憑「前一班已 commit」，判準比這弱，
下次照四項證據走。


## 判準：缺漏的時間戳必須判為最陳舊，否則是反向誘因

（2026-08-05，`blocker_verified_at` 門檻裁定）

經理問「過期多久算不可採信」。實測後發現題目要改寫：**13 篇論文裡 12 篇根本沒有
`blocker_verified_at`**，`taiwan-vt` 是唯一有的——它今天被抓出來不是因為比較糟，
**是因為它是唯一有時間戳可以檢查的一篇**。

純 TTL 規則會讓 12 篇靜默通過、只擋住唯一誠實記錄的那一篇。**記錄的被罰、不記錄的
暢行無阻**——設計任何 freshness 門檻時，第一件事是堵掉這個反向誘因：
**欄位缺漏 ⇒ 視同最陳舊，不是通過。**

三條判定順序：(1) 事件式主判準（verified_at 早於該目錄最後 commit ⇒ stale）；
(2) 缺漏即 stale；(3) TTL 7 天只作後備。7 天有出處：13 個 paper 目錄自 2026-05-01 的
相鄰 commit 間隔 median 0.33d / p75 2.13d / **p90 6.40d**，取 p90 上取整，
對應 repo 既有的「誤判率 ≤10%」慣例。

**TTL 的局限要寫在裁定裡**：taiwan-vt 的 blocker 隔天就被超越，7 天 TTL 抓不到它。
只實作 TTL 不實作規則 1 等於沒做。

## 判準：stale 判定不得升級成 block

同案。判為 stale 只改變**舉證責任**（回讀原始檔複核後即可引用），不是停擺。
**不得因為索引欄位陳舊就把被索引的東西標成 blocked**——那是拿索引的缺陷去懲罰內容。
依 `feedback_gates_smooth_no_deadlock`，三條出路要寫在同一處。

## 索引與現實脫節：class 已達 3-strike，但刻意不現在重構

三例：`enforcement_layer_map` 缺 hook、`control_gate_registry` 的 `hourly_pregate` 仍
`mode=shadow`（gate 早已退役）、`paper_pipeline_status` 的 blocker 12/13 無驗證時間戳。

**不現在重構的理由**：三例修法方向一致且都已各自派出，先看這輪收不收斂。
**第四例出現即觸發**，方向已明確：**索引不該由人維護，該由現實生成**——
layer map 從 `.claude/settings.json` 生成、gate registry 從 owner 檔存在性生成、
pipeline blocker 從 artifact mtime 標記新鮮度。下一班若看到第四例，直接開重構計劃書。


## 判準：不得用 commit message 關鍵字分類「這是不是實質變更」

（2026-08-05，論文部推翻本部門 v1 規則時提供，本部門採納為通用判準）

實質修訂（`paper(prg): v6 MINOR 9 mechanism citations`）與全域清洗
（`paper_ai_footnote_scrub_20260701 | 全 portfolio 論文清洗`）在 pattern 上不可分。
**錯的分類器比誠實的過度回報更糟**——過度回報的成本是多讀一次檔，錯誤分類的成本是
把真陽性靜默吃掉，而且沒人會知道。

同源判準：**寧可 false positive 不要 false negative**，當 FP 成本是「多做一次驗證」、
FN 成本是「一個部門據此下錯裁決」時。

## 教訓：我自己踩了整天在裁定的那個坑

同案。本部門 v1 的規則 1 用「該 paper 目錄最後一次 commit」當比較基準，論文部原型實測
**12/13 全部命中**（全域 sweep 掃過每個目錄）——**這就是「擋而無因」**，而我整天都在
用這個標準裁定別人。

**判準：自己訂的規則，要用自己當天用來否決別人的那把尺量一次。** 而且要感謝把原型跑出來
的人——他們花的時間換掉了一條會擴散到全平台的壞規則。收到推翻時，改，並寫明 v1 曾存在
（`[[判準：引用敘事欄位前，先看它的 *_verified_at]]` 是同一組紀律）。


## 主判準：訊號與它所指涉的事實之間隔了幾層（取代下面兩條的表述）

（2026-08-05，形式由論文部提出，治理部裁定採納並取代原表述）

> 引用一個欄位／指標／gate 結論之前，先問三件事：**這個欄位是誰寫的**、
> **什麼動作會讓它更新**、**那個動作與我關心的事實是不是同一件事**。
> 三個問題有一個答不出來，就去讀底層。

**為什麼取代「不要相信 X」式的表述**：每多一層間接，多的是一個**必須自己去查的地方**，
不是一個不要相信的東西。**純粹的懷疑會癱瘓，數層數不會。** 一條讓人不敢動的規則等於
沒有規則——這與「gate 要有出路」是同一件事的內側。

**誤判有四個方向不是一個**：假的看起來真（批量回填的時間戳）／過時的看起來現行
（手填 blocker）／**真警告看起來像真問題**（`INPUT_HASH_MISMATCH`：gate 沒壞、
真的有 hash 不一致，但變動的函式該實驗不呼叫——粒度不對）／過期的外觀配當期的內容
（`main.pdf` 的 mtime 早於 tex commit 但內容就是當前版）。

**第三個方向是我原本的軸抓不到的**：我先前兩條判準共用「訊號可不可信」這個軸，
會把粒度不對的**真訊號**判成可信，於是接受它的結論——而該降級的是 gate 不是被測物。

間接層數示例：`verified_at` ↔「有人核實過」隔著「有人寫了這個欄位」；整檔 hash ↔
「計算結果會變」隔著「這個檔裡有東西變了」；mtime ↔「內容變了」隔著檔案系統。

下面兩條保留為本判準的**特例**，不再單獨引用：

## （特例）恆為 0 的指標是壞掉的證據，不是健康的證據

（2026-08-05，「儀器永遠回報無事」bug class）

`ops_snapshot` 讀 `sent_at`/`ts`，而 `alerts.py` 只寫 `first_sent_at`/`last_sent_at`
（`alert_dedup.json` 實際頻次 676/635，而 `sent_at`/`ts` 各 **0** 次）。於是
`sent_last_24h` 恆為 0。實證傷害：07:58:28Z 真的寄出過一封 critical「provider 拒絕
spawn — 派工全停」，而 ops_snapshot 與經理 brief 都寫「alerts 已送 0 則」。

**一個永遠回報 0 的指標，與一個真的是 0 的系統，在畫面上長得一模一樣。**
差別只有去比對 reader 與 writer 的欄位名才看得出來。看到恆定值就去查資料源。

## Owner：canonical state 的讀取方向該收編進 audit_canonical_writers.py

`scripts/audit_canonical_writers.py` 已是寫入方向的 owner（AST 掃 `src/volpred`／
`src/api`／`scripts`，counted ratchet，搭配 `VOLPRED_NO_CANONICAL_WRITE`）。
**讀取方向是它缺的另一半，不是新 gate 的理由。** 下次看到「儀器讀錯來源」類問題，
先想這支。

## 方法紀律：掃描器要先能抓到已知真陽性，才有資格宣稱其餘乾淨

同案。我的 AST 綁定掃描器第一版漏掉了已證實的實例（模組級 `ROOT = Path(__file__)...`
沒被解析成路徑前綴），若不先拿已知案例驗證，就會回報「全平台乾淨」——**最糟的結果不是
找不到，是自信地找不到。**

而 9 個候選中 8 個偽陽性全來自同一模式：**綁定穿過了轉換函式**。所以本類 gate 的綁定
只能沿保值存取傳遞（`.get`／`[]`／`.values`／`.items`），不得穿過任意呼叫；
`X.get(A) or X.get(B)` 的 fallback 與 `d.get(k, d)` 的防禦形式必須豁免。
**8 個假陽性淹掉 1 個真陽性，就是「擋而無因」的另一種面貌。**

## 判準：修欄位錯配要「修對齊」，不是加 fallback

`or v.get("last_sent_at")` 這種補法會讓錯的鍵永久留在程式裡，下一個人看到兩個鍵
會以為兩個都合法。**錯配就是錯配，把它改對，不要並存。**
