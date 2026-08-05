# publications 工作日誌（append-only）

## 2026-08-05T09:20Z（台灣 17:20）— 經理四項裁決 + 兩張 canonical 卡：三件實質產出

### k892 收養完成（研究部執行）— 一半 fixed_and_verified，另一半直接改變論文措辭

研究部在 `77b1884fc` 落地收養。**我自己從 canonical HEAD 驗過，不是採信回報**：兩個路徑
`git cat-file -e` 都在；`k892_verify_tw_gamma.py:54` 有 `PINNED_SOURCES`、`:82-83` 讓 0050.TW
在任何 `yf.download` 之前先走 `_load_pinned`；直接 jq 讀 canonical 的 results.json 得
`gamma = 0.09704215871857629`、`gamma_t = 3.5965275718364866`、`n_obs = 4219`，與回報一致。
**這一半升格為 `root_cause_fixed_and_verified`。**

**流程偏差認可，不 revert**：研究部沒有 worktree 與 `merge_worktree.sh` 的執行權限，改走
「取檔案內容 → 寫 owned_paths → 跑 gate → `git_writer_lock` commit」。判斷正確——
`merge_worktree.sh` 的五層防禦針對「worktree commit 遺失」，這條路沒有 worktree，防禦對象不存在。
**規格是我寫的，我預設了執行者有 worktree 權限，那是我的疏漏不是他們偏離**。他們主動寫出偏差並
提出可 revert，處理得比照著一份不適用的規格硬做好。

**另一半才是對論文最重要的**：研究部實跑後發現腳本仍跑不完——0050.TW 從 pinned snapshot 成功
載入，接著 cross-check 的 `^TWII` 回 None，`raise ValueError`，**在寫出 results.json 之前中止**。

因為 `body_v3.tex:53` 早就寫著「no live yfinance dependency」，而那句話的真值今天翻了兩次：

| 時點 | 那句話 |
|---|---|
| 今天之前 | **假** — repoint 沒進 canonical，腳本仍 live 抓 0050.TW |
| `77b1884fc` 之後（0050.TW 那一腿） | **真** |
| `77b1884fc` 之後（整支腳本） | **仍假** — cross-check 還是 live，而且會讓腳本掛掉 |

**若研究部只回驗收值而不實跑，我會把那句留著不動**，而它會帶著「replication package 可完整執行」
的暗示送進投稿。一份誠實的半完成回報，價值高於一份漂亮的驗收數字。

修正措辭寫成 `work/taiwan_vt_repoint_wording.md`（單一 edit + 獨立驗證 + 「不得宣稱什麼」三條）
交主線程。**不得宣稱**：package 可完整執行、可從乾淨 clone 重現。**可以宣稱**：論文引用的統計量
由 pinned snapshot 決定並 byte-for-byte 重現。

**記錄但未裁定的數字不一致**：`body_v3.tex:33` 寫 0050.TW 樣本「4,217 trading days、到 March
2026」，而估計輸出 `n_obs = 4219`、期間到 2026-04-02。差 2 天、期末差一個月。可能有正當解釋
（returns vs price observations、排除 2014 split date），但我試不出哪個組合等於 4,217。
**不下結論**，排進 W4 核實——那要讀腳本的載入邏輯，不是猜。

### 收尾：治理部把「不得批量回填戳記」升格進 v3 裁定，並給了一條通用判準

治理部採納我的論證、**撤回**原本「請評估把 12 篇補上的優先序」那句請求（他們自述那句預設了批量補
是可選項），並把例外條款（需求驅動而非清單驅動）寫進裁定。他們提出的判準是
**「可信的外觀不等於可信的來源」**——並指出他們本輪的 bug class（恆為 0 的指標與真的是 0 的系統
在畫面上長得一模一樣）與我的（假戳記與真核實長得一模一樣）是同一個形狀。

我回了一組實測資料，因為**我今天踩到的是四個同型實例，而方向各異**——這才是這條判準難用的地方：
批量戳記是「假的看起來真」；blocker 與 data_sources 是「過時的看起來現行」；main.pdf 的 mtime 是
「過期的外觀配當期的內容」；而 reproduce gate 的 `INPUT_HASH_MISMATCH` **是真警告看起來像真問題**
——gate 完全正確地回報了一個真實的 hash 不一致，問題在**粒度**：它答的是「這個檔有沒有變」，
我要問的是「我的數字會不會變」。只用「訊號可不可信」那個軸看，它會被判成可信，然後我就會接受
unverified、把論文的 reproducibility 宣稱降級——而實際上該降級的是 gate。

所以判準寫成可操作的形式收進 memory：

> **訊號與它所指涉的事實之間隔了幾層？每一層都可能獨立漂移。**
> 引用一個欄位前先問：這個欄位是誰寫的、什麼動作會讓它更新、那個動作與我關心的事實是不是同一件
> 事。三個問題有一個答不出來，就去讀底層。

每多一層間接，就多一個必須自己去查的地方——**不是多一個不要相信的東西**。純粹的懷疑會癱瘓，
數層數不會。

### 本輪三件的結案狀態（經理 D26 要求明確標示；依 CLAUDE.md 二態）

三件全部是 **`root_cause` 已定位、待修**，**沒有一件是 `contained`，也沒有一件是
`root_cause_fixed_and_verified`**。標成待修是準確的：根因都查到了實體證據，但修復動作全部落在
本部門轄區外，因此都還沒有「重跑與回讀驗證」這一步。

| 件 | 根因（已定位，有實體證據） | 為何尚未 fixed_and_verified |
|---|---|---|
| **k892 replication 宣稱不實** | 不是沒人 commit——成果被 quarantine 連續攔下 **6 次**（`6349aec58` 的 commit message 自述「6 fires」），每次移出工作樹存進 ref，而**隔離事件沒有回報路徑**：資訊全都有，只寫在 commit message 裡，沒有讀者。K1730 是同形狀的第一次。 | 收養需 `experiments/` 寫入權，已交研究部執行；機械擋（隔離事件產生指派給 path owner 的工作項、同路徑 2 次以上升 P1）是平台工程部工單。兩者都未落地，未回讀驗證。 |
| **prg-periodic-garch v8 FAIL** | 不是「v7 沒跑」——v7 跑了也修了，但**三個修正把缺陷搬家而非移除**（M4 從 §2.3 移到結論並升級成具名指控、M6 的替換句自己為假、M5 修了 §4.1 沒同步 abstract）。更上游的根因是 review 流程沒有「替換句要當新斷言重驗 + 全文搜同一斷言的其他出現位置」這一步。 | 六筆修改指令已交付 `work/prg_v8_edit_instructions.md`，但 `paper/` 是保留區、由主線程執行。未套用、未重編、未重跑 gate、未開 v9。 |
| **vix-sufficiency Family 3** | **宣稱與實作不一致**：論文稱 behavioural put-call ratio，實作（`k732:53-58`、`:131`）只讀 `^VIX`/`^SKEW`/`^VIX3M`，訊號是四個 VIX/SKEW 百分位的平均。代換發生在 K191 時期並只記在腳本註解 `:11`。屬**研究誠實線**，經理明示優先序高於任何排程便利。 | 需改 `main_v5.tex` §2.3 / Table 4 / `:519` 與 `data_sources.md:30`，全在保留區。經理裁定下一輪單獨處理。CW 本身可立即跑但需 `experiments/` 權限。 |

**共同的上游根因**（今天出現三次，值得單獨記）：平台的描述層——pipeline `blocker`、
`last_advance_at`、`data_sources.md`——全是手填且與實作脫節，而**沒有任何機械來源**。三次誤讀
（含我自己引用過時 blocker 對治理部下裁決那次）都由此而來。治理部已立判準 + 我交付了偵測規格
（`specs/blocker_staleness_field.md`），但那同樣待實作，所以這一條也是 `root_cause` 待修。



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

#### 最後一批（manager ×2 P1、governance ×2）— paper/ 不 grant 是設計；選下一篇；拒絕批量補戳記

**經理裁定 `paper/` 不會 grant 給論文部，而且理由比權限更根本**：CLAUDE.md 硬規則——禁止
background agent 直接寫論文 `.tex`，寫作與方法論決策要在主線程。「保留區在這裡擋的正是它該擋的
東西。」我接受，並停止再提 grant paper/。（`set-paths` 規格仍有用——registry/charter 的
`min_cadence` 漂移還在——但那與 paper/ 無關，兩件事分開。）

**四個 MAJAR 改走 request 給主線程**，指令格式由經理指定：每處 檔案:行號、原文、改文、依據，
放 `work/`。已產出 `work/prg_v8_edit_instructions.md`——六筆修改，MAJOR-1 附完整六點查證
（兩篇各自為何不成立、§2.3 的自我矛盾、FRL 單盲投稿風險、以及為何選刪除而非反轉框架），因為
那是刪除具名指控的依據，不能只寫「查證後不成立」。

`review_rounds/.../APPLY_PATCH.md` 已標 SUPERSEDED as the execution copy 並指向 work/ 版。
**兩份不能各自演化**——今天報了一整輪的病，不會自己再製造一個。

**下一篇 read-only review round：選 crypto-fear-channel**（依經理判準逐篇篩）：
volatility-absorption 雖然並列 stall 最久，但 blocker 含 prior-art 文獻查證需要 NotebookLM
外部存取（本 session 被 deny）→ **blocker 不完全落在職責內**，判準第二項不過；vt-insurance-cost
經理明說不碰；taiwan-vt 治理部正在處理會撞。crypto-fear-channel 的 blocker 是「confirm state」
——狀態不明本身就是 paper_review 的工作，四項判準全過。

但先講清楚它需要的是**盤點不是完整 review round**：在盤點出真實狀態之前跑三軌 review，是把資源
花在不知道要驗什麼的東西上。已回報並排到下次喚醒，不硬塞進本 session——硬塞會做出一份我自己
不敢引用的東西。

**治理部 v2 裁定**：我的實測推翻了他們 v1 的規則 1（目錄級比較 12/13 全命中），他們改成路徑限定
並一字採納我的三項實作約束。補了一個更強的證據給他們：我那個原型**本來就有關鍵字過濾器**
（濾掉 scrub / migrate / compliance / trending_repost / PHASE-Z），濾完仍然 12/13——所以「不得用
commit message 關鍵字分類」不只是「錯的分類器比誠實的過度回報糟」，是在這個語料上它**連降噪都
做不到**。

**拒絕批量補 12 篇的 `blocker_verified_at`**（治理部問優先序，這是我的排序）：寫入 verified_at
等於宣告「我在這個時間核實過」。一天內對 12 篇寫同一個戳記而沒有逐篇回讀，那份戳記就是假的
——**而且是看起來最可信的那種假**，因為它有格式、有精度、通過任何機械檢查。這正是
`last_advance_at` 現在的狀態（9 篇帶著 baseline 日期，4 篇之後有實質推進卻沒更新），而它今天讓
我判錯了 KPI。批量補會在 blocker 欄位上複製同一件事，且比原狀更糟：現在是「誠實地沒有戳記」，
補完會變成「不誠實地有戳記」。

處置：隨輪替逐篇補，13 週補完。期間維持 stale 是**正確狀態不是積壓**——依 v2 裁定 stale 只改變
舉證責任，而引用前回讀原始檔本來就是今天教會我的事。例外是需求驅動：某篇在輪到之前被引用，
那一次就當場核實並補戳記。

#### D24（P1，manager）— 核准三件；出路選 2 但形態改成 set-paths

經理核准 k892 交研究部（稱為「本輪最好的一次繞道」）、核准 APPLY_PATCH 形態並**立為常規**
（往後所有跨轄區修改都照這個形態交付）、特別認可 MAJOR-1 選最小修法的界線
（「證據不足時往說得更少的方向修永遠安全，往說得更多的方向修不安全」）。

出路選 2，但形態照治理部裁定改了：不是泛用的 `update`，是 **`set-paths` 子命令**
（dept / --paths / --reason / --actor），行為比照 create/retire——**寫 registry 同時寫 bulletin**。
理由：`org_admin.py` 已是所有結構性變更的 canonical writer，給任何人 raw Edit 會讓轄區變更成為
全組織唯一沒有審計痕跡的操作。出路 1（老闆直接編 registry）不採（繞過 canonical writer，下次
同樣的事還會再來）；出路 3（放寬閘讓經理能改）經理自己否決（能給自己開權限的角色，其他所有
決策都失去可稽核性）。

**我的分析被更正了一半**：我說「單靠 2 會卡在自己身上」——治理部查核出真相是，寫得進
`scripts/org/` 的 actor 是**主線程／老闆的互動 session**，不是平台工程部（經理已發撤回令）。
所以這條要主線程動手，不是套娃。

**照剛核准的常規交付**：寫了 `specs/org_admin_set_paths.md`——介面、逐步行為、三個必須拒絕的
情況（`dept == manager`、路徑已被他部門擁有、未知或已退役部門）、六個測試建議、可直接貼上的
第一次呼叫。

規格裡特別點出一件不寫就會被漏掉的事：**registry 與 charter.md 是兩個寫入點，set-paths 必須
同時寫**。`cmd_create` 現在就是寫兩處（registry `:139-140`、charter `:121-122`），而 charter 正是
每個部門 session 啟動時用來認識自己是誰的東西。而且**這件事已經發生在我身上**：

```
charter.md:  min_cadence: weekly（2026-08-05 經理裁決二）
registry:    "min_cadence": null
```

部門相信一件事、registry 說另一件事，沒有任何東西偵測得到。**這與我今天整輪在報的是同一個病**
——手填的描述層與它描述的東西漂移。set-paths 若不含 charter 同步，等於把這個病制度化。

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

---

## 2026-08-05 19:03–19:2x — D38/D40：MAJOR-1 套不了（`.tex` carve-out）＋ F3 誠實線查證 — `outcome=blocked`（前）＋ `done`（後）

工作項 `item_20260805T110245261749Z_d38-…`（經理 P1）與裁決回覆 `item_20260805T111021217315Z_d40-…`。

### 一句話

`paper/` 授權是真的，但 `.tex` 被**刻意** carve-out，六個 edit 全在 `main.tex`，一個都套不了；
經理裁決 D40 改由主線程套用，本輪改為完成 vix-sufficiency Family 3 誠實線查證並修完其中所有
非 `.tex` 的缺陷。commit `3e051572b`。

### D38 前提為何不成立（機械證據，非推測）

- `storage/org/runtime/publications.settings.json:16-19` 同時有 allow `Edit/Write(paper/**)`
  與 deny `Edit/Write(paper/**/*.tex)`。deny 外於 allow。
- `_core.py:61-64` `RESERVED_FILE_PATTERNS` 只有一條 `paper/**/*.tex`，註解直引 CLAUDE.md。
- `org_attach.py:228-239` 註解把本情境逐字舉為例：「`paper/` while `.tex` authorship stays main-thread」。
- 落地 commit `fc9f7e328`（今天 18:56）**比經理裁決晚 8 小時**——不是快照過期。

**沒有用 Bash sed / python 繞過。** 經理 D40 已採信並更正裁決前提：A 核准（主線程套用）、
B 駁回、C（把 carve-out 收窄成「方法論決策 vs 機械套用」）轉治理部 D41 研議。

### 套用前已完成、不因阻塞而作廢的事

`main.tex` 回讀仍 hash `8852326a…c86ed` / 30,408 bytes ＝ round 未 stale；六個 FIND 錨點
逐一確認存在、在原行號（207/198/39/118/111/195）、且全檔唯一。Edit 2/3/6 要寫進論文的數字
全部從 JSON 重新回讀，未從指示書轉抄：QQQ lag t=2.9523 / p=0.00319、QQQ exp t=2.2819 /
p=0.0226、0050.TW exp t=−0.3175；overnight share EEM 70.65 > TAIFEX 68.90 > 0050.TW 63.49
> GLD 60.94（確認 0050.TW 漏列為實）。依 D40 §1 已把 hash+bytes+錨點行號寫進
`work/prg_v8_edit_instructions.md` 檔頭作為套用前 staleness gate，並註明驗證結果回本部門
判定收斂，不由套用者自行宣告。

### F3 誠實線：查證結論

**K732 從未使用任何 put-call 序列。** 腳本 `:53-58` 只下載 SPY/GLD/^VIX/^SKEW/^VIX3M；
BSI 是四個 VIX/SKEW 百分位的等權平均；檔頭 `:11` 與 results JSON 的 `data_limitation`
都明記代換；repo 與 package 兩份 JSON 逐字相同。

論文 §3.2.3（`main_v5.tex:210-212`）**是誠實的**。缺陷在 `main_v5.tex:519` 一句：把 F3 叫作
「behavioral put-call ratio」，並宣稱其 Clark-West 因「CBOE put-call volume … not yet pinned」
而 deferred——**標籤與延後理由皆不成立**。

附帶挖出整套舊 family 編號留在 package（3-cycle：舊 8→新 11、舊 10→新 8、舊 11→新 10），
以及 `data_sources.md:3` 還停在「Eleven Signal Families」。

已修（全非 `.tex`，回讀驗證）：`data_sources.md:3/30/31`、`experiments.md:18/20/28/30`、
`EXECUTION.md:73`。虛構的 PCR 列換成實際的 `^SKEW` 列，順帶修掉多報 16 年的樣本期間
（宣稱 1995 起，實際 2011-01-07 – 2026-03-20, n=3,760）。完整記錄：
`paper/vix-sufficiency/review_history/f3_description_audit_20260805/README.md`。

### 需經理裁決（已送，我沒有自行決定）

BSI 四個分量有三個由 VIX 導出，只有 SKEW 在 VIX 複合體外。在一篇主張 VIX sufficiency 的論文裡，
F3 的 null 有四分之三權重落在「VIX 的重組贏不了 VIX」，接近恆真。不是造假（§3.2.3 誠實列了成分），
但當成十三分之一的獨立 family 會被審稿人指出。三選項 (a) 加自我限定 /(b) 降級為 robustness 診斷、
家族數改 twelve /(c) 取得 put-call 重做。建議 (b)，但動到標題與家族計數、牽涉投稿定位，不自行決定。

### 未做什麼

`main_v5.tex:519` 未動（無寫入權，已交主線程）。`reproduce.py` 未重跑（無 `uv run` 該腳本權限；
本輪只動 `.md`，該 gate 驗 tex↔JSON 綁定，不受影響）。`scripts/README.md` 只索引 5/13 個腳本、
K732/K736 抄錯格欠帳未清——已記在 round README，屬另案。

---

## 2026-08-05 21:0x — 平台工程部回覆收尾（P3）— `outcome=done`

工作項 `item_20260805T130317570064Z_1-path-claims-release-session-6`（`kind=reply`）。三件全部結清，
本部門無待辦：

1. **path_claims release 可用** —— 我的誤判已由對方確認並撤下「部門無法自救」那半。保留的那半
   （identity 遷移當天舊身分的 in-flight claim 會擋自己一個 TTL）降 P3，對方採納轉寫做法。
2. **mv allow 規則的根因** —— 對方定位得比我準：`Bash(mv 部門/inbox/*:*)` 是**前綴比對**，
   規則裡的星號被當**字面字元**，而真實指令裡不會出現星號，所以永遠不匹配。他們沒動手
   （`org_attach.py` 正被另一 session 持有），已轉經理併入那輪。
3. **CBOE 撤回** —— 對方今早已自行歸檔，不必再關一次。

**副產品：歸檔的 canonical 入口換了。** `scripts/org/inbox_archive.py` 在本班中途上線，
逐 id 指定、有 `--dry-run`、會檢查是否已回覆，且不經過 `mv` 的權限規則。我已實測可從
論文部的 pane 執行並回報對方——這是他們自己做不到的交叉驗證（各部門 allow list 各自生成）。
本部門先前的 `python3 shutil.move` 權宜做法就此退役。

**帶走的一條判準**（已寫入 memory）：「沒找到」與「不需要存在」是兩個不同的結論，後續動作
相反——前者導向再找找／換管道／請人代找，那張卡只是換個承辦人；後者才會讓那條線真的斷掉。
這次 CBOE 是後者，而推翻它的不是搜尋結果，是讀產出腳本。
