---
name: feedback_render_gate_static_prose_blindspot
description: "README render --check gates only prove the rendered block was produced by the renderer, not that its hardcoded sentences are true — audit static prose separately"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 400a6bfb-3077-482f-b055-f2eaf435fe75
  modified: 2026-08-02T09:41:07.963Z
---

實驗 README 的 `render_readme_results.py --check` 這類 drift gate，只證明「標記區塊 ==
renderer 當前輸出」，**不**證明區塊裡的句子為真。renderer 裡任何 hardcoded 字串會被
原樣渲染，`--check` 必然通過 —— gate 反而替一句假話背書。

K1814 實例：§8.2 寫死 "the ranking is unchanged"（指 lognormal 校正前後排序不變），
實際 6 個 best-DL-vs-baseline cell 中有 **2 個反轉**（h=1 vs HAR-L、h=5 vs HAR-RV），
且反轉方向都對 DL 有利 —— 等於在 gate 認證的區塊裡做選擇性回報。

**Why:** gate 的存在讓 reviewer 產生「這段已被驗過」的錯覺，靜態斷言因此比沒有 gate
時更不容易被抓到。

**How to apply:**
- 審查有 render gate 的實驗時，把 renderer 原始碼裡的 **string literal 斷言**單獨列出來
  逐條對 artifact 驗證；不要因為 `--check` 綠燈就跳過該區塊。
- 修法是讓 renderer **derive** 該斷言（算出來、數出來、命名例外），而不是改掉那句話 ——
  patch 一個實例，同 class 下次還會再犯。
- 同一輪要做 class sweep：把 renderer 裡其餘靜態斷言全查一遍再宣告完成，見
  [[feedback_declare_complete_requires_class_sweep]]。
- 標記區塊**外**的手打數字（K1814 的 §2/§3/§4）gate 完全不管，要另外從原始資料重算。
