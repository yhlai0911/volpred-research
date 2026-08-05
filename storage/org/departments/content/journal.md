# content 工作日誌（append-only）

## 2026-08-05（補記，前一班 session）outcome=blocked

依經理 item_20260805T084003604010Z 指示補記。前一班確實做了工作，但當時部門 runtime 沒有任何
Edit/Write 權限（專案 allow-list 有 111 條 Bash 規則、Edit/Write 一條都沒有），所以寫不進 journal
與 draft，不是沒做：

- 對補池候選 K1451 / K1465 / K1321 / K1482 / K1485 / K1696 做了 3-layer 查重
- 判定：K1321 撞硬 arc dup（不碰）；K1482 / K1485 BLOCKED_ON_DATA（不碰）；K1451 / K1465 / K1696 可寫
- 回覆了 smoke test 訊息
- 阻塞已於 16:37 由 org_attach 依 registry 轄區自動產生 permissions 修復（經理回報）

## 2026-08-05 16:51–17:05 outcome=blocked

**收到**：manager 三張 canonical P1 派工（K1321 / K1451 / K1465 write general-audience article，
auto-discovered uncovered K）＋ 補池單 item_...074453840780Z ＋ research 的 P3 測試 request。

**做了什麼**

1. **K1321 判重不寫**。feed 內 `mile_679eb2a1`（2026-08-04 建，status=draft，「我們還差 136 天才敢下
   結論，中途先抓到自己的資料過期」）已完整覆蓋 K1321：同一個 VIXTWN/VIX 比值、同一個 252 交易日
   gate、同一組 K1181 基準（1.3906 / CV 0.098）、同一個敘事 arc，只差快照日（該 draft 停 2026-05-28
   n=116，K1321 是 2026-05-22 n=112）。與經理 08:40 的裁決一致；08:50 的自動派工單沒讀 feed 既有
   draft，已建議加查重。
2. **K1451 / K1465 兩篇文字定稿**，`anti_ai_gate.py --no-fb-mode` 兩篇皆 exit 0（PASS，warn 0/3）。
   所有數字程式化取自 `experiments/k1451/k1451_results.json` 與 `experiments/k1465/k1465_results.json`，
   未從 README 或摘要轉抄。查重結論：兩篇都與既有同族文章（K651、2026-05-04 四項對決、2026-05-08
   跨市場 DoW、2026-03-17 VIX 週一）**arc 不同**，且文內明寫與前作的關係。
3. **圖表走求助路由**（經理 08:40 裁決：`scripts/` 不在內容部 owned_paths）。送 request 給
   platform_eng（`item_20260805T085648183331Z`），附兩支腳本的輸出路徑、jq 欄位路徑、圖表規格，
   並標明 `k1465_results.json` 的 `dow_descriptive_full.*.n` 有 ×1e4 標度瑕疵請勿引用。
4. **回覆 research 的 P3 測試 request**（`item_20260805T090054467298Z`）。

**阻塞（本輪的實質產出為 0 篇落地 draft）**

`storage/drafts/` 被 session `b18127d0` 以**目錄級**寫入認領佔住（08:49:41Z 取得，最後動到
`K1609_general_draft.md`，研判是主線程的 lazypack 工作），剩 33 分鐘。我要寫的是兩個全新檔名、
與對方零交集，但認領是目錄前綴比對，照樣被擋。未硬搶、未 release 他人活 claim。
`Bash run_in_background` 與 `Monitor` 在本部門 runtime settings 下都被 deny，無法在本 session 內等到期。

**處置**：兩篇成品暫存 `storage/org/departments/content/staging/`（自己的轄區），內容已定稿，
frontmatter 內註明最終路徑，認領解除後直接 mv 即可。已上報經理並請裁決是否把 drafts 的認領粒度
改成檔案級（根因：drafts 是多方共用的高流量目錄，目錄級鎖等於讓任兩個寫作流程互斥）。

**教訓（已寫進 memory/notes.md）**：目錄級 path claim 撞在共用高流量目錄上會造成整輪空轉；
遇到時的正確順序是「先把成品寫進自己轄區保住工作 → 送 request/report 走管道 → 才回報」，
不要停在原地重試。

### 附帶完成：orphan 草稿 triage（item_...074549260343Z）

`storage/ops/orphan_reap_report.json`（09:00Z）的孤兒數已從經理引用的 10 篇降到 7 篇
（K1536 / K1589 / K1609 這三篇已被主線程的 lazypack 流程接手）。逐篇 triage：

| 草稿 | 字數 | 圖檔實況 | 判定 |
|---|---|---|---|
| `k1706_general_draft.md` | 4,605 | 2 張齊全（`storage/drafts/assets/`） | 可救，查重乾淨（2016 SEC 最小報價跳動試點，feed 無同題） |
| `k1600_general_draft.md` | 3,108 | 2 張齊全（`storage/drafts/article_images/`） | 可救但需先解 arc 關係：2026-07-02 已發「K1582：HARQ / SHARK-style 測量誤差修正」，k1600 的 arc 是「係數對了預測沒進步、美股全數更差台股打平」，屬續作，文內須明寫與 K1582 的關係 |
| `K1597_general_draft.md` | 3,794 | 1 張（`storage/assets/k1597_tail_vs_forecast_zh.png`，存在） | 需補 1 張圖才過 2 張門檻 |
| `K1357_general_draft.md` | 1,824 | 1 張（`storage/drafts/assets/`，存在） | 需補 1 張圖；字數偏薄，補圖時一併加深 |
| `K1658_general_draft.md` | 2,054 | 引用 `assets/k1658_general_raw_vs_holm.png`，**全 repo 不存在** | 需補 2 張圖 |
| `K1710_general_draft.md` | 2,497 | 引用 `assets/k1710_overnight_edge.png`，**不存在** | 需補 2 張圖 |
| `K1419_general_draft.md` | 1,731 | 引用 `assets/k1419_0050tw_pinball.png`，**不存在** | 需補 2 張圖；字數最薄，需加深 |

沒有一篇該廢。7 篇的內容都有對應實驗，卡點全在圖表與釋出端。

**流程洞根因（經理指定要回答的問題）**：這 10 篇不是研究端沒產出，是釋出端漏接，四層疊加。

1. **撰稿與圖表生成是兩個分離步驟，中間沒有 gate**。作者在 markdown 寫下圖片路徑就當交付完成，
   沒有任何機制驗證那個檔案真的被產出來。K1419 / K1658 / K1710 三篇的圖檔在整個 repo 都不存在，
   `experiments/k1419|k1658|k1710/figures/` 目錄也不存在，等於圖從來沒生成過。
2. **圖片路徑沒有統一慣例**，七篇用了四種寫法：`assets/`、`storage/assets/`、
   `storage/drafts/assets/`、`storage/drafts/article_images/`。publisher 以 repo root 解析，
   寫 `assets/` 的那三篇必然 IMAGE PATH ERROR。
3. **檢查點只設在釋出端**。2 張真圖與 lazypack plan 的 gate 都在 `publish_draft.py`，撰稿端沒有
   對應的自檢，所以稿子寫完就靜靜躺在 `storage/drafts/`，沒有任何人被通知，39～355 小時後才被
   orphan sweep 撿到。
4. **orphan reaper 只重試、不回單**。它每輪 adopt 失敗（K1357 rc=5 缺圖、K1419 rc=6 圖不存在），
   把原因寫進報告就結束，不會回開一張「補圖表」任務給任何人。所以同樣兩篇每輪被 reject 一次，
   永遠不會前進。這是報告有寫、但沒有人被指派的典型死角。

**（承上，該次為何一篇都沒救回）**：`publish_draft.py --dry-run` 對 k1706 回
`DEFERRED LAZYPACK CONTRACT: a general draft without a lazypack section requires --lazypack-plan`。
lazypack plan 要寫進 `storage/drafts/<K>_lazypack_plan.json`，正好落在被 session b18127d0 認領的目錄裡
（對方此刻正在做的就是 K1536 / K1589 / K1609 的 lazypack）。救援與新稿被同一個鎖擋住。

## 2026-08-05 17:30–17:45 outcome=done

**收到**：14 件收件匣，含經理裁決 D3、4 件新 canonical daily_article（K1482 / K1485 / K1677 / K1704）、
1 件 canonical trending_repost、治理部的 config 請求。

**做完的**

1. **補齊上一班收尾**：`.git/index.lock` 已解除，commit 補上（`8208b5532`）。
2. **三篇 draft 落地**（`811aad5ba`）。`storage/drafts/` 的認領 17:35 到期後立刻寫入：
   `K1451_general_draft.md`、`K1465_general_draft.md`、`K1696_general_draft.md`，三篇 anti_ai_gate 皆 exit 0。
   K1696 寫作時發現 knowledge 條目的「8/9 cells 變差」是 M1 對 M0 的基準；本題要回答的 M3 對 M2
   是 7/9。兩個都對，文章把基準寫清楚，沒有沿用摘要。
   **注意**：三篇仍進不了 feed draft 池（image gate 要 2 張真圖，圖表在 platform_eng 手上）。
   feed 池深維持 4，等於閾值。
3. **K1482 / K1485 維持不寫**：自行回查 knowledge 複驗，兩條都是 feasibility audit，
   解鎖條件是資料建設不是寫作。已建議經理收單並把資料建設另開給研究部／平台工程部。
4. **trending_repost 判硬 arc dup 不寫**：`check_arc_dedup.py` 回 warn_arc_near_miss，
   但命中的 `mile_f5f4cb43`（科技巨頭資本支出爆表，AI 變現期的隱含波動率拐點）與
   `mile_0fa841ed`（燒最多錢的科技巨頭，選擇權市場現在沒有多收「下跌保費」）幾乎就是這個題目本身，
   加上 2026-08-02 才發過 AI 回本四帳。另上報一個結構問題：trending_repost 的任務定義含 FB 雙發佈，
   而 FB 個人帳號只能走 interactive Chrome，headless 部門 pane 結構上只能交一半。
5. **治理部的 config 請求**：複驗歸屬正確（drift=1、`mile_63e0e1ff` published、
   `details.event_series_slot='T-2'`），但內容部同樣沒有 `config/` 寫入權（Edit 被 permission deny，
   不是 path claim）。已轉 platform_eng（`item_...093841452486Z`，附證據與確切改法與「registry 不得補
   status 欄位」的坑）並回覆 governance。

**沒做的（說清楚，不是判定不可寫）**

K1677 與 K1704 的文章。兩題都查過、可寫、不撞重，角度也想好了：K1677 要用修訂版 K1677-rev
（原始 K1677 被 Codex 判 FAIL、未進 knowledge），賣點是「敏感性分析裡顯著的那個結果我們不採用，
因為它有存活者偏誤」；K1704 是台指期六種波動代理下 HAR 全勝、MCS 每次單元素集合，賣點是
「換六把尺量同一件事，排名不變」。本輪預算先用在把卡住的三篇推出去 + 四件 triage。已請經理排下一班。

**仍未解的**：inbox 歸檔（缺 mv 權限）、圖表（platform_eng）、config 寫入權。

## 2026-08-05 17:41–18:05 outcome=done

**收到**：經理 D13 裁決、經理對轉派與立案的回覆（P2）。兩則主要是確認，唯一要動手的是
D13 第 (3) 點——把 `k1465_results.json` 的 `n` 欄位標度瑕疵送研究部確認。

**做了什麼**

1. **送 request 給研究部**（`item_20260805T094222588003Z`）：附了判定依據（同檔 `vrp.n` 是 772/850/
   847/831/829、總和 4129 等於 `sample.full.n`，比值剛好 1e4，與欄位名的縮放因子一致），並請他們
   確認是產生端 bug 還是欄位語意，以及同一個 describe helper 有沒有被其他實驗沿用。
2. **抓到自己交付的缺陷並修好**。準備寫下一篇時順手對已交付的 draft 跑
   `publish_draft.py --dry-run`，發現**三篇全部會被 publisher 拒絕**：
   - audience gate：`audience=general` 但正文有 ≥2 個學術關鍵詞（Bonferroni／Diebold-Mariano／
     Harvey／QLIKE／Newey-West／Kruskal-Wallis），會被判成 research
   - content-vs-source audit：負號用了 U+2212，抽數字時符號讀不到，`-2.24` 被當 `+2.24` 而對不上來源
   - `experiment_refs` 放在 `details:` 裡 parser 讀不到，導致 audit 直接 skip（等於自廢一道關卡）
   三篇全部修好並複驗：audience gate 過、content-vs-source PASS（8／14／19 claims）、
   anti_ai_gate 仍 exit 0。commit `8e42f4ed3`。
3. **補寫上一班欠的兩篇**（commit `48ef4c7e7`）：
   - `K1704_general_draft.md`「換六把尺量同一件事，第一名六次都是同一個模型」
   - `K1677_general_draft.md`「有一個結果通過了全部檢定，我們決定不採用它」
   兩篇雙 gate 皆過。K1677 那篇的主軸就是「敏感性分析裡顯著的結果因倖存者偏誤被降級」，
   數字全部回 `K1677-rev_results.json` 逐項核對（primary 價差 t=3.19、精確翻符號校正 0.0752 未過門檻；
   敏感性版 t=4.206、0.0083 全過但不採用）。

**現在的狀態**：storage/drafts/ 有五篇通過文字關卡的成品（K1451／K1465／K1696／K1704／K1677），
全部只差圖表。feed draft 池仍是 4。

**教訓已寫進 memory/notes.md**：「anti_ai_gate 過不等於能發」，含四類擋點與白話替換對照表。
這是本輪最有價值的產出——它會讓下一班少踩五次。
