# K1702：波動率管理套用到「整個因子動物園」的 OOS 崩潰再驗證

**Verdict: `NULL_OR_MIXED_INDIVIDUAL_FACTOR_OOS`。** 六個因子在 OOS + 淨成本後無一個**正向效果**
通過預設 gate；CMA 反而顯著受害。等權動物園組合 gross 只有 +0.036 Sharpe（不顯著），
10bp 即翻負，50bp 時 Sharpe 變成 **−0.177**。

**外加一個回撤 claim 的正式反證**：`R3` 宣稱的「vol-managing 讓 drawdown 改善（5/6 因子）」
不能由 raw MDD 支撐；六個因子的實現波動全部相差超過 canonical 20% 門檻。曝險匹配後只有 MOM 的 gap
為正，而且把同一權重路徑枚舉全部 circular shifts、再做 Holm 校正後是 **0/6 存活**。因此資料不支持
「回撤較淺來自 timing skill」；`MDD ÷ vol` 的 1/6 僅保留為描述性診斷，不再冒充 scale-invariant gate。
（範圍限定：本實驗只測 long-short paper factors。其他資產 / 訊號的 raw-MDD claim 須各自重驗，
見 §十 的 class sweep 待辦。）

## 研究問題

Moreira and Muir (2017, JF) 顯示對**市場因子**做 inverse-variance scaling 能提升 Sharpe 與 spanning alpha。
本實驗誠實檢驗：把同一套 vol-scaling 套到**整個因子動物園**（SMB / HML / RMW / CMA / MOM / QMJ），
**樣本外、且計入交易成本後，還存活嗎？**

先驗立場：Cederburg et al. (2020) 指出 OOS 失效；Barroso and Detzel (2021) 指出成本後不存活。
**本實驗預期 NULL，null 如實報告即為成功** —— 不為了「有結論」去挖 p 值。

## 與既有院內證據的關係

| 既有 | 內容 | K1702 |
|---|---|---|
| `R3`（2026-03-17，knowledge.json） | Factor VT OOS null；"MDD improvement robust (5/6 factors) but Sharpe unchanged" | 該 entry **無 `experiment_id` / 無 reviewer / 無 verdict — 不可復現的 orphan claim**。K1702 確認其 OOS null 方向，並證明本次 long-short factor 樣本的 5/6 raw-MDD pattern **不能當 timing 證據**（phase-null 0/6）。註：R3 的因子宇宙與 spec 不同，兩邊 5/6 是方向一致的計數巧合，不是逐項複製 |
| `N107` | 「MDD improvement is MECHANICAL（隨機 de-leveraging 下 99% 也會出現）」 | **院內早有此先驗**。K1702 的增量不是首次發現機械性，而是把 factor-zoo 的曝險匹配 gap 對完整 circular-shift null 做正式檢定：僅 MOM gap 為正，Holm 後 0/6 存活 |
| `K1265` | SPY、VIX/RV-managed、2004-2026；「MM 主要壓 MDD 而非提 Sharpe」 | **本實驗未測試該設計**（不同資產 / 訊號 / scaling rule），**不可宣稱推翻**。只能說：K1265 的 MDD claim 落在同一失效模式的射程內，須用 **exposure-matched gap + circular-shift null** 重驗（待辦，非本實驗結論） |
| `K1574` | factor **ETF** implementation shortfall（ex-post audit） | K1702 用官方 long-short paper factors，問 timing 而非 implementation |
| `research_factor_timing_regime` | ETF factor timing 不打敗 EW basket | K1702 是 vol-scaling（非 regime timing）+ 淨成本層 |

**K1702 的增量**：(1) **淨成本層**（R3 沒有）；(2) **QMJ**（R3 沒有）；(3) **固定校準常數的真 OOS**；
(4) **正式 BH-FDR**；(5) **pipeline 證偽測試**；(6) **MM 效果的樣本期分解**；
(7) **MDD claim 的曝險匹配 + circular-shift 反駁**。

---

## 一、先跑證偽測試，才准解讀 null

**一個 null 只有在「這套 code 本來就有能力驗出正結果」時才可解讀**，否則 null 只是 bug 的別名。
所以在判斷動物園之前，先用**同一條 pipeline**、在 **MM 自己的樣本**上重跑他們的 headline
（市場因子、uncapped、零成本、in-sample 常數 —— 完全照論文設定）：

| | Unmanaged SR | Managed SR | Spanning alpha | HAC t |
|---|---|---|---|---|
| **本 pipeline（1926-08…2015-12，n=1073）** | **0.416** | **0.511** | **+4.7%/yr** | **2.70** |
| Moreira-Muir (2017) 原文 | ~0.41 | ~0.56 | ~4.9%/yr | ~3.1 |

**Pipeline 通過證偽測試。** 後面的 null 不是 bug。

同一檢定切成子期，直接解釋了整份實驗：

| 市場因子子期 | n | Sharpe 差 | Spanning alpha | HAC t |
|---|---|---|---|---|
| 1926-08…1963-06（MM 效果的來源） | 443 | **+0.147** | **+7.7%/yr** | 2.21 |
| 1963-07…1999-12（本實驗校準期） | 438 | +0.008 | +2.0%/yr | 1.07 |
| 2000-01…2026-05（本實驗 OOS） | 317 | +0.024 | +3.3%/yr | 1.18 |

在這個 in-sample 分解裡，MM 的市場因子效果**集中於 1963 年之前**；1963 年後的兩格都沒有統計上
站得住的收益。這是樣本期診斷，未做正式跨子期差異檢定，不能把「集中」升格成結構性年代斷言。

---

## 二、方法論陷阱：為什麼 DM 檢定**不能**用來判定這件事

這是本實驗最重要的方法論教訓，也是 code review 抓出的錯誤（初版曾誤用）。

`strategy_dm_test(loss_fn="negative_return")` 比較的是**原始平均報酬**，**不是風險調整後**的。
而本設計的縮放常數固定在 2000 年前，2000 年後實現波動較高 → **managed 組合的曝險系統性低於 benchmark**
（MOM：年化波動 4.4% vs 17.4%，低 4 倍）。曝險低 → 平均報酬**機械性地**較低，**即使 Sharpe 大幅更好**。

MOM 就是活生生的反例：

| | Sharpe | 年化報酬 | 年化波動 |
|---|---|---|---|
| MOM unmanaged | 0.221 | 3.84% | 17.4% |
| MOM vol-managed | **0.486** | 2.12% | 4.4% |

Sharpe 說它**大幅變好**，raw mean return 說它**變差**。若拿 DM 當 gate，`t < −3` 幾乎**永遠不可能觸發**，
於是必然得出「vol-managing 沒用」—— **一個永遠不會 fire 的 gate 不是證據，是壞掉的儀器**。
而它剛好朝我們的先驗方向壞掉，這正是最危險的確認偏誤：**製造出 null 的 artifact，和製造出勝利的 artifact，
一樣不可信。**

**因此本實驗的 gate 只用 scale-invariant 統計**：
- **paired Sharpe bootstrap**（Sharpe 是 scale-invariant）
- **spanning regression alpha t**（β 吸收曝險落差；alpha 水準本身會隨 scale 改變）

DM 保留在 results JSON，但明確標記為 `strategy_dm_mean_return_SCALE_DEPENDENT_diagnostic`，**不進 gate**。

---

## 三、資料

| 來源 | 內容 | 期間 |
|---|---|---|
| Kenneth French（FF5 daily） | Mkt-RF, SMB, HML, RMW, CMA | 1963-07 起（Compustat 限制） |
| Kenneth French（Momentum daily） | MOM | — |
| Kenneth French（FF3 daily） | Mkt-RF **1926-07 起**，僅供上面的 MM 證偽測試 | 26,253 日 |
| AQR Data Library | QMJ（USA 欄，daily） | — |

- **共同樣本**：1963-07-01 … 2026-04-30，**15,813 個交易日 / 754 個月**（≫ 500 觀測要求）
- **校準期**：1963-07 … 1999-12（438 個 calendar months；因 signal lag，實際可用 training rows = **437**）
- **OOS**：2000-01 … 2026-04（**316 個月**），涵蓋 **2008 金融海嘯與 2020 疫情崩盤**（滿足「OOS 必含空頭」）
- 下載檔 SHA-256 記於 results JSON。AQR 更新時重建完整歷史，故 QMJ 是「本次 vintage」估計，
  **不宣稱 point-in-time vintage robustness**。

## 四、方法

1. 月 t 的 realized variance = 該月日報酬平方和；月 t+1 曝險 = `(1 / RV).shift(1)` —— 代碼有明確 lag。
2. **縮放常數 c 只用 1999 年前資料估**，OOS 全程固定不重估。驗證：校準期 managed 與 unmanaged 波動精確相等
   （MktRF 兩者皆 0.0440）。
3. Baseline 與 managed **使用完全相同的月報酬列**。
4. 變體：uncapped 與 cap=3.0（primary）；成本 **0 / 10 / 25 / 50 bps**（primary = 25bp）。
5. 檢定：`volpred.stats.model_evaluation.strategy_dm_test`（canonical，未自寫 local DM）；
   paired stationary bootstrap（**seed=42**、2,000 次、平均 block 12 月、含 `(1+k)/(B+1)` 連續性修正）；
   spanning regression HAC alpha。
6. **多重檢定**：對六個動物園因子做 BH-FDR。**Mkt-RF 事前排除於檢定家族之外** —— 它是「pipeline 能否重現 MM」
   的複製對照，不是 discovery hypothesis，放進去會稀釋校正。

### HAC bandwidth（依 `.claude/rules/experiments.md` 硬規則）

規則禁止把 Newey-West lag 固定在 `h−1`（h=1 時退化成 **0 lag = 根本沒做 HAC**）。
本實驗用 `lag = max(h−1, canonical)`，canonical = `ceil(h^(1/3)·n^(1/3))`，與 repo canonical `dm_test` 同一條規則。
Primary lag 先按 canonical 公式決定；ACF 是事後診斷，另完整報 lag sensitivity（全存於 results JSON 的
`residual_acf` / `hac_lag_sensitivity`）。lag 0 是 plain OLS，與 HAC 的差異同時含異質變異與序列相依，
不把 t 值變化單獨歸因於 ACF 正負：

| cell | n | primary lag | residual acf(1), acf(2) | alpha t @ lag0（**無 HAC**） | alpha t @ primary lag |
|---|---|---|---|---|---|
| MM 複製（1926-2015） | 1073 | 11 | +0.101, −0.005 | **3.02 → 會誤過 Harvey t>3** | **2.70 → 不過** |
| CMA（OOS primary） | 316 | 7 | +0.095, −0.028 | −2.52 | −2.36 |
| MOM（OOS primary） | 316 | 7 | −0.030, **−0.149** | 2.25 | **2.37 → |t| 反而變大** |

lag 0→primary 的 t 值可往任一方向移動；ACF 正負提供背景，但差異也包含異質變異，不能單獨歸因。
重要的是所有結論在 0/3/6/primary/12 的完整 sensitivity 上都不跨越正向 Harvey gate。

### 跨因子聚合（避免 iid 誤設）

同一日曆月的多個因子共享市場 shock，**stacked factor-month pooled 檢定會低估標準誤**。
本實驗**先在每個月內跨因子等權聚合**，再對單一月序列做時間序列 DM / HAC。
**全文未報告任何 stacked factor-month 檢定**（連 diagnostic 都沒有）。

---

## 五、結果

### 5.1 個別因子（primary：cap 3x、**25bp**、OOS 2000-2026）

| 因子 | OOS Sharpe（unmgd → mgd） | Sharpe 差 | bootstrap 95% CI | BH q | Spanning alpha | HAC t | BH q |
|---|---|---|---|---|---|---|---|
| SMB | 0.184 → −0.048 | −0.232 | [−0.45, **−0.01**] | 0.088 | −0.8%/yr | −1.60 | 0.219 |
| HML | 0.235 → 0.006 | −0.229 | [−0.64, 0.21] | 0.319 | −0.7%/yr | −0.56 | 0.693 |
| RMW | 0.470 → 0.118 | −0.351 | [−0.66, **−0.02**] | 0.088 | −0.4%/yr | −0.92 | 0.533 |
| CMA | 0.322 → −0.167 | **−0.489** | [−0.78, **−0.17**] | **0.012** | −1.6%/yr | −2.36 | 0.055 |
| **MOM** | 0.221 → **0.486** | **+0.265** | [**−0.05**, 0.56] | 0.157 | **+1.6%/yr** | **+2.37** | 0.055 |
| QMJ | 0.376 → 0.206 | −0.170 | [−0.48, 0.14] | 0.319 | −0.1%/yr | −0.16 | 0.871 |

- **無一因子的 spanning alpha 通過 Harvey |t| > 3。**
- **五個因子的 Sharpe 變差**，其中 **CMA 是顯著被傷害**（bootstrap BH q = **0.012**）。
- **MOM 的誠實處理**：它是唯一改善的因子（Sharpe +0.265，alpha +1.6%/yr，HAC t = 2.37），
  方向與 Barroso and Santa-Clara (2015) 的 momentum-crash 保護一致，**但本實驗無法排除雜訊**。
  **但** bootstrap CI **含 0**（[−0.05, 0.56]），alpha 的 **BH q = 0.055 > 0.05（邊緣不顯著）**，
  且 t = 2.37 未達 Harvey 門檻。**故本實驗不宣稱 MOM 存活** —— 六個因子挑最好的一個講故事，
  正是本實驗要防的事。留待專門的 momentum 實驗處理。

### 5.2 動物園組合（等權，月內跨因子聚合）—— DeMiguel et al. (2024) 視角

| 成本 | Sharpe（unmgd → mgd） | 差 | Spanning alpha | HAC t |
|---|---|---|---|---|
| 0bp（gross） | 0.562 → 0.598 | **+0.036** | +0.5%/yr | 1.73 |
| 10bp | 0.562 → 0.441 | −0.121 | +0.2%/yr | 0.81 |
| **25bp（primary）** | 0.562 → **0.207** | **−0.355** | −0.2%/yr | −0.54 |
| 50bp | 0.562 → **−0.177** | **−0.739** | −0.8%/yr | −2.53 |

**Gross 時本就只有 +0.036 的微弱改善（不顯著），10bp 就翻負，50bp 直接把 Sharpe 打成負的。**

成本算術已交叉驗證，**未重複計算**：六因子平均年 turnover 2.57 × 25bp = **0.64%/yr**，
與 JSON 實測 return drag **0.64%/yr** 完全吻合。

### 5.3 成本存活（**六個動物園因子**中維持正 Sharpe 差的個數）

| 0bp | 10bp | 25bp | 50bp |
|---|---|---|---|
| 1/6 | 1/6 | 1/6 | 1/6 |

即使 gross（零成本）也只有 1/6（MOM）。

### 5.4 **R3 的 MDD claim 不受支持：曝險匹配 + circular-shift null**

院內 `R3` 宣稱「MDD improvement robust (5/6 factors)」。K1702 的 raw MDD 也得到 5/6，但六個 managed
序列的實現波動都比 benchmark 低 45.6%–76.7%，遠超 canonical 20% mismatch 門檻，raw MDD 不能單獨比較。
`MDD ÷ vol` 同樣不是不變量（財富複利使 MDD 對槓桿非一次齊次），所以 1/6 只列描述，不當 gate。

正式檢定分兩步：

1. 把 benchmark 用**常數** λ 縮到與 managed 相同實現波動，計算 exposure-matched gap；
2. 枚舉同一 capped weight path 的全部 316 個 circular shifts，保留權重值、持續性與 turnover-cost
   路徑，只破壞它與報酬的 phase；以全 shifts 枚舉 tail fraction 作 p，再對六因子做 Holm 校正。

| 因子 | raw MDD（unmgd → mgd） | production 同風險 gap | circular-null p | Holm p |
|---|---|---:|---:|---:|
| SMB | −0.361 → −0.304 ✅ | **−14.6pp** | 0.883 | 1.000 |
| HML | −0.560 → −0.435 ✅ | **−13.4pp** | 0.797 | 1.000 |
| RMW | −0.220 → −0.130 ✅ | **−7.5pp** | 0.756 | 1.000 |
| CMA | −0.269 → −0.321 ❌ | **−16.6pp** | 0.747 | 1.000 |
| **MOM** | −0.562 → −0.092 ✅ | **+8.2pp** | 0.158 | **0.949** |
| QMJ | −0.306 → −0.146 ✅ | **−5.7pp** | 0.494 | 1.000 |

只有 MOM 的同風險 gap 為正，但它並不罕見於錯 phase 的同一權重路徑；Holm 後 **0/6** 在 5% 或 10%
水準存活。這支持的精確結論是：**本樣本沒有證據顯示較淺回撤來自 timing skill，R3 類 raw-MDD
headline 不能成立**；不是「證明 timing 完全不存在」。R3 的 universe/spec 與本實驗不完全相同，
故回溯 class sweep 仍須逐案重驗，不能把 K1702 的 p 值直接移植過去。

### 事前成功標準 vs 實際

事前門檻（六因子動物園）：≥4/6 Sharpe 改善、≥2 個 bootstrap CI 排除 0 且 FDR<0.05、
≥2 個 spanning alpha 通過 Harvey 且 FDR<0.05、≥2 個在兩子期都為正。
**實際：1/6、0、0、1 —— 四項全部不通過。**

---

## 六、結論（強度嚴格不超過證據）

1. **正向 gate 為 NULL、個別結果為 MIXED。** 把 MM 的 vol-scaling 套到因子動物園，2000 年後樣本外、
   計入成本後無一正向效果通過。無一因子的 spanning-alpha t 通過 Harvey；BH-FDR 後無一顯著改善；
   **CMA 反而顯著變差**。
2. **成本是主角不是配角。** 動物園組合 gross 的改善本就微弱（+0.036，不顯著），**10bp 即翻負**。
   分散化後組合波動僅 5.85%，~0.64%/yr 的成本 drag 就吃掉大半個 Sharpe 單位。
3. **MM 複製中的效果集中在 pre-1963 子期。** 同一 in-sample pipeline 在 1926-1963 得到 alpha 7.7%/yr，
   到 1963-1999 只剩 2.0%/yr（t=1.07）；這是樣本期診斷，不把它升格成結構性年代斷言。
4. **「vol-managing 壓低 drawdown」在本因子樣本不受支持。** raw 5/6 全部有重大曝險 mismatch；
   exposure-matched gap 只有 MOM 為正，對自身 circular-shift null 做 Holm 後 **0/6 存活**。
   精確結論是沒有 timing 證據、R3 類 raw-MDD headline 不能成立，不是證明 timing 不存在。
   `K1265`（SPY、VIX-managed）本實驗未測，不移植本案 p 值；整個 claim class 仍須逐案重驗。
5. **MOM 是唯一方向為正的因子**（與 momentum-crash 文獻一致），**但多重檢定後不顯著（BH q=0.055，邊緣），
   本實驗不宣稱它存活。**
6. **方法論教訓（可推廣）**：比較兩個**曝險水準不同**的策略時，不可用 raw mean-return DM 或 raw MDD
   承載 gate。報酬面用 Sharpe / spanning-alpha t；回撤面用 exposure-matched gap，再把 gap 對該權重路徑
   的 phase-randomization null 檢定。`MDD ÷ vol` 只能當描述性 normalisation。

## 七、限制（不可略過）

- **成本口徑是 overlay turnover 下界**：只收 factor-level 曝險變動的費用，**沒有** constituent-level 換股、
  買賣價差、放空成本、因子再平衡成本。**且因子是 long-short，Δ曝險 1 單位實際成交約 2 單位 gross notional，
  故真實成本至少還要再乘以約 2 倍。** 真實成本必然更高 → **本實驗的 null 是保守的**，真實世界只會更差。
- 動物園組合是「先各自扣成本再等權平均」，未做跨因子 turnover netting，對 combo 略為高估 overlay 成本；
  但相對於被忽略的 constituent-level 成本，整體仍是下界。
- **已發布的 long-short paper factors 不是可直接投資的組合。**
- **Managed 組合的 OOS 實現波動遠低於 unmanaged**（見 5.4 表）。Sharpe 與「成本的 Sharpe 衝擊」皆為
  **scale-invariant**（槓桿常數在分子分母同時消掉），故比較公平；但**不可**把 managed 的絕對報酬水準
  或 raw MDD 與 unmanaged 直接對比（這正是 5.4 的教訓）。
- **spanning alpha 的「水準」也不是 scale-invariant，只有它的 t 統計量是。** §5.1 的 OOS alpha
  （−0.8 … +1.6 %/yr）估在 β≈0.15 的低曝險 managed 序列上；§一 / §六-3 的 MM 複製 alpha
  （+4.7 / 7.7 / 2.0 %/yr）估在 in-sample **vol-matched**（β≈0.62）序列上。**兩張表的 alpha
  magnitude 不可互相對讀**（換算到同曝險後 OOS alpha 約放大 4 倍）。顯著性判定不受影響。
- AQR 更新時重建 QMJ 完整歷史，此處無歷史 vintage 可用。
- 與 AQR 日曆做 inner join 會裁掉部分 French 交易日，故 Mkt-RF 的 RV 不是純 French 複製
  （MM 證偽測試那條路徑用純 FF3，不受此影響）。
- 固定 2000 年切點是**一種** real-time 設計，不能消除全部 specification uncertainty。
- exposure-matched λ 使用完整 OOS realized volatility，是事後 attribution benchmark，不可交易。
- circular-shift test 假設 persistent volatility weights 近似 circularly stationary；不是 exactly-sized parametric test。
- 美股因子；無對等的台股 QMJ 序列。
- MM 複製測試的每一格**都是 in-sample**（常數在被評估的同一窗口上估），是 pipeline 診斷，**不是 OOS 主張**。

## 八、復現

```bash
uv run python experiments/k1702/k1702.py
```

固定 `SEED = 42`。原始 ZIP/XLSX 快取於 `data/`（`.gitignore` 排除），可用 `FF3_DAILY_ZIP` /
`FF5_DAILY_ZIP` / `MOM_DAILY_ZIP` / `AQR_QMJ_XLSX` 指向已下載的唯讀檔。

**產出**：`k1702_results.json`（全部 cell、acf、lag sensitivity、drawdown_analysis、SHA-256；
每個 cell 帶 `is_primary_spec` / `multiple_testing_corrected` 標記以防下游 cherry-pick）、
`summary_table.csv`、`analysis_panel.csv`、`is_vs_oos_gross_vs_net.png`、
`factor_sharpe_comparison.png`、`cost_sensitivity.png`。

## 九、參考文獻

- Moreira, A., & Muir, T. (2017). Volatility-Managed Portfolios. *Journal of Finance, 72*(4), 1611-1644. https://doi.org/10.1111/jofi.12513
- Cederburg, S., O'Doherty, M. S., Wang, F., & Yan, X. (2020). On the Performance of Volatility-Managed Portfolios. *Journal of Financial Economics, 138*(1), 95-117. https://doi.org/10.1016/j.jfineco.2020.04.015
- Barroso, P., & Detzel, A. L. (2021). Do Limits to Arbitrage Explain the Benefits of Volatility-Managed Portfolios? *Journal of Financial Economics, 140*(3), 744-767. https://doi.org/10.1016/j.jfineco.2020.11.006
- DeMiguel, V., Martin-Utrera, A., & Uppal, R. (2024). A Multifactor Perspective on Volatility-Managed Portfolios. *Journal of Finance, 79*(6), 3859-3891. https://doi.org/10.1111/jofi.13395
- Barroso, P., & Santa-Clara, P. (2015). Momentum Has Its Moments. *Journal of Financial Economics, 116*(1), 111-120. https://doi.org/10.1016/j.jfineco.2014.11.010
- Asness, C. S., Frazzini, A., & Pedersen, L. H. (2019). Quality Minus Junk. *Review of Accounting Studies, 24*, 34-112. https://doi.org/10.1007/s11142-018-9470-2

## 十、審查狀態

- **Pre-run review**：`feature-dev:code-reviewer` subagent（fresh context）。Codex CLI 在 ultra reasoning 下
  審 950 行超過 10 分鐘上界，依 `.claude/rules/experiments.md` fallback 條款改派。
- Review verdict **FAIL**，抓到兩個真問題，**均已修正**：
  1. **DM gate 是壞掉的儀器**（scale-dependent，見 §二）→ gate 改為 scale-invariant 統計；
     DM 降級為明確標記的診斷。**這個修正也讓我發現了 §5.4 的 MDD scale artifact。**
  2. **`cost_survival` 把 Mkt-RF 混進動物園統計**（報成 2/7，實為 1/6）→ 已改為 zoo-only。
  另修：silent `except: pass`（AQR parser 改為計數 + 上限 fail-loud）、bootstrap p 的 `(1+k)/(B+1)`
  連續性修正、負財富時的 MDD guard、單位尺度 fail-loud guard、每格加 `is_primary_spec` /
  `multiple_testing_corrected` 標記（K1655 教訓）。
- **Post-run review**（2026-07-13，hourly-06 主線程收件）：第二個 `feature-dev:code-reviewer`
  fresh-context 獨立審查，逐項核對 lookahead / HAC / gate 口徑 / 跨因子聚合 / 數字對帳 / seed。
  **verdict = CONDITIONAL_PASS**：計算層七項全 PASS（signal `.shift(1)`；scale 常數只用 pre-2000
  calibration window；`canonical_hac_lag` 與 repo canonical 逐字等價、h=1 時取 lag 7 未踩 `h-1` 退化；
  無 factor-month iid 串接；README 表格與 `k1702_results.json` **全量**對帳逐位吻合；seed 齊備）。
  **CONDITIONAL 的原因全在 claim 強度層，已於本次收件修正**：(a) 不再宣稱推翻 `K1265`（SPY
  VIX-managed，本實驗未測）；(b) 「完全複製 R3」→「方向一致」（因子宇宙不同，5/6 是計數巧合）；
  (c) 補 `N107` 為院內先驗（MDD 機械性早已知）並重新定位增量；(d) 補 alpha 水準非 scale-invariant
  的註記；(e) 回溯範圍由「R3 + K1265 兩條」擴為 class sweep。
- **Primary-path Codex re-verify（2026-07-13）= PASS。** Primary review 先判原版 **FAIL**：
  `MDD ÷ vol` 並非不變量、缺 exposure-matched/circular-shift gate，且 MDD 漏掉初始財富 1.0；另有 MOM
  過強語氣、ACF 定位、multifactor raw-mean DM 命名與 artifact provenance 問題。全部修正後重新下載既定
  French/AQR 來源並完整重跑；兩個 fresh-context final audit 再核對 224 summary rows、56 OOS inference cells、
  65 HAC cells、六因子 × 316 phase shifts、script/artifact/source hashes。最終無 HIGH/MEDIUM blocker，
  primary factor gate 維持 `1/6、0、0、1`，drawdown proper gate = Holm **0/6**。
- **回溯更正待辦（class sweep，非只兩條）**：raw-MDD-improvement claim class 全量掃描 ——
  至少含 `R3` / `K1265` / `N80` / `N84` / `N106` / `N107` / `N118` / `N136` / `N168` / `N172` /
  `K40` / `Q16` 及相關 meta-analysis entries；其中 reader-facing 的須一併更正。已 queue。
