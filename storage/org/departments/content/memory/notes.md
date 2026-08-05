# content 部門私有記憶

## storage/drafts/ 是目錄級 path claim 的高風險區（2026-08-05）

`scripts/hooks/write_claim_guard.py` 的認領是**目錄前綴比對**。主線程做 lazypack / 圖表工作時會
claim 整個 `storage/drafts/`，此時內容部即使寫的是全新檔名也一律被擋，且 claim 有效期 45 分鐘。

**被擋時的正確順序**（2026-08-05 實際踩到，整輪 0 篇落地）：

1. 先把已完成的稿件寫進自己的轄區 `storage/org/departments/content/staging/`，保住工作，
   frontmatter 加 `staging_note` 註明最終路徑
2. 該送的 request（圖表 → platform_eng）照送，不因為主檔卡住就一起停
3. 送 report 給經理，附證據（持有者 session id、取得時間、剩餘分鐘）與建議選項
4. 才在視窗回報

**不要做**：`VOLPRED_ALLOW_CONCURRENT_WRITE=1` 硬搶、release 別人的活 claim、原地重試等到期。
`Bash run_in_background` 與 `Monitor` 在部門 runtime settings 下被 deny，無法在 session 內等。

## 自動派工的 uncovered K 清單不查 feed 既有 draft（2026-08-05）

`auto-discovered uncovered K` 產生的 canonical 任務只看 K 有沒有對應文章 id，**不看 feed 裡是否
已有涵蓋同一 K 的 draft**。K1321 因此被重複派工（feed 內 `mile_679eb2a1` 早已完整覆蓋）。
收到這類單一律先做 feed 查重再動筆，撞重就回報經理收單，不要硬寫。

## 查重的判準是 arc 不是關鍵字（2026-08-05 套用實例）

- K1451 與 K651、2026-05-04「四項另類風向標對決 VIX」同主題但**可寫**：前作 arc 是「候選指標沒用」，
  K1451 的 arc 是「訊號真的存在但被 VIX 吸收到只剩 3.7%」，punchline 與數字都是新的
- K1465 與 2026-05-08 跨市場 DoW、2026-03-17 VIX 週一效應同主題但**可寫**：新 arc 是
  「原料端（隔夜／盤中）有星期結構，成品端（VRP）沒有」
- K1321 與 `mile_679eb2a1` **不可寫**：同資料、同 gate、同基準、同 arc，只差快照日

寫這類「同族但不同 arc」的文章時，文內要明寫與前作的關係，讓讀者看得出是續作不是回鍋。

## 讀者文章的固定作法

- 數字一律從 `experiments/<id>/<id>_results.json` 程式化取得，不從 README／agent 摘要轉抄
- 平均值與中位數一起看（K1465 的星期一隔夜波動：平均 0.7206 冠全場，中位數 0.0927 卻低於星期五
  的 0.0933，差距全來自少數極端日）。只報平均會寫出誤導讀者的結論
- results.json 本身可能有欄位瑕疵（K1465 的 `dow_descriptive_full.*.n` 被放大 1e4），引用前先對總和
- 稿子完成必跑 `uv run python scripts/anti_ai_gate.py --file <draft> --no-fb-mode`，exit 0 才算完
- 圖表腳本在 `scripts/`，**不在內容部 owned_paths**，一律 request platform_eng 代寫，
  draft 內留 placeholder ＋ `chart_status: pending_platform_eng`，圖表到齊前不進 feed-publisher
