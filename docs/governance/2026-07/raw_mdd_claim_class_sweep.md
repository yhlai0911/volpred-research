# raw-MDD-improvement claim class：全量回溯掃描

**日期**：2026-07-13
**觸發**：K1702 §5.4 證明「vol-managing 壓低回撤」在因子層是 scale artifact（raw MDD 改善 5/6 →
除以實現波動後 1/6）。依研究誠實原則 #6（推翻舊結論必回溯更正）+ `feedback_declare_complete_requires_class_sweep`，
回溯範圍不是「改 R3 一條」，而是**整個 claim class**。
**類型**：governance / 研究誠實回溯更正
**機械 gate**：`scripts/tests/test_mdd_scale_artifact_ratchet.py`（唯一 enforcement owner）

---

## 0. 一句話結論

**這個 class 比預期大一個量級，而且最嚴重的暴露不在文章，在論文。**

`paper/vt-trend-following` 的**核心貢獻**是「VT 的主要價值不是 alpha 而是 **drawdown insurance**」——
這個主張**從未對「你只是持有得比較少」這個虛無假設做過檢定**，且它唯一的防線（Calmar）已被 K1265b 證明
救不了 MDD claim。這是投 top-tier 的稿件，屬 **submission blocker**。

同時，K1265b 挖出一個**比 K1702 原本的發現更深一層**的方法論問題：

> **只匹配「實現波動」是不夠的。正的 exposure-matched gap 也不能證明擇時能力 ——
> 一個時機完全相反的策略同樣拿得到正 gap。**

因為匹配無條件波動**沒有匹配到波動的路徑**：離散的權重把風險集中成爆發，而回撤是持續失血累積出來的。
唯一誠實的判準是「gap 對照它自己的相位隨機化 null」。在那個判準下，K1265 **0/3 通過 Holm**。

處置原則：**不是全面撤回，是全面降級措辭 + 補正確的檢定**（「未證實」≠「不存在」；MDD 是單一極值
統計量，檢定 power 有限）。

---

## 1. 掃描範圍與 population count（可驗證）

| 面向 | population | 命中 | 方法 |
|---|---|---|---|
| **知識庫** `storage/memory/knowledge.json` | **2,504** entries | 446 提及 drawdown → **274 是真的 MDD claim** | 全量 re-walk，regex 定 L1 + 逐筆 LLM 判讀 |
| **Feed 文章** `storage/reports/feed.json` | **1,790** articles | 292 帶「回撤改善 × 改變曝險設計」→ 240 無 caveat → **130 以此為賣點** | 同上 |
| **程式碼** `experiments/` + `src/` + `scripts/` | **1,154** drawdown sites | **455 RAW_COMPARISON** | AST + 詞法稽核（`scripts/audit_mdd_scale_artifact.py`） |
| **論文** `paper/**/*.tex` | **64** tex files | **38** 帶 drawdown × 改變曝險的 claim；**0 篇**做過同曝險對照 | regex + 人工查證 |

### 1.1 知識庫逐條判定

| disposition | entries | unique claim_id | 說明 |
|---|---|---|---|
| **scale-artifact-suspect** | **217** | **209** | 有 MDD 改善 claim、曝險不同、**無 scale-invariant 佐證** |
| OK | 41 | 41 | 曝險相同（公平比較）或已有 scale-invariant 佐證 |
| already-corrected | 16 | 16 | entry 自己就標明是機械性（如 N107、K1702） |
| not-a-claim | 172 | 152 | 只是描述統計 / null result / 提及但無 claim |
| **in-class 合計** | **274** | | |

suspect 的曝險分佈：`yes` 193 / `unknown` 22 / `no` 2。

**Seed 清單（任務給的 12 個）的判定**：

| seed | 判定 |
|---|---|
| `R3` | **scale-artifact-suspect** — 已被 K1702 直接推翻（同類資產、同類訊號） |
| `K1265` | **降級措辭**（見 §2，k1265b 實際補跑） |
| `N80` `N84` `N106` `N118` | scale-artifact-suspect |
| `N107` `N136` `N168` | **already-corrected**（自己就寫了 MECHANICAL） |
| `N172` `K40` | not-a-claim（MDD 只是描述統計，claim 在別處） |
| `Q16` | 不是 claim 前綴，是提問編號；其對應內容（idx 641）已在 suspect 中 |

**seed 清單只佔 209 個 suspect claim 的 5%** —— 這正是「起點清單只是 seed，不是範圍」的實證。

### 1.2 Feed 逐條判定（240 篇無 caveat 者）

| disposition | n | |
|---|---|---|
| **correction-notice** | **49**（含 **13 篇 high**） | 主要 claim 就是回撤保護，須發可見更正 |
| add-caveat | 67 | claim 站得住但缺「不同曝險下 raw MDD 不可比」的但書 |
| rewrite-section | 13 | 回撤 claim 是次要但實質的段落 |
| no-action | 111 | null result / 已自我批判 / 同曝險比較 / 只是順帶提及 |

**13 篇 high severity（reader-facing、已發佈、回撤保護是頭條賣點）**：

| id | 發佈日 | 標題 |
|---|---|---|
| `mile_69261902` | 2026-03-21 | 每年付 4% 買一份「永遠不會腰斬」的保險，你買不買？ |
| `mile_2f25cb33` | 2026-03-23 | 一張圖告訴你：什麼時候該用什麼投資策略 |
| `mile_192c2df7` | 2026-03-24 | VT 保險的真實價格：每年 3%，但在恐慌時免費 |
| `mile_f17cf497` | 2026-03-24 | VT 從未失手：20 年 11 次大跌中的 100% 保護紀錄 |
| `mile_3a9e528b` | 2026-03-25 | 你最該擔心的投資錯誤：不是選錯股票，是恐慌賣出 |
| `mile_0f898126` | 2026-03-28 | 你的投資保險值多少錢？VIX 26.6 是關鍵分界線 |
| `mile_ec77e7fd` | 2026-03-30 | 你該用波動率目標策略嗎？一張表告訴你答案 |
| `mile_a3ef3b06` | 2026-03-31 | 債券市場比 VIX 更早知道危險——但研究發現 VIX 一個指標就夠了 |
| `mile_974eb2a8` | 2026-04-05 | 跌得淺 vs 回得快——兩種投資保護機制，你都需要 |
| `mile_0c6b4e0c` | 2026-05-11 | 三種投資人、七大原則：證據導向 VIX 波動率擇時完整指南 |
| `mile_23399029` | 2026-06-07 | 五次歷史危機壓力測試：退休族手上四種策略，哪個真的扛得住？ |
| `mile_2fb1dfb3` | 2026-06-12 | 投資策略是不是越複雜越厲害？我們把 14 套方法排在一起，答案有點反直覺 |
| `mile_b029eb93` | 2026-06-20 | 當壓力測試太「保守」，反而讓結果看起來比較差 |

**教科書級案例**：`mile_7081e702`「COVID 崩盤那天，我的策略只虧了 9%——而大盤跌了 34%」。
若當時部位只有 25%，跌 1/4 是**算術**，不是本事。

**判讀 agent 抓到的一個結構性 pattern（值得單獨記）**：好幾篇「研究誠實」類文章（`mile_921184c5`
「我們犯了一個重大錯誤——然後修正了它」、`mile_a068925d`、`mile_b4304948`）的敘事弧是：
**撤回了灌水的 Sharpe / alpha claim → 然後退守到「VT 真正的價值是壓低回撤」當作救贖式結論**。
而那個退守點**正是本次要更正的 claim**。誠實地撤回一個錯誤，卻退到另一個未經檢定的主張上，
是這個 class 最隱蔽的傳播路徑。

### 1.3 論文（**最高風險，且原任務 brief 沒點名**）

| paper | 暴露 | 嚴重度 |
|---|---|---|
| **`vt-trend-following`** | **核心貢獻**：「The primary benefit of VT is not alpha generation but **drawdown insurance**（22 assets）」。防線只有 **Calmar**，**無同曝險對照**。另用 **MDD Retention ratio**（MDD_VT / MDD_BH）做 bootstrap —— **該比值不是 scale-invariant** | **submission blocker** |
| **`vix-sufficiency`** | 第二貢獻即「**drawdown insurance framework**」 | 高 |
| `vt-insurance-cost` | 「sacrifices 5.40pp CAGR for a **55% reduction** in MDD」。**框架較誠實**（明說是用報酬換保護 = 承認少冒險），但 55% 這個數字仍是 raw 口徑 | 中 |
| `taiwan-vt` | VT vs buy-and-hold 的 MDD 比較 | 中 |
| `leverage-direction` | 「the one durable benefit … 」以 MDD 為主 | 中 |

**查證方法**：`grep -rliE "matched (volatility|exposure)|same realized vol|constant.leverage benchmark|exposure-matched" paper/*/*.tex` → **0 命中**。
沒有任何一篇論文建構過同曝險對照組。

---

## 2. K1265 實際補跑（硬交付，非「建議補跑」）

→ **`experiments/k1265b/`**（`k1265b.py` / `k1265b_results.json` / `README.md` / 圖，seed=42）

複製檢查先過：K1265 的 OOS Sharpe / MDD **逐格吻合**（0.639/0.768/0.670/0.743；−0.552/−0.338/−0.467/−0.276），
所以任何結論差異都來自口徑，不是來自不同的回測。

| 檢定 | 結果 |
|---|---|
| 曝險匹配對照組（同實現波動的常數槓桿 buy&hold，零擇時） | 3/3 為正：+9.8 / +11.3 / +22.1 pp。**但正 gap 不能證明擇時**（見 2.1） |
| **circular-shift randomization**（全枚舉 5,617 個 shift）+ Holm@10% | **0/3 存活**（p = .0347 / .3174 / .1250；門檻 .0333 / .05 / .10） |
| stationary bootstrap，block 階梯 22→1000 | 結論**高度依賴 block 長度**（p 從 .42 掉到 .065），全部列出不挑 |

**K1265 verdict：NOT SUPPORTED，須降級措辭。**
- 「50–62% MDD 改善」→ 分母是曝險完全不同的 buy&hold
- 「**顯著**改善」→ **原實驗從未對 MDD 做過任何檢定**；補上正確檢定後 Holm **0/3 通過**
- 「4/4 managed specs」→ 誤數，只有 3 個 managed spec
- 正確說法：**raw MDD 大幅誇大；「顯著」從未被檢驗；正確檢定下未獲證實。**
  但「未證實」**≠**「不存在」—— MDD 是單一極值統計量，power 有限。

### 2.1 三個溢出到全 class 的方法論發現（比 K1265 本身重要）

1. **【最重要】只匹配「實現波動」不夠；正的 exposure-matched gap 不能證明擇時能力。**
   受控實驗（已固化成 gate 測試 `test_a_positive_exposure_matched_gap_is_not_by_itself_evidence_of_timing`）：
   把策略設計成**時機完全相反**（動盪時**加**槓桿、平靜時減碼，劑量相同），它**仍然**拿到 **+0.85pp 正 gap**；
   而在自己的 shift-null 下 p=0.74，被正確判為無能力。
   **機制**：匹配無條件波動沒有匹配到**波動的路徑**。離散權重把風險集中成**爆發**，而回撤是**持續失血**
   累積出來的 —— 爆發式路徑在相同無條件波動下 peak-to-trough 反而較淺。
   → **唯一誠實的判準是 gap 對照它自己的相位隨機化 null，不是對照 0。**
   （這一條推翻了本文件與 k1265b README 的前一版草稿，兩處均已更正。）

2. **`MDD ÷ 實現波動` 不是真正的 scale-invariant**（連 K1702 的 canonical 口徑也受影響）。
   財富複利 → MDD 對槓桿不具一次齊次性。同一條 buy&hold 路徑在 λ=0.739/1.072/0.871 下，
   比率從 −2.951 變成 −3.157 / −2.895 / −3.052。它是有用的**正規化**，不是**不變量**。

3. **Calmar 不能當佐證。** K1265 三個 managed spec 的 Calmar **全部改善**，仍然沒通過檢定。
   這一條是本次 audit **自己踩到的坑**：第一輪判讀時，agent 依「Calmar = scale-invariant 佐證」
   規則把 **K1265 本人標成 OK** —— 而 K1265 正是這次 sweep 被授權去重驗的對象。
   **12 個僅憑 Calmar 就被判 OK 的條目已全數降級為 suspect。**

---

## 3. 機械 gate（anti-stacking：收編進單一 owner，不新增第 N 個 watchdog）

| 層 | 檔案 | 職責 |
|---|---|---|
| **Runtime 規則本體** | `src/volpred/stats/drawdown.py` | `compare_max_drawdown()` / `assert_drawdown_comparison_is_fair()`：兩序列實現波動差 **>20%** 就 flag / raise，並算出 exposure-matched gap |
| **稽核器** | `scripts/audit_mdd_scale_artifact.py` | 全量掃 `experiments/` + `src/` + `scripts/`，分類 1,154 個 drawdown site |
| **Enforcement owner（唯一）** | `scripts/tests/test_mdd_scale_artifact_ratchet.py` | 13 tests：runtime 規則 + 靜態分類器 + ratchet |
| **凍結 backlog** | `storage/ops/mdd_scale_artifact_baseline.json` | **455 sites，只准變少** |
| **散文 pointer** | `.claude/rules/experiments.md` | 一條硬規則，指向上面的機械層 |

**負向控制已驗證**：塞一個新的 raw-MDD 比較進 `experiments/` → ratchet **FAIL**；移除 → **PASS**。
（gate 通過不等於 gate 會擋，所以這一步不能省。）

**gate 的關鍵性質測試**（`test_pure_deleveraging_shows_a_raw_mdd_improvement_that_is_entirely_fake`）：
把曝險砍半 —— 零技巧、零擇時 —— raw MDD 顯著改善，但 exposure-matched gap **必須 ≈ 0**。
這條 assert 就是「gate 還看得見這個 artifact」的活體證明。若它哪天失效，gate 就死了。

---

## 4. 盲區分析（audit hard rule 要求，不可省）

**我這次的方法可能漏掉什麼：**

1. **【最大盲區】沒有 drawdown 字樣的回撤 claim。** 例如「我的策略只虧了 9%，大盤跌了 34%」——
   純數字比較、沒有「回撤 / drawdown / MDD」任何一個詞。我的 L1 regex 抓不到。
   *部分緩解*：這類文章通常內文別處仍會出現 MDD 字樣（上例確實被抓到了）。但**只在標題出現、
   內文完全不提**的 claim 會漏。**未量化，屬已知殘留風險。**

2. **關鍵字過濾器已證實會漏。** 第一版用「改善」動詞 + 「曝險」關鍵字當硬 gate，結果 seed 清單裡的
   **N80 / N84 / N136 直接掉出去**（它們用純數字表述「MDD −1.35% vs BH −2.21%」，沒有任何動詞）。
   **因此本次放棄關鍵字硬 gate，改為全部 446 筆逐筆 LLM 判讀。** 這是方法上的主動修正，記在這裡
   是為了讓下一次 audit 不要重蹈。

3. **LLM 判讀非確定性。** 緩解：(a) 判讀規則明訂「不確定 → 判 suspect」（false-OK 是危險方向，
   false-suspect 只是多做工）；(b) 事後對所有 OK 做 false-OK 反掃 —— **這一步真的抓到 12 個**（§2.1）。

4. **靜態稽核無法評估「波動差 >20%」。** AST 看不出 runtime 數值。所以靜態層只能 enforce 可靜態檢查的
   版本（「比較 MDD 就必須同時算 scale-invariant companion」）；20% 那條由 runtime helper 擋。
   **既有 455 個 site 是凍結，不是修好。**

5. **`storage/memory/knowledge.json` 已知有重複。** 已用 claim_id 去重（217 entries → 209 unique）。
   但 claim_id 抽取本身有邊界（K1265 的 title 沒冒號 → 落到 fallback id）。

6. **未掃描面**：`storage/reports/<id>.json` 個別報告檔（feed.json 已掃，但兩者可能 drift）；
   前端硬編碼的策略卡文案；FB 貼文歷史；`storage/indicator_arena/`。

**驗證方法（可重跑）**：
```bash
# 知識庫 population + L1
jq 'length' storage/memory/knowledge.json                      # -> 2504
# 程式碼 class
uv run python scripts/audit_mdd_scale_artifact.py              # -> 455 ratchet-tracked
# gate
uv run --extra dev python -m pytest scripts/tests/test_mdd_scale_artifact_ratchet.py   # -> 12 passed, 1 skipped
# K1265 重驗
uv run python experiments/k1265b/k1265b.py
# 論文盲區
grep -rliE "matched (volatility|exposure)|exposure-matched" paper/*/*.tex   # -> 0
```

---

## 5. 待辦（本 sweep 不做，須主線程派工）

| # | 項目 | 優先 | 理由 |
|---|---|---|---|
| 1 | **`vt-trend-following` 補同曝險對照 + circular-shift 檢定（22 assets）** | **P1 / blocker** | 論文核心貢獻懸空；投稿前必做 |
| 2 | `vix-sufficiency` 的 drawdown-insurance framework 同上 | P1 | 第二貢獻 |
| 3 | knowledge.json 209 條 suspect claim 降級措辭 | P2 | **須走正式 writer（`src/volpred/memory/system.py`），禁手改 JSON** |
| 4 | 13 篇 high-severity feed 文章發更正 | P2 | reader-facing 信賴度 |
| 5 | 49 篇 correction-notice + 67 篇 add-caveat | P3 | 量大，可分批 |
| 6 | 455 個 code site 逐步 retire（baseline 只准變少） | P3 | 漸進，不 big-bang |

**本 agent 依規定未寫 `knowledge.json`、未動 `feed.json`。** 結論落在本文件 + `experiments/k1265b/`，
由主線程驗證後入庫。

**逐條判讀原始資料（已入 repo，可獨立複核，不依賴 `/tmp`）**：
- `docs/governance/2026-07/raw_mdd_knowledge_classification.json` — 446 筆知識庫條目的逐條判定
  （含 disposition / 曝險 / 佐證 / 原文引句 / 降級註記）
- `docs/governance/2026-07/raw_mdd_feed_dispositions.json` — 240 篇文章的逐篇判定
  （含 severity / disposition / 建議更正文字）

---

## 6. 這次 audit 自己犯的錯（留著，因為它是本文件最有用的部分）

**k1265b v1 被 Codex 判 FAIL，而且 FAIL 的是作者的動機，不只是代碼。**

v1 跑出 paired bootstrap **不支持**顯著性（p≈0.32–0.42），於是我把它標成 **"BROKEN INSTRUMENT"** 並排除，
理由寫得很漂亮：「MDD 是路徑相依極值，block resampling 會打碎 2008 那種長回撤 episode」。

Codex 實測：換成合理的 block 長度（L=504/1000），**同一個檢定的 p 值掉到 0.041–0.077，反而變顯著**。

**那不是發現了壞掉的儀器，那是拿「儀器壞了」當藉口丟掉一個不利的檢定。**

諷刺的是，K1702 §2 親手寫過這句警告 —— *「製造出 null 的 artifact，和製造出勝利的 artifact，一樣不可信」* ——
我在執行 K1702 的回溯任務時，朝相反方向犯了同一個錯。

**教訓（已寫進 k1265b README §6，不可刪）**：當一個檢定的結果不利於你想講的故事時，
**先假設是自己的 spec 選錯了，不是儀器壞了**。要宣告一個檢定失效，必須先做 block-selection /
sensitivity / coverage 分析 —— 而不是事後找一個聽起來合理的理由。
v2 因此把**全部 5 個 block 長度**列出來，一個都不丟。

### 第二次自我更正：這次是 gate 抓到的

v2 寫完後，本文件與 k1265b README 都寫了一句：**「3/3 gap 為正 → 效果不是純機械 de-leveraging」**。

然後我為機械 gate 補一條「有鑑別力」的測試 —— 斷言「反向擇時應該得到**負** gap」。**它 fail 了**：
反向擇時（時機完全相反、劑量相同）拿到 **+0.85pp 的正 gap**。

不是 bug，是我的前提錯了。**匹配無條件波動沒有匹配到波動的路徑**，離散權重本身就會產生較淺的回撤。
於是「gap > 0 → 不是機械性」這個推論**當場作廢**，兩份文件都已更正，
而那個反直覺的事實被**固化成一條測試**（`test_a_positive_exposure_matched_gap_is_not_by_itself_evidence_of_timing`），
讓 codebase 永遠不會再做這個跳躍。

**這是本次 sweep 最好的一件事**：一個為了防止 overclaim 而建的 gate，第一個抓到的 overclaim 是**它作者的**。
機械化的價值就在這裡 —— 散文提醒攔不住你自己的動機，會 fail 的測試可以。
