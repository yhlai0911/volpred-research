# Boss Blockers — 需要老闆協助 / 資源 的項目

**更新節奏**: 每 cycle 更新；item 一旦解決 / 用戶說過 → **立即移除**，不可殘留（2026-05-21 用戶糾正：已完成項目殘留在 boss_report email 第⑦區段）。
**只列真 blocker**: 我自己能做的、可自主的、有 fallback 的 — 一律不列。
**boss_report.py `_blockers()` 抓本檔進每 4h email 第 ⑦ 區段。**

---

## 目前無待老闆協助的真 blocker

2026-05-21 清查（用戶 audit 觸發）。原 P1-P3 六項全數關閉：

| 原項目 | 關閉原因 |
|---|---|
| P1.1 Claude-in-Chrome popup gate | 實測已不阻塞 — 本 session 用瀏覽器自動化成功發 2 篇 FB（mile_8d61b9b3 / mile_32eb397f），無 popup gate 規模化問題。 |
| P1.2 FB Page vs personal | 用戶已決定 personal、明示「不再 surface」。關閉。 |
| P2.3 Supabase service-role key | 已自查 `.env` key 為 service_role、寫權限正常。關閉。 |
| P2.4 寫作風格仲裁 | 可自主（Layer 4 narrative-arc dedup + anti-ai-style gate 已落地）；非 blocker。 |
| P3.5 NotebookLM quota | 可自主（≤10 notebook/≤50 source 不徵詢；sci-hub fallback）；非 blocker。 |
| P3.6 Codex CLI 連線 | 可自主（code-reviewer subagent fallback；agy 第三 reviewer 已驗證可用）；非 blocker。 |

---

## 新增 blocker 規範

真 blocker 才進此檔，且必須：(a) 我無法自主解、(b) 無 fallback、(c) 不解會卡 Mission。
解決後 **當 cycle 立即從本檔移除**（移到上方關閉表保留 audit trail），不等下次、不殘留。
