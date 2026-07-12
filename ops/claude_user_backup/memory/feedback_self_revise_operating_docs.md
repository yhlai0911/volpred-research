---
name: feedback_self_revise_operating_docs
description: 老闆 standing directive — 運作指示文件（CLAUDE.md / skills / rules）要自我優化、自我修訂，不等老闆點名
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9548c778-d60c-43c8-b9c4-60631f360f5e
---

2026-07-13（Telegram msg 604）老闆指示：「自我優化 自我修訂運作指示文件」。

**Why:** 運作指示文件是 loop 的行為源碼。過去修訂只在踩坑後被動發生（error_log → 補一條 prose），文件越疊越厚、規則彼此矛盾或失效（path-trigger 沒 load、已機械化的 prose 沒縮成 pointer）。老闆要的是把「修訂指示文件」變成主動、週期性的職責，而不是事故驅動。

**How to apply:**
- Enforcement owner = `pdca-operations` skill 的 A（Act）階段 + 週期性 governance 任務 `governance_self_revise_operating_docs`（每週派工一次），**不新增第四層機制**（anti-stacking）。
- 每輪自我修訂做四件事：(1) 規則 vs 實際行為的 drift（規則寫了但沒在做 / 在做但沒寫）；(2) path-trigger 是否真的會在該階段 load（見 CLAUDE.md「Rule path-trigger 時序原則」）；(3) 已機械化的 prose 縮成一行 pointer；(4) 矛盾/重複規則合併。
- 修既有 skill 必寄 email 通知老闆（見 [[feedback_skill_autonomy]]）；新建 skill 可自主。
- 相關：[[feedback_proactive_result_level_operation]]、[[feedback_declare_complete_requires_class_sweep]]
