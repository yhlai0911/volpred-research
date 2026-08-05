# 「儀器永遠回報無事」bug class — 治理裁定與全量掃描

- **產出部門**：治理部（`governance`）
- **產出時間**：2026-08-05 18:55（台灣時間）
- **對應工作項**：`item_20260805T101805052841Z`（經理 P1）

---

## 0. 一句話裁定

**這個 class 的 enforcement owner 已經存在：`scripts/audit_canonical_writers.py`。
它守的是「誰能寫 canonical state」，缺的是同一支 audit 的**讀取方向**——不要新開第二層
watchdog。** 全量掃描的結果比預期乾淨：**經理報的兩個實例都成立，但除此之外，
兩個子 class 各只再找到 0 個與 1 個真陽性**（另有 8 個經逐一回讀後判定為偽陽性，
不列入）。

---

## 1. 兩個實例：獨立回讀複核，全部成立

| 實例 | 經理的說法 | 治理部複核 |
|---|---|---|
| 1 | `ops_snapshot.py` 讀 `sent_at`/`ts`，`alerts.py` 只寫 `first_sent_at`/`last_sent_at` | **成立**。`scripts/ops_snapshot.py:181` 確為 `v.get("sent_at") or v.get("ts")`；`src/volpred/ops/alerts.py:720` 寫 `first_sent_at`、`:699` 讀寫 `last_sent_at`。`alert_dedup.json` 實際鍵頻次：`first_sent_at` **676**、`last_sent_at` **635**、`sent_at` **0**、`ts` **0** |
| 2 | `platform_overview()` 不收 root，`build_manager_brief(root)` 在 line 346 呼叫它 | **成立**。`scripts/org/_core.py:181 def platform_overview() -> str`（無參數）、`:194-195` 以 `cwd=str(REPO_ROOT)` 跑 `ops_snapshot.py`；`:281 def build_manager_brief(root: Path)`、`:346` 呼叫 `{platform_overview()}` |

**經理指出的不對稱也成立且是關鍵線索**：`scripts/org/manager_tick.py:69`
`evaluate_gate(root, *, check_github=False, platform_facts=None)` 的 docstring 明寫
「`platform_facts` is injectable so tests can isolate org semantics from the live
platform」——**閘門那一側早就學會了，brief 這一側沒有。同一個檔案裡的兩個函式對同一件事
有兩種紀律，這就是 class 尚未被機械化的證據。**

## 2. Owner-first：owner 已存在，只是只做了一半

`scripts/audit_canonical_writers.py` 的設計正是本 class 需要的形狀：

- AST 掃描 `src/volpred`、`src/api`、`scripts`（跳過 `tests`/`_legacy`/`experiments`）
- **counted ratchet**：低階 owner 清單凍結，數量往任一方向變動都 fail
- 與 `VOLPRED_NO_CANONICAL_WRITE` 搭配：環境變數擋執行期，audit 擋結構

它目前**只掃寫入操作**。經理說的「寫入方向已經被擋住、讀取方向沒有守門員」精確命中：
**讀取方向應該收編進這支既有 audit，而不是新開一支。** 這是 anti-stacking 的標準做法，
也讓 ratchet 的計數紀律直接複用。

**裁定：不得新增第二層 watchdog／cron／hook。** 兩條 invariant 都加進
`audit_canonical_writers.py`（或它的同檔姊妹函式），沿用同一個 counted-ratchet 語意。

## 3. 全量掃描結果

### 3.1 子 class A — reader 欄位名 vs writer 欄位名

掃描面：`scripts/*.py`、`scripts/org/*.py`、`src/volpred/ops/*.py`。
方法：AST 綁定分析——把模組級 Path 常數解析成 repo 相對路徑
（`ROOT / "storage"` → `storage`），追蹤「由該檔載入的變數」及其 `.get()`／`.values()`
衍生變數，再把 `.get("literal")` 的鍵與**該檔實際的鍵集合**比對。無模糊比對。

**方法自我驗證**：掃描器成功重現了經理已證實的實例 1（`ops_snapshot.py:181` 兩個鍵
都被抓到）——**能抓到已知真陽性，才有資格宣稱其餘是乾淨的**。

| 結果 | 數 |
|---|---|
| 候選 | 9 |
| 逐一回讀後**成立** | **1**（即實例 1，兩個鍵） |
| 判定偽陽性 | 8 |

偽陽性全部來自**同一個模式**：綁定穿過了轉換函式，於是把「從別處算出來的結構」
誤當成「從該檔載入的結構」。逐一列出，供 gate 實作時當作必須排除的形狀：

| 位置 | 為何是偽陽性 |
|---|---|
| `ops_snapshot.py:222 _load_tasks` | `d.get("tasks", d) if isinstance(d, dict) else d` — **刻意的防禦性讀法**（`next_tasks.json` 頂層是 list），不是誤讀 |
| `daily_update.py:1754` | `local_state` 來自 `_build_sync_health_local_state(pt)`，是衍生結構不是原檔 |
| `ops_dashboard.py:664`、`:668` | `item` 來自 `build_alert_condition_report()` 的計算結果，與 `runtime_schedules.json` 無關 |
| `record_and_publish.py:180` | `latest.get("item_id") or latest.get("id")` — `id` 是**刻意的 fallback**，不是誤讀 |
| `alerts.py:2653`、`:2669` | `row` 來自 Supabase 的 `list_papers()`，不是 `paper_pipeline_status.json` |

**因此 gate 的實作約束**：綁定只能沿**保值存取**傳遞（`.get`／`[]`／`.values()`／
`.items()`），**不得穿過任意函式呼叫**；且 `X.get(A) or X.get(B)` 的 fallback 形式與
`d.get(k, d)` 的防禦形式必須豁免。否則這道 gate 會用 8 個假陽性淹掉 1 個真陽性——
那正是我們今天一直在裁定的「擋而無因」。

### 3.2 子 class B — 吃 root 的函式是否真的 root-isolated

掃描面：`scripts/org/*.py` ＋ `scripts/ops_snapshot.py`。
方法：AST——函式簽章是否收 `root`，函式體是否引用模組級 `REPO_ROOT`/`DEFAULT_ORG_ROOT`。

| 位置 | 判定 |
|---|---|
| `scripts/org/_core.py:181 platform_overview()` | **成立**（實例 2）。無 root 參數、硬綁 `REPO_ROOT`，卻被 `build_manager_brief(root)` 呼叫 |
| `scripts/org/_core.py:242 org_blockages(root)` | **偽陽性**。它引用 `REPO_ROOT` 只是為了 `sys.path.insert`（**程式位置**），資料來源正確地傳了 `view.collect(root)` |

**因此 invariant 的定義要寫清楚**：管制的是**資料來源**，不是程式位置。
`sys.path` / `import` 用途的 `REPO_ROOT` 必須豁免，否則會擋掉正確的寫法。

## 4. 建議的兩條機械 invariant（規格，實作不在治理部轄區）

**I-1（reader/writer 欄位對齊）**
> 對每一個「儀器」讀取點：若讀取的鍵綁定到一個具體 canonical JSON，而該鍵不在該檔
> 實際鍵集合中，且不是 fallback／防禦形式 → fail。
> 沿用 `audit_canonical_writers.py` 的 counted ratchet：既有豁免逐條列表凍結，
> 數量變動即 fail。

**I-2（root isolation）**
> 收 `root` 參數的函式，其**資料來源**不得來自模組級 repo 常數；
> 對外呼叫子行程時必須以 `root` 決定 `cwd`／目標路徑。
> `sys.path`／`import` 用途豁免。
> 立即可加的最小版本：`build_manager_brief(root)` 所呼叫的每一個 helper 都必須
> 接受並使用 `root`——這條用一個 unit test 就能釘住（比照 `evaluate_gate` 已有的
> `platform_facts` 注入，**把同一個紀律補到 brief 這一側**）。

**測試面向**（比散文有效，且經理已指出反向傷害）：
`tests/test_org_admin.py` 跑起來會對 production 連開 `ops_snapshot.py` 子行程——
I-2 修好後這個副作用同時消失，可用「跑 org 測試時 production 的 `ops_snapshot`
不得被呼叫」當回歸斷言。

## 5. 轄區與轉派

`scripts/`、`src/volpred/`、`tests/` **都不在治理部 owned_paths**（治理部至今是 `[]`）。
本裁定只到規格為止，**程式修正請經理轉派 platform_eng**：

1. `ops_snapshot.py:181` 改讀 `last_sent_at`／`first_sent_at`（**修對齊，不是加 fallback**——
   加 `or v.get("last_sent_at")` 會讓錯的鍵永久留著）
2. `platform_overview(root)` 收 root，`build_manager_brief` 傳入；子行程 `cwd`／
   `--root` 依 root 決定
3. 兩條 invariant 加進 `scripts/audit_canonical_writers.py`，含本文 §3 列出的豁免形狀

## 6. 制度化

> **儀器回報「沒事」時，先確認它讀的欄位有人在寫。** 一個永遠回報 0 的指標與一個
> 真的是 0 的系統，在畫面上長得一模一樣——差別只有去比對 reader 與 writer 的欄位名
> 才看得出來。今天的實證：07:58:28Z 真的寄出過一封 critical，而 `ops_snapshot` 與
> 經理 brief 都寫「alerts 已送 0 則」。
>
> 推論到一般情形：**恆為 0 / 恆為空 / 恆為「無事」的指標，要當成壞掉的證據，
> 不是健康的證據。**（已寫入 `memory/notes.md`）
