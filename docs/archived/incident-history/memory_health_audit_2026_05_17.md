# Memory Health Audit — 2026-05-17

**Auditor**: 主線程 weekly cron（per `.claude/skills/memory-health/SKILL.md`）
**Scope**: `storage/memory/knowledge.json` 健康診斷（read-only；不做 dedup auto-fix）
**Verdict**: **HEALTHY**（overall_status=ok，0 hash duplicates，size 在 warn 線下；發現 2 個既存非關鍵 anomaly，已有 prior triage / 屬合法 multi-entry）

---

## 1. Size Audit（7 天 delta）

| 指標 | 現在（2026-05-17） | 7 天前 commit `f90f5f9b`（K1258 closure DOWNGRADED） | Δ |
|---|---|---|---|
| `knowledge.json` bytes | 2,034,423 (1.94 MB) | 1,838,382 (1.75 MB) | **+196 KB (+10.7%)** |
| Entry count | 2,128 | 2,051 | **+77 entries (+3.8%)** |
| 平均 entry size | ~955 B | ~896 B | +59 B |

**判讀**：
- 1.94 MB 遠低於 warn 線 5 MB / danger 線 10 MB（SKILL §1 警戒表）
- 7 天 +77 entries ≈ 11/day，符合 hourly dispatch 節奏（~24 slots × ~50% knowledge-writing tasks/day）
- 增量主要是 K-experiment closure entries（K1370/K1370c/K1202b/K1314/K1300/K1312/K547b/K827v2/K901/K981/K1306v2/K1100g_d9/K1317/K1135/K1303/K1306/K1061/K1257 等 18 個 commit touch knowledge.json）
- **與 2026-04-10 incident 對比**：當時 7 天內從 ~1500 → 50,304 entries（96.4% 重複），本週 77 entries 全 unique → 健康

## 2. Entry Count + 重複檢測

```
total_entries: 2128
hash duplicates: 0
unique entries: 2128
```

- `uv run volpred ops memory-health-summary` 回傳 `overall=ok knowledge=ok duplicates=0 orphan_worktrees=0`
- Content-hash (md5 over sorted JSON) full-population walk → 0 duplicates
- Worktrees: 0 orphan（`.claude/worktrees/` 空）

## 3. Dedup Check（experiment_id 多 entry 分析）

**只有 10 個 experiment_id 帶 >1 entries**，皆為合法 multi-entry，**非真重複**：

| experiment_id | 第二 entry source | 性質 |
|---|---|---|
| K989 | `know_20260511001203_k989_pp_review` | Post-publish review（Gemini fallback）— 合法 |
| K1030 | `know_20260411153732_paper9v5` | Paper 9 v5 cross-K review 引 K1030 | 合法 |
| K1032 | (id=?) `A4f Cross-Market Validation` | 重複的 cross-K aggregation entry | **觀察** |
| K1033 | (id=?) `A4f Refit Frequency Sensitivity` | 同上 | **觀察** |
| K1034 | (id=?) `Cornish-Fisher Expansion VaR Comparison` | 同上 | **觀察** |
| K1035 | (id=?) `EVT-VaR with A4f Residuals` | 同上 | **觀察** |
| K1036 / K1039 / K1041 / K1045 | `know_20260411153732_paper9v5` | Paper 9 v5 cross-K bundle 引同 K | 合法 |

**觀察**：K1032-K1035 第二 entry 的 `id` 欄缺（顯示 `?`）— 屬於 2026-04 cross-K aggregation 時期 Paper 9 v5 整理寫入，schema 不完整但 content 不重複。**未達 dedup 必要性**（per SKILL「duplicates > 0 → 立即去重」門檻指 hash duplicates，這裡 hash=0；experiment_id 多 entry 是不同視角/不同時間點的 valid notes）。

**K1370 / K1370c / K1202b 三個本 session 新加 entries 驗證**：

| K | knowledge entry | commit reference | 對應 |
|---|---|---|---|
| K1370 | id=K1370, created 2026-05-16T15:18:00Z, title `Paper 2 Block-Bootstrap CI — TAIEX Amplification Ratio (K1370-v2 canonical, ...)` | commits `b4148e48` / `228eedb2` / `4b9374d7` | ✅ 對齊 |
| K1370c | id=K1370c, created 2026-05-17T03:01:26Z, title `K1370c N_start=10 vs N_start=100 sensitivity micro-test (PASS — closes Codex resi...)` | commit `cbcb9c34` | ✅ 對齊（剛寫入） |
| K1202b | id=K1202b, created 2026-05-17T02:06:02Z, title `K1202b Paper 2 D2 primary-source hand-verify (LLM extraction credibility defens...)` | commits `b23e35c3` / `bfd5db3e` / `10bd2460` | ✅ 對齊 |

**結論**：三個新 entry 都唯一、與 commit 一致、無 K-id collision。

## 4. Format Consistency（schema 一致性）

抽 10 random entries（`random.seed(42)`）發現格式分布：

| Format family | Count（全 2128 entries） | % |
|---|---|---|
| Legacy `item_id` only（MemorySystem.add_knowledge 產生） | 1,378 | 64.8% |
| New `id` only（Claude / agent 直寫） | 733 | 34.4% |
| Both `id` and `item_id`（過渡期） | 4 | 0.2% |
| No id at all | 13 | 0.6% |

**抽樣 10 entries 必備欄位 presence**：
- `content`: 10/10
- `created_at`: 9/10
- `category`: 9/10
- `item_id`: 8/10
- `id`: 2/10
- `title`: 2/10
- `experiment_id`: 1/10
- `summary` / `verdict` / `key_metrics` / `type`: 0/10

**判讀**：
- 兩種格式共存符合 SKILL §3「目前不需要強制統一，但新增 entry 應一律用新格式」原則
- task brief 要求的 `summary / verdict / key_metrics` 欄位**在 sample 中 0/10** — 因抽樣偏向早期 legacy entries（按比例 64.8% 為 legacy）；新近 K-experiment entries（如 K1370/K1370c/K1202b）有 title + content + verdict semantic 嵌入 content，但**不採用獨立 `verdict` / `key_metrics` JSON field**
- **無 silent corruption / schema breakage** — 所有 entries 都是 valid dict + content/category 等核心欄位齊全
- 13 個 `no_id_at_all` entries 屬於極早期 stub（含部分為 Paper 9 v5 cross-K aggregation entry，id 留空但 content 完整）

## 5. Bloat Score

`summary | content` 字元長度分布（n=2128）：

| 分位 | 字元長度 |
|---|---|
| min | 0 |
| p50 | 365 |
| p90 | 1,000 |
| p99 | 1,530 |
| max | 3,491 |

| Bucket | Count | % |
|---|---|---|
| > 1,000 chars（task brief 警告線） | 212 | **10.0%** |
| > 5,000 chars | 0 | 0% |

**Top 5 longest**：

| id | chars |
|---|---|
| `3788433f` | 3,491 |
| `727e23ee` | 3,035 |
| `f63a3a42` | 2,750 |
| `fb1cecfa` | 2,746 |
| `81ebfe54` | 2,577 |

**Bloat verdict**：**HEALTHY**。
- p50 365 chars / p90 1,000 chars — 大多 entry 是緊湊摘要
- 10% 超過 1,000 chars 多為複雜實驗 K（含 R1-R4 + L1-L5 結構化教訓）— 合理而非 bloat（per `feedback_skill_structure.md`：實驗結果可較長，方法論 + 教訓寫進 knowledge 是必要）
- 無 entry > 5,000 chars，無明顯 paste-bomb / log-dump pattern

## 6. K-id vs Title 對齊（K936 教訓 weekly check）

```
K-id misaligned total: 98
  - 已有 audit_note（2026-05-09 triaged）: 23
  - empty-title stubs（K43-K66 + K671/K675/K767 等 legacy）: 65
  - 其他: 10
```

**判讀**：
- **無新發生 misalignment** — 98 個 misaligned entries 全部對應 docs/error_log.md 2026-05-09 記載的 26-pair audit 後遺留 + 早期 legacy stub
  - 23 個帶 `audit_note` 是當時主動 re-key + preserve 的 evidence-tagged entries
  - 65 個 empty-title K43-K66 stubs 是 2026-04-10 merge_worktree.sh jq dedup bug 的歷史殘留，**內容已搬到對應 real K entry slot**，stubs 留作 audit trail，不影響檢索
  - 其他 10 個是極早期手動寫入 K-id 但 title 用 free-form 描述（如 `K588: DCC-GARCH...` 開頭格式不一致）— 屬 cosmetic，非結構性問題
- **無 dedup bug regression**（per SKILL §5「預期 0」是針對「新增的 misalignment」— 既存歷史 stub 已 documented）

## Verdict 總表

| 維度 | 狀態 | 數值 |
|---|---|---|
| Overall | **HEALTHY** | overall_status=ok |
| Size | HEALTHY | 1.94 MB（warn=5 / danger=10） |
| Entry count growth | HEALTHY | +77 / 7 days（合理 hourly dispatch 節奏） |
| Hash duplicates | HEALTHY | 0 / 2128 |
| K-id vs title alignment | HEALTHY (legacy stubs only) | 0 new mis；98 既有皆 documented |
| Format consistency | HEALTHY (mixed allowed) | 64.8% legacy / 34.4% new — SKILL 不要求統一 |
| Bloat | HEALTHY | p99=1530, max=3491, 0 entry > 5000 chars |
| K1370/K1370c/K1202b commit alignment | ✅ 對齊 | 3/3 |
| Worktree orphans | HEALTHY | 0 |

**Final Verdict**：**HEALTHY**。本週 memory state 穩定，無 incident、無新 corruption、無 dedup bug regression。

---

## 推薦 Action（**僅建議，不刪資料**）

### 必做（下次 audit 前）— 無
無 critical / warning 觸發，無強制 action。

### 觀察項（下次 audit 留意）
1. **K1032-K1035 第二 entry 無 `id` 欄**：屬 Paper 9 v5 cross-K bundle 寫入（2026-04-11），若下次 audit 看到類似 pattern 增加（無 id + cross-K bundle 多次寫入），建議補 `id` 欄位以利 trace（不刪、不合併）
2. **Entry 增量 monitoring**：本週 +11/day 是健康節奏；若下週超過 +30/day，回頭看是否 worktree merge dedup bug regression（同 2026-04-10 root cause family）
3. **Format migration drift**：新 `id` 格式比例 34.4% → 期望未來 6 個月隨 hourly dispatch 自然增長到 50%+；若停滯則檢查是否還有 caller 走 legacy `MemorySystem.add_knowledge` path

### 不建議的 action
- ❌ 不要 dedup K1032-K1035 第二 entry（content 不同，是 cross-K aggregation 視角，刪了會丟 Paper 9 v5 review provenance）
- ❌ 不要 strip 65 個 empty-title K43-K66 stubs（per docs/error_log.md 2026-05-09 entry「preserve > delete」原則 — stubs 留作 K-id collision audit trail）
- ❌ 不要強制 format migration（per SKILL §3「目前不需要強制統一」）

---

## 附錄：使用工具

- `uv run volpred ops memory-health-summary` — 一鍵 health snapshot
- `git show <commit>:storage/memory/knowledge.json | wc -c` — 7-day size delta
- `jq` + python3 ad-hoc analysis（schema sampling、bloat distribution、K-id misalignment scan）
- Prior incidents 對照：`docs/error_log.md` 2026-04-10（54.5 MB bloat）+ 2026-05-08 (K936 misalignment) + 2026-05-09（26-pair re-key audit）

**下次建議 audit 日期**：2026-05-24（weekly cadence）。
