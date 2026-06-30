---
name: reference-antigravity-cli
description: Antigravity CLI (agy) — 官方獨立終端 agentic CLI，取代 gemini-cli；安裝位置、模型、用法
metadata: 
  node_type: memory
  type: reference
  originSessionId: 2d8ee424-fc5e-4485-9771-36d7a353880b
---

# Antigravity CLI (agy)

Gemini CLI 的官方繼承者，Google I/O 2026-05-19 發布。獨立 headless 終端 agentic CLI，**不是** IDE launcher。

## 安裝（2026-05-20，本機）

- 版本：`agy 1.0.0`，位置 `/Users/yhlai0911/.local/bin/agy`（Mach-O arm64 binary）
- 安裝：`curl -fsSL https://antigravity.google/cli/install.sh | bash`
- PATH：已寫入 `~/.zshrc` / `~/.zprofile` / `~/.bash_profile`
- 認證：Google OAuth（token 存 keyring）— 必須在使用者自己的 terminal 跑 bare `agy` 完成一次性登入；OAuth 不能代跑（每次執行產生新 PKCE challenge，舊 code 立即失效）

## 模型

- **預設模型 `gemini-3.5-flash`**
- 沒有 `-m` flag — 換模型走環境變數 `ANTIGRAVITY_MODEL`
- 例：`ANTIGRAVITY_MODEL=gemini-2.5-pro agy -p "<prompt>"`

## headless 用法（2026-05-20 實測通過）

```bash
agy -p "<prompt>"                                  # 一次性 print，真 stdout pipe
agy -p "<prompt>" --dangerously-skip-permissions   # agentic 工作（會動檔案）
```

實測 3 項皆 exit 0 + 正確輸出：單行中文 prompt、多行中文 prompt、code-bug 偵測。
舊 CLAUDE.md「`agy chat` 開 GUI 無 stdout pipe，headless 不可用」已作廢 — 那指
`agy chat`（互動模式）；`agy -p` / `--print` 是 headless 入口，stdout pipe 正常。

**陷阱**：`-p` 吃**參數**不吃 stdin（`echo ... | agy -p` 報 `flag needs an argument`）。
中文多行 prompt 用 heredoc 存變數再傳：
```bash
PROMPT=$(cat <<'EOF'
<多行中文 prompt>
EOF
)
agy -p "$PROMPT"
```

## 定位（與 gemini_ask.py / Codex 的分工）

`agy` 是**第三個 agentic CLI**，與 Codex CLI 並列 — 可做 code review、針對性修正、
獨立子任務，與 Codex 一起分擔工作。
- agentic 多步工作 → Codex CLI 或 `agy`
- 一次性問答 / fact-check → 優先 `agy -p`；`scripts/gemini_ask.py` 僅作 **fallback**
  （agy 不可用、或需純 pipe API 呼叫時）。
- ⚠️ `gemini_ask.py` 每次成功呼叫 = PAID Gemini API 費用 → script 底層已內建：
  每次自動 email 通知 admin（`send-alert --force`）+ 記 `storage/logs/gemini_ask_usage.jsonl`。
  用戶 2026-05-20 硬性要求 — fallback 有使用就要強調通知。

## 易混淆陷阱（2026-05-20 教訓）

Homebrew cask `antigravity` 是**完全不同的東西** — 它裝的是 Antigravity IDE（GUI 編輯器）+ 一個叫 `agy` 的 IDE launcher wrapper（像 `code`）。要的是獨立 CLI，**只走官方 install.sh**，不要碰 Homebrew cask。

## 停服時間表

2026-06-18 Gemini CLI 停止服務，由 `agy` 繼承 agentic 角色。專案 `gemini-cli` skill 已 DEPRECATED。`scripts/gemini_ask.py`（直打 API）不受影響，續用於輕量一次性問答。
