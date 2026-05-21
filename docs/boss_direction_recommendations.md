# Boss Direction Recommendations (我給老闆的方向建議)

**Updated**: 2026-05-19 (rolling — 我每 cycle 更新)
**目的**: 給老闆做平台方向決策用的當前建議，可隨時 ignore

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
- **🔴 P1**: Reader analytics（CTR / 停留時間 / 跳出率 / 回訪 cohort） — 沒這個我盲打文章品質
- **🔴 P1**: 註冊 / 登入 flow（如果還沒）+ welcome onboarding
- **🟡 P2**: 文章 share button + 社群 OG meta（Mission 5 曝光直接 lever）
- **🟡 P2**: Member dashboard 改版（提問 → 研究進度視覺化、增加回訪誘因）
- **🟡 P2**: Email subscription（weekly digest = 留客武器）
- **🟢 P3**: 策略 sparkline 升級到 interactive chart
- **🟢 P3 之後**：付費 tier 入口（達到上面 6 個月目標再規劃）

我會自主寫 `docs/free_tier_growth_plan.md` spec，1-2 週上 P1 MVP。

## 3. 開發中的結構性改善

- ✅ ops_dashboard.py — 7 區段健康儀表板（本 cycle 落地）
- ✅ live_verify gate — 發文後驗證 live URL（本 cycle 落地，agent a677637 完成）
- ✅ audit_publish_sync / audit_fb_pipeline — 兩個 standing audit script（本 cycle 落地）
- 🔄 Reader analytics ingestion — spec 撰寫中
- 🔄 Monetization funnel — 規劃中
- 🟡 FB MCP ext bug 短期繞 Playwright（cookie injection 已 work），長期需 escalate Anthropic OR FB Page + Graph API

## 4. 需要你決策的策略性事項

只標出來，你不回我也會自主走。

- **目標期刊**：我預設 JBF（top-tier finance），如果你想往 RFS / JFE 衝需要拉高 contribution claim
- **FB 路線**：personal account（現況）vs Page（可用 Graph API 自動發）
- **付費 tier 命名與定價**：你 vs 我寫 mock-up（我可以做但市場價格判斷你比較知道）
- **策略上架節奏**：active 11 個都 healthy，是否擴張到 15-20 個 strategy universe

---

**這份 doc 我每 cycle 更新**。建議過時的會劃掉、新建議加上來。
