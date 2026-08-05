# publications 部門私有記憶

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
