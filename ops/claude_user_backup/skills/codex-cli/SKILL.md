---
name: codex-cli
description: "Invoke OpenAI Codex CLI (codex exec) to send prompts to GPT models and get responses. Use when the user wants to ask Codex/GPT a question, compare answers across AI models, or leverage Codex's coding capabilities."
user_invocable: true
---

# OpenAI Codex CLI Integration

在 Claude Code 內用 `codex exec` 對 OpenAI GPT 模型跑非互動 prompt。

## 這份文件的分工（先讀這段，別把它當普通前言）

| 你要什麼 | 去哪 |
|---|---|
| **某個指令有哪些參數**（完整、逐字） | `references/cli-reference.md` — **binary 自己吐的**，56 個指令節點 |
| **桌面 App / Cloud / 三個 binary 的版本問題 / doctor** | `references/codex-app-and-binaries.md` |
| **怎麼用、會踩什麼坑、VolPred 規則** | 本檔 |
| **官方說法** | 文件 2026 年已搬到 **`learn.chatgpt.com`**（`developers.openai.com/codex/*` 會 308 轉址）：[developer-commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli) · [config-reference](https://learn.chatgpt.com/docs/config-file/config-reference) · [models](https://learn.chatgpt.com/docs/models) · [changelog](https://learn.chatgpt.com/docs/changelog) · [GitHub](https://github.com/openai/codex) |

⚠️ **官方文件也會錯 / 會過時**，2026-07-17 實測抓到三處：(1) config-reference 的 `model_reasoning_effort` 合法值漏列 `none`/`max`/`ultra`；(2) 把 `-a` 放在「Global flags」並說 global flags 大多會 propagate —— **對 `exec` 不成立**；(3) model 範例還停在 `gpt-5.4`/`gpt-5.5`。**衝突時以本機實跑為準。**

**為什麼這樣切**：這份 skill 曾經整份是手寫的，然後就漂掉了 —— 教了一個 `codex exec -a never`，而 `-a` 在 exec 根本不存在，照抄的人拿到 exit 2 + 空 stdout，看起來像卡住，實際是參數錯（2026-07-17 K1729 事故）。**參數的窮舉交給機器，判斷留給人**：

```bash
uv run python scripts/gen_codex_cli_reference.py           # 重新產生參考文件
uv run python scripts/gen_codex_cli_reference.py --check   # exit 1 = 版本/文件漂移
```

**衝突時誰說了算**：flag 的拼法 / 屬於哪個子指令 → 以 `cli-reference.md` 為準（binary 自己吐的）。**但「某個東西存不存在」→ 以實跑為準**：help 有隱藏 flag、也不列 config 合法值，光看文件會誤判（本檔已經誤判過一次，見下方 `ultra`）。

## 基本事實（2026-07-17 實測）

- **Binary**：`codex`（`$PATH` 上是 npm 版 **0.144.1**；npm latest 0.144.5）
  - ⚠️ 這台機器上有**三個不同版本的 codex**（npm / 桌面 App / VS Code 擴充）。自動化用的是 npm 那個。詳見 `references/codex-app-and-binaries.md`。
- **模型**：`gpt-5.6-sol`（官方 GPT-5.6 三階：`-sol` 旗艦 / `-terra` 均衡 / `-luna` 快而省）
- **reasoning effort**：**要引用前先實測，不要照抄任何文件（含本檔）**：
  ```bash
  grep model_reasoning_effort ~/.codex/config.toml     # 2026-07-17 實測 = high
  ```
  合法值 = `none|minimal|low|medium|high|xhigh|max|ultra`（upstream `ReasoningEffort` enum）。
  - `ultra` **是合法的**（2026-07-17 實測 `-c model_reasoning_effort=ultra` → header 印 `reasoning effort: ultra`、exit 0）。它是 **Codex 客戶端專屬**、由 CLI 自己處理，**不是**合法的 Responses API 原始值 —— API 的 enum 只認到 `max`。
  - ⚠️ 本檔 2026-07-17 稍早曾宣稱「ultra 不是合法值」，**那是錯的**，理由也錯：當時的推論是「`--help` 裡找不到 ultra」。`--help` **根本不列 config 的合法值**，找不到不能證明不存在。已更正。
  - ✅ 真正該守的紀律沒變：**config 實測是 `high`，所以不要對外說我們的 reviewer 跑 ultra**（那才是原本的研究誠實問題 —— 誤述我們實際跑了什麼）。
- **認證**：ChatGPT account（`codex login status`）；亦可 `codex login --with-api-key`。
- **出事先跑** `codex doctor --summary`（一次驗 config/auth/mcp/sandbox/network/websocket）。

## ⚠️ 四個會讓你白花時間的坑

### 坑 1：裸 `codex exec` 已被機械 deny

`.claude/hooks/pretooluse-bash-optimizer.sh` 會擋（2026-07-11 事故：agent 裸跑卡 >30min → 撞 supervisor 3000s cap → SIGKILL）。Bash tool 沒有 timeout、macOS 沒有 coreutils `timeout`，裸跑 = 把整個 fire 交給一個無上界的 agentic loop。

**一律包起來**：

- 短工作（你會盯著）→ `bash scripts/codex_exec_bounded.sh --timeout <秒> <args>`（逾時 exit 124）
- 重活 / 長 review / 你不會坐著等 → `uv run python scripts/compute_queue.py enqueue --script <path> --timeout 1800`
- Python 內 `subprocess.run(timeout=)` 不受攔截（本來就有界）

### 坑 2：exit 2 + 空 stdout = 參數錯，不是超時

**最貴的坑**：參數打錯時 codex 是**安靜地**死 —— exit 2、stdout 全空、stderr 才有 `error: unexpected argument`。看起來跟「超時卡住」一模一樣，於是人會跑去查認證、查模型、查網路，查半天。

**症狀對照**：

| 現象 | 真正原因 | 先做什麼 |
|---|---|---|
| exit 2 + stdout 空 | **參數不存在** | 看 stderr；查 `cli-reference.md` |
| exit 124 | 包裝腳本逾時 | 拆任務 / 拉長 timeout |
| exit 0 但 stdout 空 | 多半也是參數/prompt 問題 | 看 stderr |
| exit 1 + API `invalid_enum_value` | config **值**打錯（如 effort 拼錯） | 看 header 的 `reasoning effort:`；見坑 4 |
| 400 / 模型錯誤 | config model × CLI 版本不合 | smoke test；見 app-and-binaries |

**任何 codex 指令沒產出，第一動作是看 stderr，不是猜。**

### 坑 3：flag 分屬不同 context —— 這正是 K1729 的死因

`codex` 頂層（互動 TUI）與 `codex exec`（非互動）**參數表不一樣**。以為通用就會中：

| Flag | 互動 `codex` | `codex exec` | 說明 |
|---|---|---|---|
| `-a, --ask-for-approval` | ✅ 有 | ❌ **沒有** | **K1729 死因**。exec 本來就非互動。`-a never` → exit 2 靜默失敗。**不要好心加回去。** exec 要控 approval → `-c approval_policy=never` |
| `--search`（live web search） | ✅ 有 | ❌ **沒有** | headless exec **無法上網**。要網路 → Claude WebSearch/WebFetch 接手 |
| `--include-plan-tool` | ❌ 沒有 | ❌ 沒有 | 0.144.1 不存在 → **exit 2**。官方無移除公告，靜默消失。別用 |
| `--full-auto` | ❌ 沒有 | ⚠️ **隱藏但可用** | **help 裡看不到，但 exec 吃它、exit 0**（2026-07-17 實測）。官方稱 deprecated → 改用 `-s workspace-write`。**別依賴** |
| `--no-alt-screen` / `--remote` | ✅ 有 | ❌ 沒有 | TUI 專屬 |
| `-o, --output-last-message` | ❌ 沒有 | ✅ 有 | exec 專屬 |
| `--json` / `--output-schema` / `--ephemeral` | ❌ 沒有 | ✅ 有 | exec 專屬 |

📌 **要查某個 flag 屬於誰，用 `codex help exec`，不要用 `codex exec --help`** —— 後者字串會撞坑 1 的 deny hook（雖然 `--help` 本身是安全的，hook 是字串比對）。`codex help <subcmd>` 完全等價且不會被擋。

⚠️ **`--help` 不是全知的**（`--full-auto` 就是活證據：help 沒有、實際可用）。所以 `cli-reference.md` 窮舉的是**檯面上的 flag**，不含隱藏 flag，也**不含 config 的合法值**。要斷言「某個東西不存在」，**必須實跑**，不能只靠 grep help —— 這正是本檔 2026-07-17 誤判 `ultra` 的原因。

### 坑 4：reasoning effort 打錯不會被 CLI 擋

CLI 對 effort **不做驗證**（upstream enum 有 `Custom(String)` fallback），打錯會原樣送給後端：

```
-c model_reasoning_effort=ultraa
  → CLI header 照印 "reasoning effort: ultraa"（看起來很正常）
  → 後端 400 invalid_enum_value → exit 1
```

錯誤來得晚且來自 API 而非 usage 檢查，所以**別以為 CLI 沒抱怨就是拼對了**。確認方式：看 exec header 印出的 `reasoning effort:` 那行。

## `codex exec` — 預設入口

```bash
bash scripts/codex_exec_bounded.sh --timeout 300 "<prompt>" 2>/dev/null
```

最常用的 flag（**完整清單見 `cli-reference.md`**）：

| Flag | 用途 |
|---|---|
| `-m, --model <MODEL>` | 切模型（舊 CLI 不支援新 model 會 400） |
| `-c, --config <key=value>` | TOML 覆寫，如 `-c model_reasoning_effort='"high"'` |
| `-C, --cd <DIR>` | working root |
| `--add-dir <DIR>` | 額外可寫目錄（專案外路徑必加） |
| `-s, --sandbox <MODE>` | `read-only`（預設）/ `workspace-write` / `danger-full-access` |
| `--skip-git-repo-check` | 容許在非 git repo 下跑 |
| `-o, --output-last-message <FILE>` | 最後一則訊息寫檔 |
| `--json` | JSONL events（要結構化 parsing 才用） |
| `--output-schema <FILE>` | 用 JSON Schema 約束最終回應形狀 |
| `--ephemeral` | 不寫 session 檔 |
| `-i, --image <FILE>...` | 附圖 |

### 範例

```bash
# 純問答
bash scripts/codex_exec_bounded.sh --timeout 120 "<prompt>" 2>/dev/null

# 換模型 + 調 effort
bash scripts/codex_exec_bounded.sh --timeout 300 -m gpt-5.4 -c model_reasoning_effort='"high"' "<prompt>" 2>/dev/null

# 可寫 sandbox（注意：沒有 -a 這個 flag）
bash scripts/codex_exec_bounded.sh --timeout 600 -C /Users/yhlai0911/volpred-research -s workspace-write "<prompt>" 2>/dev/null

# 結構化輸出
bash scripts/codex_exec_bounded.sh --timeout 300 --output-schema /tmp/schema.json -o /tmp/last.txt "<prompt>" 2>/dev/null

# smoke test（升級 CLI / 改 model 後必跑）
bash scripts/codex_exec_bounded.sh --timeout 60 --skip-git-repo-check "echo TEST" 2>/dev/null
```

### Stdin 模式（中文 / 多行 prompt 必用）

包裝腳本吃 stdin，但 **heredoc 直接接它會被腳本內部的 `exec python3` 吃掉**。寫檔再 pipe 最穩：

```bash
cat > /tmp/prompt.txt <<'PROMPT'
<多行 / 含中文 / 含特殊字元的 prompt>
PROMPT
cat /tmp/prompt.txt | bash scripts/codex_exec_bounded.sh --timeout 600 -s workspace-write - 2>/dev/null
```

## 其他常用指令

| 指令 | 用途 |
|---|---|
| `codex help <subcmd>` | **查參數的正確方式**（不會撞 deny hook） |
| `codex doctor --summary` | 出事第一站；`--json` 可機器讀 |
| `codex review --uncommitted \| --base <BR> \| --commit <SHA>` | 非互動 code review（比 exec 精準；或用 `/codex:review`）。三個 target flag **互斥，只能選一個**；`--title` **必須配 `--commit`**。另有 `codex exec review` 入口，官方只記載 top-level 那個 |
| `codex resume --last` / `codex fork --last` | 接續 / 分岔先前 session |
| `codex mcp {list,get,add,remove,login,logout}` | 管 external MCP servers |
| `codex features list` | 看 feature flags（會隨版本變，勿照抄） |
| `codex update` | 升級（**先確認沒有 in-flight job**，見 app-and-binaries） |
| `codex app [PATH]` | 開桌面 App — **會開 GUI，自動化勿用** |
| `codex` (無參數) | 互動 TUI — **Claude Code 內勿啟動**（會 hang） |

## 執行規則

1. 一律走 `codex exec` 且**一律用 `scripts/codex_exec_bounded.sh` 包**；禁用 bare `codex`。
2. timeout：包裝腳本吃**秒**（複雜 300–900、簡單 60–120）；Bash tool 吃**毫秒**，別搞混。長 review 一律 `run_in_background: true`。
3. 中文 / 多行 prompt 必用寫檔 + stdin，不要 inline 字串。
4. 預設 plain text；要結構化才加 `--json` / `--output-schema`。
5. `2>/dev/null` 過濾 debug stderr —— **但排查失敗時務必拿掉**（坑 2：錯誤只在 stderr）。
6. Codex 的回答**明確標註**「來自 Codex / GPT」再回給用戶。
7. 引用 model / effort / feature 前先實測，不要照抄文件。

## Collaboration Protocol（Claude ↔ Codex）

Codex 強在 local code 分析、結構化重構、review；Claude 強在 web、跨 MCP、多 agent 編排。

1. **派給 Codex**：純本地 code 分析、檔案 read、local 計算、code review、structured diff。
2. **Codex fail → Claude 接手**：出現 `Could not resolve host` / `operation not permitted` / `network unreachable` → Claude 用 WebSearch / WebFetch 補（**exec 沒有 `--search`，本來就上不了網**）。
3. **Merge**：Codex 的 local 分析 + Claude 的 web 資料 → 統一報告。
4. **Proactive split**：任務同時要 local + web → 上來就拆，兩邊並行。

### 範例：Citation Verification

```bash
# Step 1: Codex 跑 local references 對照
cat > /tmp/cite_prompt.txt <<'PROMPT'
Parse references.bib, cross-check against main.tex \cite{} keys,
report any orphans / typos / duplicates.
PROMPT
cat /tmp/cite_prompt.txt | bash scripts/codex_exec_bounded.sh --timeout 300 -C /paper -s read-only - 2>/dev/null

# Step 2: Claude 用 WebSearch 驗 DOI / 作者 / 期刊
# Step 3: Claude 合併
```

## 近期 breaking changes（會咬到我們的）

- **`approval_policy = "on-failure"` 已移除**：現存值只有 `untrusted | on-request | never`（或 granular 物件）。舊腳本寫 `on-failure` 會失效。
- **0.144.5 收緊 dangerous-command 偵測**（更多 forced `rm` 形式被拒）：**升級後原本能跑 `rm -rf` 的自動化腳本可能開始被拒**。升級時要一起驗（見 `platform_ops_codex_cli_upgrade_0144_5`）。
- **0.143.0 起強制 auto-compaction**，不能關。
- **0.145.0-alpha 沒有任何 release notes**（今天還在出 alpha）。**別把 0.145 的行為寫進任何文件**。

## Error Handling

- **exit 2 / 空輸出** → 參數錯。看 stderr、查 `cli-reference.md`。（別再誤診成超時）
- 未認證 → `codex login`（先 `codex doctor`）
- 模型不存在 → 暫時移除 config 的 `model =` 讓 CLI auto-pick，smoke 過再鎖回
- timeout（exit 124）→ 縮 prompt 或拆任務
- 網路錯誤 → Claude 接手 web 部分
- 持續異常 → `.claude/rules/experiments.md`「Codex CLI 故障 diagnostic 5 步」
