# v8 round — staleness gate 複驗與 Edit 1 處置確認

**時間**: 2026-08-05T13:1xZ（台灣時間 21:1x）
**執行**: 論文部
**觸發**: 經理 P1 工作項 `item_20260805T134851468670Z_prg-v8-staleness-gate-round-sta`
（老闆 telegram msg 1615-1619 點名最急）

---

## 1. Staleness gate（獨立複驗，非引用經理的代驗結果）

腳本：`scratchpad/verify_prg_v8_anchors.py`（唯讀，可重跑）

```
sha256  actual 8852326a7b77eb3455038f558c823dcefa311a282697f82ff2e5d798813c86ed
        expect 8852326a7b77eb3455038f558c823dcefa311a282697f82ff2e5d798813c86ed   MATCH True
bytes   actual 30408   expect 30408   MATCH True
```

## 2. 六個錨點的全檔唯一性（經理未驗的那一格，本輪補上）

Gate 只證明「整檔未變」，不證明「每個 FIND 唯一命中」。後者才是逐字 find/replace 的正確性前提
——一個字串若出現兩次，套用者會改到錯的那一處，而 hash 完全通過。所以這一格必須單獨驗。

| Edit | 全檔出現次數 | 命中行號 | 期望行號 | 結果 |
|---|---|---|---|---|
| 1 MAJOR-1 FRL 具名指控 | 1 | 207 | 207 | OK |
| 2 MAJOR-2 robustness 假斷言 | 1 | 198 | 198 | OK |
| 3 MAJOR-3 abstract 未限定 | 1 | 39 | 39 | OK |
| 4 MAJOR-4 bit-identical 超出證據 | 1 | 118 | 118 | OK |
| 5 MINOR-1 家族事後定義 | 1 | 111 | 111 | OK |
| 6 MINOR-2 高佔比組漏列 0050.TW | 1 | 195 | 195 | OK |

**verdict: ROUND VALID — 六筆指令全部仍然有效，可直接套用，不需重出一輪。**

## 3. Edit 1（MAJOR-1）處置：維持最小修法，且理由與投稿策略無關

**動作**：`main.tex:207` 移除 `\citep[e.g.,][]{Tsiakas2008,Todorova2014}`，句子其餘不動。
兩個 key 在 `:55` 仍被引用，無 `\bibitem` 成為孤兒（套用後以編譯確認無 undefined citation）。

**為什麼是移除，而不是反轉成正面引用**：

移除一個未經證實的指控，不需要外部文獻確認；把它換成一個未經證實的讚許（「兩篇都是 coherent
open-time 的先行者」），則需要。前者的舉證責任在稿件自己——稿件提出指控卻拿不出證據，撤回即可；
後者是一個新的正面斷言，需要讀原始 PDF 才能成立，而本輪 `WebFetch` / `curl` 均被權限層擋下，
只有二手來源。**證據不足時往「說得更少」修永遠安全。**

**為什麼這與投稿策略無關**（經理 P1 指令特別點出這點，我同意並補強）：

即使本文不投 FRL、即使 Todorova & Souček 從未在 FRL 發表，這句話還是必須撤——因為
研究誠實原則下，**無證據支持的具名方法論指控本身就不能留在稿件裡**。FRL 這層只是讓後果更難看
（審稿人可能就是被指控者），不是撤除的理由。把它當成投稿策略問題會得出「換個期刊就能留著」的
錯誤結論。

**稿件自我矛盾（獨立於前述兩點的第三個理由）**：`:103` 明說 mixed comparison 唯一已知實例是
「including earlier drafts of this paper」，`:106` 進一步論證這個慣例「not a straw man」正是
**因為**舉不出已發表案例。結論段接著舉了兩個。依序讀的審稿人會直接撞上這個矛盾。

## 4.「誰套用」這一格：目前是空的

論文部**產得出交接件但套用不了**。本輪已重測，非引用舊結論：

- `storage/org/runtime/publications.settings.json:16-19` 仍是 allow `Edit/Write(paper/**)`
  ＋ deny `Edit/Write(paper/**/*.tex)`，deny 外於 allow，檔案未變更。
- 實際跑一次 Edit 1 的逐字替換 → `File is in a directory that is denied by your permission settings.`

**未以任何方式繞過權限層**（無 `sed -i`、無 shell 重導向、無 python 寫檔）。

**一個容易漏掉的操作事實**：解鎖是**兩步**，不是一步。平台工程部改了生成端的 settings 之後，
**執行中的 pane 不會自動生效**——權限是 attach 當下載入的快照（今天早上 registry 已 grant
`paper/` 但我這班仍要等 re-attach 才看得到，就是同一個機制）。所以若裁決由論文部套用，
必須是「改 settings → re-attach 論文部 pane → 才可套用」。只做第一步會看起來修好了，實際仍擋。

這一格由經理裁決，論文部不自行選擇承辦人。
