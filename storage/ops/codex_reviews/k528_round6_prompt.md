# K528 round-6 獨立審查（對抗性）

你是第六輪獨立審查者。目標**不是**確認我修好了，而是**設法推翻**我的每一項宣稱。
預設立場：宣稱為假，除非我留下的證據能讓你自己重現。

## 環境

- repo（linked worktree，可直接讀寫執行）：
  `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp`
- 受審 commit：`52fde3f49`（branch `k528-nfp-official-dates`）
- 前一輪 commit：`17f12d16c`；再前一輪：`73dca01d0`
- 實驗目錄：`experiments/k528/`
- 你可以跑 `uv run python`、`uv run --extra dev python -m pytest`、`git show <sha>:<path>`。
- 跑實驗腳本本體需要 FRED key：
  `set -a; . /Users/yhlai0911/volpred-research/.env.local; set +a`（重跑約 60 秒，會連網）。
- **請勿** merge、勿 certify、勿改 `storage/reports/feed.json` 或 `storage/memory/*.json`。

## 這條審查鏈的歷史

round 5 判 FAIL，四個 blocking defect：

- **B1 Friday estimand 錯置** — 程式用**映射後的交易 session weekday** 篩 237 筆，
  不是官方**發布日** weekday。253 個有效發布中 243 個發布日在週五，6 個 Good Friday
  被映射到下週一而排除。README 卻宣稱識別「在週五公布的 NFP」。
  最小修法：同時保存 release_date / session_date；若沿用現分析，全文改稱 Friday
  trading-session estimand 並揭露那 6 個 Good Friday。
- **B2 raw 與 selected 同步截短端點月仍通過** — 70 天容忍容得下整個首/尾月消失。
  最小修法：釘住預期首尾月份或發布數（需獨立於被截短的 feed）；新增對抗測試。
- **B3 價格資料尾端截短不 fail closed** — `yf.download` 後無覆蓋/freshness gate；
  VIX `ffill()` 會沿用陳舊值。最小修法：覆蓋 gate、`n_outside_price_sample == 0`、
  限制 VIX forward-fill 最大資料年齡。
- **B4 未定義多重比較 family 卻宣稱 5% 顯著** — 22 個 inferential outputs。
  最小修法：指定 rerun 前既有的 confirmatory endpoints、報 Holm 調整值、
  其餘明標 exploratory。family 未定義前不得無限定地寫「顯著」。

殘留 gap `single-month upstream truncation` 於 round 5 被裁決為 **blocking**。

commit `17f12d16c` 修了這四項。隨後一輪**收件審查**（artifact:
`experiments/k528/k528_round5_collection_verdict.json`，未 commit 的
untracked 檔，你可以讀）判定：**B2 / B3 PASS**（該審查者自行重現了修復前後行為），
**B1 / B4 FAIL** —— 理由是分析層修好了但**面向讀者那層沒改**，同一產物內兩個口徑並存。

## 我這一輪（commit 52fde3f49）宣稱做了什麼

請逐條查證，並主動尋找我**沒宣稱**但可能弄壞的東西。

1. **B1 殘留**：`experiments/k528/build_article_correction.py`（更正文產生器，
   `--apply` 由主線程對線上文章執行）原有七處寫「在週五公布的 NFP」，
   且 `:108` 寫「253 場 NFP 裡有 237 場落在週五、16 場不是」——
   把 release-dated(243) 與 session-traded(237) 併成一句錯話。
   我全部改寫為「消息落在週五交易日的 NFP」並講明 243/237/6 的關係。

2. **我宣稱收件審查漏掉了東西**：retired 口徑也存在於**產生出來的結果檔**：
   `k528_nfp_event_study_results.json` 的 `conclusions[1]`（"Scoped to Friday releases"）
   與 `statistical_tests.B_nfp_vs_friday.claim_scope`（"ON A FRIDAY" / "must say 'Friday NFP'"），
   以及 `k528_nfp_official_dates_results.json` 的 note。
   我改的是 `k528_nfp_event_study.py` 裡的字串來源後**重跑**產生，不是手改 JSON。
   → 請查證我確實沒有手改 JSON（例如比對腳本字串與 JSON 內容是否一致、
     或自行重跑看是否重現）。

3. **B4 殘留**：`README.md` 原「可以寫的」那行授權下游寫
   「**事先聲明的**六項 confirmatory family」，與同檔 `pre_registered=false` 矛盾。
   已改為不宣稱預先登記，並要求同時揭露「對全部 22 個 outputs 校正後不拒絕」。
   `conclusions[1]` 的 "rejects at 5%" 也改成明標 nominal 並指向 `multiplicity`。

4. **三個新迴歸 gate**（`tests/test_nfp_official_release_dates.py`，65 → 69 tests）：
   - `test_friday_estimand_pins_release_vs_session_and_names_the_good_fridays`
   - `test_reader_facing_surfaces_do_not_resurrect_the_release_dated_estimand`
   - `test_readme_does_not_sanction_a_pre_registration_claim`
   我宣稱三個都**做過反空洞實測**：把 pre-fix 版本擺回去各自轉紅
   （A 對 `73dca01d0` 的結果檔、B 對 `17f12d16c` 的產生器、C 對 `17f12d16c` 的 README），
   現況全綠。**請自己重跑驗證這個宣稱，不要採信我的敘述。**
   同時請判斷這三個 gate 是否只是「釘字串」而擋不住真正的語意回歸。

5. **範圍外改動**：原 test 斷言 `"Friday NFP" in claim_scope`，我改成釘 session 措辭
   並額外要求明文否定 release-dated 讀法。我宣稱這是**收緊**不是放寬 —— 請裁決。

6. **數字**：我宣稱在呈報精度上完全未動（1.1890x、p=0.0209、p=0.1121、2.03x、r=0.440），
   但如實揭露重跑會重新下載 yfinance，adjusted-close 浮點微幅變動使 1322 個 numeric leaf
   改變，最大相對變化 1.65e-3。請查證這個揭露是否誠實、以及這種不可 bit-reproduce
   的性質是否應被視為 blocking。

## 請特別攻擊這些點

- B1 的**裁決本身**：我沿用 session estimand（relabel）而非改用 release weekday 重跑。
  理由是「被比較的是 session 報酬、被固定的是該 session 的星期效應；改用 release weekday
  會把六筆週一報酬丟進純週五對照組，正好把要修的污染放回來」。這個理由站得住嗎？
  還是這只是為了避免重跑而找的說辭？如果站得住，README / 結果檔 / 產生器
  是否**每一處**都已改用 session 口徑、且沒有殘留會誤導讀者的句子？
- B4：family 是在看到資料**之後**才定義的（git 可查：family 標籤首見於 `17f12d16c`，
  比重跑 `e42dc25ad` 晚約 26 小時；但六個 endpoint 本身首見於 `461d23ae4`，早三個月）。
  現在的揭露是否足夠？「六項 confirmatory family」這個切分本身是否還有 cherry-pick 空間？
- B2 / B3 前一輪被判 PASS —— **請不要繼承那個結論**，自己再攻一次。
  特別是：`KNOWN_MISSING_MONTHS` allowlist 與端點期望合起來還有沒有後門？
- 有沒有**新引入**的缺陷（我改字串時弄壞語意、測試互相遮蔽、gate 被繞過）？

## 輸出格式

輸出一份 Markdown 裁決，直接輸出到 stdout（不要嘗試寫檔）。結構：

```
# K528 round 6 verdict
verdict: PASS | FAIL
reviewed_commit: 52fde3f49

## 逐條裁決
- **B1** — PASS/FAIL — 證據（file:line 或可重現指令）+ 理由
- **B2** — ...
- **B3** — ...
- **B4** — ...
- **殘留 gap（single-month upstream truncation）** — 裁決 + 理由

## 新發現的缺陷（若有）
（每條：嚴重度 blocking/non-blocking、證據、最小修法）

## Non-blocking observations

## 我獨立重現了什麼
（明列你自己實際跑過的命令與看到的輸出，區分「讀碼推論」與「實測」）
```

每一條裁決都要能指向**你自己看過的證據**。若你只是讀碼而未實測，明講。
