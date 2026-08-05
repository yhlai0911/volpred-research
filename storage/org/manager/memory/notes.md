# 運營經理私有記憶

## 待主線程代寫（manager 角色 Edit/Write 對 docs/ 一律機械 deny，非 path_claims）

**2026-08-05T14:50Z**：docs/error_log.md 需要補一則 3-STRIKE TRIGGER 條目（owned_paths 檔案
vs 目錄構造連續4次歸因錯誤，根因在 org_admin.py:202 上游正規化，修法 commit 1a0d4b274）。
逐字內容已擬好，請直接搜尋這段標題插入 docs/error_log.md 現有內容尾端（緊接 2026-08-05
enforce_final_text.py 條目之後）：

標題：`## 2026-08-05 — **3-STRIKE TRIGGER**：owned_paths「檔案 vs 目錄」構造連續 4 次歸因錯誤`

內容要點（主線程可依此展開，不必逐字照抄我的草稿）：
- 症狀：治理部授權 storage/org/policy.md 後 pattern 一路只命中 policy.md/**（目錄前綴）
- 前 3 次修復都改了 org_attach.py 的 pattern 產生邏輯（絕對路徑單斜線／檔案被當目錄／
  點開頭目錄不被萬用字元命中），都對症不對根因
- 第 4 次才在 org_admin.py:202 找到根因：owned_paths 這個欄位「存的是目錄還是路徑」
  從未被定義過，set-paths 寫入前就 rstrip('/')+'/' 正規化成目錄
- 修法 commit 1a0d4b274：_core.declares_a_file / normalize_owned_path，寫入讀取共用同一份
  定義；三不變式 I1(正規化只在渲染時發生)/I2(邏輯只住一處)/I3(產出規則需自證命中，
  匹配不到即 raise)；新增端到端測試(set-paths寫入→turf_patterns產出)＋破壞驗證
- 驗收判準升級：授權後當場跑 generate_dept_settings 回讀驗證命中，不留假宣告
- **殘留、不可混為一談**：治理部授權生效後，Edit .claude/rules/paper-workflow.md 仍被
  deny，對照組 docs/governance/** 成功 —— 證明 .claude/ 前綴另有一層與本條無關的阻擋
  （疑似 Claude Code 對 .claude/ 目錄的內建保護），本條狀態 root_cause_fixed_and_verified
  僅限 owned_paths 型別契約本身，.claude/ 阻擋另計未解，見
  docs/governance/2026-08-05_paper_workflow_exemplar_patch.md §5
- 治理部已建議：.claude/** 應從所有 owned_paths 移除，org_admin.py set-paths 對該前綴
  直接拒絕宣告，此類編輯改由互動 pane 人工套用——**本班 manager session 遇到同一道牆**
  （docs/error_log.md、docs/error_log.md 所在的 docs/ 目錄本身、以及 outbox/proposals 新檔
  最初也被同一層 deny 過，前兩者最終確認是 path_claims 誤判可 release 解決，但 docs/
  本身是真的權限層 deny，與 .claude/ 那道牆同類——manager 角色的 Edit/Write allowlist
  範圍本身可能設得比 policy.md 描述的『可寫：registry、bulletin、任何部門 inbox、manager
  自身子樹』更窄，值得下次 org_review 追查 allowlist 設定來源）
