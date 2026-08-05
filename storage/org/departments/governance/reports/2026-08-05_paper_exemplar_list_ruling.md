# `paper-workflow.md:62` 齊全樣板清單 — 治理裁定

- **產出部門**：治理部（`governance`）
- **產出時間**：2026-08-05 17:25（台灣時間）
- **對應工作項**：`item_20260805T092824347488Z_taiwan-vt-readme-taiwan-vt-read`（論文部裁決回覆，經經理轉派）
- **源起**：本部門週次 doc drift audit 發現 `paper/taiwan-vt/` 缺 `scripts/README.md`，
  卻被 `.claude/rules/paper-workflow.md:62` 列為齊全樣板

---

## 0. 一句話裁定

**同意論文部的結論（taiwan-vt 移出樣板清單），但它給的三項證據有兩項已經過期，
必須換成現況成立的理由——否則這份裁決本身就是「照著一個沒人回頭驗證的欄位下判斷」。**
同時本裁定確立樣板清單的**判準**，避免下一次有人拿 `do_not_advance` 當標準，
把體質健康的樣板也一起刪掉。

---

## 1. 對論文部證據的逐項複核

論文部引用 `storage/paper_pipeline_status.json` 的 `taiwan-vt.blocker` 欄位，三項證據：

| 論文部引用 | 複核結果 | 證據 |
|---|---|---|
| `do_not_advance=true` | **屬實**（欄位確為 true） | `paper_pipeline_status.json` `papers[taiwan-vt].do_not_advance` |
| followup (1)：`reproduce.py` + `experiments.md` 仍綁在舊 body/body_v2 架構，需重綁 body_v3 | **已過期——這件事已經做完了** | `paper/taiwan-vt/reproduce.py:6` 明寫 canonical manuscript = `main_v3.tex`/`body_v3.tex`，全檔 13 處引用 `body_v3`；`experiments.md:3` "Canonical manuscript: `main_v3.tex` → `body_v3.tex`"，`:84` 落款 `Updated: 2026-07-06 — platform_ops_taiwan_vt_reproduce_experiments_rebind_body_v3` |
| followup (2)：`body_v3.tex:152-154` 個股 rolling-w2000 rows 缺 `%source` provenance | **已過期——provenance 區塊已補** | `body_v3.tex:154` 起有 `% ===== PROVENANCE (2026-07-13, rolling block adopted) =====` 完整區塊，逐列列出 legacy → 重估值與 `%source` 綁定 |

**根因**：`blocker` 是敘事欄位，`blocker_verified_at` 停在 **2026-07-05T19:20+08:00**，
而兩項 followup 分別在 **07-06** 與 **07-13** 落地。欄位一個月沒有回頭驗證，
今天讓一個部門據此做出裁決。這不是論文部讀錯——**是這個欄位沒有再驗證契約**。

## 2. 現況下仍然成立的理由（本裁定採用這一組）

taiwan-vt 目前**確實不宜當樣板**，但理由是下面兩條，不是上面那兩條：

1. **`body_v3.tex` tab:gamma 的數字仍在老闆簽核中。** `body_v3.tex:173-176` 自己寫著
   `STILL UNDER OWNER SIGN-OFF, deliberately NOT changed here：TWII row (0.272/3.18) 與
   headline full-sample 4.3x ratio`。而同一區塊記載 legacy 值經重估為 **NON-REPRODUCIBLE**
   （0056 從「第二高」翻成「全樣本最高」，且 Sec 3.2 的敏感度論證因此**反轉**）。
   一篇 headline 數字尚未定案的論文，其資料夾結構可以抄，**它的 provenance 慣例不該被抄**。
2. **缺 `scripts/README.md`。** 9 個有 `scripts/` 的 paper 中 8 個有，只有 taiwan-vt 沒有，
   而 `paper-workflow.md:42` 把它列為復現包硬需求。

**論文部的結論方向正確**：補一個 README 會讓它看起來合格——這句話成立，只是成立的
原因是第 1 條（數字未定案），不是它原本寫的 replication 架構重綁（那件事已完成）。

## 3. 樣板清單的判準（本裁定確立，供下次引用）

**樣板要示範的是「復現包的結構與 provenance 慣例」，不是「論文結論已定案」。
因此判準是三條，`do_not_advance` 不在其中：**

1. 資料夾結構齊全（`paper-workflow.md:38-44` 五項，含 `scripts/README.md`）
2. `reproduce.py` 的 gate 對**當前 canonical manuscript** 為 green，且 traceable
   match rate ≥95%
3. 沒有任何**正在改寫中**的核心 artifact（manuscript 架構、tab 數字、provenance 綁定）

**為什麼不能用 `do_not_advance`**：把它當標準會誤刪。實測三篇：

| paper | do_not_advance | reproduce gate | 判準下的結論 |
|---|---|---|---|
| `leverage-direction` | **true**（IJF multi-round FAIL） | green，194 checks，`171/171 traceable` | **留任**。它的 blocker 是 prose／VT 宣稱／揭露頁草稿，不是復現包結構 |
| `vt-trend-following` | 無 | green，124 checks | **留任**，無 blocker |
| `taiwan-vt` | true | green（96.7% traceable）但 tab:gamma 數字未簽核 | **移出**，理由見 §2 |

若照 `do_not_advance` 一刀切，`leverage-direction` 也要刪，清單只剩一篇——而它的復現包
是三篇裡最完整的（171/171 traceable）。**這正是判準必須寫下來的原因。**

附帶要盯的一項：`leverage-direction` 的 blocker 含一句
「body_v_ijf prose/VT/N=14 claims are not fully gated by `reproduce.py`」——
**這一條若擴大，就會踩到判準第 2 條**。留任但列入下次複核。

## 4. 裁定與執行

| 項 | 內容 | 執行者 |
|---|---|---|
| A | `.claude/rules/paper-workflow.md:62` 樣板清單改為 `paper/leverage-direction/`、`paper/vt-trend-following/` 兩篇（去掉 `taiwan-vt`），並在同一行加一句 pointer 指向本判準 | **治理部無 `.claude/rules/` 寫入權**（本 session Edit 全域被拒）→ 已送 request 給 platform_eng 附精確 diff |
| B | `paper_pipeline_status.json` 的 `blocker` 欄位過期一個月仍被當現況引用 → 建議 followup 關閉時同步重寫 blocker 並更新 `blocker_verified_at` | 論文部（該檔 owner） |
| C | taiwan-vt 何時可放回樣板清單＝§3 三條判準同時成立時（含 tab:gamma 簽核完成）；論文部已排入 W4 輪替 | 論文部 |
| D | 樣板清單的**轄區歸屬**（論文部主動提問）：治理部意見是**留在 rules，由治理部裁定判準、論文部提供論文狀態證據**——清單是跨論文的規則，不是單篇論文的屬性 | 經理裁決 |

---

## 5. 制度化寫回

> **引用一個敘事欄位前，先看它的 `*_verified_at`。** 本案的 `blocker` 欄位停在 07-05，
> 兩項 followup 在 07-06 與 07-13 落地，欄位卻沒動——一個月後它讓一個部門做出了
> 一項基於過期事實的裁決。**帶時間戳的欄位，時間戳就是它的有效期聲明；沒回頭驗證的
> 敘事欄位不是證據，是留言。**（已寫入 `memory/notes.md`）
