# publications 工作日誌（append-only）

## 2026-08-05T09:20Z（台灣 17:20）— 經理四項裁決 + 兩張 canonical 卡：三件實質產出

**outcome=done**（收件匣 3 件全處理；prg v8 review round 完成判 FAIL、K1730 randomization
裁定不可能、vix-sufficiency 的 blocker 拆成三種不同處置——三者都不是「等資料」）。

### 裁決一：prg-periodic-garch v8 review round → `FAIL`（4 MAJOR / 2 MINOR / 0 BLOCKING）

產出在 `review_rounds/prg-periodic-garch/v8_review_20260805/`（latex_review / citation_report /
reproducibility_manifest / README manifest，全部 hash 記錄）。

**先更正經理裁決依據的一件事**：blocker 寫「v7 review cycle not yet run」是錯的。v7 那輪
2026-07-14 跑過，6 個 MAJOR 也全修了（`e2ffd8d90` / `af81d2e73` / `c23e36b5c`）。真正缺的是
**修完之後的下一輪**——review report 綁在修改前的 hash，fix 一落地就全 stale。所以我跑的是 v8
不是「補跑 v7」。

四個 MAJOR 裡有三個是同一個模式：**v7 的修正把缺陷搬家了，沒有移除**。

- **MAJOR-1（最貴的一個）** L207 結論段用 `\citep[e.g.,]{Tsiakas2008,Todorova2014}` 具名指控
  這兩篇犯了 mixed-timing confound。查證後兩篇都不成立：Tsiakas (2008) 建模 daytime returns
  且不建模隔夜報酬，沒有兩時點成分可加；Todorova-Souček (2014) 預測的是 intraday RV，隔夜當獨立
  regressor，沒有 full-day composite。兩篇其實是本文推崇的 coherent open-time 設計的先行者。
  更糟的是 §2.3 自己說唯一已知實例是「作者舊稿」——前後矛盾。而且 Todorova-Souček **就發表在
  FRL**，正是投稿目標，單盲審稿很可能送到這個作者圈。
- **MAJOR-2** L198（v7 M6 的替換句）「nothing approaches the conservative threshold in either
  variant」是假的：QQQ lag variant t=−2.95、p=0.0032，距門檻 0.048，且幾乎正好落在論文自訂的
  Bonferroni α/m=0.0028 上。
- **MAJOR-3** abstract「zero of six markets significant」沒有門檻限定詞；§4.1 為此修過的同一句
  沒有同步到 abstract。
- **MAJOR-4** L118「every number reproduces bit-identically」目前沒有現行 receipt 支撐（見下）。

Table 2 的 24 個 DM cell + 6 個 share + 5 個 p 值全部自己從 JSON 重算過，數字全對；字數
230/2133 都在 FRL 限制內；PDF 第一頁與當前 tex 相符。**沒有一個 MAJOR 需要新計算**，全是一到兩句
的措辭修正——有序修訂清單寫在 round README。

**未能執行的部分（誠實記錄）**：本 session 權限模式下 `Write` 進不了 `paper/`，所以 (a) round
產物暫存在部門子樹而非 `review_history/v8_review_20260805/`；(b) 四個 MAJOR 的 paper-update 我做
不了。已請經理指派有寫入權的執行體。Codex 第三軌也被擋（`codex exec` 與 bounded wrapper 都
deny），本輪只有兩軌——而 v7 正是靠 Codex 軌抓到 M5/M6，也就是這輪 MAJOR-2/3 的同類缺陷，
所以 v9 應該把第三軌補回來，不是當作可省略。

### 裁決二：cadence 改每週輪替 → charter 已更新

輪替表寫進 `charter.md`（W1 已執行=prg，W2 vt-insurance-cost，W3 volatility-absorption，
W4 taiwan-vt，W5 crypto-fear-channel，W6 vix-sufficiency，W7+ 其餘七篇）。排序原則照經理給的
「先清停最久，但明顯快好的不壓後面」，另加一條我自己的：**能推進到可投稿的，排在還在找期刊的
前面**。順序不是承諾，證據狀態變了就重排。

### 裁決三：FRL 佇列排序 —— vt-insurance-cost 先行，理由如下

經理要求把排序理由寫下來讓日後看得懂，所以寫完整：

**原本 blocker 的顧慮前提不成立。** vt-insurance-cost 的 blocker 寫「sequenced after
vt-crowding-abm to avoid two concurrent VT letters at FRL」。但查 pipeline：vt-crowding-abm 的
`journal_target` 是 `"decide"`（**還沒選期刊**），blocker 是 `"finishing"`（**本體還沒寫完**）。
拿一篇沒選期刊、沒完稿的論文去壓一篇「academic content 與 replication package 都已 closed out」
的論文，是把確定的延遲成本（已經 76 天）付給一個還不存在的衝突。

**真正的 FRL 併發是另一組，而且沒人注意到**：vt-insurance-cost 與 prg-periodic-garch 都是 FRL
target。但這一組不需要人為排序——prg 這輪判 FAIL，要修 4 MAJOR、重編、再跑 v9；
vt-insurance-cost 只差一個機械的 format/word-limit gate。**成熟度自己決定了順序。**

所以：**1. vt-insurance-cost（跑完 FRL format gate 即投）→ 2. prg-periodic-garch（v9 PASS 後）
→ 3. forecast-tail-divergence（仍在 draft，最遠）**。

**vt-crowding-abm 在等什麼**：它要進 FRL 佇列的條件是「完成 journal fit 決策並選定 FRL」。
若那時 vt-insurance-cost 已在審或已有決定，衝突自然消解；若它選了別的期刊，衝突根本不存在。
兩種情況都不需要現在為它讓路。

### 裁決四：volatility-absorption 排到 W3，本輪未動

經理指定排在 A 之後、且文獻查證走 NotebookLM RAG。A 完成了，但本輪還有兩張 canonical 卡要清，
且 NotebookLM 需要外部存取（本 session `WebFetch`/`curl` 都被 deny，可行性存疑）。已排進 W3，
不是漏掉。

### P2 canonical：K1730 randomization null → **NO VALID EXACT RANDOMIZATION**

裁決全文 `adjudications/k1730_randomization_null_20260805.md`。任務明說這是合法結果，而它確實
是被設計逼出來的結果，不是放棄。

證明的核心是一行：**PIT-safe 與 bijective 在時間索引上互斥**。設 σ 把第 i 週指派第 σ(i) 週的
macro 歷史，PIT-safe ⟺ σ(i) ≤ i；而 `{σ ∈ Bij(T) : σ(i) ≤ i ∀i} = {id}`（對有限全序歸納即得）。
randomization test 的 exactness 來自變換群的不變性，沒有群就沒有 `(r+1)/(B+1)`。這一刀同時砍掉
whole-row permutation（已否決）、circular shift（wrap 就是把晚期放到早期）、任意 block
permutation、限制在子窗的重排。而 v2 用的 non-circular lag shift 之所以 PIT-safe，**正是因為它
不是雙射**（前 L 個 block 沒有原像）——所以它永遠只能是 placebo。

推論值得記住：v2 那個 1/6 的 p 值下限**不是「粗糙、待升級」，而是這個觀測設計的資訊天花板**。
加更多 shift 只會把地板降低，不會改變它是 placebo 的事實。

兩條跳出這一類的路線都評估過也都拒絕了：block sign-flip（成本近零、不用 refit，但 nested 比較
下 loss differential 在 H0 就是偏斜的，對稱性假設先驗地錯，會產出一個「便宜、精確好看、而且錯的
方向剛好與現有結論一致」的 p 值）；conditional randomization test（唯一真 exact 的路，但 exactness
轉嫁到一個無法驗證的 macro 生成模型，還是要付 743 CPU-h——結論已經是 NULL，付這個價只是多一位
小數）。**B=199 compute task 不實體化。**

若未來 K1730 家族出現**正結果**，CRT 那條路的算計會反轉，屆時應重開此裁決。

### P3 canonical：vix-sufficiency F3/F9/F10 → blocker 是誤填的，三個家族三種處置

裁決全文 `adjudications/vix_sufficiency_f3_f9_f10_20260805.md`。

卡片寫「blocked on CBOE put-call / Google Trends / intraday VIX open snapshots」，讀起來像資料
拿不到。但 `data_sources.md` 三個來源都有記錄，`main_v5.tex` Table 4 三個家族的主表 DM 也都算出
來了（|t|=0.52/0.67/1.12）。缺的是 **pinned snapshot，不是存取**。

- **F10 根本沒 blocked**。論文 L240 定義是 `|VIX_open,t − VIX_close,t−1|`，需要的是 daily `^VIX`
  OHLC 的 **Open 欄**，不是 intraday tick——「intraday VIX opening print」這個措辭本身就是卡點。
  Yahoo `^VIX` 早就在用。唯一的坑：現有 VIX pin 註明「lagged 1 day」，F10 必須用未 lag 的版本，
  套用日頻家族的 shift 會在看起來很嚴謹的同時毀掉這個訊號。**可立即派工。**
- **F3 卡在一個小決策**，不是資料存在性：`data_sources.md:30` 寫 "via yfinance/**manual**"，
  manual 表示沒有可重播腳本，而那是 JoF replication package 的硬要求。已送 P3 request 問平台
  工程部：還能不能程式化抓？能就寫進 harness，不能就走「一次性 pinned snapshot + 完整 provenance」。
- **F9 應該撤回，不是延後**。Google Trends 回傳的是對查詢窗口相對縮放的值、會回溯重採樣、沒有
  vintage API——今天 pin 一份 snapshot 只是凍結「2026 年回頭看的歷史」，不是各 forecast origin
  當時可得的值。這直接撞 `.claude/rules/experiments.md` 的修訂型資料規則。**做出來會是一個
  在不可採信輸入上做的精確算術**，與 K1730 的 permutation 同一種危險。建議改寫 `main_v5.tex:519`
  把 F9 從「deferred」改成方法論排除（建議句已寫在裁決文件）——它的 DM 是 0.67，撤回不損失任何東西。

另外先講清楚：F10 跑出來若 |t|>3.0，那是**發現**不是麻煩（它的主表 |t|=1.12 是三者最大，
且開盤原點確實在其他家族的資訊集之外）。不能用「預期 immaterial」預先框住結果。

### 送出的求助

- **platform_eng（P2）**：reproduce gate 用整檔 hash，`model_evaluation.py` 動三行（改的是
  `strategy_dm_test`，兩個實驗根本不呼叫）就讓 k1699/K1710 全部 `INPUT_HASH_MISMATCH`，而且
  **判 mismatch 後直接拒跑**，連「重跑看數字有沒有變」都做不到。附了 AST 函式級 hash 證明呼叫面
  byte-identical，並給了三個修法建議。
- **platform_eng（P3）**：CBOE equity put-call volume 的可重播取得路徑（見上）。

### 給經理的兩件事

1. **本部門在目前權限模式下寫不進 `paper/` 與 `experiments/`**，所以 review round 的歸檔、四個
   MAJOR 的 paper-update、F10 的實驗執行都做不了。要嘛放寬轄區，要嘛指派有寫入權的執行體——
   兩種都行，但現在是「裁決做得出來、動手做不了」的狀態。
2. **pipeline blocker 字串系統性過時**：今天查的兩篇都錯（prg 說 v7 review 沒跑，其實跑完也修完；
   vix-sufficiency 說停在 main_v4，其實已到 main_v5）。2/2 不是巧合。blocker 是散文，會停在寫下的
   那一刻。建議把它改成結構化欄位（指向最後一輪 review 目錄 + 最後一個 fix commit），由機械產生。

### 追加：工作期間又進三件（D4 / D7 / governance），一併處理

**收尾時差點出錯，記下來**：歸檔 inbox 時用 glob 掃全部 `item_*.json`，把工作期間新到的三件
一起歸檔了。當場發現並移回，三件都完整處理。教訓：歸檔要**列出本輪處理過的 id**，不要用
「掃目錄裡剩下的」——收件匣在你工作時是會動的。

#### D4（P1，manager）— 與 08:46 那則裁決大幅重疊，但裁決三是新的

裁決一、二與先前那則相同（已執行）。**裁決三是新指派**：查那批 `last_advance_at=2026-07-01`
的可信度，若確實批次填寫則代表 advance 記錄機制在說謊，是流程缺陷，查到回報、**別自己改資料**。

查證做法：找出 stamp 等於 `_meta.baseline_set_at`（2026-07-01T00:00:00+08:00）的論文——**實際是
9 篇不是 8 篇**——對每篇跑 `git log --since=2026-06-24 --until=2026-07-08 -- paper/<id>/`。

結果分三類，而且**方向與我上輪的推論相反**：

- **(a) 4 篇有實質推進 commit 且在 07-01 之後**：taiwan-vt（07-06/07 body_v3 SE 標籤 + provenance）、
  vix-sufficiency（07-06 三個 SEVERE fix：Clark-West nested correction / lag convention /
  Table 6 reconcile）、vt-insurance-cost（07-05/06 citation verification + severe fixes +
  cross-OOS rerun）、eav-universal-magnitude（07-06 v2 review 歸檔）
- **(b) 3 篇只有全 portfolio 掃描類 commit**（AI footnote scrub / compliance scrub / repo 搬遷 /
  trending 文章掃到 paper 目錄），無實質推進：crypto-fear-channel、garch-x-vix、vt-crowding-abm
- **(c) 2 篇窗口內完全無 commit**：btc-gas-negative、forecast-tail-divergence

所以缺陷有**兩個方向**：對 (b)(c) 那 5 篇，stamp 是 baseline 佔位不是事件（我上輪不採計是對的）；
對 (a) 那 4 篇，stamp 是**過時的**——真實推進發生了卻沒更新（**我上輪把它們一起剔除是錯的**，
它們 7 月 KPI 實際達成）。

**真正的病不是虛報，是根本沒有自動更新**：`last_advance_at` 是手填欄位，只在有人記得改時才動
（prg 07-14、volatility-absorption 07-14、vt-trend-following 07-19 就是有人記得的那三篇）。
用它衡量 KPI 會**系統性低估**。該修的是「stamp 由機械從 git / review_history 推導」。
依指示未自行改資料，已回報經理。

這與 blocker 字串過時是同一個病的兩個症狀：**論文 pipeline 的狀態欄位全是手填散文，沒有機械來源。**

#### D7（P1，manager）— replication package 是裝飾品

經理的三個事實核對後**全部屬實**：k892:38 與 k994:371/392 直拉 yfinance；pinned snapshot 存在
（在 `paper/garch-x-vix/data/` 四份 CSV，不在 `experiments/k892/data/`，後者確實空的）且無人消費；
審稿人照跑會拿到今天的 yfinance 資料。

**但這張卡去年七月做過一半，而那一半沒落進 canonical main**：
`experiments/k994/PINNED_REPOINT_COVERAGE_GAP.md`（2026-07-27）記載 k892 半邊已完成並驗證，
repoint 到 pinned `0050_tw_adj_close` 後 byte-for-byte 重現 gamma=0.097042 / t=3.5965 /
n_obs=4219。但 canonical 的 `k892_verify_tw_gamma.py` 仍是 `yf.download` 版本，`git log`
對 `experiments/k892/` 只有兩筆搬遷 commit，沒有任何 repoint commit。

**這是「宣稱完成但沒落地」的第二個實例**（第一個是 K1730，靠 k1730_v2_adopt 從 preservation ref
收養回來）。建議先找回那份實作，不要重寫——重寫會丟掉當時已解出的欄位/vintage recipe
（`*_adj_close` 欄 + yfinance `end` 是 exclusive 的截斷處理）。

較小的發現：`k892_verify_tw_gamma.py:31` 的 `sys.path.insert` 硬編碼指向已刪除的 worktree
`agent-adc7e97d`。**不會 ImportError**（`clean_tw50_data` 在 canonical `src/volpred/utils.py:21`），
所以不是 blocker——但它隱含一個沒人驗證過的假設：當年 worktree 版本與現行 canonical 版本行為相同。

**k994 半邊不是工程工作，是取捨**：論文引用的 0050.TW DM t=1.44（`main.tex:531`）是
2019-01-01…2026-04-08 的 OOS 統計量，而隨附的 pinned CSV 只到 2022。直接 repoint 會截斷樣本、
必然改變數字。經理信裡「數字若變了就回溯更正論文」等於預設了「截斷並改論文」那條路；
**我建議相反的選項：把 0050.TW + ^VIX 的 snapshot 延長到 2026-04-08**。理由是那兩個序列的
adjusted close 公開可得，延長不涉及任何方法論妥協，成本只是重新 snapshot + 一次 bounded 重跑；
而截斷會把「當初 snapshot 取短了」這個純資料缺口，變成論文的實質修改。回溯更正是為了誠實，
不是為了遷就一個可以直接補的洞。已回報經理待裁。

機械化那一半（「檢查腳本是否真的讀 pinned snapshot」）建議做成 AST 級而非 grep 級，並與今天送給
平台工程部的 reproduce gate 缺陷一起設計——兩者是同一家族（那邊整檔 hash 太粗，這邊根本沒檢查
資料來源），分開做會變成兩個各自為政的 gate。

#### D11（P1，manager）— D7 改採選項 1；k892 找到了，而且找到了根因

經理推翻自己上一則的方向，**採納我建議的選項 1**（延長 pinned snapshot 而非截斷樣本改論文）。
另指派兩件：找回 k892 已驗證實作（不准重寫）、回報「宣稱完成但沒落地」這個 class 該怎麼機械擋。

**k892 找到了**：`git log --all -- experiments/k892/` 挖出 2026-07-27 的四個 quarantine commit，
其中 `6349aec58` 含 634 行的 pinned 版 `k892_verify_tw_gamma.py`——檔頭寫「reads the taiwan-vt
pinned snapshot」、有 `_load_pinned()` 讀 `0050_tw_adj_close` 欄、註解記載 t=3.5965 / n_obs=4219
byte-for-byte、`sys.path.insert` 已改成有條件。依賴的 CSV 在 canonical 就有
（`paper/taiwan-vt/data/0050_tw_..._2008-2026.csv`，**是 taiwan-vt 的 snapshot 不是 garch-x-vix
的**，覆蓋到 2026，不受 k994 的 2022 截斷問題影響）。收養時只取 k892 兩個路徑，不可整包 merge
（56 foreign paths，同 K1730 規矩）。

**根因比「沒落地」精確得多**：那個 commit 的 message 寫著這兩個檔「**6 fires**」——成果不是做完
沒人 commit，是被 quarantine **連續攔下 6 次**，每次移出工作樹存進 ref，而**沒有任何人收到通知**。

> quarantine 是 fail-safe，它做了正確的事（不讓 foreign path 混進 merge），但它的輸出只寫在
> commit message 裡，**沒有讀者**。所有者不知道東西被隔離了，於是 task 標 succeeded（工作確實
> 做完了）、canonical 卻是空的。K1730 第一次、k892 第二次，形狀完全相同。

建議的機械擋：隔離事件同時產生指派給路徑 owner 的工作項（資訊全都有，只是沒送出去）；同一路徑
被隔離 ≥2 次直接升 P1（6 次沒人知道 = 沒有累犯偵測）；收養流程有現成範本，缺的只是「有人被告知」。

**12 篇 blocker 過時篩選**：做了機械篩選，12/12 全命中——**而這個數字不能採信**。全域 sweep
commit（manuscript-declared 重構、9 份 CSV 定期 refresh、compliance scrub、repo 搬遷）會碰到每個
paper 目錄，false positive 極高。它是排序器不是判定器。真訊號是帶論文自身名字的 commit：已確認
3 篇（prg / vix-sufficiency / taiwan-vt），新增高度可疑 1 篇（vt-crowding-abm——blocker 只寫
finishing，但 07-16 有「P0-5 收官 — 修正流動性歸因方向倒置」）。逐篇核實走治理部示範的回讀法，
已排進輪替當固定步驟，不另開 12 張卡。

#### D19（P1，manager）— 收養核准；但 paper/ 權限沒生效，而且是 org 架構的死鎖

經理核准 k892 收養（硬條件照我寫的）、核准三條 quarantine 機械擋法、核准 blocker 篩選的處置，
並說 paper/ 已列入我的 owned_paths（他口述給平台工程部代行 registry 變更）。

**我先試了再回報**：直接對 `main.tex` 做 MAJOR-1 的修正 → 權限閘 deny。回查 registry：
`publications -> owned_paths = []`，`min_cadence` 也還是 null。變更沒落地。

**但真正的問題不是「還沒做」**：`org_admin.py` 的子命令只有 init / create / retire / suspend /
resume / list——**沒有 update，沒有 set-paths**。owned_paths 是建立部門時一次性指定的，之後在
CLI 層沒有任何修改路徑。要改只能直接編輯 `storage/org/registry.json`，而：

| 角色 | 能改 registry 嗎 |
|---|---|
| 經理 | 不能（自述三輪寫不進去） |
| platform_eng | 不能（owned_paths 只有 `frontend-v2-fix/`） |
| 各部門（含我） | 不能（章程明文禁止） |
| `org_admin.py` | 沒有提供這個操作 |

**四個角色都不能動，這不是配置錯誤而是設計缺口**，且直接違反老闆立的「gate 必須有出口、禁死局」。
已上報並給三條出路（老闆直接編輯 / 開工單加 `update` 子命令 / 放寬 registry 寫入閘），並指出
第二條會卡在自己身上——修 `org_admin.py` 要寫 `scripts/`，而那正是平台工程部因 owned_paths 太窄
卡住的地方。**死鎖套娃。**

**繞道立刻執行**：k892 收養要的是 `experiments/` 寫入權，而**研究部的 owned_paths 正是
`experiments/`**。已送 P1 request 給研究部，附完整收養規格——來源 commit `6349aec58`、只取哪兩個
路徑、不可整包 merge 的理由、pinned CSV 是 taiwan-vt 那份而非 garch-x-vix 那份的消歧（經理特別
要求留在收養紀錄裡）、驗收標準 gamma=0.097042 / t=3.5965 / n_obs=4219、以及 `sys.path.insert`
那個未驗證假設要顯式確認。**這件事不必等 registry。**

**prg 四個 MAJOR 真的卡住，但執行成本已降到最低**：寫了
`review_rounds/prg-periodic-garch/v8_review_20260805/APPLY_PATCH.md`——四個 MAJOR + 兩個 MINOR 的
**逐字 find/replace 對照**，含套用順序、每筆一句理由、套用後三個驗證步驟、以及 MINOR-1 的兩個
選項（推薦純揭露修法；另一個把 family 擴到 24 個 test、門檻 3.0→3.08，我已驗證**無任何 verdict
改變**）。拿到權限的人不必重讀論文、不必重新判斷。

MAJOR-1 選最小修法（拿掉兩個 `\citep`）而非反轉框架改引為 coherent open-time 先行者。理由：
反轉框架是更好的論文，但需要先對 primary PDF 確認兩篇的設計，而本 session 取不到外部文獻。
**移除一個未經證實的指控不需要那道確認，換成一個未經證實的讚許則需要。**

#### 平台工程部回覆 CBOE 查詢 → 我早上對 F3 的裁決被推翻（同日第二次更新）

他們回報 `src/` 與 `scripts/` 全域 **0 命中**，沒有任何 put-call collector，並誠實表示這一班沒做完
外部來源測試、不想憑印象回答會寫進論文資料章節的問題。

**那個 0 命中不是漏找，是決定性證據**——它讓我去讀產出腳本而不是繼續讀資料清單。結果是資料清單
本身錯了：

`paper/vix-sufficiency/experiments/k732_pcr_behavioral_sentiment.py`（`experiments.md:18` 指定的
Family 3 產出者）`:53-58` 只下載 SPY / GLD / `^VIX` / `^SKEW` / `^VIX3M`，**沒有任何 put-call
序列**。`:131` 的訊號是 `BSI = (vix_level_pctile + ts_ratio_pctile + vix_mom_pctile +
skew_pctile) / 4`。檔頭 `:11`/`:13` 自己寫著「K191: PCR data unavailable, used VIX proxies」
——put-call 當年就沒拿到，換了 proxy，而這件事只留在腳本註解裡，**沒傳到任何下游文件**。

三個後果（嚴重度遞增）：
1. `data_sources.md:30` 記載了一個從未被讀取的來源。
2. **F3 根本沒有 blocker**：輸入全部 Yahoo 免費可得，跟 F10 一樣可以立刻跑。三個「blocked on
   external data」的家族裡**兩個從來沒被 blocked**——這張卡從 2026-07-09 掛到今天，掛的是一個
   不存在的障礙。
3. **論文把 Family 3 稱為 behavioural put-call ratio**（`main_v5.tex:519` 與 Table 4），而它實際
   檢定的是「VIX 的百分位重組 + SKEW 能否改進 VIX」。四個成分裡三個是 benchmark 自己的變換，
   第四個 SKEW 也是 SPX 選擇權隱含指數——全都落在論文正在檢定其充分性的那個資訊集內。所以
   Family 3 的 null 是**論文自己的理論所預測的**，不是對該理論的獨立證據；而且它與 Family 2
   （VIX 期限結構）共用成分，而十三個 family 宣稱 pre-specified 且各自獨立。

結論不受影響（NULL 仍成立、沒有訊號被漏掉），受影響的是**證據的獨立性計數**。已建議主動更正而
非靜默吸收——審稿人打開 replication package grep put-call 找不到東西，代價高得多。裁決文件已更新
並標 SUPERSEDED（保留原文存查），已回覆平台工程部停止那三個步驟、並回報經理。

**這一輪的方法教訓（第三次同型）**：資料清單、pipeline blocker、last_advance_at——三個都是手填的
描述層，三個都與實作脫節。**要知道一個實驗用了什麼資料，只能讀產出腳本。**

#### governance P3 — taiwan-vt 樣板資格

選「從樣板清單移除」，但理由比「缺一個 README」強：taiwan-vt 現在 `do_not_advance=true`，且有兩個
OPEN followups（reproduce.py 仍綁舊 body/body_v2 架構待重綁 body_v3；body_v3.tex:152-154 缺
provenance）——**它的 replication map 本身還在重綁中**。補一個 README 只會讓它看起來合格，而後續
論文照抄的會是「表面齊全、實質未完成」的結構，那種缺口不會被目視發現。建議樣板清單改為
leverage-direction + vt-trend-following 兩篇，等 taiwan-vt 的 followup 關閉（我排的 W4）再議。
已回覆治理部（本部門寫不進 `.claude/rules/`，這是裁決不是動作）。

## 2026-08-05T08:41:36Z（台灣 16:41）— 部門首次啟動：KPI 基線建立

**outcome=noop**（收件匣 0 件，未自創工作）——但完成 bootstrap 應有的 KPI 基線，並依決策鏈把
portfolio 全面 stall 的裁決需求上報經理。

### 做了什麼

- 收件匣 0 件；`state.json` 為 `health=new` / `last_run=null`，確認這是部門第一次執行。
- 依章程收尾契約「state.json 需含 KPI 快照」，讀取 `storage/paper_pipeline_status.json`
  並跑 `scripts/paper_pipeline_check.py`（機械 stall 檢查，非人工估算）建立基線。

### 基線事實（來自機械檢查，generated_at 2026-08-05T08:40:49Z）

- 總論文 13 篇，`stall_days` 門檻 7 天 → **stalled_count = 13（全部）**，`data_issues = 0`
- 最久 `days_in_stage = 76.7` 天（prg-periodic-garch、volatility-absorption、vt-insurance-cost）
- stage 分布：revision 10、draft 2、multi_round_review 1；`do_not_advance=true` 2 篇
  （leverage-direction、taiwan-vt）
- **2026-08 至今推進 = 0 篇**（今天是 8 月第 5 天，尚未逾月，非 KPI 失敗，是本月未開始）
- 2026-07 只有 5 篇有可驗證的推進敘述；另 8 篇 `last_advance_at=2026-07-01` 與
  `_meta.baseline_set_at` 同日且無對應敘述證據，**疑為 audit 批次填寫，不採計為 KPI 達成**

### 口徑更正（避免誇大）

`days_in_stage` 是「停在同一 stage 多久」，不是「多久沒有任何動作」。後者看 `last_advance_at`，
最近一次是 2026-07-19（17 天前）。回報時兩者分開講，不混用。

### 未做什麼（以及為什麼）

沒有自行啟動任何 review round。啟動哪一篇牽涉部門間優先序與資源，屬經理職權；且
vt-insurance-cost 的投稿時機還牽涉「兩篇 VT letter 不得同時投 FRL」的排序決策。依組織通則
「遇到需要決策的事一律問經理，並附證據與建議選項」，已送 P1 report 到 manager/inbox，
附三個具選項與成本評估的裁決方案（建議 A：prg-periodic-garch v7 review cycle）。

### 下一步（等經理裁決）

經理指派後即可開工；論文部不自行排班（min_cadence=on-demand）。
