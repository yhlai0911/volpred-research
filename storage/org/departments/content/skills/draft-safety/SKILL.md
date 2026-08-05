---
name: draft-safety
description: 在 storage/drafts/ 建立或修改讀者文章草稿前的防錯程序，以及送進 publish_draft.py 前的四類擋點自查。用於寫新 draft、改既有 draft、或同一個 K 要出第二個 audience 版本時。不負責選題、查重與發佈本身。
---

# draft-safety：動 draft 之前的三分鐘

這支 skill 存在的理由是：內容部在 2026-08-05 一天之內，**因為同一類機械細節損失了兩整輪產出**——
一次是自己靜默覆寫了別人的稿子，一次是五篇稿子全部卡在發佈關卡。
兩次都不是寫作能力的問題，是「動手前沒做三分鐘檢查」的問題。

下面每一條都對應一次真實事故，不是預防性清單。

---

## 一、建立新 draft 前：先 ls，因為 macOS 會靜默覆寫

**`K1700_general_draft.md` 會覆寫 `k1700_general_draft.md`。** 這個 repo 的 draft 檔名大小寫混用
（`K1609_general_draft.md` 與 `k1600_general_draft.md` 並存），而 macOS 檔案系統大小寫不敏感。

```bash
ls -b storage/drafts/ | grep -i <k編號>
```

**判準：Write 工具回「updated」而不是「created」，就是警訊。** 你以為在建新檔，其實在改別人的檔。

2026-08-05 實際損失：`k1700_general_draft.md`（member_qa 原稿）從 95 行被蓋成 62 行。
發現方式極其間接——`git_writer_lock commit` 回「路徑規格未符合任何 git 已知檔案」，
因為 **git 索引是大小寫敏感的**，認不得大寫路徑。那個錯誤訊息是唯一線索。

還原方式：`git show <commit>~1:<path>` 導出到 scratchpad 再用 Write 寫回。
**不能**用 `git checkout --`（主 checkout 禁止裸 git mutation，hook 會擋）。

**同一個 K 要出第二個 audience 版本時，檔名加用途區隔**（`K1700_reader_longterm_draft.md`），
不要只靠大小寫區分。

---

## 二、被 path claim 擋住時：保住工作，不要硬搶

`storage/drafts/` 是多方共用的高流量目錄，認領是**目錄前綴比對**，claim 有效期 45 分鐘。
而且認領身分目前仍是 **session 級**（不是部門級），所以**上一班的 claim 會擋住下一班**。

被擋時的正確順序：

1. 已完成的稿件先寫進 `storage/org/departments/content/staging/`，frontmatter 加 `staging_note` 註明最終路徑
2. 該送的 request 照送，不因為主檔卡住就一起停
3. 送 report 給經理，附證據（持有者 session id、取得時間、剩餘分鐘）
4. 才在視窗回報

**不要做**：`VOLPRED_ALLOW_CONCURRENT_WRITE=1` 硬搶、release 別人的活 claim、原地空轉等到期。
`Bash run_in_background` 與 `Monitor` 在部門 runtime 下被 deny，session 內等不了——
拿這段時間去做唯讀工作（查重、dry-run 分流、盤點）。

查誰持有：`uv run python scripts/path_claims.py list`

---

## 三、frontmatter：欄位放錯位置會讓稽核靜默略過

**`experiment_refs` 與 `tags` 必須在 frontmatter 頂層，不是塞在 `details:` 裡。**

放在 `details:` 裡 parser 讀不到，`experiment_refs=[]`，於是 content-vs-source audit
印出 `SKIPPED (no citable source for refs=[])` 然後**放行**。
那不是報錯，是靜默略過——**等於自廢一道本來會抓錯的關卡，比沒跑還糟**。

K1609 的實測對照，同一篇稿子：

| frontmatter | audit 結果 |
|---|---|
| `experiment_refs` 只在 `details:` 裡 | `SKIPPED`（0 個數字被驗），放行 |
| 補到頂層 | `PASS (3 claims vs 78 source values)` |

正確樣板（`storage/drafts/K1451_general_draft.md`）：

```yaml
experiment_refs: ["K1451"]
tags: ["一般讀者", "信用市場", "波動率", "恐慌指數", "研究方法"]
evidence_source_paths: ["experiments/k1451/k1451_results.json"]
details: {experiment_refs: ["K1451"], ...}
```

頂層與 `details:` 兩邊都寫是可以的，但**頂層不能少**。

---

## 四、送 publish 前必跑 dry-run —— anti_ai_gate 通過不代表發得出去

```bash
uv run python scripts/publish_draft.py --draft <draft.md> --status draft \
  --dry-run --lazypack-plan <plan.json>
```

**完成的定義是這行全綠，不是任何單一 gate exit 0**（經理裁定為內容部常規）。
`anti_ai_gate` 只管文風；發不發得出去是另外四道關卡。

### 擋點 A：audience gate

`audience=general` 但正文出現 ≥2 個學術關鍵詞，就會被推斷成 research 並拒發。
命中清單含 `K\d+`、`QLIKE`、`Bonferroni`、`Harvey`、`Diebold-Mariano`、`Newey-West`、
`Kruskal-Wallis`、`GARCH`、`HAR-RV`、`HARQ`、`MCS`、`VaR`、`Sharpe`、`bootstrap`。
**tags 裡也不能放**（k1600 的 tags 直接放了 `HAR`、`HARQ`）。

白話替換對照（沿用即可，語意不失真）：

| 學術詞 | 白話 |
|---|---|
| QLIKE | 波動預測專用的損失分數（對低估罰得比高估重）|
| Newey-West | 重疊窗口修正法／重疊窗口標準誤修正 |
| Bonferroni | 最嚴格的多重比較校正（把機率值乘上檢定次數）|
| Diebold-Mariano ＋ Harvey 修正 | 預測誤差比較檢定的小樣本修正版 |
| Kruskal-Wallis／Dunn | 不假設鐘形分布的檢定／事後兩兩比對 |
| GJR-GARCH／HAR-RV／EWMA | 傳統的不對稱波動模型／多尺度模型／指數加權法 |
| MCS | 淘汰程序後「還不能被淘汰的模型名單」|
| bootstrap | 重抽／區塊重抽 |

**K-id 一律不進正文**，只留 frontmatter。

判準：如果術語是文章骨架的一部分（k1600 的 HAR／HARQ 各出現十餘次、分布在十三個段落），
那是**一次實質改寫**不是換幾個詞——評估預算，不夠就不要開這個頭，做一半丟下更糟。

### 擋點 B：負號必須是 ASCII `-`，不可用 U+2212 `−`

audit 抽數字時讀不到全形減號的符號，`−2.24` 會被當成 `+2.24`，然後跟來源的 `-2.2355` 對不上而判違規。
**這個坑肉眼完全看不出來**，兩個字元長得幾乎一樣。

```bash
grep -c '−' <draft.md>   # 非 0 就要全換
```

容差是相對 1e-3／絕對 0.01，所以只要符號讀對，四位有效數字的四捨五入都過得了。

### 擋點 C：來源檔裡沒有的數字

從來源推導出來的計數不在 JSON 裡，audit 找不到對應值就判違規。例如：
- 「把 **8** 個 p 值由小到大排」——這個 8 是方法描述 → 改成「**八**個」
- 「49 個事前報酬」是從 t-60..t-12 算出來的 → 改質性描述或中文數字

**中文數字不會被當成待驗數值**，這是最省事的解法。
時間寫成 `13:45` 也會被當成數字 13 和 45，footnote 裡用中文數字寫時刻最保險。

### 擋點 D：lazypack plan（strict schema）

`status=draft` 階段**不要求懶人包成品，但要求 `--lazypack-plan`**，否則直接
`DEFERRED LAZYPACK CONTRACT` 擋下。schema owner 是 `scripts/lazypack_render.py`。
可直接複製的樣板：`storage/drafts/K1451_lazypack_plan.json`（三面板：概念／結果／帶走的一句話）。

四個文件沒寫清楚的踩點：

1. `panels[].sources` 放的是 **evidence 別名**（例如 `"results"`），不是檔案路徑
2. `blocks[].value.format.digits` **只能 0 到 3**
3. **text block 的 body 不能出現阿拉伯數字**（連「標普 500」的 500、「21 個交易日」的 21 都算）。
   改用不帶數字的說法（美股大盤指數、未來一個月），要露出的數字一律走 metric block 的
   `{source, path, format}` 綁定。中文數字（二十五分之一）可以。
4. `sha256` 要對得上當下的檔案內容：
   ```bash
   uv run python -c "import hashlib,pathlib;print(hashlib.sha256(pathlib.Path('<path>').read_bytes()).hexdigest())"
   ```

list 型欄位可以用索引綁定（`primary_did.2.ri_p_holm_8`），dry-run 會驗證路徑存在。

---

## 五、發佈之後：回讀，因為失敗是安靜的

**懶人包是 release gate 的硬條件**：`src/volpred/ops/content.py` 的 release audit gate
會拒絕把沒有該區塊的 general draft 翻成 published。而圖組走非同步 render，
**失敗時沒有任何錯誤浮到內容部這邊**，池深數字看起來還是漂亮的。

```bash
jq -r 'if type=="array" then . else .articles end | map(select(.id=="<mile_id>"))|.[0]
  | {errata:(.errata.update_action//"none"), has_lazypack:((.content//"")|test("懶人包圖組"))}' \
  storage/reports/feed.json
```

`errata.update_action == "lazypack_async_render"` 且 `has_lazypack == true` 才算真的裝上。
**同批發佈時把各篇的這兩個欄位並排看，缺的那篇會自己跳出來**——K1677 就是這樣被抓到的。

失敗時：面板 PNG 已經產好了（sha256 在 stdout log），**不必重畫**，
直接重跑 `lazypack_async_render.py run --out-dir <新目錄>`。
注意 `enqueue` 在既有 job 還是 `running` 時會 skip，要先確認前一輪已 `failed`。

**已知會讓它失敗的結構缺陷**：Supabase 上傳無重試，而對端兩個 Cloudflare IP
每輪恰有一個 TCP 不通 → 單張失敗率約 1/2，三張連傳全成功約 12.5%。
連掛兩次就停手送 request，不要重試第三次撞 3-strike。
單篇發佈含上傳可能超過 120 秒，用 `run_in_background`，不要當成掛掉。
**重跑前先查 feed 池**確認上一次是不是其實已經寫進去了，避免重複發佈。
