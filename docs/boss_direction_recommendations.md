# Boss Direction Recommendations (我給老闆的方向建議)

**Updated**: 2026-07-18 (rolling — 我每 cycle 更新)
**目的**: 給老闆做平台方向決策用的當前建議，可隨時 ignore
**對帳**: 每個 roadmap item 綁一個 task id（行尾 `<!-- rid:… task:… -->`）。
`uv run python scripts/audit_roadmap_coverage.py` 會把它對到 `storage/next_tasks.json` 查真實 status；
`task:none` = 我還沒開工，會在報告裡顯示成 MISS 而不是靜靜躺在這裡。這份 doc 從此無法只靠文字宣稱進度。

---

## 1. 論文投稿優先序（自主排程，除非你改）

- **Paper 4** body_v4 rewrite — gate UNLOCKED via K1116c/f + K1201 + K1203 4-experiment. 先做最 unblock 的這一個。目標期刊：JBF 或 IJF。
- **Paper 2 §5 rewrite** (taiwan-vt) — K1204 synthesis materials ready (commit cf5188eb)，跨市場 §5 改寫；EAV universal-magnitude 是 spinoff。目標：JBF。
- **Paper 1 errata** (leverage-direction) — 15 no-source rows + 4 個新 K 實驗待補；不是 BLOCKER 但要排第 3 順位。
- **Paper 6** prg-periodic-garch / **Paper 10** crypto-fear-channel — 還在 outline/draft 階段，下一輪 cycle 再規劃。

## 2. 網站功能優先序（修正：先衝免費會員基數，不談付費）

**修正自前版**：先前列「付費 tier 入口」是 premature monetization — 還沒幾個會員就想收費 = 平台運營錯誤順序。先設**免費階段目標**，達標後再談收費。

### 免費階段目標（自主設定，會調整）
- **3 個月內**：註冊會員 ≥100、weekly active ≥40、回訪率 ≥30%
- **6 個月內**：註冊 ≥500、提問池 active ≥10/week、外部分享 ≥20/week

### 為達標需建的功能（按優先序）
- **P1**: Reader analytics（CTR / 停留時間 / 跳出率 / 回訪 cohort） — 沒這個我盲打文章品質 <!-- rid:reader-analytics task:growth_p1_reader_analytics -->
- **P1**: 登入/註冊 flow **已上線可用**（Google OAuth 走全站 header 的 AuthButton，`auth/callback` route + `handle_new_user` DB trigger 自動建 profile 都在；線上 `/auth/callback` 回 200、Supabase 公鑰已注入、`/me` 可用）→ 本項縮為 **welcome onboarding**（首登歡迎頁 / 引導 / welcome email，目前全缺）；完整盤點證據見 `docs/growth_auth_onboarding_status.md` <!-- rid:auth-onboarding task:growth_p1_auth_onboarding -->
- **P2**: 文章 share button + 社群 OG meta（Mission 5 曝光直接 lever） <!-- rid:share-og-meta task:none -->
- **P2**: Member dashboard 改版（提問 → 研究進度視覺化、增加回訪誘因） <!-- rid:member-dashboard task:none -->
- **P2**: Email subscription（weekly digest = 留客武器） <!-- rid:email-subscription task:none -->
- **P3**: 策略 sparkline 升級到 interactive chart <!-- rid:sparkline-interactive task:none -->
- **P3** 之後：付費 tier 入口（達到上面 6 個月目標再規劃） <!-- rid:paid-tier task:none -->

**逾期揭露（2026-07-18 自我盤點）**：上面這份清單原寫於 2026-06-22，附帶「我會自主寫
`docs/free_tier_growth_plan.md` spec，1-2 週上 P1 MVP」。26 天過去 — 該 spec 不存在，7 個項目在
task pool 內 0 覆蓋，而這份 doc 每 4 小時被原樣寄給老闆一次。這是老闆 email-12157 問
「這些任務有盤點與檢討嗎」的正確答案：**沒有**。兩個 P1 已於本次建 backing task；
4 個 P2/P3 誠實標 `task:none`（= 尚未開工，不是進行中）。

## 3. 開發中的結構性改善

- ✅ ops_dashboard.py — 7 區段健康儀表板（本 cycle 落地）
- ✅ live_verify gate — 發文後驗證 live URL（本 cycle 落地，agent a677637 完成）
- ✅ audit_publish_sync / audit_fb_pipeline — 兩個 standing audit script（本 cycle 落地）
- 🔄 Reader analytics ingestion — **更正**：先前寫「spec 撰寫中」但 spec 從未存在；實際狀態 = 未開工，已建 task <!-- rid:analytics-ingestion task:growth_p1_reader_analytics -->
- ⬜ Monetization funnel — **更正**：先前寫「規劃中」，實際 = 未開工，且依 §2 順序應排在免費階段目標達標之後 <!-- rid:monetization-funnel task:none -->
- 🟡 FB 個人帳號發文流程 — Page/Graph API 已永久撤回；保留 Claude-in-Chrome interactive path + 72h auto-expire/audit。

## 4. 需要你決策的策略性事項

只標出來，你不回我也會自主走。

- **目標期刊**：我預設 JBF（top-tier finance），如果你想往 RFS / JFE 衝需要拉高 contribution claim
- **FB 路線**：已決定 personal account only；Page/Graph API 不再作為 active 建議或 fallback。
- **付費 tier 命名與定價**：你 vs 我寫 mock-up（我可以做但市場價格判斷你比較知道）
- **策略上架節奏**：active 11 個都 healthy，是否擴張到 15-20 個 strategy universe

---

**這份 doc 我每 cycle 更新**。建議過時的會劃掉、新建議加上來。
