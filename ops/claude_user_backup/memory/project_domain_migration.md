---
name: project_domain_migration
description: 未來可能買新網域，記錄 SEO 遷移步驟和雙網域策略
type: project
---

用戶考慮購買自訂網域（取代 volpred.zeabur.app）。

**Why:** 自訂網域更專業、SEO 權重更好（非子網域）、品牌辨識度高。

**How to apply — 換網域時的 SEO 遷移步驟：**
1. 舊網域（volpred.zeabur.app）設定 **301 redirect** 到新網域 — 這是最關鍵的一步，保留 Google 排名
2. Google Search Console 加新網域並驗證
3. 全域替換 `volpred.zeabur.app` → 新網域：layout.tsx metadataBase、OG url、JSON-LD、sitemap
4. 更新 Umami Analytics 的 domain
5. 提交新 sitemap 到 Search Console
6. Zeabur 綁定新網域（custom domain 設定）

**雙網域策略（兩個都用）：**
- 可以。設定一個為**主網域（canonical）**，另一個 301 redirect 過去
- 或兩個都指向同一個 Zeabur 服務，但必須在 HTML 中用 `<link rel="canonical">` 指定主網域，否則 Google 會視為重複內容
- 建議：新網域當主域，zeabur.app 當備用（301 redirect）

**時間點：** 2026-04 可能購買新網域
