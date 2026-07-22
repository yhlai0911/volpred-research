# 2026 Q3 companion archive — general-audience brief contract

## 2026-07-22 — General article brief 沒有 provenance/display 邊界，補池成功卻永遠補不到 general lane

**現象**：`K1597_article_general` 明確為「no general article in feed.json」的 publish-drought
remediation。交付稿的數字已逐項對齊實驗、anti-AI gate 通過，但 reader-visible 正文放了 K1597，
同時使用 QLIKE、Diebold-Mariano、Harvey 等詞；canonical `_infer_audience` 因而回傳 `research`。
若照舊發佈，task receipt 會看似成功，general coverage 仍是零，refill 下輪再生同類任務。

**根因層級**：上游 brief / governance contract 衝突，不是 writer 品質，也不是 audience gate
過嚴。全域發文 checklist 要求文末標 K 編號與統計方法；general 分流規則則禁 K 編號與裸術語。
`refill_task_pool.py` 與 `task_generator_v2.py` 只寫「write general-audience article」，沒有說明
哪條優先，也沒有把可驗證 provenance 與 reader-visible prose 分成兩個 channel。writer 忠實遵守
前者就必然觸發 gate；放寬 `_infer_audience` 或加 type exemption 反而會重開 research 偽裝成 general
的舊事故。

**根因修復**：保留並信任 audience gate。新增單一 owner
`volpred.ops.article_brief.GENERAL_AUDIENCE_BRIEF_CONTRACT`，讓兩個 auto task generator 共用
同一條交付契約：精確數字、樣本、視窗、as-of、資料來源與統計強度全部保留並用白話呈現；K-id
與實驗路徑只放 frontmatter / `details.experiment_refs` / `evidence_source_paths`，不放標題正文；
完成前以最終 title/body/tags 回讀 publisher inference，只有 `general` 才能成功。publishing rule 與
feed-publisher skill 另補 research-only 適用範圍，消除同一份規範內的歧義。

**驗證**：K1597 原稿重放可見 inference=`research`，證實症狀；refill 與 legacy generator 的
regression 皆斷言新 brief 帶 metadata boundary 與 inference postcondition，並重跑 audience inference
及 publish-draft fail-fast tests。狀態：**root_cause_fixed_and_verified**。
