# v6 修正覆核（re-verify）— vt-crowding-abm

- **日期**：2026-07-14（台灣時間）
- **覆核對象**：`paper/vt-crowding-abm/main.tex`，HEAD = `b48585619`（在 fix commit `4217af920 paper(abm): fix v6 cross-model review 3 BLOCKING + 1 MAJOR + 3 MINOR` 之後；`git merge-base --is-ancestor 4217af920 HEAD` = true）
- **ground truth**：`experiments/k1471_vt_crowding_redesign/{k1471_vt_crowding_redesign.py, k1471_full_results.json}`
- **覆核性質**：唯讀（本 agent 未修改任何 .tex / .json / .py），僅寫本檔與 `codex_reverify_transcript.txt`
- **兩軌**：本 agent 對 code/JSON ground truth 獨立核對 + Codex 異模型（gpt-5.6-sol）read-only 覆核。**兩軌獨立收斂**：B1/B3/M1/m1/m2 = FIXED；B2 初判 NOT_FIXED（L212 換位殘留）→ **修復（a74895380）後 Codex 終驗 CONFIRM_FIXED，見文末 Addendum** → **六條全 FIXED，0 blocking 達成**。
- **v6 review 原始 findings 定義**：同目錄 `README.md`（B1/B2/B3 BLOCKING、M1 MAJOR、m1/m2 MINOR）

---

## 總結

| 編號 | 級別 | verdict | 一句話證據 |
|---|---|---|---|
| **B1** | BLOCKING | **FIXED** | 符號式 `TF/MR $\le$ VT` 家族 ordering 主張全清除；全文唯一 `\le` 是 L193「MC 標準誤 $\le 0.02$」（與 ordering 無關），零 unicode `≤`；殘留 ordering 全為撤回/歷史/降級敘事，與 abstract、§cross_strategy 一致 |
| **B2** | BLOCKING | **FIXED（經 Addendum 終驗）** | 原 2 處（L99/L243）已改 distributional，但 **§Matched-Control 開頭句 L212 仍稱「holds the per-step trading footprint fixed at VT's realized level」**——斷言逐步幅度 pin 到 VT 實現值，與 code 的 lognormal(matched moments) 抽樣矛盾，且與已改的 L99/L243 自相矛盾。研究誠實級 overclaim 殘留 |
| **B3** | BLOCKING | **FIXED** | applicability gate 改為單條件（baseline-Sharpe floor $> -0.5$）；turnover-cap / clip-rail-gate / 10%-of-MC / 20%-of-days 第二條件全刪；與 code `detect_threshold_exogenous`（只有 `base_mean < APPLICABILITY_FLOOR`）一致；TF 4/5、MR 5/5 排除計數保留 |
| **M1** | MAJOR | **FIXED** | 「no internal break」歸零，改為「no interior break / breakpoint localizes to the saturation boundary (after 70%, 100% endpoint)」；與 JSON `breakpoint_split_after="70%"`、`threshold="100%"` 相容 |
| **m1** | MINOR | **FIXED** | L60 改為「+0.080 to +0.098」；JSON RR_VT Δ 範圍 0.0803（cell3, min）~0.0977（cell4, max），mean 0.0910 → L243「+0.091」皆吻合 |
| **m2** | MINOR | **FIXED** | L295 揭露 S₅₀=0.336/S₇₀=0.084 取自 Phase-1，並明列 redesign canonical 0.338/0.091；JSON cell1 VT 50%=0.33804、70%=0.09086 精確吻合 |

**初判 5 FIXED + B2 NOT_FIXED（L212）；L212 修復（a74895380）後 Codex 終驗 CONFIRM_FIXED → 最終 6/6 FIXED。** 附帶項通過：pdflatex 過（`main.pdf`, 35 頁, 無 fatal error）、`reproduce_report.json` green（173/173 checks matched, 100.0%, 7 tables verified）。~~但 B2 未過 0-blocking gate~~ → **Addendum 終驗後 0-blocking gate 達成，可進 QF compliance gate。**

---

## 逐條覆核（本 agent 獨立核對）

### B1 — 符號式家族 ordering 主張 → **FIXED**

**雙編碼 grep**（unicode `≤` + LaTeX `$\le$`）：
- `grep '\le' main.tex` → 唯一命中 **L193**：「Monte Carlo standard error … is $\le 0.02$ for all adoption levels」——這是 MC 標準誤界限，**與家族 ordering 完全無關**。
- `grep '≤' main.tex` → **零命中**（無 unicode ≤）。
- 故 P0-2 假性通過的根因（grep 用 unicode `≤` 抓不到 LaTeX `$\le$`）已無殘留標的：符號式 `TF/MR $\le$ VT` 主張式宣稱 = **0**。

**舊 4 處主張式殘留（v6 review 定位）已消除**：
- 舊 L413「The directional ordering TF/MR $\le$ VT is preserved under both MC settings」→ 已改（現 footnote b, L413：「these superseded-detector level-crossings sit at or below VT's---**reported as a property of that detector's output, not as a family-level claim**」）。
- 舊 L420「17 distinct parameter-perturbation checks …, **all preserving TF/MR $\le$ VT** … not supported by the data」（捍衛 70% threshold + 家族 ordering）→ **重寫**為現 L420：「For VT itself, all five microstructure cells preserve the **monotone-erosion shape**, so the critique that a single $(\lambda,\gamma)$ choice manufactures the **VT result** is not supported by the data. We **draw no family-level ordering conclusion** from the legacy 12-cell strategy-spec grid…」——防守對象由「70% threshold + 家族 ordering」改為「VT monotone shape」，並顯式對齊同節 L418「draw no family-level ordering conclusion」。
- 舊 L462「whose **ordering (TF/MR $\le$ VT) is robust**」→ 現 L458 段：「a shape robust to the tested specification choices」（ordering 字樣移除）。

**殘留 ordering 提及全為誠實敘事（非主張）**：L36 abstract「family claims are withdrawn」、L300「supersedes the family-level ordering claims of earlier drafts … confine … to VT」、L330「we withdraw it as evidence of class-level crowding」、L377「we no longer advance a family-level ordering claim」、L418「draw no family-level ordering conclusion」、L469/L471「retained for continuity only … not counted as evidence for any family-level claim」、L478「family-level ordering claims are withdrawn rather than supported」。§oat + Limitations 與 abstract / §cross_strategy **無 split-brain**。

**一處非 blocking 觀察（不影響 verdict）**：footnote a（L412）保留「the null is treated as **MR threshold $\ge$ VT threshold**」，但語境明標「under the rank encoding used in our **verdict-classification logic**」——描述的是 code 對 saturated null 的**內部 rank 編碼機制**，位於 superseded-detector legacy 表的 footnote，且被同小節 L418「draw no family-level ordering conclusion」框住。屬機械/歷史描述，非論文 voice 的主張式家族 ordering，故不列 NOT_FIXED。Codex 亦判 B1 CONFIRM_FIXED。

### B2 — RR matched-control fidelity overclaim → **NOT_FIXED（殘留於 L212）**

**原始 2 處已修**：
- **L99**：「inherits the realized trading-footprint **\emph{distribution}** … its rebalance frequency and the **mean and standard deviation** of its per-step weight-change magnitude $|\Delta w^X|$ … applies the sign … from an **independent Bernoulli$(0.5)$** draw」——舊「inherits, at every step $t$, … in a paired simulation」已改。
- **L243**：「trades **volumes drawn from VT's realized footprint distribution (rebalance frequency and $|\Delta w|$ moments matched within 5\%)** but selects the trade sign by coin flip」——舊「trades exactly the same per-step volumes」已刪。
- L237 誠實版保留（「within 5\%」）；abstract L36 / intro L60 亦改 distributional。

**但殘留一處研究誠實級 overclaim（Codex 抓到，本 agent 讀 L212 原文確認）**：
- **L212**（§Matched-Control Identification 開頭句）：「The random-direction matched-control RR\_VT … **holds the per-step trading footprint fixed at VT's realized level** while randomizing the direction of weight changes via independent Bernoulli$(0.5)$ draws」。
- 此句斷言 RR_VT 把**每一步幅度固定在 VT 的實現值（per-step footprint fixed at VT's realized level）**、只隨機化方向。但 code 實況（`RandomRebalanceAgent`, L256–276）是：`__init__(freq, dw_mean, dw_std)` 三標量 → L260–263 以 lognormal 參數配 mean/std → L273 Bernoulli(freq) 觸發 → L276 `dw = sign * rng.lognormal(ln_mu, ln_sigma)`。即**從配好 moment 的 lognormal 抽幅度，並非逐步 pin 到 VT 的實現 `|Δw_t|`**。
- 「fixed at VT's realized level」= 同一 B2 overclaim（幅度逐步固定）換到 §Matched-Control 開頭句，且**與已改的 L99/L243 distributional 措辭自相矛盾**——投稿時 replication-package 審查會抓到論文↔code 不一致（正是 v6 review 警告的情形）。
- **次要一處**（tidy，非獨立 blocking）：L99 首句框架語「holds the treatment's trading footprint **fixed** but randomizes its directional rule」的「fixed」亦宜掛 distributional 限定；惟該句緊接精確 distributional 定義，語意被下一子句澄清，嚴重度低於 L212。

**修法**：把 L212 的「holds the per-step trading footprint fixed at VT's realized level」改為與 L99/L243 一致的 distributional 措辭（例：「matches VT's realized trading-footprint distribution—rebalance frequency and $|\Delta w|$ moments (within 5\%)—while randomizing direction」），去掉「per-step … fixed at VT's realized level」的逐步 pin 含義。此為純寫作修正，不需重跑。**修完須再跨模型複核（B2 研究誠實級，不可同模型自審放行）。**

### B3 — turnover-cap applicability gate（code 不存在）→ **FIXED**

**第二條件全刪**：`grep -iE 'turnover-cap|clip rail.*gate|10\% of (MC|sims)|20\% of trading|>80\% of MC|either condition'` → 僅 L99「retaining the original **clip rail $[0,1.5]$**」命中，那是**權重界限**（= code `EXPOSURE_CAP=1.5`, L254/L278），非 phantom turnover-cap gate。turnover-cap 第二條件 = **0**。

**gate 改為單條件**：
- **L101**：「reported as applicable only when the treatment $X$ … passes a **baseline-Sharpe floor: mean Sharpe across MC simulations $> -0.5$**」——只有一條。
- **L237**：「baseline-Sharpe floor $> -0.5$」+ 描述性「realized footprint … within 5\%」（不再宣稱 gate 條件 (ii)）。

**與 code 一致**：`detect_threshold_exogenous`（L505–531）gate 只有 `if not np.isfinite(base_mean) or base_mean < APPLICABILITY_FLOOR: status='not_applicable_saturated_loss'`；`APPLICABILITY_FLOOR = -0.5`（L143）。全 code 無 turnover-cap / clip-rail-gate 邏輯。

**排除計數保留**：TF 4/5、MR 5/5 敘述在 L36 / L247 / L300 / L330 / L458 / L478 皆在（由 Sharpe floor 驅動，不受第二條件刪除影響）。Codex 亦判 B3 CONFIRM_FIXED。

### M1 — detector「no internal break」措辭 → **FIXED**

**「internal break」歸零**：`grep 'internal break'` → **零命中**。全部改為「**interior** break」+ 邊界定位：L36「identifies **no interior break** (the single breakpoint localizes to the saturation boundary)」、L136 footnote「the argmax breakpoint sits at the saturation boundary, after 70\%」、L199/L293「locates/identifying **no interior break**」、L478「the single breakpoint localizes to the saturation boundary rather than an interior adoption level」。

**與 JSON 相容**：`.cells.cell1_baseline.detector.VT_baseline` = `breakpoint_split_after:"70%"`、`threshold:"100%"`、`degradation_direction:true`、`threshold_bootstrap_freq:{"100%":1.0}`、`status:"ok"`。新措辭「breakpoint 落在飽和邊界（after 70%，即 100% endpoint）」與 detector 機械回報的 argmax 斷點完全相容。Codex 亦判 M1 CONFIRM_FIXED。

### m1 — intro RR_VT 改善值 → **FIXED**

L60 現為「Sharpe in fact improves by **$+0.080$ to $+0.098$** with adoption」（舊「+0.06 to +0.09」已改）。JSON RR_VT 各 cell Δ(100%−10%)：cell1 0.0932、cell2 0.0953、**cell3 0.0803（min）**、**cell4 0.0977（max）**、cell5 0.0887 → 範圍 +0.080~+0.098；mean = 0.0910 → L243「mean RR\_VT change is **$+0.091$**」吻合。Codex 亦判 m1 CONFIRM_FIXED。

### m2 — §Statistical S₅₀/S₇₀ 來源 → **FIXED**

L295 現為：「$\bar{S}_{50\%} = 0.336$ vs.\ $\bar{S}_{70\%} = 0.084$; **these Welch comparisons are computed on the Phase-1 cross-treatment run---the redesign-layer canonical-cell means are $0.338$ and $0.091$, with identical qualitative conclusions**」——Phase-1 揭露句在場，redesign 值 0.338/0.091 明列。JSON `.cells.cell1_baseline.treatments.VT_baseline.per_adoption`：50% sharpe.mean = **0.33804**、70% = **0.09086** → 精確吻合。Codex 亦判 m2 CONFIRM_FIXED。

---

## 附帶檢查

- **pdflatex**：`main.log` 尾部「Output written on main.pdf (**35 pages**, 562483 bytes)」；`grep '^!|Fatal error|Emergency stop'` → 無。編譯通過。
- **reproduce gate**：`reproduce_report.json` → `alert_level:"green"`；`match_summary`：tables_verified 7、checks_total 173、checks_matched 173、overall_match_rate_pct 100.0。green。

---

## Codex 獨立覆核軌（異模型 gpt-5.6-sol，read-only）

- **命令**：`printf '%s' "$(cat <prompt>)" | bash scripts/codex_exec_bounded.sh --timeout 420 -s read-only -`（唯讀 sandbox，中文 prompt via stdin）
- **codex-cli**：0.144.1；exit 0
- **raw transcript**：同目錄 `codex_reverify_transcript.txt`（340KB，含 codex 讀 main.tex/git diff/code/JSON 全程 + 最終結構化 verdict）
- **prompt**：禁 fan-out、單 pass、每條回 CONFIRM_FIXED / NOT_FIXED + 一句證據

### Codex 最終 verdict（verbatim）

```
- [B1] CONFIRM_FIXED — `≤` 無命中，`\le` 僅剩無關的 MCSE 敘述；TF/MR ordering 殘留均明列為歷史、superseded 或已撤回，無 split-brain。
- [B2] NOT_FIXED — main.tex:212 仍稱「holds the per-step trading footprint fixed」，但程式僅以 `freq/dw_mean/dw_std` 生成 lognormal 幅度及 Bernoulli 符號（k1471_vt_crowding_redesign.py:256），仍屬 per-step fidelity overclaim。
- [B3] CONFIRM_FIXED — main.tex:101 僅保留 baseline Sharpe floor，與 k1471_vt_crowding_redesign.py:527 唯一 gate 一致，且 TF 4/5、MR 5/5 計數仍在。
- [M1] CONFIRM_FIXED — 稿中已統一為「no interior break／saturation boundary」，並與 JSON 的 `breakpoint_split_after="70%"`、`threshold="100%"` 相容。
- [m1] CONFIRM_FIXED — main.tex:60 已改為 `+0.080` 至 `+0.098`，與表格及 JSON 五格差值範圍一致。
- [m2] CONFIRM_FIXED — main.tex:295 已揭露 `0.336/0.084` 來自 Phase-1，並明列 redesign 的 `0.338/0.091`，與 JSON 的 `0.3380435/0.0908566` 一致。

總結：CONFIRM_FIXED：B1、B3、M1、m1、m2；NOT_FIXED：B2。
```

### 兩軌一致性

本 agent 獨立核對與 Codex **完全一致**：B1/B3/M1/m1/m2 = FIXED，B2 = NOT_FIXED。B2 的 NOT_FIXED 由 Codex 先指出 L212，本 agent **親自讀 L212 原文 + 對 code L256–276 核對後採信**（本 agent 初掃 grep pattern 未涵蓋「per-step trading footprint」故漏抓，經 Codex 指認後補核確認——此為 cross-model review 的正面例證：異模型抓到 same-model 自審漏掉的研究誠實級殘留）。

---

## 結論

fix commit `4217af920` 對 v6 review 六條 findings，**5 條 FIXED（B1/B3/M1/m1/m2）**、**1 條 NOT_FIXED（B2）**。

- B1（符號式家族 ordering）、B3（phantom turnover-cap gate）兩條研究誠實級 BLOCKING **已對齊 code/JSON ground truth**，M1/m1/m2 亦全 FIXED，附帶編譯與 reproduce gate 通過。
- **B2 仍未過**：L212「holds the per-step trading footprint fixed at VT's realized level」是同一 fidelity overclaim 換位到 §Matched-Control 開頭句，與 code 的 lognormal-moment 抽樣及已改的 L99/L243 自相矛盾。**須修 L212（純寫作）並再跨模型複核，才可進 QF compliance gate / paper-update。** v6 review 的 0-blocking DoD **尚未達成**。


---

## Addendum（2026-07-14 14:01，主線程記錄）

L212 殘留於 commit `a74895380` 修復（「holds the per-step trading footprint fixed at VT's realized level」→「matches VT's realized trading-footprint distribution---rebalance frequency and the $|\Delta w|$ moments, within 5\% per cell---」；L99 框架句同步掛 distribution 限定）。覆核 agent 隨後執行 Codex 窄範圍終驗（transcript 已 append 至 `codex_reverify_transcript.txt`，455KB），Codex verdict verbatim：

> [B2] CONFIRM_FIXED — L99/L212 現明確為頻率與 |Δw| ensemble moments 匹配，符合 L256–276 的 lognormal＋Bernoulli 實作；全稿未見逐步固定或完全相同交易量的殘留宣稱。

覆核 agent 在寫回本檔前 idle，主線程據上述 durable 存證代錄（非同模型自我認證 — verdict 出自 Codex 異模型終驗）。**v6 review 0-blocking DoD 於此達成。**
