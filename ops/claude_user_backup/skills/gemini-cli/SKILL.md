---
name: gemini-cli
description: "DEPRECATED 2026-05-20 — gemini-cli 已放棄（Google 6/18 停服）。所有 headless Gemini 呼叫改用 scripts/gemini_ask.py（直打 Gemini API，預設 gemini-3.1-pro-preview，真 stdout pipe）。"
user_invocable: true
---

# gemini-cli — DEPRECATED（2026-05-20 放棄）

## 為什麼放棄
- Google 把 gemini-cli 併入 Antigravity CLI；消費者版 **2026-06-18 停服**。
- oauth-personal 認證下 Gemini 3 全 404（只剩 2.5-pro/flash）。
- Antigravity `agy chat` 開 GUI IDE chat，stdout 0 bytes，headless 不可用。

## 取代方案：scripts/gemini_ask.py
```bash
uv run python scripts/gemini_ask.py "你的問題"           # 單行
cat /tmp/x.txt | uv run python scripts/gemini_ask.py -   # stdin pipe
uv run python scripts/gemini_ask.py --model gemini-2.5-flash "快問"
```
- 直打 Gemini API（`GOOGLE_CLOUD_API_KEY` 在專案 `.env`）
- 預設 `gemini-3.1-pro-preview`（API key 路徑有 Gemini 3，oauth 沒有）
- 真 stdout pipe；exit 0 + 答案到 stdout

## 相關
- memory `reference_dual_cli_availability`（2026-05-20 更新）
- CLAUDE.md「AI CLI 可用性」段；commit `2774f26c`
