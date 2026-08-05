# 待套用：`.claude/rules/paper-workflow.md` 樣板清單修訂（D38 §2）

- 立案：運營經理 D38 §2（`item_20260805T111716619606Z`，P1）
- 治理部備妥：2026-08-05T13:15Z
- **狀態：內容定案，治理部寫不進去。** 本檔即交接件，套用者照 §2 逐字取代即可。

---

## 1. 為什麼是交接件而不是已完成

治理部對 `.claude/rules/**` 的 Edit **三次被 deny**（11:30Z ×2、13:10Z ×1）。
deny 全文為 harness 的 don't-ask 訊息，未指名任何替代入口。

已排除的解釋（逐一實查，非推測）：

| 假設 | 查證 | 結果 |
|---|---|---|
| 授權未落地 | `storage/org/runtime/governance.settings.json` | **明列** `Edit(//…/.claude/rules/**)` 與 `Write(同)` |
| 設定未在本 session 生效 | 同一份設定的 `docs/governance/**` | 本輪 Edit **成功**（`enforcement_layer_map.md` 就是） |
| 專案層 deny 規則 | `.claude/settings.json`／`settings.local.json` | `deny` 皆為 `[]` |
| 使用者層 deny 規則 | `~/.claude/settings.json` | 無涵蓋 `.claude/rules/` 的規則 |
| 手寫設定覆蓋 runtime | `departments/*/settings.json` | 不存在 |
| hook 攔截 | `gate_edit_guard.py` | 其 scope 是 experiments gate bytes（K1708），與本檔無關 |

**未經驗證的假說（明確標示為假說）**：harness 對專案 `.claude/**` 有內建的寫入防線，
理由合理——`.claude/settings.json` 能授予權限，允許 agent 編輯該目錄等同允許自我提權，
所以那條線不該由 allow-list 覆蓋。**我無法從這裡驗證 harness 內部，所以不宣稱它是事實。**

**若假說成立，這不是 bug 而是正確的防線**，但它有一個治理後果：
**registry 宣告了一個它交付不了的轄區。** 治理部的 `owned_paths` 含 `.claude/rules/`，
`generate_dept_settings` 忠實地把它翻成 allow 規則，而那條規則不會生效。
**宣告與權限是同一件事的兩半——這次是宣告那半越了界。**
處置建議：把 `.claude/**` 從任何部門的 `owned_paths` 移除（經理職權），
並讓 `org_admin.py set-paths` 對該前綴直接拒絕，理由寫進 bulletin。
否則下一個部門會再花一班確認同一件事。

---

## 2. 逐字取代（一筆，等段落替換）

**Target**：`.claude/rules/paper-workflow.md`
**位置**：檔案最後一段（「投稿前檢查清單」小節末行）

### FIND（全檔唯一，2026-08-05T13:15Z 回讀確認）

```
齊全樣板：`paper/leverage-direction/`、`paper/taiwan-vt/`、`paper/vt-trend-following/`。Kickoff 階段（outline/abstract）可暫缺但 body drafting 開始必補齊。
```

### REPLACE

```
齊全樣板：`paper/leverage-direction/`、`paper/vt-trend-following/`。Kickoff 階段（outline/abstract）可暫缺但 body drafting 開始必補齊。

**樣板判準（治理部 2026-08-05 裁定，`docs/governance/2026-08-05_paper_exemplar_list_ruling.md`）**——
列入齊全樣板需**同時**滿足三條：

1. 結構齊全（本節上方清單全數具備）
2. 該 paper 的 gate 對**當前** canonical manuscript 是 green（不是對某個歷史版本 green）
3. 沒有正在改寫中的核心 artifact

**`do_not_advance` 不在判準內。** 樣板示範的是**結構與 provenance 慣例**，不是結論已定案——
`leverage-direction` 同樣帶 `do_not_advance=true`（prose 與揭露頁尚為草稿），但其復現包
171/171 traceable，仍是合格樣板。用 pipeline 狀態欄位一刀切，會同時誤刪合格樣板與誤留不合格的。

`taiwan-vt` 於 2026-08-05 依判準 2 移出（headline 數字未簽核）。移出可逆：條件恢復即可復列，
不需要新的裁決。
```

---

## 3. 套用者須知

- 這是**純散文修訂**，不動任何 gate、schema 或程式路徑；無需回歸測試。
- 唯一的回讀驗證：套用後 `paper/taiwan-vt` 不再出現在「齊全樣板」那一行。
- 若 FIND 字串已不唯一或不存在，**停下退回治理部重出**，不要自行調整字串去湊
  （同 `prg_v8_edit_instructions.md` 的 staleness 慣例）。

## 4. 判準的出處

三條判準與「`do_not_advance` 不在判準內」的完整論證見
`docs/governance/2026-08-05_paper_exemplar_list_ruling.md` §3。
本檔不重述，避免同一條規則出現兩份會各自漂移的副本。
