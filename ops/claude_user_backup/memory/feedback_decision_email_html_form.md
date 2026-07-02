---
name: feedback-decision-email-html-form
description: 老闆需要 decision / 判斷時，email 直接給 HTML 選項/文字框引導填寫，不寫純文字 A/B/C/D + 「回信」型 prompt
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 0d843359-9bdd-4972-9273-6d56e72925e9
---

寄需要老闆做**判斷 / 決策 / 選項**的 email 時，body 直接嵌入可點選 HTML form（radio buttons / dropdown / textarea），不寫「請回信 A/B/C/D」型純文字 prompt。

**Why**: 2026-07-01 14:22 boss email-12393 回覆 leverage-direction decision memo 時明說：「以後你要我判斷或決策的話 應該直接給我 html 的選項/文字框之類的 引導我直接填寫就好」。純文字 A/B/C/D + 「請回信 X」需要老闆手動 type 回信、易誤打、增摩擦。HTML form 一鍵選一鍵送、降 friction、加快 turnaround。

**How to apply**:

1. **觸發時機**：任何 email 需要老闆 action / decision / preference 選擇
   - 例：投稿路徑 A/B/C/D、期刊 shortlist 排序、實驗方向 pivot、研究誠實 borderline case、預算/採購 approve 
   - 例：paper_decision / owner_decision_pending 類 task 產出的 memo
   - 不含：報告 / 通知 / status update / 一般 progress 郵件（那些用純文字即可）

2. **HTML form 元素**（VolPred email template 支援）：
   - **Radio buttons**：≤5 options 的 exclusive choice（A/B/C/D + 補充 textarea）
   - **Dropdown**：≥6 options 的 exclusive choice（如 10 期刊 shortlist）
   - **Checkboxes**：可複選（multi-select）
   - **Textarea**：自由文字補充 / 額外指示
   - **Submit button** → `mailto:yihao.lai@gmail.com?subject=...&body=...` 或 form action pre-fill 回信

3. **Volpred send-alert HTML markup pattern**：
   ```html
   <form>
     <p><b>選項</b>：</p>
     <label><input type="radio" name="choice" value="A"> A. Reframe → JBF R&R</label><br>
     <label><input type="radio" name="choice" value="B"> B. Downshift → FRL/IJF （建議）</label><br>
     ...
     <p><b>補充</b>：</p>
     <textarea name="notes" rows="3" cols="50" placeholder="可空"></textarea>
     <p><a href="mailto:yihao.lai@gmail.com?subject=Re:%20[原 subject]&body=選：%20%0A補充：%20">📧 一鍵回信</a></p>
   </form>
   ```
   （note: email client 不執行 form submit action，但 mailto: link 可 prefill reply → 效果等同）

4. **Fallback / degradation**：email client 不 render HTML form 元素時，附純文字 backup（「若無法顯示 form，請回信寫：選：X / 補充：Y」）— HTML form 是 primary UX，純文字是 fallback

5. **強度**：**強制**。violation = 老闆需要多打字 = friction 累積 = 未來決策拖延 = 平台運營流速下降

**相關**：[[feedback_email_on_major_decisions]] （何時該寄 decision email） + [[reference_email_html_shell]] （send-alert 已自動 markdown→HTML 包裝，但 form element 需明確 `<form>` `<input>` `<textarea>` markup）
