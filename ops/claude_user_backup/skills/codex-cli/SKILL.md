---
name: codex-cli
description: "Invoke OpenAI Codex CLI (codex exec) to send prompts to GPT models and get responses. Use when the user wants to ask Codex/GPT a question, compare answers across AI models, or leverage Codex's coding capabilities."
user_invocable: true
---

# OpenAI Codex CLI Integration (v0.130+)

Use `codex exec` for non-interactive prompts against OpenAI GPT models from inside Claude Code.

- **Binary**：`codex`（`codex-cli` v0.130.0+）
- **預設模型**：`gpt-5.4`（reasoning effort = `medium`，由 `~/.codex/config.toml` 控制）
- **認證**：ChatGPT account（`codex login status` 確認）；可改為 API key（`codex login --with-api-key`）

## 主指令一覽（v0.130）

| 指令 | 用途 | 何時使用 |
|---|---|---|
| `codex exec` / `codex e` | **非互動式**執行 prompt（headless） | **預設入口**。任何 `/codex <prompt>` 一律走這個。 |
| `codex` (no args) | 互動 TUI | 不在 skill 範圍 — Claude Code 內請勿啟動 |
| `codex review` | 非互動 code review（branch / commit / uncommitted） | 比 `exec` 更精準的 review 場景；改用 `/codex:review` skill 更佳 |
| `codex resume [SESSION_ID]` | 繼續先前 interactive session | 用戶要接續某次 Codex 對話 |
| `codex fork [SESSION_ID]` | 從先前 session 分岔 | 想保留原 session 不動、另起分支實驗 |
| `codex apply <TASK_ID>` | 把 Codex 產的 diff 套到本地（`git apply`） | Codex Cloud / async task 完成後拉 patch |
| `codex login` / `codex login status` / `codex logout` | 管理認證 | 排查 401 / `codex --version` 連不上 |
| `codex mcp {add,list,get,remove,login,logout}` | 管理 external MCP servers | 加 Gmail / GitHub / Supabase 等 plugin |
| `codex plugin marketplace` | 管理 plugin marketplaces | 安裝官方 / 第三方 Codex plugins |
| `codex features {list,enable,disable}` | 查看 / 切換 feature flags | 開啟 experimental 功能（如 `tool_search`） |
| `codex sandbox {macos,linux,windows}` | 在 Codex sandbox 下執行任意 command | 想複用 Codex 的 Seatbelt / Landlock 隔離跑 build / test |
| `codex mcp-server` | 把 Codex 自己變成 stdio MCP server | 被 Claude Code 或其他 host 當 tool 用 |
| `codex remote-control` / `codex app-server` / `codex exec-server` | **experimental** headless service | 進階：把 Codex 暴露成 WebSocket service |
| `codex cloud {exec,status,list,apply,diff}` | **experimental** Codex Cloud 任務 | 把長任務丟雲端跑、稍後拉 diff |
| `codex debug {models,app-server,prompt-input}` | Debug 工具 | 看 raw model catalog / prompt input |
| `codex update` | 升級 Codex 本身 | 用戶要求升級 |
| `codex completion` | 產 shell completion 腳本 | 安裝 zsh / bash completion |

## `codex exec` 用法

### 預設執行（gpt-5.4, medium reasoning）

```bash
codex exec "<prompt>" 2>/dev/null
```

### 常用 flags（v0.130 新增 / 變更標 ⚡）

| Flag | 用途 |
|---|---|
| `-m, --model <MODEL>` | 切模型（`gpt-5.4`, `gpt-5.5`, `o3`, `o4-mini` 等） |
| `-c, --config <key=value>` | TOML 路徑覆寫（如 `-c model_reasoning_effort="high"`） |
| `-C, --cd <DIR>` | 設定 working root |
| `--add-dir <DIR>` | ⚡ 額外可寫目錄 |
| `-s, --sandbox <MODE>` | `read-only` / `workspace-write` / `danger-full-access` |
| `-a, --ask-for-approval <POLICY>` | ⚡ `untrusted` / `on-request` / `never`（headless 用 `never`） |
| `--dangerously-bypass-approvals-and-sandbox` | ⚡ 完全跳過 sandbox（極度危險；外部已隔離才用） |
| `--skip-git-repo-check` | ⚡ 容許在非 git repo 下跑 |
| `--ephemeral` | ⚡ 不寫 session 檔到磁碟 |
| `--ignore-user-config` | ⚡ 不讀 `~/.codex/config.toml`（auth 仍走 `CODEX_HOME`） |
| `--ignore-rules` | ⚡ 不載入 `.rules` execpolicy |
| `--output-schema <FILE>` | ⚡ 用 JSON Schema 限制最終 response 形狀 |
| `-o, --output-last-message <FILE>` | 把 agent 最後一則訊息寫到檔案 |
| `--json` | 以 JSONL 印 events 到 stdout（結構化 parsing 才用） |
| `-i, --image <FILE>...` | 附圖到 prompt |
| `-p, --profile <NAME>` | 用 `config.toml` 內定義的 profile |
| `--oss` / `--local-provider {lmstudio,ollama}` | 走 OSS / 本地 provider |
| `--color {auto,always,never}` | 控制顏色輸出 |
| ~~`--full-auto`~~ | ⚠️ **deprecated** → 用 `--sandbox workspace-write` |

### 範例

```bash
# 純問答（網路自動關閉）
codex exec "<prompt>" 2>/dev/null

# 換模型 + 拉高 reasoning
codex exec -m gpt-5.4 -c model_reasoning_effort='"high"' "<prompt>" 2>/dev/null

# 改 working dir + 可寫 sandbox + 不問 approval
codex exec -C /Users/yhlai0911/volpred-research -s workspace-write -a never "<prompt>" 2>/dev/null

# 結構化輸出（JSON Schema 約束）
codex exec --output-schema /tmp/schema.json -o /tmp/last.txt "<prompt>" 2>/dev/null

# 非 git repo
codex exec --skip-git-repo-check "echo TEST" 2>/dev/null

# Ephemeral（不留 session）
codex exec --ephemeral "<prompt>" 2>/dev/null
```

### Stdin 模式（heredoc — 中文 prompt 必用）

```bash
codex exec - 2>/dev/null <<'PROMPT'
<多行 / 含中文 / 含特殊字元的 prompt>
PROMPT
```

## Argument Parsing（給主 agent 解析 `/codex <ARGS>`）

- 開頭若 `-m <model>` → 抽出 model 用 `-m`
- 含 `-C <dir>` → 抽出 dir 用 `-C`
- 含 `-s <mode>` → 抽出 sandbox 用 `-s`
- 含 `--search` / 提到「web」「網路」「fetch URL」 → **不能**靠 `codex exec`（見下方限制）；改由 Claude WebSearch / WebFetch 處理
- 其餘文字為 prompt

## 執行規則

1. 一律走 `codex exec`，**禁用** bare `codex`（會打開 TUI hang 住）。
2. timeout：複雜 prompt 300000ms（5 分鐘）；簡單 prompt 120000ms。
3. 中文 / 多行 prompt **必用 heredoc + stdin**，不要 inline 字串（雙引號逃逸易爆）。
4. 預設 plain text；只有需要結構化 parsing 才加 `--json` 或 `--output-schema`。
5. `2>/dev/null` 過濾 debug stderr。
6. 把 Codex 回答**明確標註**為「來自 Codex / GPT」回給用戶。

## 已知限制（v0.130）

- **`codex exec` 無內建 web search**：`--search` flag **只在 TUI** 可用；headless exec 無網路、無 fetch URL、無 DOI 驗證。需網路 → Claude WebSearch / WebFetch 接手。
- **Sandbox 預設 read-only**：要寫檔必加 `-s workspace-write`；要寫專案外路徑必加 `--add-dir`。
- **無互動輸入**：無法處理需要用戶 prompt 的指令（必用 `-a never`）。
- **`--full-auto` 已 deprecated**：改用 `--sandbox workspace-write`。

## Collaboration Protocol（Claude ↔ Codex）

兩者互補：Codex 強在 local code 分析、結構化重構、Codex review；Claude 強在 web、跨 MCP、多 agent 編排。

### 分工原則

1. **派給 Codex**：純本地 code 分析、檔案 read、local 計算、code review、code generation、structured diff。
2. **Codex fail → Claude 接手**：output 出現 `Could not resolve host`, `operation not permitted`, `network unreachable` 等 → Claude 用 WebSearch / WebFetch / Agent 補上。
3. **Merge**：Codex 的 local 分析 + Claude 的 web 資料 → 統一報告。
4. **Proactive split**：任務同時需要 local + web → 上來就拆，Codex 跑 local、Claude 並行跑 web。

### 範例：Citation Verification

```bash
# Step 1: 派 Codex 跑 local references 對照
codex exec -C /paper -s read-only - 2>/dev/null <<'PROMPT'
Parse references.bib, cross-check against main.tex \cite{} keys,
report any orphans / typos / duplicates.
PROMPT

# Step 2: Claude 用 WebSearch 驗 DOI / 作者 / 期刊
# Step 3: Claude 合併兩邊結果
```

## Error Handling

- 未認證：建議 `codex login`
- 模型不存在：暫時移除 `~/.codex/config.toml` 的 `model =` 行讓 CLI auto-pick default，smoke test 通過後再鎖回。
- timeout：縮 prompt 或拆任務
- 網路相關錯誤：Claude 接手 web 部分
- 持續異常：見專案內 `.claude/rules/experiments.md` 的「Codex CLI 故障 diagnostic 5 步」

## Example

User：`/codex what is the time complexity of quicksort?`

```bash
codex exec "what is the time complexity of quicksort?" 2>/dev/null
```

回傳結果並標註「來自 Codex / GPT」。
