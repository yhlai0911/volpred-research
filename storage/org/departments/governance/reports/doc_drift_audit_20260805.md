# 運作指示文件 drift audit — 2026-08-05（2026-07-28 週次 instance）

Task: `governance_self_revise_operating_docs_20260728`
前一份：`docs/governance/2026-07/doc_drift_audit_20260721.md`
執行者：治理部（組織改組後第一次由部門而非主線程執行）

> **落點異常**：本報告的 canonical 位置應是 `docs/governance/2026-08/doc_drift_audit_20260805.md`。
> 治理部 `owned_paths = []`，寫該路徑被權限層拒絕（實測：Write `docs/governance/2026-08/...` denied），
> 只能暫存於部門子樹。這正是本班 finding 1 的實證，已上報經理；核准後應搬回 canonical 位置。

## 結論

上週 4 條追蹤全部有交代：1 條是**上週自己讀錯路徑造成的偽陽性**（已澄清並附真實掃描）、
1 條**觸發條件已消失**（7 個 stale skill 於 2026-07-29 全部被動過）、1 條**複核後維持原決策**、
1 條**本班補完且乾淨**。

本週新開 3 條 finding。最重要的一條不是文件寫錯，而是**組織改組把治理部寫成了一個
沒有轄區卻要維護 `docs/governance/**` 的部門** —— 今天 `audit_enforcement_map.py` 是紅的，
修法就是加一行到 enforcement layer map，而治理部依章程與權限層都無權寫該檔。這是改組
留下的授權缺口，不是文件筆誤。

**本班未新增任何 enforcement，未退役任何 gate，未修改任何 `.claude/skills/*`（故不需寄信）。**

## 上週追蹤清單現況

| # | 上週追蹤項 | 現況 | 證據 |
|---|---|---|---|
| 1 | `scripts/README.md` 復現包缺口 | **偽陽性，撤回** — `paper-workflow.md:42` 的 `scripts/README.md` 是 **paper-scoped**（`paper/<name>/scripts/README.md`），不是 repo root。上週按 repo root 去 stat 才判成缺。真實掃描：9 個 paper 有 `scripts/`，其中 **8 個有 README.md** | `ls paper/*/scripts/README.md` → 8 筆；`.claude/rules/paper-workflow.md:42` 上下文「若完整程式在 `experiments/kXXX/`，**此處**需 `scripts/README.md`」 |
| 1b | （由 #1 掃描新發現） | `paper/taiwan-vt/` 缺 `scripts/README.md`，但 `paper-workflow.md:62` 把它列為**齊全樣板** — 樣板本身不合格 | `ls paper/taiwan-vt/scripts/README.md` → 不存在；`.claude/rules/paper-workflow.md:62` |
| 2 | 7 個 stale_skills 逐檔判讀 | **觸發條件已消失** — 7 個 skill 的最後一次 commit 全部是 **2026-07-29**（上週 audit 之後），staleness 時間戳啟發式已不再指向它們。本班改做**實質**檢查（引用路徑存在性）：7 個 skill 共 24 條 repo 路徑引用，**0 條失效**（`docs/official` 為 regex 截斷偽陽性；`scripts/deploy-zeabur-safe.sh` 在原文是 `$FRONTEND_PATH/scripts/...`，路徑正確） | 逐 skill `git log -1` + 路徑 stat |
| 3 | `read_context_budget.py` explicit-limit escape hatch | **維持原決策，無回歸** — `:108` 仍是「有 limit 或 offset 就完全不覆寫」，`:138` 仍明寫 "explicit limits are never overridden"。補洞＝新增第二套 enforcement，違反 anti-stacking；列為**知情選擇**而非疏漏的判定繼續成立 | `scripts/hooks/read_context_budget.py:108`、`:138` |
| 4 | 維度 3 未掃 `.claude/skills/*/SKILL.md` 內部散文 | **本班補完，近乎乾淨** — 對 5 條已機械化的禁令全文掃 26 個 skill：`worktree remove --force` 0 命中、`ScheduleWakeup` 0 命中、裸 `zeabur deploy` 0 命中、裸 git mutation 0 命中；只有「禁止整檔載入 memory」出現 3 次（見本週 finding 3） | `rg` over `.claude/skills/**/*.md` |

## 本週 findings

| # | 維度 | 位置 | 問題 | 嚴重度 |
|---|---|---|---|---|
| 1 | 1 doc↔實作 / 組織授權 | 7 份 `storage/org/departments/*/charter.md:34` | 章程寫「只可寫自己的部門子樹、自己 owned_paths 與 **Zone C 共用區**」，但 (a) `storage/org/policy.md` 全文**沒有 Zone 的定義**，部門的身分簡報裡查不到；(b) Zone C 的真正定義在 `docs/agents/ownership.md:60`，是一張 **7 列具名表**（error_log / project_improvement_status / architecture / next_tasks / work_log / AGENTS.md / git commit），**不含 `docs/governance/**` 也不含 `config/**`**；(c) 治理部 `owned_paths = []`，KPI 卻是「skill architecture check 常綠」與 enforcement owner 稽核 —— 職責要求它維護 `docs/governance/**`，章程與權限層都不授權它寫 | **med → 已上報經理**（改 registry 是經理職權，部門不得自改） |
| 2 | 1 doc↔實作 | `docs/governance/enforcement_layer_map.md` hooks 表 | `scripts/hooks/write_claim_guard.py`（PreToolUse `Edit|Write|MultiEdit|NotebookEdit`，2026-08-05 上線）在磁碟上、不在 map 裡。`uv run python scripts/audit_enforcement_map.py` **今天是紅的**。這正是 anti-stacking 最怕的狀態：索引過期 → 下一個人查不到 owner → 疊第二層 | **med → blocked**（修法只有一行，受 finding 1 授權缺口所阻；建議 diff 已附給經理） |
| 3 | 3 anti-stacking | `publication-candidates/SKILL.md:37`、`autonomous-research/SKILL.md:50`、`research-topic-discovery/SKILL.md:37` | 三處各自重述「不要整檔載入 memory」，都**沒有 pointer 指向唯一細則 owner** `.claude/rules/context-hygiene.md`。後果不是重複而是**讀者拿不到例外規則**（explicit limit 從不被覆寫、Bash 側是 deny 而 Read 側只是 bound —— 三處散文都沒講） | low → **未修**（改 skill 需寄信通知老闆，部門不得直發；已請經理裁決是否值得動） |

### finding 2 的建議 diff（待授權後套用）

在 `docs/governance/enforcement_layer_map.md` hooks 表 `record_fire_manifest` 那列之前插入：

```
| `PreToolUse` | `Edit&#124;Write&#124;MultiEdit&#124;NotebookEdit` | `scripts/hooks/write_claim_guard.py` | 同一 scope 的並行編輯認領（45 分鐘 TTL）|
```

套用後 `uv run python scripts/audit_enforcement_map.py` 應轉綠。

## 沒找到 drift 的面向（查了但乾淨，避免下週重複查）

- **hook 註冊完整性**：`.claude/settings.json` 引用的 13 條命令，其 script 檔**全部存在**。相對上週新增 4 支（`gate_edit_guard` / `record_fire_manifest` / `enforce_fire_receipt` / `write_claim_guard`），其中 3 支已在 layer map 內，只有 `write_claim_guard` 漏（finding 2）。
- **`.claude/commands/deploy.md` 部署路徑**：`:27` 的 `./scripts/deploy-zeabur-safe.sh` 位於 `cd frontend-v2-fix` 之後，路徑正確；`web-ui-ux-review` / `admin-ops` 兩份 skill 都用 `$FRONTEND_PATH/scripts/...` 從 config 解析。**無硬編碼 drift**。
- **CLAUDE.md §組織層新段落**：所稱 4 支入口（`org_status.py` / `dept_send.py` / `org_admin.py` / `dept_routing.py`）與 `model_router.py` 投影機制，檔案全部存在，描述與實作一致。
- **維度 3 對 skills 的全量掃描**：見追蹤項 4，5 條機械化禁令中 4 條 0 命中。

## 需老闆決策

**無。** 本班未修改任何 `.claude/skills/*`，不觸發 skill 修改寄信規則。
Finding 1 與 2 屬組織內部授權問題，已循 `dept_send.py --to-manager` 上報經理裁決。

## 下週追蹤清單

1. **finding 1（治理部無轄區）** 經理裁決結果；若核准 `owned_paths += ["docs/governance/"]`，下班第一件事是把 finding 2 的那一行補上、讓 `audit_enforcement_map.py` 轉綠，並把本報告搬回 canonical 位置。
2. **finding 2 若仍紅** → 同一道 audit 連續兩週紅，計 §governance-index class strike 1；連三次要走 3-strike 重構（把 map 的維護改成從 `.claude/settings.json` 生成，而非人工同步）。
3. **finding 3** 三處 SKILL.md pointer 是否值得動（改 skill 有寄信成本，收益低）；經理不裁決就維持不動，並在下週明記「不動是決策不是遺漏」。
4. **`paper/taiwan-vt/scripts/README.md`** — 已送 request 給論文部；下週複核是補檔還是把它從 `paper-workflow.md:62` 的樣板清單移除。
5. **本 session 的工具面觀察（非文件 drift，供平台工程部參考）**：本 session 的 don't-ask 權限模式下 **`Edit` 工具全域被拒、`Write` 只在部門子樹可用**。結果是部門只能整檔覆寫、不能做最小 diff —— 對 `docs/error_log.md` 這類 append-only 共用檔是**風險**（整檔重寫會抹掉併發者的 append）。已一併上報。

## Cadence

下一個日期化 instance：週次 2026-08-04，沿用 `blocked_until` + hourly
`unblock_expired_blocked_tasks.py --apply`，不重用固定 id。建立由經理／控制面執行
（部門不自建任務）。
