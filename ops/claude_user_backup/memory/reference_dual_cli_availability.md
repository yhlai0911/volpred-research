---
name: reference-dual-cli-availability
description: 本機雙 AI CLI 可用性快照 — Codex 0.132 + Gemini CLI 6/18 將停用，headless 改走 gemini_ask.py（Gemini 3.1 Pro API）（2026-05-20 更新）
metadata: 
  node_type: memory
  type: reference
  originSessionId: 0ca8f10c-d34e-4570-af41-a25c2fff4e5c
---

# 雙 AI CLI 可用性快照（2026-05-20 更新）

## Codex CLI `codex-cli 0.132.0` ✅
- 2026-05-20 更新 0.130→0.132；reinstall 時需 `npm install -g @openai/codex@latest --include=optional` 才會帶 `@openai/codex-darwin-arm64` binary（少了會 crash）
- Auth：`Logged in using ChatGPT`（個人 ChatGPT 帳號 OAuth）
- 預設模型：`gpt-5.4`，`model_reasoning_effort = "medium"`（`~/.codex/config.toml`）
- Headless 入口：`codex exec`；中文/多行 prompt 用 heredoc + stdin
- 限制：`codex exec` 無 web search
- Deprecation：`--full-auto` → `-s workspace-write`

## Gemini CLI `0.42.0` ⚠️ 2026-06-18 停用
- **重大變更**：Google 把 Gemini CLI 併入 Antigravity CLI。消費者版（含 AI Pro/Ultra 訂閱）的 gemini-cli **2026-06-18 停止服務**
- Auth：`oauth-personal`，active = `ideahub.everything@gmail.com`（Gemini Pro 訂閱）
- oauth-personal 認證下**只有 gemini-2.5-pro / gemini-2.5-flash 可用**；gemini-3-pro / 3-flash / 3.5-flash 全 **404**（Gemini 3 access 移到 API / Antigravity）
- Headless 入口：`gemini -p`，必加 `-y --skip-trust`
- **6/18 前可繼續用 gemini-2.5-pro 做 review；6/18 後改 gemini_ask.py**

## Antigravity CLI `agy` (Antigravity 1.107) — headless 不可用 ❌
- 2026-05-20 brew cask 裝（`brew install --cask antigravity`），GUI IDE（VS Code fork）+ `agy` CLI
- `agy chat -m ask "prompt"` → 開 GUI IDE chat 面板，**stdout 0 bytes**，無 pipe
- **不能取代 `gemini -p` 的 headless 用法**（second-opinion / fact-check 需 cmd→stdout pipe）
- GUI 本體保留可用（人要用 IDE 時、Gemini 3 在裡面），但自動化不走它

## ✅ Headless Gemini 正解：`scripts/gemini_ask.py`（2026-05-20 建）
- 直打 Gemini API（`GOOGLE_CLOUD_API_KEY`，在 `.env`）→ 真 stdout pipe
- **API key 路徑有 Gemini 3**：`gemini-3.1-pro-preview` / `gemini-3-pro-preview` / `gemini-3-flash-preview` 全可用（2026-05-20 驗證）
- 預設 model `gemini-3.1-pro-preview`（API key 下最佳）
- 3 模式：`gemini_ask.py "prompt"` / `echo ... | gemini_ask.py -` / `--model gemini-2.5-flash ...`
- commit `2774f26c`
- **這是 6/18 後 headless second-opinion 的 canonical 路徑**

## 何時重新確認
- Codex 更版後 `codex --version` + `codex login status` re-check
- **2026-06-18 gemini-cli 停用日** — 屆時所有 `gemini -p` 呼叫改 `gemini_ask.py`
- Gemini API key 失效 → `.env` GOOGLE_CLOUD_API_KEY re-check
- 相關 memory：[[feedback-3model-review-discipline]] / [[feedback-gemini-cli-share-load]] / [[feedback-gemini-v042-skip-trust]] / [[feedback-codex-cli-capability]]
