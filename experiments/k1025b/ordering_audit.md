# K1025 家族 Cholesky-FEVD 排序假象 — 稽核與回溯更正

**日期**：2026-07-13
**觸發**：K865b class sweep 標記 `k1025.py` / `k1025_v2.py` / `k1025b.py` 三支以 Cholesky FEVD
推導 NET transmitter/receiver 方向性結論，未做排序置換檢查。
**證據包**：`experiments/k1025b/k1025b_v2.py` → `k1025b_v2_results.json` + `k1025b_v2_results.png`

---

## 0. 一句話結論

**「BTC 是波動淨接收者（`mean_net_btc = −76.64pp`）」是假象，不是效應 —— 而且排序只是第三順位的原因。**
主因是 **FEVD 陣列誤切**：`decomp[-1]` 把「最後一個變數」當成「最後一個 horizon」，
`n_vars` 被讀成 10，總連動指數因此**機械性地**被推到 ~90%（在純雜訊上也一樣）。
Order-invariant 的 KPPS 重估後：**BTC net = +2.70pp（翻號，量級縮 ~28 倍）**。

---

## 1. 排序會不會翻結論？（Step 1：先讀 v3，不重跑）

`k1025_v3_results.json`（SPY/^VIX panel，2026-07-12 已完成）已回答：

| 項目 | 值 |
|---|---|
| Cholesky NET_BTC 跨排序 gap | **18.66pp**（`order_sensitivity.cholesky_btc_net_gap_pp`） |
| Generalized (KPPS) 跨排序 gap | **5.6e-12pp** — order-invariant |
| KPPS TCI | 19.52%（原 v2 報 90.11%） |
| KPPS NET_BTC | **−0.95pp**（原 v1/v2 報 −76.89pp） |

→ **v3 已足以取代 k1025 v1/v2 的方向性結論**，v1/v2 無需重跑。

**但 v3 不能取代 k1025b**：k1025b 不是同一個 panel。
`k1025b.py:58-60` 下載的是 **QQQ / BTC-USD / ^VXN**（NASDAQ-100 恐慌指數），
v3 用的是 SPY / ^VIX。故 k1025b 必須自己重算 —— 這正是 Step 2。

---

## 2. k1025b KPPS 重算（Step 2：本任務的實質計算）

實作紀律：`generalized_fevd` / `cholesky_fevd` / `connectedness` **直接 import k1025_v3 的函式**，
不重寫第二套（兩套實作分歧是下一個 bug）。資料 pin 成 snapshot
（`data/qqq_btc_vxn_2015-2026.csv`），樣本窗口與原始 k1025b 完全一致，
**只換估計量**，避免把「估計量修正」和「樣本變動」混在一起。

### 2.1 先重現原缺陷（before/after 要用「量」的，不是用「說」的）

| 指標 | k1025b 發表值 | 本次重現 | 判定 |
|---|---|---|---|
| rolling `mean_net_btc` | −76.64pp | **−76.62pp**（差 0.02pp） | ✅ 重現 |
| rolling `mean_total` | 90.09% | **90.09%**（差 0.001pp） | ✅ 重現 |
| rolling 視窗數 | 512 | **512** | ✅ 完全一致 |
| VAR 樣本數 | 2,812 | **2,812** | ✅ 完全一致 |

→ 原缺陷重現，因此以下 before/after 是**實測**，不是宣稱。

⚠️ **不可寫成「位元級重現」/「identical data」**（2026-07-14 review 抓到的 overclaim，已改）：
原始 k1025b 是各 ticker 各自 index 下載，本次 pin 成單一 union CSV（見 `build_var_panel`
的對齊註記），**對齊處理刻意改過** → 輸入不是 byte-identical，所以才會差 0.02pp
（hardcode 才會完全相等）。誠實的說法是「在重新 pin 的同期 snapshot 上重現到 0.02pp，
視窗數與樣本數完全一致」—— 這同樣有說服力，而且是真的。
一份專門在指控別人「宣稱不是實測」的稽核，自己的措辭必須零瑕疵。

### 2.2 三組 NET 對照

⚠️ **口徑要標清楚**（2026-07-14 review 抓到本表原本把 rolling mean 與 full-sample 混在
同一張「全樣本」表）：發表的 90.09% / −76.64pp 是 **512 個視窗的 rolling mean**，
不是全樣本值；誤切估計量的**全樣本**值是 90.02% / **−88.62pp**。

| 估計量 | 口徑 | TCI | NET_BTC |
|---|---|---|---|
| k1025b 發表版（誤切 + Cholesky） | **rolling mean（512 窗）** | 90.09% | **−76.64pp**（「淨接收者」） |
| k1025b 發表版（誤切 + Cholesky） | **全樣本** | 90.02% | **−88.62pp** |
| Cholesky（正確切片）6 種排序全枚舉 | 全樣本 | 8.2–12.5% | **−2.60pp ~ +8.96pp**（跨度 11.55pp，**變號**） |
| **KPPS generalized（order-invariant）** | **全樣本** | **13.72%** | **+2.70pp** |
| **KPPS generalized（order-invariant）** | **rolling mean（512 窗）** | 20.3% | **−0.11pp**（65% 視窗為負） |

「量級縮 ~28 倍」是拿 rolling-mean 發表值（−76.64pp）比 full-sample KPPS（+2.70pp）；
**同口徑比較**是 rolling→rolling：TCI 90.09% → 20.3%、NET −76.64pp → −0.11pp。
兩種說法都指向同一結論（發表值是假象），但引用時**必須標明口徑**。

KPPS 在同樣 6 種排序下 NET 跨度 = **3.2e-12pp** → 確認 order-invariant。

### 2.3 NET 對照「無傳染 null」，不是對照 0

`+2.70pp` 這種小數字不能用肉眼跟 0 比（這正是 repo MDD 規則警告的錯誤）。
以 **circular-shift randomization**（保留各序列自身自相關與邊際分布，破壞跨序列對齊）
建無傳染 null，B=1000：

- null 均值 −0.03pp，95% 區間 [−1.06, +0.96]
- 觀測 +2.70pp → **p = 0.005**（雙尾）
- null 的 TCI floor = 0.44% → 觀測 13.7% 遠高於估計噪音底線

### 2.4 誠實讀法（不可把一個 overclaim 換成它的鏡像）

**可以說的**：發表的量級（−76.6pp）與「強淨接收者」讀法是假象；order-invariant 下
BTC 淨連動小一個數量級，且**符號不穩定**（全樣本 +2.7pp，rolling 均值 −0.11pp，
**65% 的視窗為負**）。
**不可以說的**：「BTC 其實是淨傳播者」。全樣本 +2.7pp 雖然過了 null，但相對它取代的
−76.6pp 在經濟意義上可忽略，且 rolling 口徑不支持穩定方向。

### 2.5 三個缺陷的相對重要性（排序其實最小）

1. **FEVD 誤切【主因】** — `fevd.decomp` 實為 `(n_vars, horizon, n_vars)`；`decomp[-1]` 取到
   最後一個**變數**的 (horizon, n) 表。`n = shape[0]` 變成 10（而非 3），TCI 被機械推到 ~90%
   （**在純雜訊上也是 ~90%**）；NET 變成「10 列 row-normalized 的 column 和」減「3 個元素的 row 和」，
   維度不相容。**單這一條就足以生出 −76.64pp。**
2. **欄位命名反了【誤導，但非計算錯誤】** — `mean_from_btc` 是 column 和（BTC **傳出**），
   但 DY 慣例 `FROM_i` 指 i **收到**的。**已實測驗證**：NET 公式本身（column − row = to − from）
   **結構正確**，餵進正確的 (3,3) 矩陣可重現 canonical `connectedness()` 到 1e-9。
   故這是標籤缺陷，不是符號錯誤。
3. **Cholesky 排序相依【本次稽核的觸發點，卻是最小的一條】** — 即使切對，NET 跨 6 種排序
   仍跨 11.55pp 且變號，無法承載方向性結論。

---

## 3. 全量下游稽核（Step 3）

### (a) 掃描範圍（full population，非抽樣）

| 目標 | 方法 | 母體 |
|---|---|---|
| `storage/memory/knowledge.json` | `jq` 全陣列 tostring 比對（禁整檔 Read） | **2,507 筆全掃** |
| `storage/reports/feed.json` | `jq` 全陣列 + 內容行比對（禁整檔 Read） | 全篇文章 |
| `paper/**` | `grep -rn` `.tex` / `.py` / `.json` | 全 paper 樹 |
| `research_program.md` | `grep -n` | 全檔 |

**可驗證 evidence（可直接重跑）**：

```bash
# knowledge.json：全 2507 筆中所有提及 k1025 的 entry + 是否帶方向性數字
jq -r 'to_entries[] | select((.value|tostring)|test("k1025";"i"))
  | "idx=\(.key) id=\(.value.id // "NONE") dirnum=\((.value|tostring)
  |test("76\\.6|90\\.09|net receiver|淨接收";"i"))"' storage/memory/knowledge.json
# → 8 筆命中 k1025，其中 3 筆帶方向性數字（idx 1951 / 2048 / 2497）

# feed.json：引用 k1025 家族的文章
jq -r '.[] | select((tostring)|test("k1025";"i")) | "\(.id) | \(.status) | \(.title)"' \
  storage/reports/feed.json
# → 3 篇（mile_113ce9d1 / mile_a93c8580 / mile_36690fbd）

# paper：net receiver 宣稱
grep -rn "net receiver\|74\.4\|76\.64\|76\.89" paper/crypto-fear-channel/*.tex
```

### (b) 稽核結果 — 逐站點（有無污染都列）

| # | 站點 | 狀態 | Evidence |
|---|---|---|---|
| 1 | `knowledge.json` idx=**2048**（K1025b entry） | 🔴 **污染** | 明文寫 `(4) DY net BTC **-76.64pp** (vs K1025 -76.89pp; near identical)`，並據此宣稱「5/5 stylized facts 複製」 |
| 2 | `knowledge.json` idx=**1951**（Paper 6 kick-off） | 🔴 **污染** | 「**BTC is net receiver**」寫入 Paper 6 central claim 素材 |
| 3 | `knowledge.json` idx=**2497**（2026-07-12 Codex 更正） | 🟢 已正確 | 已撤回 K1025 v1/v2 的 90.11% / −76.89pp，並自己標註「**須另做 K1025b v3 重寫**」← 本任務即補上此缺口 |
| 4 | `knowledge.json` idx=1793（K1025 主 entry） | 🟢 乾淨 | content 只列 Granger / 非對稱 / quantile / 相關 / forecasting NULL，**未含任何 FEVD/NET 數字** |
| 5 | `paper/crypto-fear-channel/main.tex` L282, L296, L359, L29, L48 | 🔴 **污染（最嚴重）** | L282「total 90.1% … BTC net **−74.4pp**」；L296「BTC remains a net receiver **in every window**」；L359 摘要、L29 摘要、L48 內文皆宣稱 net receiver |
| 6 | `paper/crypto-fear-channel/reproduce.py` L238-255 | 🔴 **污染（治理層）** | 投稿 gate 以 byte-match 釘住 `k1025_v2.spillover_index.mean_total` / `mean_net_btc` → **gate 會「PASS」一個假象** |
| 7 | `paper/crypto-fear-channel/body_v0_intro / v1 / v2 / v3.tex` | 🟡 舊稿 | 同樣含 net receiver 宣稱（非 active manuscript，但屬 audit trail） |
| 8 | `research_program.md` L888 | 🔴 **污染** | 「spillover from_btc=21.5%→23.7%, net=−76.9pp→**−74.4pp**」 |
| 9 | `research_program.md` L890-898 | 🟢 已正確 | 2026-07-12 override 已記載 v1/v2 誤切，並註明「另需 **K1025b v3**」 |
| 10 | `feed.json` mile_113ce9d1（published） | 🟢 **已正確** | 標題即「K1025 修正版」，內文已撤回 90.11% / −76.89pp，並報正確 KPPS 19.52% / −0.95pp |
| 11 | `feed.json` mile_a93c8580（published） | 🟢 乾淨 | 只用相關係數（0.265 等），未引用 FEVD NET |
| 12 | `feed.json` mile_36690fbd（archived） | 🟢 乾淨 | 無 NET 宣稱 |
| 13 | `paper/crypto-fear-channel/main.tex` L298 | 🟢 已自保 | 「Deferred robustness work」已主動聲明 VXN/QQQ 交叉複製「still relies on an older, uncorrected methodology」→ K1025b 的**論文曝險已先被降級**（但 knowledge 與 reproduce gate 未同步） |

### (c) Blind-spot 分析（子集外可能漏掉什麼）

1. **數字碰撞造成的偽陽性 —— 已排除，不可誤報**：
   `paper/leverage-direction/*` 大量出現 `−76.6%`，但那是 **BTC 的 buy-and-hold 最大回撤（MaxDD）**，
   與 spillover NET **完全無關**，只是數值巧合。`feed.json` 亦有多篇因「90%」「766 億」等字串命中。
   → 本稽核以**語意**（是否為 DY/FEVD 方向性宣稱）判定，不以字串命中判定。
2. **改寫過的敘述可能不含原始數字**：若下游把「−76.6pp」改寫成「比特幣主要是恐慌的接收方」這類
   純文字，grep 數字會漏。→ 已補掃 `net receiver` / `淨接收` / `net sender` 等語意詞，
   idx=1951 正是靠這條抓到的（它不含 −76.64，只含 "BTC is net receiver"）。
3. **Supabase / Mirror 線上副本**：本 worktree 無法查線上 DB。若 knowledge/feed 已同步到線上，
   主線程更正後需重新 sync。
4. **`k1025b_results.json` 本身未修改**（保留為歷史紀錄）。任何仍讀取
   `k1025b_results.json.spillover_index` 的下游都會拿到已撤回的值 —— 已在 `k1025b.py` banner 標明。

---

## 4. 處置（Step 4）

### 4.1 本 worktree 已完成

- ✅ `k1025.py` / `k1025_v2.py` / `k1025b.py`：加 `!!` 撤回 banner；`compute_spillover_index`
  改用 **canonical KPPS**（import `k1025_v3.generalized_fevd`，不刻第二套），
  Cholesky 降級為具名 `cholesky_order_dependent_diagnostic`。
  （沿用 `k628b_vol_spillover.py` 2026-07-13 已建立的慣例。）
  實測：patched `k1025b.compute_spillover_index()` 回傳 **+2.7048pp**，與 canonical 一致。
- ✅ `experiments/k1025b/README.md`、`experiments/k1025/README.md`：標 SUPERSEDED + 更正段。
- ✅ `storage/ops/fevd_ordering_baseline.json`：移除 3 站點（4 → **1**，只剩 k865），
  並在 `resolved` 補三筆含 how/evidence。
- ✅ `scripts/tests/test_fevd_ordering_ratchet.py`：**2 passed**。
- ✅ `scripts/audit_fevd_ordering.py`：**修偵測器盲點**（見 4.3）。

### 4.2 交回主線程的下游污染清單（worktree **不得**自行修改 canonical）

| 優先 | 檔案 | 動作 |
|---|---|---|
| **P1** | `paper/crypto-fear-channel/main.tex` L29 / L48 / L282 / L296 / L359 | 撤回 net-receiver 敘事。**L296 的「net receiver in _every_ window」尤其要撤** —— order-invariant 下 **35% 的視窗 NET 為正**，該句被直接推翻 |
| **P1** | `paper/crypto-fear-channel/reproduce.py` L238-255 | byte-match gate 釘在 `k1025_v2.spillover_index` 的假象值上 → gate 形同背書錯誤。改指 `k1025_v3_results.json`，或移除 DY 檢查 |
| **P1** | `storage/memory/knowledge.json` idx=2048（K1025b） | 「5/5 複製」需降為 **4/5**。第 (4) 項（DY net −76.64 「near identical」to −76.89）是**兩支腳本共用同一個 bug 的一致**，不是效應的複製；order-invariant 下兩 panel 連正負號都不同（−0.95pp vs +2.70pp） |
| **P2** | `storage/memory/knowledge.json` idx=1951（Paper 6 kick-off） | 移除「BTC is net receiver」central claim |
| **P2** | `research_program.md` L888 | 「net=−76.9pp→−74.4pp」標撤回（L890-898 的 override 已部分涵蓋，但 L888 仍留舊值） |
| **P3** | `paper/crypto-fear-channel/body_v*.tex` | 舊稿；若仍作 audit trail 保留，加註撤回 |
| **P3** | Supabase / Mirror | knowledge/feed 更正後重新 sync |

**不需動**（明確排除，避免誤傷）：`feed.json` 三篇皆乾淨（`mile_113ce9d1` 已是正確的更正文章）；
`paper/leverage-direction/*` 的 −76.6% 是 MaxDD，與本案無關。

### 4.3 順帶修掉的偵測器盲點（`scripts/audit_fevd_ordering.py`）

原判準只認「**檔案自己的文字裡**有 `sigma_u` / `ma_rep`」。後果：
**複製貼上第二份 KPPS 實作 → 判 OK；import 既有的正解 → 判 MISLABELED。**
偵測器**獎勵了會製造實作分歧的行為，處罰了正確的重用**（`k1025b_v2.py` 沿用
`k1025_v3.generalized_fevd`，正是被這條誤判）。

修正：新增 `RE_KPPS_REUSE`，辨識**真的綁定 canonical 符號**（`from … import generalized_fevd`
或 `<module>.generalized_fevd`），而非散文宣稱。
**負向對照已驗證**：只在註解宣稱自己是 KPPS、實際呼叫 `.fevd()` 的檔案，
仍被判 `MISLABELED` → 偵測力未被削弱。

> ⚠️ 此檔在本任務原始 scope 之外（scope 限 `experiments/k1025*`、`docs/`、baseline）。
> 但任務同時要求「沿用 v3 函式、不重寫第二套」**且**「ratchet 保持綠」——
> 在舊偵測器下這兩者不可能同時成立。故必須修偵測器。**特此明列，請主線程覆核。**

---

## 5. 復現

```bash
uv run --extra dev python experiments/k1025b/k1025b_v2.py       # seed=42, pinned snapshot
uv run --extra dev python -m pytest scripts/tests/test_fevd_ordering_ratchet.py -q
uv run python scripts/audit_fevd_ordering.py                    # 應只剩 k865 一個 VIOLATION
```

**資料**：QQQ / BTC-USD / ^VXN，yfinance，2015-01-01 → 2026-04-09（requested），
VAR panel 2015-02-02 → 2026-04-08，**N = 2,812**，seed = 42，pinned snapshot（無 live fetch）。

**參考**：Diebold & Yilmaz (2012) IJF 28(1); Koop, Pesaran & Potter (1996) JoE 74(1);
Pesaran & Shin (1998) Econ. Letters 58(1)；同類缺陷：K865b、K628b、K1025 v3。

---

## 5. Review provenance（2026-07-14 主線程補記）

| 項目 | 值 |
|---|---|
| Reviewer source | **`code-reviewer` subagent fallback** — Codex primary path 逾時（bounded run 撞 10min tool 上限），依 `.claude/rules/experiments.md` 的 fallback 條款改派 |
| Verdict | **CONDITIONAL PASS** — 科學內容成立（KPPS 實作正確、缺陷確為真實重跑非 hardcode、無 lookahead、null 建構與 p 值自洽、結論未把 overclaim 換成鏡像） |
| 5 個條件 | 全數已完成（見下） |
| knowledge entry | `e3e4b1fa`（category=self-correction） |

**Reviewer 開出的 5 個條件與處置**：

1. **[Critical]** 已 patch 的 `k1025b.py` 仍寫回 `k1025b_results.json` → **重跑一次就會用 KPPS 新值蓋掉發表紀錄**（且沿用同一組 legacy key，而 paper reproduce gate 正是 byte-match 這些 key）→ banner 承諾的 immutable 是空的。**已修**：輸出改 `k1025b_results_kpps.json` + 加 write guard（指回發表檔就 raise）。
2. 「Bit-level reproduction on identical data」是 overclaim（原始各 ticker 各自 index 下載，本次 pin union CSV，對齊刻意改過 → 差 0.02pp；hardcode 才會完全相等）。**已修**：改為「re-pinned 同期 snapshot，重現到 0.02pp，512 窗 / 2,812 樣本完全一致」。
3. 「NET 公式重現 canonical 到 1e-9 — verified rather than assumed」在證據包內**找不到對應計算**。一份指控別人「宣稱不是實測」的稽核不能有同型無憑宣稱。**已修**：加 runtime assert，實測 `abs_err = 8.9e-16pp`，寫入 results JSON 的 `net_formula_equivalence_check`。
4. §2.2「全樣本」表混入 rolling mean。**已修**：表格加「口徑」欄，補 full-sample 誤切值 −88.62pp / 90.02%。
5. `k1025b.py` print label `Net BTC (from - to)` 與內容相反（正是本次被稽核的同類缺陷）。**已修**：改 `Net BTC (to - from; DY convention)`。

⚠️ **Closure 尚未成立**：per K1259 教訓，**subagent fallback PASS ≠ primary-path Codex PASS**。
Codex 恢復後必須對本份做一次 primary-path 二次驗證才能立 closure
（follow-up task 已入池：`k1025b_v2_codex_primary_path_verify`）。
