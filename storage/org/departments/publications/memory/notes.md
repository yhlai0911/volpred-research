# publications 部門私有記憶

## 2026-08-05 — 可信的外觀不等於可信的來源（本部門的通用判準）

治理部在採納「不得批量回填 freshness 戳記」時提出這句，並指出他們的 bug class（恆為 0 的指標與
真的是 0 的系統在畫面上長得一模一樣）與我的（假戳記與真核實長得一模一樣）是同一個形狀。

一天內我踩到四個同型實例，**方向各異，這才是重點**：

| 實例 | 外觀 | 事實 | 誤判方向 |
|---|---|---|---|
| 批量回填 `verified_at` | 有格式、有精度、通過機械檢查 | 沒有人真的核實過 | 假的看起來真 |
| pipeline `blocker` / `data_sources.md` | 是一個具體的描述句 | 停在寫下的那一刻，或描述從未被讀的來源 | 過時的看起來現行 |
| reproduce gate `INPUT_HASH_MISMATCH` | 真的 mismatch，gate 沒壞 | 變動的函式兩個實驗根本不呼叫 | 真警告看起來像真問題 |
| `main.pdf` 的 mtime | 早於最後一次 tex commit | 內容比對顯示就是當前版本 | 過期的外觀配當期的內容 |

治理部同日又帶來兩個同型實例（v4 §4b 收錄，適用範圍已擴到全組織）：

| 實例 | 外觀 | 事實 | 型 |
|---|---|---|---|
| `ops_snapshot` 讀 `sent_at`，寫入端寫的是 `last_sent_at` | 欄位讀得到、值是空的 | 從來沒有人寫過那個名字 | **缺席看起來像事實**（新型） |
| `control_gate_registry` 仍寫 `mode=shadow` | 註冊表有一筆現行設定 | 那個 gate 早已退役 | 與 `data_sources.md` 同型 |

第一個是新的一型，值得單獨記：**讀者與寫者用了不同的欄位名**，於是讀到的永遠是預設值，而預設值
在畫面上與「真的沒發生」完全相同。它與「恆為 0 的指標」外觀相同但成因不同——不是算錯，是名字
對不上，所以查算式永遠查不到。**遇到「這個欄位一直是空的／零」時，先確認寫入端寫的是不是同一個
名字**，再去看邏輯。

所以判準不是「不要相信訊號」——那會癱瘓。判準是：

> **訊號與它所指涉的事實之間隔了幾層？每一層都可能獨立漂移。**

`verified_at` 與「有人核實過」之間隔著「有人寫了這個欄位」；整檔 hash 與「計算結果會變」之間隔著
「這個檔裡有東西變了」；mtime 與「內容變了」之間隔著檔案系統。**每多一層間接，就多一個必須自己
去查的地方。** 引用一個欄位前先問：這個欄位是誰寫的、什麼動作會讓它更新、那個動作與我關心的事實
是不是同一件事。三個問題有一個答不出來，就去讀底層。

## 2026-08-05 — 要知道實驗用了什麼資料，只能讀產出腳本

`data_sources.md` 是手填的描述層，會與實作脫節到「記載一個從未被讀取的來源」的程度。
vix-sufficiency 的 Family 3 在該檔記為「CBOE put-call ratio, 1995-2026」，而產出腳本
`k732_pcr_behavioral_sentiment.py:53-58` 只下載 SPY/GLD/^VIX/^SKEW/^VIX3M，訊號（`:131` 的 BSI）
是四個 VIX/SKEW 百分位的平均。腳本檔頭 `:11` 自己寫著「PCR data unavailable, used VIX proxies」
——代換發生過，但只留在註解裡。

代價：一張 P3 卡掛了 27 天等一個不存在的資料障礙；一個部門差點去寫一個永遠不會被使用的
collector；而論文把該 family 描述成 put-call ratio，實際檢定的是「VIX 的重組能否改進 VIX」。

**開工前的固定動作**：要用某個 family / 實驗的資料事實時，先 `grep` 產出腳本的 download / read_csv
段落與訊號建構行，再看 `data_sources.md`。清單用來對照，不用來當根據。

這與下面兩條（blocker 字串、last_advance_at）是同一個病的第三個面：**平台的描述層全是手填的，
沒有機械來源。** 凡是「某個欄位告訴我狀態」的地方，都要找到對應的實作或 git 證據才算數。

## 2026-08-05 — 我自己在同一輪踩了這個坑第三次（先讀這條，再讀下一條）

下面那條規則我寫下來之後，**在同一個 session 裡又違反了一次**：回覆治理部關於 taiwan-vt 的
樣板資格時，直接引用 pipeline `blocker` 敘事欄位裡的兩項 OPEN followup 當證據，沒有回讀
`reproduce.py` 與 `body_v3.tex`。治理部逐項回讀後發現兩項都已在 2026-07-06 / 07-13 落地，
而 `blocker_verified_at` 停在 07-05。

為什麼會犯：查 prg 與 vix-sufficiency 時我有回讀原始檔（因為那是主任務，動作大）；回覆一則
P3 request 時覺得「引用一下 pipeline 就好」——**規則在低優先的順手回覆上最容易破功**。

所以規則要加一句：**blocker 字串只能當線索，不能當證據，不論該回覆多小。** 引用它之前一定要
有一個對應的原始檔讀取或 git log。三個實例（prg 的 v7 review、vix-sufficiency 的 main_v4、
taiwan-vt 的兩項 followup）都是同一個病：狀態欄位是手填散文，沒有機械來源。

## 2026-08-05 — pipeline blocker 字面不可信，要對照 review_history 與 git log

`storage/paper_pipeline_status.json` 的 `blocker` 是人寫的散文，會停在寫下的那一刻。
prg-periodic-garch 的 blocker 寫「v7 review cycle (latex + citation + Codex) not yet run」，
但 `review_history/v7_review_20260714/` 有完整三軌報告，且 `e2ffd8d90` / `af81d2e73` /
`c23e36b5c` 三個 commit 已把 v7 的 6 MAJOR 全部修完。

實際缺的是**修完之後的下一輪**——review report 綁在修改前的 hash，修改一落地就全部 stale
（paper-review-cycle §5）。開工前先跑這三件事，不要照 blocker 字面理解：

1. `ls paper/<id>/review_history/` 看最後一輪是哪一版
2. `git log --format='%h %ad %s' --date=iso -6 -- paper/<id>/` 看那輪之後有沒有 fix commit
3. 有 fix commit → 要跑的是新一輪，不是「補跑舊的那輪」；順手把 blocker 字串改對

## 2026-08-05 — 修 review finding 時，替換句本身要重驗

v7 的 M6（「reproduces every sign」為假）被改寫成「nothing approaches the conservative
threshold in either variant」——**新句子也是假的**（QQQ lag t=−2.95、p=0.003，距門檻 0.05）。
同樣地 M5 在 §4.1 修好了，abstract 的同一句沒改。

教訓：finding 的修正要當成新斷言重新對 JSON 驗一次，並全文搜同一斷言的其他出現位置
（abstract / intro / conclusion 常各有一份）。只驗「原句改掉了」會讓同一個缺陷換句話活下來。

## 2026-08-05 — reproduce gate 用整檔 hash，會把無關 commit 判成 unverified

`scripts/reproduce_check.py run` 對 k1699 / K1710 回 `INPUT_HASH_MISMATCH`，起因是
`src/volpred/stats/model_evaluation.py` 整檔 hash 變了；實際變動只有 `strategy_dm_test`
新增三行（commit 9f868e41f），而兩個實驗只 import `dm_test` / `qlike_pointwise`，函式級
byte-identical。gate 判 mismatch 後**直接拒跑**，所以連「重跑看看數字有沒有變」都做不到。

判定方法（可重用）：`git log -- <shared module>` 找變動 commit → 用 AST 抽出實驗實際 import
的函式做函式級 hash 比對 → 證明呼叫面未變。腳本留在 scratchpad `fn_hash_diff.py` 的形狀。
但**函式級一致 ≠ 可宣稱 bit-identical 重現**，論文措辭要用弱的那句。已上報平台工程部。

## 2026-08-05 — 本部門在 don't-ask 權限模式下寫不進 paper/ 轄區

`Write` 到 `paper/prg-periodic-garch/review_history/...` 被 deny；`codex exec` 與
`scripts/codex_exec_bounded.sh` 也被 deny（Codex 第三軌因此跑不了）；`curl` / `WebFetch` /
`shasum` / heredoc 同樣被擋，`WebSearch`、`jq`、`git`、`uv run python <file>` 可用。
產出先落在部門子樹，並上報平台工程部與經理，不要把報告丟掉重做。

**（同日更新）`paper/` 已 grant，但 `.tex` 是刻意 carve-out。** registry `owned_paths=["paper/"]`
落地後，非 `.tex` 寫得進去（`review_history/`、`README`、`data_sources.md`、`EXECUTION.md`
都實測成功）；`paper/**/*.tex` 由 `_core.py:61-64` `RESERVED_FILE_PATTERNS` 挖洞，deny 外於 allow。
所以「論文部拿到 paper/ 了」不等於「可以改論文」。**任何 `.tex` 修改一律走交接給主線程**，
交接件要帶套用前 staleness gate（hash + bytes + 錨點行號）與「驗證結果回本部門判定收斂」。

## 2026-08-05 — 錯誤的描述不只是描述錯，它會長出下游工作（本輪最貴的一課）

`data_sources.md:30` 記載了一個從未被下載的資料源（CBOE put-call，宣稱 1995 起）。這一行單獨看
只是「一筆過時記載」，但它實際生出了三樣東西：

1. 一張送給平台工程部、掛了 **27 天**的 P3 資料採集卡（去採一個不需要的序列）
2. 論文 `main_v5.tex:519` 一個錯誤的 family 標籤，**以及一個錯誤的延後理由**
   （「CW deferred 因為資料未 pin」——真相是那個 family 根本不用那份資料）
3. `EXECUTION.md` 一張**永遠不會完成**的 followup：pin CBOE put-call 不會補上 F3 的 CW cell，
   那會製造一個新的 family，不是完成這一個

所以「開工前先讀產出腳本」不是可選的謹慎，是**唯一能終止這條鏈的動作**。描述層錯了，
所有以它為前提的工作都是在錯誤方向上加深投入，而且每一項看起來都很正當。

副教訓：修描述層時要**回頭掃它生出來的東西**。我修完 `data_sources.md` 才想起那張 P3 卡還在
別人的收件匣裡，差點讓平台工程部去做一件我已經知道沒必要的事。修完描述，去撤掉它的下游。

## 2026-08-05 — 一個子命令被 deny，不代表整支腳本不能用

`uv run python scripts/path_claims.py list` 被 deny，我就在給平台工程部的 request 裡寫下
「path_claims.py 不在我的 allow list，所以我無法自行 release」。**錯的。** `release` 子命令
可用，一跑就成功。我以一次 deny 推論了整支腳本的可用性，而且把這個錯誤結論當成證據送出去，
差點讓別人去修一個不存在的缺口。

而且經理在同一輪剛提醒過：「正規入口就寫在 deny 訊息裡，先貼 deny 訊息全文再判定是不是權限缺口」
——deny 訊息的選項 3 逐字寫著那條 release 指令。**我讀了訊息卻沒照它做。**

規則：被擋時，(a) 讀完 deny 訊息裡指定的出路並**實際試一次**，(b) 換一個子命令／參數形狀再試，
(c) 兩者都失敗才叫權限缺口。宣稱「我做不到」之前要有一次真的嘗試，不是一次推論。

## 2026-08-05 — 不要對收件匣做 glob 批次操作

歸檔時用 `*.json` 一次搬走全部，把工作期間新到的經理裁決（D40）一起歸檔了才發現。
收件匣是活的，會在你工作時變動。**歸檔前先列出、逐一確認是不是自己已處理的那幾筆**，
搬完再列一次確認剩下什麼。
