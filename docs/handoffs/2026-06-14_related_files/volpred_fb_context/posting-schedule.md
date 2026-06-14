# VolPred FB Posting Schedule

Updated: 2026-06-14 13:42 CST

Latest rerank status: 2026-06-14 02:24 CST 已刷新 `https://volpred.zeabur.app/` 最新 feed。這輪新增納入 7 篇本地 library 尚未收錄、且已逐篇打開全文讀完的新候選：`mile_74d12ac6`、`mile_483425f2`、`mile_47ff52c7`、`mile_40c66bef`、`mile_1b56cf6b`、`mile_9d646fae`、`mile_2fb1dfb3`。另外也重讀了既有 queue 裡的 `mile_b65e01ee` 脈絡，並沿用已存在的 `mile_5e0786d0` 外部 duplicate cache。這輪先查 `posted-links.json`、`profile-state.md`、dashboard 與既有 library，確認本地沒有 Ivan 已發 exact duplicate；再對 7 篇新文逐篇讀全文後才評分，並補做 exact-id 公開 Facebook-visible 搜尋。目前沒有看到 public VolPred/platform exact duplicate。排序上把題材最廣、最容易接住一般讀者的「跌了就多買一點」、「股票＋黃金再加長債」與「策略越複雜不一定越強」拉到最前；新鮮但較方法論的 0DTE / 尾部風險 / 量測方法文往後排；和現有模型題過近的 `mile_5e0786d0`、`mile_c5881a5b`、`mile_97e0bb31` 維持 reserve。這輪只更新發文庫與排序，沒有發文、留言或做任何互動。

Latest runner status: 2026-06-14 13:42 CST runner 依最新 queue head 改為重試 `mile_9d646fae`，先重開 VolPred v3 全文並刷新 exact-id / exact-title 公開 duplicate 搜尋，兩者都過關；但 Chrome 視窗層級掃描後，`Ivan Lai | Facebook` 仍被 `查看更多 Ivan Lai 的內容` 登入 / QR 驗證 modal 蓋住，無法安全確認 Ivan live session、也無法完成 content library duplicate check 與發文 / 第一留言，因此本輪再次停止，沒有發布任何 VolPred 新文。

## This Week Queue

| Slot | Candidate | Status | Score | Reason |
|---|---|---|---:|---|
| 2026-06-13 07:40 | `mile_651c242d` 好策略被成本吃掉 27%：11 個 VT 策略的實施費用拆解 | posted | 92 | 2026-06-13 07:47 CST 已發布；主文無連結，第一留言全文連結已驗證可見。 |
| 2026-06-13 13:40 | `mile_5ef55c52` 同樣從 5 萬美元出發，20 年後差到快 5 倍：問題常常不是你不夠會算 | posted | 89 | 2026-06-13 21:40 CST 已補發完成；主文 permalink 與第一留言全文連結都已驗證可見。 |
| 2026-06-14 07:40 | `mile_9d646fae` 跌了就多買一點，真的比較聰明嗎？把 5 段歷史排開後，答案沒有想像中穩 | blocked | 89 | 2026-06-14 13:42 CST 全文與公開 duplicate 檢查都過關，但 Facebook 仍卡登入 / QR modal，無法安全確認 Ivan live session 後發布。 |
| 2026-06-14 13:40 | `mile_1b56cf6b` 股票加黃金還不夠？多放一點長債，報酬會少一點，但跌的時候真的差很多 | ready | 88 | 資產配置問題夠大眾，實務價值高，能接在逢低加碼文後面不撞題。 |
| 2026-06-14 19:40 | `mile_2fb1dfb3` 投資策略是不是越複雜越厲害？我們把 14 套方法排在一起，答案有點反直覺 | ready | 86 | 「複雜不等於更強」好轉發，全文已讀且和前兩篇讀者角度銜接順。 |
| 2026-06-15 01:40 | `mile_47ff52c7` 量今天的波動，選哪種方法差很多？五種工具實測 20 年 SPY 資料 | ready | 85 | 方法題但切口夠生活化，可把 VolPred 的研究感帶出來。 |
| 2026-06-15 07:40 | `mile_74d12ac6` 0DTE 真的把 SPY 的波動搬進日內了嗎？2022 斷點檢定只答對一半 | ready | 83 | 新鮮度高，但仍偏市場微結構，放在前段後半比較安全。 |
| 2026-06-15 13:40 | `mile_483425f2` 同樣都在尾巴加保險，為什麼只有這個模型真的補對？ | ready | 82 | 實務價值不差，但風險模型味道較重，避免排到太前。 |
| 2026-06-15 19:40 | `mile_40c66bef` 風險模型愈花俏愈準嗎？這次市場給了相反答案 | ready | 79 | 和隊列裡多篇模型題較近，先放在第二波末端。 |
| 2026-06-16 01:40 | `mile_b65e01ee` 波動率預測最準的模型，為什麼算風險卻輸得最慘？ | ready | 86 | 分數高，但與 6/15 的模型題群過近；保留到下一段較不擠。 |
| 2026-06-16 07:40 | `mile_23312ae9` 做了 305 次投資研究後，真正活下來的結論有多少？ | ready | 84 | meta 角度仍有價值，但新鮮度已被 6/13-6/14 新文壓過。 |
| 2026-06-16 13:40 | `mile_c1f5a8f6` 降息交易退了，MOVE 也退了：為什麼 VIX 還停在 19？ | ready | 84 | 還有 Fed 時效，但排太前容易連撞多篇波動題。 |
| 2026-06-16 19:40 | `mile_77795ca2` Fed 開會那天 VIX 跳了 5 點，然後呢？ | ready | 86 | FOMC 題材仍可用，但已不適合再壓到前兩天。 |
| 2026-06-17 01:40 | `mile_37df0259` 中東風險還在，OVX/VIX 卻從 4.17 降到 2.90：油市恐慌怎麼外溢？ | ready | 80 | live 題但受眾較窄，排在週中後半較合理。 |

## Reserve / Hold

| Candidate | Status | Score | Reason |
|---|---|---:|---|
| `mile_5e0786d0` 波動率模型是不是加越多料越好？SPY 這次給的答案是：先學會刪 | reserve | 74 | 全文已讀、duplicate cache 仍有效，但目前和 6/15-6/16 的模型題過近，先讓位給新鮮度更高的廣泛題。 |
| `mile_c5881a5b` 把兩個模型加在一起，反而打敗了其中最強的那一個 | reserve | 73 | 和本輪多篇模型組合/ensemble 題太接近，先避免 queue 過度技術化。 |
| `mile_97e0bb31` K482：MCS p-value 加權 Ensemble 在 5 個市況全輸給等權重 — Timmermann 謎題頻率學派實證 | reserve | 58 | 太技術，這週不適合拉回前排。 |
| `mile_9b76989e` 酒店娛樂業是股市的晴雨表嗎？文獻回顧與十年實證 | reserve | 72 | 文獻回顧偏長，停留力仍弱於前排。 |
| `mile_4e5a221e` 明知道 VIX 在比特幣恐慌時會失靈，為什麼把它關掉還是沒救？ | reserve | 62 | BTC/VIX 題材相對窄，短期沒有比前排更強的催化。 |
| `mile_938a158f` 跌的時候才算數：RS⁻ 跨 8 資產預測力實測 | reserve | 55 | 和半變異題群太近，先繼續拉開間隔。 |
| `mile_872abdc3` 比特幣自己的數據，真的比 VIX 更懂它的波動嗎？ | reserve | 58 | 比特幣題材仍偏窄，不搶本週前排。 |
| `mile_ea4b38b7` 同樣 100 萬，30 年後差 4.9 倍：投資策略真的要看年齡 | reserve | 68 | 仍靠近先前已發的一次投入/分批買與退休規劃題群。 |
| `mile_579ad22f` 債券波動明明最怕利率，為什麼最後還是 VIX 比較有用？ | reserve | 65 | 債券/VIX 題不差，但被更廣泛的新文蓋過。 |

## Automation Behavior

Daily 02:20 rerank job:

1. Refresh latest VolPred feed.
2. Open and read full text for new candidates.
3. Compare against `posted-links.json`, profile notes, dashboard, Ivan live Facebook if cache is stale, and external/platform Facebook-visible posts.
4. Score and rerank using `README.md`.
5. Update `posting-library.json` and this schedule.

Six-hour runner:

1. Select the next `ready-next` candidate by `recommended_slot`, but stop immediately if the current queue head is still marked `needs_review` or `blocked`.
2. Refresh that article and duplicate checks before publishing.
3. Publish only if all guards pass.
4. First comment must be the `全文：.../v3/reports/{id}` link.
5. Cache the final FB URL and check result.

Latest published URL cache:

- `mile_64f2e656`: `https://www.facebook.com/yihao.lai/posts/pfbid0221SjL5VNFiG5d7itQdPgRu9k9f15tyYpbC5opYH3P1ypZUGyQfu1nmGMZ2spgejel`
- `mile_c07025d2`: `https://www.facebook.com/yihao.lai/posts/pfbid022Rub5UYtDCRA5ufexFnnjAnaBeHzjYen8eYNKoxs1rBrnmdsqQv1gweW5dNYqFMyl`
- `mile_166eda01`: `https://www.facebook.com/yihao.lai/posts/pfbid0b2LSL7YwZHiSWmmYiY8GwaWaXRXssaLAwoZfa848g28H7izSKU3QLwhcj9ZUSGmwl`
- `mile_0e1eb5aa`: `https://www.facebook.com/yihao.lai/posts/pfbid0k65D9kqzjFtQnmrpcgoVayyJ6PkU9h4c37MLkPDsNE8SRf5JSXWQHxs9XAULL9G5l`
- `mile_41b7c7d0`: `https://www.facebook.com/yihao.lai/posts/pfbid026hvbjSUN47NwQhVBXaZQCBGKWVoTBCMRXu9dW2PmDjgCVTRycq9LNTDwgoehFFuLl`
- `mile_651c242d`: `https://www.facebook.com/yihao.lai/posts/10226062614951348`

## Missing Considerations To Watch

- VolPred itself may post the same article to Facebook. We need a cached external/platform duplicate check, not just Ivan-local history.
- Time-sensitive posts expire. If market-event articles age past the useful window, downgrade them instead of forcing the slot.
- Six-hour cadence can still be too dense if comments start appearing. Pause before burying a live discussion.
- Facebook comment posting can fail even when the main post succeeds. The runner must verify the first comment, not assume it posted.
- Facebook 有時會先給 publish toast，卻沒有立刻把新文寫回 timeline / content library；這種情況不能假裝成功，必須先鎖成 `needs_review`，若 follow-up 仍無 live row 且 fallback surface 帶有錯誤附件風險，就要升級成 `blocked`。
- Research-category or VIX-heavy pieces should not cluster back-to-back unless live timing forces it.
