# Refactor plan — 複合假說的單點 accept gate（K1734 三輪發散的根因）

- **觸發**：經理裁決 D8（2026-08-05），K1734 認證審查 rev2 FAIL(1) → rev3 FAIL(2) → rev4 FAIL(5)，
  缺陷數逐輪**增加**。裁決明文禁止 rev5，要求三層診斷。
- **診斷人**：research 部門，2026-08-05
- **檔案位置說明**：3-Strike 流程規定寫 `docs/refactor_plan_<topic>.md`，但 `docs/` 不在研究部
  轄區（寫入被 deny），故依經理「或等價診斷文件」的授權落在部門子樹。要移進 `docs/` 需經理
  指派有該轄區的角色搬運，內容不必改。
- **結論先講**：這不是 K1734 的實作瑕疵，是**假說形式與 gate 形式的結構不匹配**，而且這個
  不匹配一旦被審查發現，在**同一份資料上**沒有任何修補路徑能修好它。K1734 建議判 null 收尾。

---

## 一、三輪缺陷的實際軌跡（證據）

| 輪次 | reviewer | 結果 | blocking 缺陷 |
|---|---|---|---|
| rev1 | — | **UNAVAILABLE** | Codex CLI 撞 usage limit（至 2026-08-02），依 two-strikes 規則改派替代模型 |
| rev2 | codex primary-path | FAIL(1) | **H1 的 accept gate 只測了兩個 limb 的其中一個**：H1 敘述是「左尾更肥 **AND** 壓力下放大更快」，gate 只讀 skew ＋ semivariance；`amp_down`/`amp_up` 算了但既沒進檢定也沒進 gate，README 卻引用 1.35x vs 1.30x 當作第二 limb 的支持 |
| rev3 | codex primary-path | FAIL(2) | (a) **H2 的 accept gate 只測了兩個 limb 的其中一個**：H2 敘述是「yen **OR** risk-off」，gate 只讀 FXY，明文把 UUP/dVIX/HYG 排除為「另一個較軟的主張」——而那三個迴歸的 HAC t 值是 −17.26 / −11.22 / +13.82；(b) figure 4 是 QLIKE 累積增益圖，標題卻掛 MSE 的 `CW p=0.015`，而該圖自己的檢定 p=0.4744 |
| rev4 | codex primary-path（對抗式認證） | FAIL(5) | (1) H2b 被呈現為 ex-ante/prespecified，但 `RISKOFF_SIGNS`、三個 H2b lead 檢定與六路 aggregation 都是 rev4 才出現，且 parent 早已暴露 fitted signs，rev4 的 fix report 自陳 risk-off limb「已知會成功」→ 事後探索被標成 confirmatory；(2) H2a 與 H2b 的 gate 口徑不一致（H2a OR 兩個 raw-p、H2b OR 六個 raw-p，最終 verdict 直接複製 raw boolean 不讀 BH flag）；(3) H2 lead logit 對日頻尾部事件序列用 statsmodels 預設 IID 共變異數，非 HAC/cluster-robust（獨立 HAC(21) 敏感度把 UUP p 從 0.000268 推到 0.002129）；(4) QLIKE 程序被標為 nested-valid general-loss test，實際只 resample 已實現的 OOS loss-differential path，既未施加 nested null 也未重估訓練模型；(5) README 宣稱每個數字可 byte-traceable 到結果 JSON，但 power check / bootstrap SD / 最小可偵測效果沒有可執行的存檔計算 |

**rev2 與 rev3 是同一個 bug class 的兩次出現**：複合假說（compound `AND` / disjunctive `OR`）
只實作了一個 limb 的 gate。作者的結果 JSON 自己記下了這件事：

> `H2_accept_definition`：「Before rev4 only H2a was gated, so a false H2_accept was being read
> off a hypothesis twice as wide as the gate.」

**rev4 不是新的 bug class，是 rev3 修補動作的直接後果。**

---

## 二、為什麼會發散（三層診斷）

### (a) 底層邏輯 — domain model 錯在哪

**假說空間是樹狀的，accept gate 是單點的。**

K1734 的三個假說都不是原子命題：
- H1 = H1a **AND** H1b（靜態左尾 ∧ 壓力放大）
- H2 = H2a **OR** H2b（yen-funding ∨ risk-off）
- H2b 自己又展開成 3 個 lead 檢定 × 6 路 aggregation

實驗設計時，每個假說配了**一個** boolean accept gate，實作的是最容易算、或最先想到的那個 limb。
於是每一輪審查都能找到「還有一個 limb 沒被 gate」——而且**修好一層就會長出下一層葉子**
（rev4 缺陷 2 正是 H2b 展開後兩個 limb 多重性口徑不一致）。

這解釋了缺陷數為什麼**增加而不是收斂**：不是修補品質差，是**每次修補都在展開假說樹的下一層，
而每一層新葉子都要各自承擔檢定、多重性、推論口徑三種義務**。1 → 2 → 5 的成長是這個結構的
自然行為。

### (b) 流程 — 為什麼三輪審查沒讓缺陷收斂

**因為 rev3 給的兩條出路，在 rev3 的時間點上都已經走不通了。**

rev3 對 H2 的處置寫得很明確：「frozen artifact 必須**要嘛**把 H2 到處都窄化成 yen-specific，
**要嘛**正式定義並 gate 兩個 limb」。

- 走「窄化」→ 事後把預先登錄的假說縮小，那是 HARKing 的另一種形式
- 走「補 limb」→ risk-off 的全部結果在 rev1–rev3 期間已經算完、看過、寫進 README（HAC t 值都在
  README 裡），任何此時才加進 confirmatory family 的 limb 都**不可能**是 ex-ante

作者選了第二條，rev4 就精準地判它是 post-outcome 探索被標成 confirmatory。

**這不是作者選錯，是兩條路都通不過。** 真正的失效點在更早：**pre-registration 的資訊在第一輪
就已經洩漏了**——不是被實作洩漏，是**假說寫成了 disjunctive 而 gate 只蓋一半**，等到有人指出
另一半存在時，另一半的資料早就看光了。

**pre-registration 一旦洩漏就不可逆。沒有任何 revision 能在同一份資料上把它變回 ex-ante。**
這是 rev5 註定失敗的機械理由，跟修補品質無關。

流程層的第二個缺口：**rev1 因 Codex 撞 quota 而 UNAVAILABLE，改派替代模型**；rev2 的 verdict
檔案自陳 reviewer 的 workspace 是唯讀，「回報這一個 blocking defect 就停了」，另外四個維度
**沒有涵蓋**。也就是說前兩輪都不是完整的五維審查——缺陷是**分批被發現的**，而不是一次盤點完。
一個只回報第一個踩到的地雷就停下的審查，會讓作者以為「只剩這一項」，於是每輪都用「只差最後
一哩」的心態修，而不是回頭重新檢視設計。

### (c) 架構 — 該不該換做法

有兩個缺陷即使重做也修不掉，必須先認清：

- **rev4 缺陷 4（nested-valid general-loss test）不是實作 bug，是方法論空缺。** nested 模型 ＋
  一般損失（QLIKE/pinball）＋ expanding/rolling 重估的組合，目前沒有可用的推論法；Clark-West
  只對 MSE 有效，對 QLIKE 不成立。這一點在本平台已有明確記錄（memory
  `reference_nested_forecast_inference_gap`）。K1734 想要的那個檢定**不存在**，所以只能把宣稱
  降級成「對凍結預測路徑的條件推論」，不能靠重寫程式解決。
- **rev4 缺陷 3（IID → HAC）可以修，但修了會削弱結論。** rev3 已獨立測過：HAC(21) 讓 UUP 的
  p 從 0.000268 變成 0.002129（仍顯著），其他 lead 檢定「materially weakens」。

### 科學盤點：修好之後還剩下什麼

這是決定「該不該再投入」的關鍵，逐項用凍結結果 JSON 的數字盤：

| 主張 | 狀態 | 實質內容 |
|---|---|---|
| H1a 靜態左尾不對稱 | accept | carry trade 崩跌不對稱是文獻常識，**接近 stylized fact 的重述** |
| H1b 壓力下放大更快 | **NULL** | CEW gap +0.0499，CI [−0.1646, +0.2640]，p=0.6924；約 68 個 stress-tail 觀測，**檢定力極低的 null**，不是等價性 |
| H2a yen-funding 觸發 | **REJECTED** | FXY beta 符號與 yen-funding 崩跌通道相反，lagged FXY logit 為 null |
| H2b 同日 risk-off 共動 | accept | 作者自己寫的 `interpretive_ceiling`：「EM carry 本身就是風險資產，共動接近定義上必然，幾乎沒有因果內容」 |
| H2b lead 半邊 | 部分 | 只有 UUP_{t−1} 過關，dVIX_{t−1} 與 HYG_{t−1} 沒過；且 HAC 修正後削弱 |
| H3 OOS 預測增量 | accept（薄） | RMSE 0.00010257 → 0.00010202（**+0.53%**）；CW MSE 單尾 p=0.015，BH 校正後 0.0451（保守加倍後仍 <0.05，**極薄邊際**）；**QLIKE bootstrap p=0.4744 不顯著**；rev3 記載換成平方報酬 RV 後消失 |

**唯二有內容的是兩個 null**：H1b 的壓力放大不成立（但檢定力不足）、yen-funding 觸發被拒
（這個推翻了一個流行敘事，有價值）。其餘不是定義必然，就是薄到經不起口徑變化。

**再投一輪 xhigh 審查去換這些，投報率不成立。**

---

## 三、處置建議

### 對 K1734：判 null 收尾，但不是「就地爛掉」

經理裁決允許三種結論，本部門建議第三種——**判 null 並如實記錄**——並附一個必要的執行細節：

**「判 null」不等於「檔案留在 worktree 不管」。** `experiment_gates.py certify` 要求
verdict=PASS 才能 merge，所以一個被判定不繼續的實驗，產物仍然進不了 main。正確收尾是：

1. **把 claim surface 全面降級**：README 與結果 JSON 裡所有 accept 宣稱改寫成 null / exploratory /
   descriptive；H3 的 0.53% 標成「只在 MSE 口徑薄邊際顯著、QLIKE 不顯著、換 RV 估計量消失」；
   H2b 直接引作者自己的 `interpretive_ceiling`；nested-valid 的宣稱降級為「凍結預測路徑上的
   條件推論」。
2. **對降級後的 bytes 做一次終審**。這**不是 rev5**：rev4 的缺陷 1（事後探索標成 confirmatory）
   與缺陷 2（兩個 limb 口徑不一致）在沒有任何 confirmatory claim 之後**自動消失**——它們是
   claim 的缺陷，不是計算的缺陷。缺陷 3/4/5 降級為已揭露的限制。rev3 已獨立驗證過 lookahead、
   leakage、statistics 三個維度全 PASS，計算本身是乾淨的。
3. 終審通過後，**null result 依規則可以寫進 `knowledge.json`**（`.claude/rules/experiments.md`
   的 provenance gate 只對 `verdict == "PASS"` 要求 reviewer 欄位，NULL/FAIL/MIXED 不 gated），
   H1b 與 yen-funding 兩個 null 就留在知識庫裡，供 topic dedup 與後續選題使用。

若經理認為連這一次終審都不值得投，退路是走
`config/experiment_artifact_exclusions.json` 並寫明「為什麼做不到」——但那只放行 artifact gate，
不放行 certify gate，產物仍然留在 worktree。**這條退路會讓一份計算乾淨的實驗永久留在 main 之外，
本部門不建議。**

### 對 bug class：機械 gate（防下一個 K1734）

散文提醒擋不住這個 class——rev2 發現 H1 的時候，H2 的同型缺陷就已經寫在同一份程式碼裡了，
沒有人聯想到「同一個 bug 在隔壁」。依 CLAUDE.md 的 anti-stacking 與「散文不是處置」原則，
建議把它機械化：

**提案**：在 `scripts/experiment_gates.py` 加一道 `compound-hypothesis` gate（收編進既有 owner，
不新增第二層 watchdog）：

- 掃 `*_results.json` 的 `verdicts` 區塊，凡是 key 形如 `<H>_accept` 且同時存在
  `<H><limb>_accept`（如 `H1a_*`/`H1b_*`）的，斷言 `<H>_accept` 的計算方式在
  `<H>_accept_definition` 裡被顯式宣告為 AND / OR，且每個 limb 都有自己的檢定統計量欄位
- 凡是 README 敘述含 `AND`/`OR`/「且」/「或」的假說，要求對應的 limb flag 存在

這道 gate 攔的是「宣稱的假說比 gate 寬」，也就是 rev2 與 rev3 的共同形狀。實作與優先序屬
平台工程部/主線程轄區，本部門只提規格。

**同時建議寫入 `docs/error_log.md` 的 3-STRIKE TRIGGER 條目**（研究部無此轄區，文字備妥給經理
指派）：三次 incident 分別是 rev2（frozen bytes 早於 commit `87594200e`）、rev3（frozen commit
`87594200efcaf324ea4cb60a4eedef9b59aab8be`）、rev4（`4f1f2749a`，2026-07-29T21:56:30Z 裁決）。

---

## 四、附帶裁決：`diversity_rule_post_null_quartet` 沒有在擋正當研究

經理問這條規則是不是在擋住正當的後續研究。**不是。** 證據：

被它擋住的 4 件全部是 ML 架構實驗：K1383（PatchTST-lite vs HAR-RV）、K1385（Sentiment-Augmented
GARCH-LSTM）、K1388（HAR-GNN）、K1389（KAN for VIX）。`research_program.md:444` 記載 2026-07-06
已做過 C14 冷卻評估，結論是這 4 筆全在日頻波動率 ML ceiling 的飽和弧（9 次確認）：

- KAN 已經 NULL（K1263，QLIKE 比 GJR **差 23.7%**）
- GARCH-LSTM 已經 NULL（K1312）
- GNN / Transformer 都是架構重複（K1380/K1386 已確認日頻 ML-vs-HAR 飽和）

也就是說，這條規則擋的正是它設計要防的東西——**對日頻點預測不斷疊新架構的 ML treadmill**。
C14 評估甚至否決了任務原本「解封 1 筆試水」的預設，理由是「試水任一筆 = diversity rule 要防的
ML treadmill」，這是研究誠實優先於 task 慣性的正確判斷。

**而且原本的治理缺口已經修掉了**：4 筆最初是 `blocked_until=null`（永久凍結），2026-07-06 全部
改成 `blocked_until=2026-09-04`（約季度 re-eval）。今天是 2026-08-05，**它們仍在冷卻期內，
這是正常狀態不是卡住**，一個月後會自動回到 dispatch 視野。

**要提醒的一個小 drift**：`src/volpred/ops/blocked_reasons.py:34` 的註解寫
「paused per CLAUDE.md ML novel-method NULL-quartet diversity rule」，但**現行 CLAUDE.md 沒有這條
規則**——規則本體在 `research_program.md:444`（C14 評估）與 `research_program.md:52`
（NULL quartet 的定義：K868/K1301/K1303/K1309 四類 HAR 分解在 TX1 上全 NULL）。註解指向錯誤的
文件，下一個讀它的人會 grep CLAUDE.md 然後找不到，可能誤判成孤兒規則而解封。建議改成指向
`research_program.md`。（`src/volpred/ops/` 屬 Codex 熱區，非研究部轄區，未自行修改。）

**另外 6 件 blocked 實驗的分布**（經理提到 blocked 17 件中 10 件是實驗）：
`awaiting_external_data` 2（K1438 vix1d intraday、`research_n_partial_day_rv`）、
`awaiting_codex_review` 2（`assign_67f56b79`、k1731/k1730 merge）、
`awaiting_owner_decision` 3（K1734 自己、k892/k994 pinned snapshot repoint、`assign_17f813da`）、
`awaiting_prerequisite_fix` 1（`k_reruns_0050_snapshot_contaminated_20260719`）。
這些都有明確且正當的 blocker，沒有一件是被規則誤擋。**真正該注意的是
`awaiting_codex_review` 那 2 件與 K1734 屬同一族：審查產能才是這批實驗的瓶頸**，
與研究部上一班在 13 個 worktree 收編判定裡得到的結論（14/14 卡 certify）指向同一件事。
