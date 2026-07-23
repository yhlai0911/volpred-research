---
name: reference-shell-utf8-locale-required
description: 非互動 shell 未設 UTF-8 locale，中文/emoji argv 會壞掉；telegram-send 會噴 surrogates not allowed
metadata: 
  node_type: memory
  type: reference
  originSessionId: eb5b0a61-ad79-4bcb-b914-afad7bc35e57
  modified: 2026-07-21T17:38:13.659Z
---

launcher 起的非互動 shell（例如 telegram_responder workdir）預設 locale 不是 UTF-8，
中文與 emoji 經 argv 或 heredoc 傳進 Python 時會變成 lone surrogate，症狀：

- `volpred ops telegram-send --text "中文..."` → `UnicodeEncodeError: 'utf-8' codec can't encode characters ...: surrogates not allowed`（純 ASCII 訊息則正常送出，容易誤判成訊息內容問題）
- `python3 - <<'PY'` heredoc 內含中文 → `SyntaxError: Non-UTF-8 code starting with '\x8d'`

修法：每個 Bash 呼叫都加 `export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8`，
長訊息用 Write 工具寫 /tmp 檔再 `--text "$(cat ...)"`，不要在 shell 裡拼中文 heredoc。
同一個 shell 也常缺 uv：一併 `export PATH="$HOME/.local/bin:$PATH"`。

相關：[[feedback-responder-reply-before-complete]]
