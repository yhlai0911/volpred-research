# platform_eng 工作日誌（append-only）

## 2026-08-05 18:30–18:40（台灣時間）｜D26 遵辦：三件完成 + 一次性批次判定｜outcome=done

**完成 1｜研究部第二批產物保全**：三份 review_verdict.json 已 commit 並逐檔回讀
（`git cat-file -s` 對磁碟 byte size）——K1745 `67ffc24cd`(5350)、K1720 `b859282b3`(2247)、
k1813 `f3e10d1eb`(3889)，全為 verdict=FAIL，未 merge、未移除 worktree。
順帶把方法交給研究部（`git_writer_lock.py run -- git -C <wt> …` 是 hook 訊息自己指定的
正規入口，他們白名單裡有），下次不必再找本部門代工。

**完成 2｜新單 A/B 修復面確認（只確認，未診斷，照 D26）**：
A（content-vs-source audit 靜默略過）→ `src/volpred/publisher/prepublish_audit.py`；
B（quarantine 無回報路徑）→ `scripts/dispatch_supervisor/{isolation,worker}.py`。
兩張都不在可寫區，標 blocked-on-owned-paths。

**完成 3｜/questions 登入入口 incident 根因（未搶鎖）**：
`questions/page.tsx:255` 的 skeleton 條件只有 `authLoading`；而 `useEffect` 第一行就
`getMemberContinuityBrowser().read()`，該函式先 `JSON.parse(localStorage)` 再跑 schema
驗證，**兩者都會 throw 而 effect 沒有 try/catch** → 永遠不執行 `setAuthLoading(false)`。
`getSession().then` 也沒有 `.catch`。這解釋了「已登入 owner 也壞」——owner 的本機快取
最舊，schema 漂移後最先驗證失敗。
修復面 `frontend-v2-fix/` 是我唯一能寫的地方，**但動手時撞到互斥鎖：會員部 session
當下正在寫同一個 repo**。沒有硬搶——把完整根因與 class 修法（read() 壞資料丟棄重建、
雙版路由都要改）送過去並請他們回一句是不是在改同兩個檔。這是最不會產生兩份衝突實作的走法。

**批次判定（一次性，不再重複回報）**：收件匣 46 件機械掃路徑——
**可寫區 0 件**、blocked 30 件、未指名 16 件。阻塞根目錄：`scripts/` 26、`src/` 17、
`storage/` 17、`.claude/` 11、`config/` 8、`paper/` 4、`docs/` 3、`supabase/` 2。


## 2026-08-05 18:17–18:27（台灣時間）｜P1 provider 拒絕 spawn｜outcome=root_cause_identified_not_fixed

**工作項**：`item_20260805T101737280578Z_dispatch-supervisor-worker-spaw`

**真實拒絕字串**（照裁決要求取自 worker.py 傳給 `send_provider_denial_alert` 的
`str(exc)`，**沒有**照抄 alerts.py 的建議）：
`provider settings bytes do not match the pinned auth surface`。
經理的提醒成立——**不是 CLI 升級 sha**：executable identity 檢查
（`registry.py:884-895`）已經通過，流程才走到 `registry.py:912-919` 的
settings 位元組比對被擋。

**根因**：`config/provider_registry.json` 釘住 `.claude/settings.json` 的
sha=`95f06ba0…`（commit `76e6bfc7c`，07-23）；commit `e69a0c55c`
「feat(conflict): write-claim guard」於今天 15:29:14 改了那個檔（現值 `c4d7ed4e…`），
pin 沒跟著更新。第一封警報 15:58 本地，時間軸完全對上。
逐鍵比對確認變更**不涉及 auth**（只新增兩行接 write_claim_guard.py，
env/apiKeyHelper/base URL/model 全沒動）→ 重新 pin 是安全的。

**同 class 今天第二次**：早上那張 CI 紅燈也是「被釘住雜湊的檔案被改了但沒重新釘」
（cron wrapper manifest）。差別是 cron manifest **有 CI 測試會擋**、auth surface **沒有**，
所以它一路 push 到 production 才由 daemon 在 runtime 擋下，代價是執行層停 2.5 小時。

**dedup 靜音之謎（經理指定回答）—— 不是 1h dedup 幹的**：兩層 dedup，
產生端 1h/per-class、**投遞端 24h/per (level,title)**。兩邊帳對不起來即是證據：
產生端認為 09:13、10:15 都送了，投遞端 `send_count=1 / last_sent_at=07:58:28Z`。
三個缺陷咬合：(1) 標題是常數 → 條件越持續、內容越相同、越保證打不過內容雜湊，
優先序是反的；(2) `alerts.py:242-243` 呼叫 `_send` 後**無條件** `mark_alert_sent`，
忽略 exit code（今天有一筆 `exit=-15`）→ supervisor 的自我認知是錯的；
(3) `provider_policy_denied` 從未接進 incident 生命週期，沒有 occurrence／episode／升級。

**未完成**：五步 Gate 的第 4、5 步都沒做。修法 A（重新 pin）／B（加 CI 檢查，治本）／
C（`mark_alert_sent` 只在投遞成功時蓋章）／D（持續條件的 dedupe key 帶 episode）
全部落在 `config/` 與 `scripts/`，依 D14 (a) 停在原地、未繞路。
已建議經理把 A 從 D14 整批授權裡**拆出來單獨請老闆放行**——單一檔案、單一欄位、
變更已逐鍵驗證為良性，而執行層每停一小時就損失一小時產能。


## 2026-08-05 18:09–18:20（台灣時間）｜D14 遵辦：降載 + 分類 + 出口規格｜outcome=done

**工作項**：`item_20260805T100857005235Z_d14-d9-registry-json-write-mana`（經理裁決 D14）

**(a)(b) 已停**：六張跨區修法與五個部門的代寫 request 全部停在原地，
沒有重複開單、沒有找繞路寫法。清單與已備妥的診斷收在 `work/blocked_on_d14/backlog.md`，
核准後照那份解凍即可，不需重新診斷。

**(c) 出口規格**：`work/sidecarless_index_lock/mechanical_exit_spec.md`。
四項判準（0 bytes ＋ 齡 ≥300s ＋ `lsof` 無持有者 ＋ 全機無 git 行程；
**探測失敗一律視為未證明、不放行**）、改名保留成 `index.lock.stale-<UTC>`、
receipt 必帶 `evidence`、收編進既有 `phase_z.reclaim_leaked_index_lock`
（不新增第二個 watchdog）、六條驗證 gate 且**必須在臨時 repo 上做**。
規格裡寫明它不能取代 pre-spawn sidecar：後者管 daemon 自己的鎖，
這條管外部來源永遠不會有 sidecar 的鎖，只做前者全組織仍會被凍結。

**(d) 分類，結論與預期不同**：池內實際 88 件（單子寫 86）。
**沒有任何一張是「只要 frontend-v2-fix/ 就能做完」的**——72 張指名轄區外路徑，
16 張沒指名路徑，逐張看過後只有 1 張能動，而且能動的原因是它**不需要寫 repo**：
`deploy_verify_v3_digest_route_20260717`（v3 導讀頁 Chrome 視覺審查，
且萬一看出問題修正面正好在 frontend-v2-fix/）。依 (a) 未啟動，等經理排序。
完整逐張判定：`work/pool_classification/platform_ops_scope_20260805.md`。

**附帶發現**：四張 CI 紅燈**不是同一根因**（我原本也這樣假設，比對後推翻）——
是四個獨立失敗。最新那張唯讀確認為
`manifest_missing_entry: cron_org_boss_digest.sh / cron_org_manager_tick.sh`：
**組織遷移自己新增了兩支 wrapper 卻沒跑 `--render-manifest`**，於是每次 push 都紅。
修法是一道 canonical 指令但會寫 `config/`，依 (a) 沒動手，已建議經理單獨排序——
CI 紅燈對全 repo 生效，所有部門的 push 都掛在同一盞燈上。

**新單已記未做**：`check_experiment_artifacts.py` 的 substring 匹配
（`k1095_v3` ⊃ `k1095` 自動繼承 gate 通過權），標 blocked-on-D14。
修法方向我贊成比對 results JSON 的 `experiment_id` 欄位而非 word-boundary：
後者仍要猜命名慣例，前者是直接問資料本人。


## 2026-08-05 17:53–18:05（台灣時間）｜五支文章圖表腳本｜outcome=done

**工作項**：`item_20260805T095303899389Z`（需求 C/D/E）＋ 前一班已歸檔的
`item_20260805T085648183331Z`（需求 A/B，經理指明仍有效）

**交付**：11 張圖，路徑與檔名完全照規格落在 `storage/assets/`——
k1451(leadlag, coef_collapse)、k1465(dow_mean_vs_median, vrp_flat, oos_equity)、
k1677(directional, primary_vs_sensitivity)、k1696(dm_heatmap, tsv_timeseries)、
k1704(qlike_by_proxy, split_oos)。dpi=180、白底、繁中、與既有 `*_general_*.png`
同色系；每個數字都程式化讀取，逐張目視檢查過。

**偏差一項（已明確回報，不是偷渡）**：腳本在
`work/content_charts/gen_*_article_charts.py`，不是規格寫的 `scripts/`——
owned_paths 裁決仍未下來。腳本用「往上找含 experiments/ 與 storage/ 的目錄」
定位 repo root，**搬進 scripts/ 不需改任何一行**。取捨理由：卡著的是 P1 池隊首，
先把圖交出去比等裁決好。

**三處主動更正敘事**（原說法與資料不符，照畫就是替不成立的句子背書）：
1. K1696 熱圖原標題「九種情境沒有一種變好」→ HYG 的 h1/h63 是負值。
   改成程式計算的「7 格更差、2 格略好但都不顯著」。
2. K1677 圖 1 註腳原稱安慰劑「貼近 0」→ 實際兩個安慰劑在 t≈1.3，
   比兩個真指標還高（仍遠低於門檻）。改成據實描述。
3. K1465 圖 3 權益曲線做不出來——`.backtest_oos` 只有彙總統計、無逐日序列。
   依規格改夏普／最大回撤對照，**未自行重跑回測補序列**。
另兩個技術判斷：K1465 的 n 一律取 `.vrp.n`（避開 `r_*_sq_x1e4.n` 的 ×1e4 瑕疵）；
K1696 的利差波動序列以 `import K1696.py` 自身的 `build_features` 產生，不另算一套。

**踩到的坑**：`×10⁻⁴` 的上標負號（U+207B）PingFang 沒有字，會變豆腐——
reader-facing 圖一律改寫成 `×1e-4`。


## 2026-08-05 17:30–17:45（台灣時間）｜20 件收件匣批次｜outcome=done(3)+contained(1)+blocked(rest)

**完成**

1. **研究部 P1 產物保全**：三個 worktree 的未追蹤研究產物已 commit——
   K1747 圖表/表格 `d18fee80b`、signforecast 的 Codex round-2 FAIL 裁決 `3ca7e6685`、
   K1721 外部資料快照 `8876b7334`。k1737 依指示完全沒動。
   驗證用 `git cat-file -s HEAD:<path>` 對磁碟 byte size 逐檔比對（14/14 相符），
   不是看 `git status`——要證明 bytes 真的進了 commit，不是還躺在工作區。
   **關鍵發現**：worktree 的 git 操作在部門權限下走
   `git_writer_lock.py run --actor <x> -- git -C <wt> ...` 是通的，
   而且這正是 hook 訊息指定的正規入口（裸 `git -C` 會被 deny）。
2. **weekly_2026-07-31 回填**：34,585 bytes、billable_total 126,428,721。
   但回報時已註明 `unique_sessions=436` 正是 F2 要修的灌水指標、
   `estimated_cost_usd` 建立在 F3 的 20.2% 覆蓋上——回填完成 ≠ 數字可用。
3. **裁決 D2 的當下解**：寫了 `work/inbox_archive/archive_inbox.py`，
   七個部門都能跑（只需 `uv run python`，不需對該路徑有寫入權），
   解掉「收尾契約第 3 步機械不可能」。已回覆研究部、治理部、經理。

**調查完成（contained）— canonical `assign_3e73a554` 無 sidecar index.lock**

用 scratchpad 臨時 repo 做實驗（不在本 repo 上做破壞測試）：
SIGPIPE 中斷 `git status` 洩漏 **0/40 → 排除**；SIGKILL 打斷 `git add` 洩漏 **5/10
且正是 0-byte lock**。成因確立＝「正在寫 index 的 git 子行程被 SIGKILL」。
兩顆 lock 在 `writer_log.jsonl` 都查無對應交易。唯一時間吻合的 phase_z
orphan-half probe timeout，讀碼後確認它殺的是 clone 裡的 pytest，
**不能解釋主 repo 的 index.lock，沒有拿它當結論**。個案創建者未鎖定。
報告與修法規格：`work/sidecarless_index_lock/forensics.md`。

**第一人稱佐證治理部的 gate 缺陷**：`path_claims.py list` 顯示 `src/volpred/ops/`
由本 session 持有，而本 session 對它的 Edit 是**被 deny 的**、一個 byte 都沒寫。
更嚴重的推論已回報：沒有寫入權的部門會系統性地生產幽靈鎖——它一定被 deny，
所以一定留下 claim，鎖住的正是它永遠寫不了、只有別人能寫的路徑。

**其餘全部卡在同一根因**：F1/F2/F3 token 會計、內容部兩支圖表腳本、
治理部 R4、path claim 修法、org_attach settings 生成（含 D5-1/D9）、
三張 canonical——修改面全在 `scripts/`、`src/`、`config/`、`tests/`。
已向經理指出 **D9 的遞迴性**：經理自己也寫不了 `registry.json`，
而 `owned_paths` 就住在裡面——這個死結組織內部無人能解，需要老闆授權一次。
未動的三張 canonical 沒有假裝處理，也沒有歸檔。


## 2026-08-05 17:19–17:27（台灣時間）｜reproduce gate 整檔 hash｜outcome=blocked

**工作項**：`item_20260805T091934819770Z_reproduce-gate-hash-commit-unver`
（論文部 `request`，非 canonical 派工）

**做了什麼**

1. 論文部的證據逐項獨立重驗（不轉抄）：spec hash `29c6f80d` 確為 `9f868e41f^` 版本；
   AST 逐 top-level def 比對後該 commit 唯一變動者是 `strategy_dm_test`；
   `dm_test`／`qlike_pointwise` 兩版完全相同；兩支實驗只 import 這兩個符號。**全部成立。**
2. 根因：`audit_experiment()`（`scripts/reproduce_check.py:1169-1183`）用**整檔** sha256
   比對 `spec["inputs"]`。整檔 hash 的語意是「檔案沒變」，實驗依賴的卻是「我 import 的
   符號沒變」——在共用模組上這兩者**必然發散**。更糟的是判定後直接 `return`，
   連「重跑看數字有沒有變」都做不到，等於把唯一能產生證據的路也關掉。
3. 採論文部建議的 (a)，但把比較單位從「單一函式」修正為**從被 import 符號出發、
   模組層可達名字的傳遞閉包**——只 hash 那個 def 會漏掉它呼叫的 helper 與讀的常數。
   三條 fail-closed 退路：整模組 import／`import *`、模組頂層有副作用敘述、
   spec 版本在 git 歷史查不到，任一成立就退回整檔比對。
4. **不需改 spec schema**：spec 只記整檔 hash，但那個版本可用內容 hash 反查 git 歷史
   （本例反查到 `42ec9aa70`）。舊 spec 全相容、零 migration。
5. 寫成可執行原型跑真實 repo 實測：k1699／K1710 正確放行（閉包
   `[dm_test, qlike_pointwise, np, stats, Tuple]`）；四個負控制/突變測試
   （閉包內插一行、改綁可達的 `stats` import、`import <module>`、只動閉包外）
   全部符合預期。**設計不是紙上的。**

**結論（誠實）**：**一行未落地。** 修復面在 `scripts/reproduce_check.py` 與 `tests/`，
`Edit` 再次被權限閘擋下（今天第二張同因卡住的任務）。定稿修正與可逐字貼上的 helper
在 `work/reproduce_gate_import_surface/`（`diagnosis_and_patch.md` +
`import_surface_helpers.py`）。

**已走管道**：回覆論文部（含對 `main.tex:118` 那句話的建議：拿到 receipt 後應改成
引用比對基準，否則下次共用模組再動一行，同一個 MAJOR finding 會原封不動回來）；
P1 上報經理 `item_20260805T092519977832Z`，並言明在 owned_paths 裁決下來之前，
本部門收到的任何 platform_ops／code_review 任務都只能停在同一個位置。


## 2026-08-05 16:51–17:0x（台灣時間）｜alert_control_gate_source_health｜outcome=blocked

**工作項**：`item_20260805T085055{722967,835067,932635}Z_canonical-alert-evidence-source`
（三張重複派工，同一 canonical `alert_control_gate_source_health_20260802`）
＋ 期間新到的 `item_20260805T090020179678Z`（canonical `..._20260805`，同一 detector 的第二張單）。

**做了什麼**

1. 以原 detector fresh 重驗（`scripts/audit_control_gate_lifecycle.py`）：警報仍 breached，
   `unhealthy_source_count=2`，非自然解除 → 不適用 fresh no-op 收尾。
2. 兩個失明的 evidence source 都追到根因層級（非資料髒）：
   - `dispatch_worker_ownership`：transition reason 詞彙表**雙源漂移**。producer
     （`scripts/dispatch_supervisor/workspace.py:4493`）以 `f"worker_{outcome}"` 生成，
     `config/control_gate_registry.json` 手抄一份，中間無 gate；outcome 詞彙只以散文
     記在 `state.py:152-162`。新 outcome 一出現就變 `unknown` → audit fail-closed。
     實際漏掉的三個：`worker_killed_timeout`、`worker_orphan_gone_or_reused`、`merge_failed`。
     與 2026-05-27 `BLOCKED_REASONS` 漂移同 class。
   - `event_reaction_coverage`：`_join_outcomes()` 以「沒有 deadline」判 malformed，
     但終態任務滿 3 天就被 `compact_terminal_tasks()` 壓成 tombstone、`deadline` 不在
     `_TOMBSTONE_KEEP_FIELDS`；gate review window 卻是 14 天。跨過第 3 天必然失明且
     不會自癒。即 `is_tombstoned()` docstring 已命名的 class J（2026-08-03 dreaming 同因）。
3. 定稿四處修正 ＋ 一個機械 gate 測試，全文寫在
   `work/alert_control_gate_source_health_20260802/diagnosis_and_patch.md`（P1–P6）：
   詞彙表單一 owner 進 `incident.py`、寫入端不再沉默、registry 補齊分類、
   reader 先問 `is_tombstoned`、新測試 `tests/test_incident_reason_vocabulary.py` 擋未來漂移。

**結論（誠實）**：**一行都沒有落地，警報仍在 breached。** 修復面在
`src/volpred/ops/`、`config/`、`tests/`，而 platform_eng 的 `owned_paths` 只有
`frontend-v2-fix/`，`Edit` 被權限閘擋下（與稍早 `scripts/token_usage_report.py` 同型）。
本輪回報層級只能是 `blocked`，不是 `contained`，更不是 `root_cause_fixed_and_verified`。

**已走管道**：`dept_send.py --to-manager --priority P1`（
`item_20260805T090132643067Z_alert-control-gate-source-healt`），請經理二選一：
(A) 把 `src/volpred/ops/`、`config/control_gate_registry.json`、`tests/` 納入本部門
owned_paths（建議；擁有 `platform_ops` task_type 卻不能寫對應程式碼 = 所有 platform_ops
任務都無法結案）；(B) 指派有寫入權的執行體照 P1–P6 套用。

**同輪處理的 incident（不在派工單上，但屬本部門轄區）**

收尾 commit 時發現 `git_writer_lock` 一律回 `cannot snapshot current index`；
治理部與會員部同時送 P1 request 來（全 repo 的 commit 都過不去）。
`.git/index.lock` 判定為孤兒——0 bytes、滯留 483 秒、`lsof` 無持有者、全機無 git 行程，
四項 fail-closed 檢查齊全才動手，依 2026-07-28 前例**改名**保留為
`.git/index.lock.stale-20260805T090147`（不刪除，證據留存）。解除後 `git status` rc=0，
本部門 commit `fdecaaea7` 落地，兩個部門已回覆可重試。

這只是 **contained**：這是 error_log 記載的 index.lock class **第 5 次**。機械 owner
`phase_z.reclaim_leaked_index_lock()` 只回收帶 owner sidecar 的鎖，git 原生操作留下的
無 sidecar 鎖落在盲區（2026-08-04 13:49 已知，followup 仍在池中）。修復面在
`scripts/dispatch_supervisor/`——同樣寫不了，卡在同一張 owned_paths 裁決。

**順帶回報的兩個流程缺陷**
- 同一 canonical 任務被派三張重複工作項。
- `alert_remediation_bridge` 對同一 detector 的同一根因開了第二張單
  （`..._20260802` 與 `..._20260805`，差別只是「1 類」變「2 類」source）——
  memory `feedback_incident_not_alert_task_mapping` 指的同一個 class。
