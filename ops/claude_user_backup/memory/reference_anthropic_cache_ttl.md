---
name: Anthropic Claude Code Cache TTL by Tier
description: Claude Code prompt cache TTL 依訂閱 tier 不同（Max=1h, Pro=5min, API=5min）— 影響 cron heartbeat 設計
type: reference
originSessionId: 91283b9e-7227-43f5-88bb-9d92168d243a
---
# Claude Code Prompt Cache TTL（依 tier）

## 事實（2026-04-26 經 Anthropic 官方文檔驗證）

| Tier | Cache TTL |
|---|---|
| Max（$100 Max 5x / $200 Max 20x） | **1 小時**（自動啟用，無需 beta header） |
| Pro | 5 分鐘 |
| API key 直連 | 5 分鐘（除非加 `prompt-caching-2024-07-31` beta header） |

用戶 yihao.lai@gmail.com 是 **Max $200/月（Max 20x）** 訂閱者 → 1h cache。

## 來源

- [Using Claude Code with your Pro or Max plan (Anthropic Support)](https://support.claude.com/en/articles/11145838-using-claude-code-with-your-pro-or-max-plan)
- [Prompt caching API docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [GitHub issue #46829 — Cache TTL silently regressed](https://github.com/anthropics/claude-code/issues/46829)

## 影響：cron heartbeat 設計

volpred-research 專案 `continue_task` session cron 設為 `*/30 * * * *`（嚴格每 30 分鐘等距 fire），**永遠落在 1h cache window 中央**，cache 命中率最佳。

設計過程教訓：
- 先試 `*/50 * * * *` 想對齊「每 50 分鐘」，但標準 cron 把 `*/50` 解析為 `minute=0,50`（每小時 :00 / :50 兩次，間隔 50 / 10 不等距）
- 60 不能被 50 整除，cron 表達不出真正等距 50 分鐘
- 改 `*/30 * * * *` 才是真正等距、真正符合 cache window 對齊邏輯

## 監控警示（important）

**這是政策不是合約。** 2026-03 初 Anthropic 曾悄悄把 default TTL 從 1h 降到 5min（issue #46829），雖然 Max 用戶當時保持 1h，但未發 changelog。已 schedule remote routine `cache-ttl-check-2026-05-26` (trig_01GRSZ8d5Kj2c7yQp4tXm2Vb) 在 2026-05-26 09:00 Asia/Taipei 重新驗證。

若未來發現 Max plan cache hit rate 異常掉，**立即懷疑 TTL 政策變動**：
1. 重新 fetch support article 11145838 確認當前 Max tier TTL
2. 查 GH issue #46829 最新狀態
3. 若 TTL 已降到 5min：`continue_task` cron 必須改回 ≤ 4 分鐘 heartbeat 才能在 cache 內，但實務上 5min 太短會爆 token；建議直接放棄 cache 對齊邏輯，恢復 `13 */4 * * *` 4h heartbeat 控制 token

## How to use

- 設計新 session cron / heartbeat 頻率時，以 1h cache TTL 為對齊基準（Max 用戶）
- 用戶若降級到 Pro，cron 邏輯整個失效，要重新評估
- API key 直連的 sub-script（非 Claude Code session）TTL 是 5min，不要套用 1h 假設
