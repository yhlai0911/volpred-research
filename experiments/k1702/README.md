# K1702：波動率管理套用到「整個因子動物園」的 OOS 崩潰再驗證

**Verdict: NULL。** 六個因子在 OOS + 淨成本後無一通過多重檢定；等權動物園組合 gross 只有 +0.036 Sharpe
（不顯著），10bp 即翻負，50bp 時 Sharpe 變成 **−0.177**。

**外加一個推翻既有結論的發現**：院內知識庫宣稱的「vol-managing 讓 drawdown 改善（5/6 因子）」
在 scale-invariant 檢驗下**崩潰到 1/6** —— 那個「改善」主要是**曝險變低的機械結果，不是避險技巧**。

## 研究問題

Moreira and Muir (2017, JF) 顯示對**市場因子**做 inverse-variance scaling 能提升 Sharpe 與 spanning alpha。
本實驗誠實檢驗：把同一套 vol-scaling 套到**整個因子動物園**（SMB / HML / RMW / CMA / MOM / QMJ），
**樣本外、且計入交易成本後，還存活嗎？**

先驗立場：Cederburg et al. (2020) 指出 OOS 失效；Barroso and Detzel (2021) 指出成本後不存活。
**本實驗預期 NULL，null 如實報告即為成功** —— 不為了「有結論」去挖 p 值。

## 與既有院內證據的關係

| 既有 | 內容 | K1702 |
|---|---|---|
| `R3`（2026-03-17，knowledge.json） | Factor VT OOS null；"MDD improvement robust (5/6 factors) but Sharpe unchanged" | 該 entry **無 `experiment_id` / 無 reviewer / 無 verdict — 不可復現的 orphan claim**。K1702 **確認**其 OOS null 方向，但**推翻**其 MDD claim（見下） |
| `K1265` | VIX-managed NULL；「MM 主要壓 MDD 而非提 Sharpe」 | 同上：MDD 部分是 scale artifact |
| `K1574` | factor **ETF** implementation shortfall（ex-post audit） | K1702 用官方 long-short paper factors，問 timing 而非 implementation |
| `research_factor_timing_regime` | ETF factor timing 不打敗 EW basket | K1702 是 vol-scaling（非 regime timing）+ 淨成本層 |

**K1702 的增量**：(1) **淨成本層**（R3 沒有）；(2) **QMJ**（R3 沒有）；(3) **固定校準常數的真 OOS**；
(4) **正式 BH-FDR**；(5) **pipeline 證偽測試**；(6) **MM 效果的樣本期分解**；
(7) **MDD claim 的 scale-invariant 反駁**。

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

**MM 的市場因子效果幾乎全部來自 1963 年之前**（大蕭條與二戰的極端波動期）。1963 之後連市場因子本身
都已經沒有統計上站得住的 vol-managing 收益。動物園在 2000 年後全面失效，是這個趨勢的延續。

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
- **spanning regression alpha**（β 吸收曝險落差，α 正是 MM 自己的 headline 統計量）

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
- **校準期**：1963-07 … 1999-12（437 個月）
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
**先量 acf 再決定，並報 lag sensitivity**（全存於 results JSON 的 `residual_acf` / `hac_lag_sensitivity`）：

| cell | n | primary lag | residual acf(1), acf(2) | alpha t @ lag0（**無 HAC**） | alpha t @ primary lag |
|---|---|---|---|---|---|
| MM 複製（1926-2015） | 1073 | 11 | +0.101, −0.005 | **3.02 → 會誤過 Harvey t>3** | **2.70 → 不過** |
| CMA（OOS primary） | 316 | 7 | +0.095, −0.028 | −2.52 | −2.36 |
| MOM（OOS primary） | 316 | 7 | −0.030, **−0.149** | 2.25 | **2.37 → |t| 反而變大** |

這兩格正好演示規則說的「**遺漏 HAC 是雙向誤設**」：CMA 的正 acf 讓無 HAC **高估** |t|；
MOM 的負 acf 讓無 HAC **低估** |t|。所有結論對 lag 選擇 robust。

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
  與 Barroso and Santa-Clara (2015) 的 momentum-crash 保護一致，**不是雜訊**。
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

### 5.4 **推翻既有 claim：「MDD 改善」是 scale artifact**

院內 `R3` 宣稱「MDD improvement robust (5/6 factors)」，`K1265` 宣稱「MM 主要壓 MDD 而非提 Sharpe」。
本實驗**先確認、再推翻**：

| 檢驗方式 | 動物園 6 因子中改善的個數 |
|---|---|
| **raw max drawdown** | **5/6** ← 完全複製 R3 / K1265 的 claim |
| **MDD ÷ 實現波動**（scale-invariant） | **1/6** ← 崩潰 |

| 因子 | raw MDD（unmgd → mgd） | **每單位波動的 MDD** | 年化波動（unmgd → mgd） |
|---|---|---|---|
| SMB | −0.361 → −0.304 ✅ | −3.37 → **−6.83** ❌ | 10.7% → 4.4% |
| HML | −0.560 → −0.435 ✅ | −4.65 → **−7.85** ❌ | 12.0% → 5.5% |
| RMW | −0.220 → −0.130 ✅ | −2.21 → **−5.59** ❌ | 9.9% → 2.3% |
| CMA | −0.269 → −0.321 ❌ | −3.44 → **−7.53** ❌ | 7.8% → 4.3% |
| **MOM** | −0.562 → −0.092 ✅ | −3.23 → **−2.12** ✅ | 17.4% → 4.4% |
| QMJ | −0.306 → −0.146 ✅ | −2.96 → **−5.39** ❌ | 10.3% → 2.7% |

**raw MDD 不是 scale-invariant。** managed 組合的波動只有 benchmark 的 1/2 到 1/4，
drawdown 當然比較淺 —— 那叫**少冒險**，不叫**會擇時**。除以實現波動之後，
**單位風險的 drawdown 反而普遍更深**（SMB −3.37 → −6.83）。

**所以「vol-managing 至少能壓低回撤」這個安慰獎，在因子層是站不住的**（MOM 除外）。
任何人只要把曝險等比例降到 1/4，都能得到同樣的 raw MDD 改善，不需要 vol-managing。

### 事前成功標準 vs 實際

事前門檻（六因子動物園）：≥4/6 Sharpe 改善、≥2 個 bootstrap CI 排除 0 且 FDR<0.05、
≥2 個 spanning alpha 通過 Harvey 且 FDR<0.05、≥2 個在兩子期都為正。
**實際：1/6、0、0、1 —— 四項全部不通過。**

---

## 六、結論（強度嚴格不超過證據）

1. **NULL。** 把 MM 的 vol-scaling 套到因子動物園，**2000 年後樣本外、計入成本後全面不存活**。
   無一因子的 spanning alpha 通過 Harvey；BH-FDR 後無一顯著改善；**CMA 反而顯著變差**。
2. **成本是主角不是配角。** 動物園組合 gross 的改善本就微弱（+0.036，不顯著），**10bp 即翻負**。
   分散化後組合波動僅 5.85%，~0.64%/yr 的成本 drag 就吃掉大半個 Sharpe 單位。
3. **MM 的原始效果是 pre-1963 現象。** 同一 pipeline 在 1926-1963 重現 alpha 7.7%/yr，
   到 1963-1999 只剩 2.0%/yr（t=1.07）。這讓動物園的 null 顯得理所當然。
4. **「vol-managing 壓低 drawdown」在因子層是 scale artifact**（5/6 → 1/6）。此結論**推翻**
   `R3` 與 `K1265` 的既有 claim，需回溯更正。
5. **MOM 是唯一方向為正的因子**（與 momentum-crash 文獻一致），**但多重檢定後不顯著（BH q=0.055，邊緣），
   本實驗不宣稱它存活。**
6. **方法論教訓（可推廣）**：比較兩個**曝險水準不同**的策略時，**不可**用 raw mean return 的 DM 檢定，
   也**不可**用 raw max drawdown —— 兩者都不是 scale-invariant，會系統性地朝「低曝險組合較差／較安全」
   的方向誤導。必須用 Sharpe / spanning alpha / 單位波動的 drawdown。

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
- AQR 更新時重建 QMJ 完整歷史，此處無歷史 vintage 可用。
- 與 AQR 日曆做 inner join 會裁掉部分 French 交易日，故 Mkt-RF 的 RV 不是純 French 複製
  （MM 證偽測試那條路徑用純 FF3，不受此影響）。
- 固定 2000 年切點是**一種** real-time 設計，不能消除全部 specification uncertainty。
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
- **Primary-path Codex review 仍待主線程執行**（`.claude/rules/experiments.md`：subagent fallback PASS
  ≠ primary-path Codex PASS）。**在 Codex review 通過前，不得寫入 `knowledge.json`。**
- 若 Codex review 通過，主線程需一併處理：**回溯更正 `R3` 與 `K1265` 的 MDD claim**（研究誠實原則：
  推翻舊結論必回溯更正）。
</content>
