# Paper 3 A 擴展 — meta synthesis 裁決

**Task**: `Paper3_expansion_synthesis_decision_meta`（P2，建單 2026-05-28，本次執行 2026-07-19）
**性質**：純 meta 分析，不重跑任何模型。所有數字可追溯到 E1/E2 兩份既存 results JSON。
**產出**：`paper3_synthesis.py` → `paper3_synthesis_results.json`

## 觸發條件與實際覆蓋（先講缺口）

原任務要求 `E1+E2+E3 全部 succeeded` 才啟動。實際狀態：

| Arm | 狀態 | pairs | 產物 |
|---|---|---|---|
| E1 個股 | succeeded | 12（原規劃 15） | 有 |
| E2 跨股市 | succeeded | 10 | 有 |
| **E3 商品** | **failed** | **0**（原規劃 8） | **磁碟上無任何產物** |

**實際 pooled N = 22 pairs，非原規劃的 33-43；涵蓋 1 個資產類別，非 3 個。**
E3 從未產生結果，因此本裁決**不能**、也未對「跨資產類別」下任何結論。這是本次裁決的硬邊界。

## 途中發現的源頭缺陷（materially 影響原本的讀法）

E1 與 E2 用**同一個欄位名 `significant_harvey`、兩把不同的尺**：

- `paper3_E1.py:717` — `significant_harvey = abs(t) > 3.0`，硬編門檻，**完全未套 HLN 修正**
- `paper3_E2.py:784-791` — `t = t_raw × hln_factor`，再比 `student_t.ppf(0.975, df)` ≈ **1.961**

後果：「E1 有 0 個顯著、E2 有 2 個顯著」這種並列讀法是無效的。若把 E2 的 1.96 標準套到 E1，
E1 會冒出 copula 方向的命中（NVDA-AMD, t=+1.974）以及數個 DCC 方向的命中。

本 synthesis 因此**丟棄兩邊存好的 flag**，一律從 `(t, n_oos)` 用統一規則重算 p，再做 BH-FDR。
HLN 缺漏本身無害：n_oos > 1500 時 factor > 0.9997，E1 最大 |t|（GOOGL-META/Clayton, 2.8880）
修正後為 2.8875，任何門檻下都不改判。

符號慣例已獨立驗證：`loss = log(h) + r²/h`（標準 QLIKE，越低越好），
`mean_loss_diff = loss(DCC) − loss(copula)`，逐位吻合 `mean_qlike` 欄位差 →
**t > 0 表示 copula 較優**。結論方向無翻轉風險。

## D1 — λ_L threshold（推測 0.1-0.2 邊界）是否顯著？

**裁決：NO——但正確的說法不是「沒有關係」，而是「唯一顯著的關係跑反了」。**

預先登錄的 H3（E1 README:12）預測 **負相關**：低 λ_L → copula 優勢。實際（regressor 與各自
copula 配對，即 E1/E2 自己報的估計量）：

| Spearman(λ_L, DM t) | rho | p | n |
|---|---|---|---|
| E1 / Student-t | +0.049 | 0.880 | 12 |
| E1 / Clayton | −0.007 | 0.983 | 12 |
| E2 / Student-t | +0.406 | 0.244 | 10 |
| **E2 / Clayton** | **+0.903** | **0.00034** | 10 |
| Pooled / Student-t | −0.159 | 0.481 | 22 |
| Pooled / Clayton | +0.207 | 0.355 | 22 |

E1 兩個口徑都是零。**E2/Clayton 是兩份來源資料中唯一達顯著的 λ_L 關係，rho = +0.903，
符號與 H3 相反**——在 E2 內，tail dependence 越**高**，copula 優勢越大。

**不可以寫「pooled rho ≈ 0，所以 λ_L 無關」。** 兩臂效應反號
（E1 −0.007 vs E2 +0.903）且 λ_L 支撐幾乎不重疊（E1 0.009–0.552；E2 0.00004–0.142，
E2 的上限甚至低於 E1 的中位數）。Fisher-z 異質性檢定 **Cochran Q = 8.805, df=1, p = 0.0030**
—— 異質性顯著，naive 22-pair pooling 不是正當的主估計量。pooled rho≈0 是把兩個不相容的
study-level 效應平均掉的產物，不是證據。

**對 Paper 3 A 而言，正確的陳述比「無關」更不利**：不是找不到關係，而是唯一找到的顯著關係
與預先登錄的機制方向相反，且在另一臂不複製。

把 0.1-0.2 邊界當成真正的切分來檢定，三個切點全不顯著——**但這三個檢定本身是廢的**：

| 切點 | n_low / n_high | mean t (low) | mean t (high) | MWU p | high 組組成 |
|---|---|---|---|---|---|
| 0.10 | 14 / 8 | +0.368 | −0.192 | 0.525 | E1×7 + E2×1 |
| 0.15 | 16 / 6 | +0.357 | −0.347 | 0.367 | **E1 同業 6 個，完全等同** |
| 0.20 | 17 / 5 | +0.452 | −0.812 | 0.101 | E1 同業 5 個 |

thr=0.15 時「high λ_L」組**恰好就是** E1 那 6 個同業 pair（E2 掛零）。這個切分是
study／sector 的啞變數換了個名字，不是 λ_L 的檢定。**結論應為「這批資料無法裁決 threshold」，
而非「threshold 已被切分檢定推翻」。**

## D1e — 第二檢定族：FZ0 尾部損失（88 檢定）

copula 的理論賣點是尾部風險，所以這一族才是它最該贏的地方。結果：

- **raw p<0.05 且 copula 方向：0 / 88**
- DCC 方向：2（AAPL-MSFT 兩個 copula @ α=2.5%）
- BH-FDR 5% 後：**兩個方向都 0 個存活**
- Spearman(λ_L, FZ t) = −0.141 (p=0.191)

唯一的 QLIKE 存活者 TW0050-N225 在 FZ 上的 t 只有 +0.16 / +0.73 ——**它的優勢延伸不到尾部損失**。
這一族是本裁決最強的支持證據。

## D1f — 第三維度：VaR/ES 校準（Trinity）——copula 確實贏的地方

必須誠實報告，否則會把負面結論講過頭：

| α | DCC | Copula-t | Copula-Clayton |
|---|---|---|---|
| **2.5%** | **10/22** | **19/22** | 18/22 |
| 1.0% | 19/22 | 18/22 | 19/22 |

α=2.5% 時 copula 大幅勝出；**但 α=1% 時順序反轉**（E1 單獨看更明顯：Copula-t 8/12 vs DCC 11/12）。
所以校準優勢是真的，但**不跨尾部深度一致**——是 2.5% 的現象，進不到更深的尾部。

這是 **校準** 主張，不是 λ_L threshold 主張，救不了 Paper 3 A 的主論點；但它說明
「copula 一無是處」也是錯的讀法。

## D1c — 多重檢定後還剩什麼

22 pairs × 2 copula = **44 個 DM 檢定**。統一重算 p 後：

- 未修正 p<0.05：copula 方向 **3** 個（NVDA-AMD/t、TW0050-HSI/t、TW0050-N225/t）；
  **DCC 方向 6 個**（GOOGL-META/Clayton、XOM-CVX 兩者、AAPL-XOM 兩者、MSFT-JPM/t）
- **BH-FDR 5% 後，copula 方向只剩 1 個：TW0050-N225 / Student-t（t=3.923, p_adj=0.0040）**
- Bonferroni 5%（α=0.00114）後：同樣只剩該 1 個

**反向證據多於正向證據**（6 vs 3）。存活者集中度檢查：唯一存活的 pair 是單一 pair，
且正是 K1416 已標 `CONDITIONAL_PASS` 的那一個（其 5/5 OOS robustness 是重疊樣本的
sensitivity grid，非獨立重複，K1416 自己已載明此 caveat）。

## D2 — same-sector NULL vs cross-sector PASS 是否 robust？

**裁決：NO。E1 的預先登錄型態直接失敗。**

H2 宣稱 cross-sector pairs 會達到 Harvey |t| > 3.0。實際：

- same-sector 平均 t = **−0.491**；cross-sector 平均 t = **−0.699**
- Mann-Whitney p = **0.818** — 兩組無區別
- cross-sector **最大的 copula-favoured t 只有 +0.509**，離 H2 要求的 3.0 極遠；**0/6** 達標
- cross-sector 絕對值最大者是 **−2.639**（AAPL-XOM，DCC 方向）——報絕對值會遮蔽方向，
  故此處報帶號值：H2 是 a fortiori 失敗
- 兩組平均都是**負的**，即兩組平均而言 DCC 都較優

原本以為的 sector 效應，在 E2 換成了 region 效應，而且只有一格會動：

| E2 region | 平均 DM t |
|---|---|
| developed cross-region | −0.054 |
| developed vs emerging Asia | −0.009 |
| **asia intraregional** | **+2.532** |

唯一的訊號既不來自 λ_L，也不來自 sector，而是**亞洲區域內、且由 TW0050 相關 pair 帶動**。

## D3 — Section 4 rewrite scope

**裁決：不要以現行主論點動筆。λ_L threshold 版本的 Paper 3 A 不成立。**

四點理由，依強度排序：
1. **FZ 尾部損失 0/88 copula-favoured**（D1e）——copula 最該贏的維度完全沒有訊號，
   且唯一的 QLIKE 存活者在此僅 t=+0.16/+0.73
2. 多重檢定後 QLIKE 只剩 1/44，且反向證據 6 個多於正向 3 個（D1c）
3. 唯一顯著的 scaling 關係（E2/Clayton +0.903）**符號與預先登錄的 H3 相反**，且不在 E1 複製；
   兩臂異質性顯著（Q=8.805, p=0.0030），無法用 pooling 掩蓋（D1）
4. 預先登錄的 sector 型態直接失敗，p=0.82，cross-sector 最大 copula-favoured t 僅 +0.509（D2）

**不成立的理由不包括** threshold 切分檢定——那三個檢定與 study/sector 完全共線，無鑑別力（D1b）。

且這是**第三次獨立確認**，不是新發現。`docs/research_program_archive_2026Q2.md` §7
（2026-04-13，K1100 系列 6 實驗 + K1115）已判定 copula-GARCH 不可推廣，其中
K1100b 的 SPY-QQQ λ_L=0.589 也是 NULL。E1/E2 這 22 pairs 是在一個獨立樣本上
再次撞到同一面牆。λ_L threshold reframe 本質上是嘗試搶救一個已被否決的論點。

存活下來的唯一實證，指向 §7 當初列的**選項 B（TAIFEX / 亞洲 microstructure 特有現象）**，
而非選項 A 想要的通用 methodology：唯一過 BH-FDR 的是 TW0050-N225，
唯一有訊號的 region 是 asia intraregional，而 §7 原本的結論正是
「Lai 2024 PRS copula edge 是 TAIFEX 市場 microstructure 特有現象」。

**建議（待老闆拍板，不自行推進）**：
- **不採** A 的現行 λ_L threshold 框架動筆 Section 4
- 若要保 Paper 3，往 **B（Taiwan/Asia microstructure 範圍限定）** 收，正向主張只能建立在
  TW0050 相關 pair 上，並須誠實載明 22 pairs 中只有 1 個存活、6 個反向
- 或往**負面結果論文**收（A 的誠實版）：主張是「tail dependence 不能預測 copula 在
  portfolio-variance 或尾部損失上的優勢」，22 pairs × (44 QLIKE + 88 FZ) 檢定 + BH-FDR
  是足夠乾淨的證據，但**不能宣稱跨資產類別**（E3 從未跑），且**必須同時報 Trinity α=2.5%
  的 copula 校準優勢**，否則是選擇性報告
- E3 商品臂：要嘛正式重跑補上第三個資產類別，要嘛正式放棄並在任何論文中載明覆蓋範圍僅
  equity。現狀不可接受：E3 於 **2026-05-29 失敗**，`next_tasks.json` 內**無失敗原因記錄**、
  磁碟無 partial 產物、**7 週從未重試**，而下游的 synthesis 任務就這樣一直掛著等一個
  永遠不會到的觸發條件。

## E3 商品臂裁決（2026-07-21，assign_f3419501 結案）

**決定：(a) 正式重跑，不放棄。** 落檔於此，不再無聲擱置。

理由（不是「補滿三個資產類別比較好看」）：本 synthesis 最強的發現是**唯一顯著的 scaling
關係符號與預先登錄的 H3 相反，且不在 E1 複製，兩臂異質性顯著（Q=8.805, p=0.0030）**。
在只有兩個 equity 臂的情況下，這個反號無法區分兩種完全不同的解釋 ——「H3 本身是錯的」
還是「E2 那個 TW/跨市場臂有 arm-specific 結構」。第三個**非 equity** 資產類別是目前唯一
能把這兩種解釋分開的證據；它在任一方向上都有診斷價值（複製反號 → 是真發現；不複製 →
坐實 arm-specific）。放棄 (b) 等於永久停在無法裁決的狀態。

可行性也支持重跑：E3 於 2026-05-29 失敗但**無失敗原因記錄、無 partial 產物**，
「7 週沒人重試」不是「做不到」的證據；資料（Gold/Oil/Copper/Wheat）走既有 yfinance 路徑，
管線可沿用 E2（跨市場臂）的腳本骨架。

**執行約束（child task 的硬合約）**：
1. 走 `scripts/compute_queue.py`，**禁止塞進 hourly fire**（heavy compute）。
2. **必須沿用 E2 判準**（HLN 修正 + `t.ppf(0.975, df)`），不得重蹈 E1 硬編 `abs(t)>3.0`。
   三臂共用同一把尺是本次裁決的前提，否則跨臂計數再次不可並列。
3. 產出前跑 `scripts/check_experiment_artifacts.py`；knowledge 條目只能主線程寫。
4. E3 落地前，任何論文**仍不得宣稱跨資產類別** —— 上面第 18 行的硬邊界在 E3 成功前不解除。

### 附帶完成：E1/E2 判準不一致的量化

`rescore_e1_unified_criterion.py` 把 E1 已存的 raw t 與 n 用 E2 的判準重評分
（純算術，不需重跑；archived `paper3_E1.py` / results.json 保持不動以維持可重現性）。

| 口徑 | 108 個 DM 檢定中顯著數 |
|---|---|
| E1 原判準 `abs(t) > 3.0`，無 HLN | 9 |
| 統一判準 `abs(t×hln) > t.ppf(0.975, df)` | 23 |
| 翻轉 | 14，**全部由不顯著→顯著**，無反向 |

⚠️ **這組 23 是逐對、未做多重檢定修正的口徑**，只用來量化「換一把尺差多少」；
本 README 主結論走的是統一 p + BH-FDR，兩組數字**不可並列引用**。
上面第 31-32 行「HLN 缺漏本身無害」仍然成立 —— 造成 14 筆翻轉的是**硬編 3.0 這個門檻**，
不是 HLN 因子（n_oos > 1500 時 factor > 0.9997）。

## Honesty notes

- 本裁決未重跑任何模型；若 E1/E2 的 OOS 管線本身有 lookahead，本 meta 不會發現。
  兩臂皆宣稱沿用 K1100b 的 rolling refit 嚴格 t-1 資訊集。
- BH-FDR 假設檢定近似獨立；實際 pairs 共用底層資產（尤以 TW0050、SPY 為甚），
  此違反使 FDR 偏**寬鬆**，即真實存活數只會更少、不會更多。
- `t_best = max(t_student_t, t_clayton)` 是選擇後的最大值，僅用於描述切分表，
  未用於任何推論；推論一律走 44 個檢定的 BH-FDR。
- E1 規劃 15 pairs 實跑 12，差額原因未在 E1 產物中載明。
- E1 的 p 值原存為常態近似（`2*norm.cdf(-|t|)`），本 synthesis 統一改用 t 分配（df=n−1）；
  差異 ≤1.2e-4，不改任何判定。E2 存的 p 與本重算吻合至 3e-16。
- E1 為 raw t、E2 為 HLN 修正後 t，本 pool 混用兩者。失真 ≤0.02%、不翻任何結論，此處揭露。
- **本裁決已經一輪對抗性複核**（獨立 agent，指令為「駁倒」而非背書）：裁決
  `CONDITIONAL_PASS`、**BLOCKERS 無**。複核獨立重現了 D1c（3 raw copula-favoured、
  6 raw DCC-favoured、1 個 BH 存活、1 個 Bonferroni 存活）並確認符號慣例、BH-FDR 實作、
  p 值重算、pair join、sector 預先登錄清單皆正確。複核提出的 10 項措辭收斂已全數反映在
  本檔與 results JSON（含 regressor 配對修正、異質性檢定、threshold 共線揭露、
  Trinity 補報、帶號極值）。複核漏引的一點由本方補上：Trinity 優勢在 α=1% 反轉。
