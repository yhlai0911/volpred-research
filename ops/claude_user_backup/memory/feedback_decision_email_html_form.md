---
name: feedback-decision-email-html-form
description: 老闆需要 decision 時 email 給可點選選項降摩擦；但 radio/textarea/<form> 在 email 裡走不通，改用「每選項一個 mailto 連結」
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 0d843359-9bdd-4972-9273-6d56e72925e9
---

寄需要老闆做**判斷 / 決策 / 選項**的 email 時，body 要給**可一鍵點選的選項**降低摩擦，不寫「請回信 A/B/C/D」型純文字 prompt。**但實作方式不是 `<form>`/radio/textarea**（見下方 2026-07-02 更正）——用**每個選項各一個 `mailto:` 連結**，點下去自動 prefill 回信主旨+內文帶該選項。

**Why（原始訴求）**: 2026-07-01 14:22 boss email-12393：「以後你要我判斷或決策的話 應該直接給我 html 的選項/文字框之類的 引導我直接填寫就好」。純文字 A/B/C/D 需老闆手動 type、易誤打、增摩擦。核心是**低摩擦、可點選**，不是「一定要 form 元素」。

**🔴 2026-07-02 更正（email-12487 incident）**：老闆回報「你信件最後的 HTML 沒有正常渲染出來，我無法決策」。根因兩層，證明 `<form>`/radio/textarea 在 email 裡本質走不通：
1. **送信管線把 raw form HTML 逃逸成純文字** — `src/volpred/publisher/email_notifier.py::_try_markdown_to_html` 用 `MarkdownIt("commonmark", {"html": False})`，body 裡的 `<form>`/`<input>` 被轉義成字面 `&lt;form&gt;`，老闆看到一堆標籤文字。
2. **就算改 html=True，email client（Apple Mail / Gmail / Outlook）基於安全一律 strip 互動表單元素**（form/input/radio/textarea）。
→ radio/textarea 這條路無解。**唯一能同時「渲染出來 + 可點選 + 存活 client sanitization」的是 `<a href="mailto:...">` 連結**（標準 anchor，markdown link 語法 `[text](mailto:...)` 也 OK，`html=False` 照樣渲染）。

**How to apply（更正後 canonical）**:

1. **觸發時機**：任何 email 需要老闆 action / decision / preference 選擇（投稿路徑、期刊 shortlist、實驗方向 pivot、研究誠實 borderline、預算 approve、paper_decision memo）。不含純報告 / status update。

2. **正確作法 = 每選項一個 mailto 連結**（markdown link 語法，送信管線與 email client 都不會壞）：
   ```markdown
   ## 請選一項（點連結即自動 prefill 回信）

   | 選項 | 說明 |
   |---|---|
   | **A** | 停用自動更新（建議）… |
   | **B** | 搬 repo … |
   | **C** | 維持現狀 … |

   - [📧 選 A](mailto:yihao.lai@gmail.com?subject=Re:%20<主題>&body=%E6%88%91%E9%81%B8%20A%0A%E8%A3%9C%E5%85%85%EF%BC%9A)
   - [📧 選 B](mailto:yihao.lai@gmail.com?subject=Re:%20<主題>&body=%E6%88%91%E9%81%B8%20B%0A%E8%A3%9C%E5%85%85%EF%BC%9A)
   - [📧 選 C](mailto:yihao.lai@gmail.com?subject=Re:%20<主題>&body=%E6%88%91%E9%81%B8%20C%0A%E8%A3%9C%E5%85%85%EF%BC%9A)
   - [📧 其他（自由說明）](mailto:yihao.lai@gmail.com?subject=Re:%20<主題>&body=%E6%88%91%E7%9A%84%E6%8C%87%E7%A4%BA%EF%BC%9A)
   ```
   選項本體用 **markdown 表格 / 粗體 / 標題**呈現（`_try_markdown_to_html` 能正確渲染），每個 mailto 的 `body=` 用 URL-encode 預填該選項字串，老闆點下去信件已帶好答案、只要送出。

3. **禁止**：`<form>`、`<input type="radio">`、`<textarea>`、`<select>`、submit button —— 送信端逃逸 + client strip，必然破圖。

4. **強度**：**強制**。給選項降摩擦是老闆硬性要求；但用 form 元素 = 破圖 = 老闆無法決策 = 比純文字更糟。

**相關**：[[feedback_email_on_major_decisions]]（何時寄 decision email）+ [[project_repo_moved_out_of_desktop]]（本次 incident 的 TCC 根因脈絡）
