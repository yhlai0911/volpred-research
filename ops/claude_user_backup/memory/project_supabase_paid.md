---
name: project_supabase_paid
description: Supabase 已付費升級（2026-03-24），不再是免費方案限制
type: project
---

Supabase 已於 2026-03-24 付費升級。

**Why:** 免費方案 5GB egress + 500MB RAM 限制導致多次網站中斷（2026-03-23 504 超量、2026-03-24 RPC 超時）。

**How to apply:** 不再需要極度節省 Supabase 呼叫。可以：
- 正常使用 force-full sync
- 不需要 local-first 的 release-settings workaround（但保留作為 fallback）
- RLS 警告應該處理（安全性問題，與付費無關）
- 仍應避免不必要的大量查詢（好習慣）
