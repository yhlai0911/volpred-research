# P0-1 Errata Map（K880 SPY 漂移逐行對照）

產出時間：2026-07-14 11:46:49（台灣時間）
考古 agent：唯讀，只寫本檔，未動 main.tex / JSON / reproduce.py。
canonical 稿：`paper/prg-periodic-garch/main.tex`（646 行，單體 .tex）。

---

## 0. 核心結論（load-bearing，rewrite 前必讀）

**根因（single source）**：K880 SPY 於 2026-06-13 用 live yfinance（`auto_adjust=True`，見 §D）重跑後，`experiments/k880/k880_results.json`（現行檔，mtime Jun 14）全列漂移。main.tex 目前引的 SPY 數字全部來自**重跑前的舊 K880**，逐一 stale。既有稽核檔 `reproducibility_audit/main_tex_numbers.csv` 是**重跑前**產物，把 6.00 標成 `MATCH_K880`（舊值 6.0039），該稽核檔本身已過時，不可當現況依據。

**三個 vintage 一定要分清（最常踩雷）**：
| 名稱 | 檔 | 定位 | SPY PRG_Ext QLIKE | SPY DM PRG-vs-GJR |
|---|---|---|---|---|
| 舊 K880（重跑前） | 已被覆蓋，僅存於 `reproducibility_audit/main_tex_numbers.csv` 記載 | main.tex 現值來源 | 0.748 | 6.0039 → 稿寫 6.00 |
| **現行 K880（canonical）** | `experiments/k880/k880_results.json`（Jun 14 rerun） | **rewrite 目標值來源（Open 慣例）** | **0.7626** | **5.064** |
| K880v2（Close 消融） | `experiments/k880v2/k880v2_results.json`（Apr 18，**未重跑**） | Table 3 Close row + 附錄 Close 欄 + ES 表來源 | 0.8636（=Close 0.864） | −0.57 |

**三個 narrative 級變動（不是單純換數字，rewrite 要做敘事決策）**：

1. **SPY best model：PRG Extended → PRG Basic**。現行 K880 `layer1`：PRG_Basic QLIKE **0.7546** < PRG_Extended **0.7626**（差距 DM t=−1.05，**不顯著**）。main.tex L183 / Table 2 note L206 宣稱「PRG Extended 在除 GLD 外每個市場 QLIKE 最低」對 SPY 已不成立。→ 要嘛把 SPY 併入「GLD 式」PRG Basic 最佳，要嘛保留 PRG Ext headline 並註明 Basic 以不顯著幅度勝出。

2. **SPY MCS：All → 只有 PRG Basic + Extended survive**。現行 K880 `layer2_mcs.surviving = ["PRG_Basic","PRG_Extended"]`；GJR/HAR/Separate 全被 10% MCS 淘汰（p≈0.0004、HAR p=0.0）。這直接推翻 main.tex **L212**「For the U.S. ETFs, all models survive the MCS, reflecting the noisier daily OHLC proxies」——對 SPY 反而變成與 TAIFEX 同級的「PRG-only」強結果。L197 Table 2 SPY MCS 欄 `All` → `PRG Basic+Ext`。

3. **資料 vintage 不一致（重構品質風險）**：若 rewrite 只把 Open/主表更新到現行 K880（Jun 14），但 Close row / 附錄 Close 欄 / ES 表仍留 K880v2（Apr 18 未重跑），全稿 SPY 會**混用兩個 yfinance vintage**。乾淨解 = 先建 snapshot pin（§D）再把 k880 + k880v2 + k880b 同一 snapshot 重跑，讓 Open/Close 同源。

---

## A. main.tex 逐行對照表

判讀慣例：DM 在稿中以「benchmark loss − PRG loss，正值利 PRG」呈現；JSON 的 `PRG_Extended_vs_Separate`、`HAR_vs_PRG_Extended` 等 t_stat 帶方向號，取絕對值填表。所有 canonical 值皆已 jq 實跑驗證。

### A-1. 主結果（Abstract + Table 2 `tab:main_results` + Table 3 `tab:ablation`）— 全 stale，來源＝現行 K880

| main.tex 行 | 語境 | 現值(stale) | canonical | source 檔 | jq path |
|---|---|---|---|---|---|
| 41 | Abstract「6.00 (SPY)」DM 列 | 6.00 | **5.064** | k880_results.json | `.cross_market_comparison.spy_k880.DM_t_PRGExt_vs_GJR`（=`.layer5_dm_tests.GJR_vs_PRG_Extended.t_stat`）|
| 41 | Abstract「reduces … 6.00 to −0.57」 | 6.00 / −0.57 | **5.064** / −0.57（−0.57 不 stale，見 note）| k880 / k880v2 | 同上 / `k880v2::.layer5_dm_tests.GJR_vs_PRG_Extended.t_stat` = −0.5687 |
| 197 | Table 2 SPY「Best QLIKE」 | 0.748 | **0.7546**(PRG Basic 為最低) / 0.7626(PRG Ext) | k880_results.json | `.layer1_loss_functions.PRG_Basic.QLIKE` / `.PRG_Extended.QLIKE` |
| 197 | Table 2 SPY「PRG vs GJR」 | 6.00 | **5.064** | k880_results.json | `.layer5_dm_tests.GJR_vs_PRG_Extended.t_stat` |
| 197 | Table 2 SPY「PRG vs Sep」 | 6.69 | **5.689** | k880_results.json | `.layer5_dm_tests.PRG_Extended_vs_Separate.t_stat` = −5.6887（絕對值）|
| 197 | Table 2 SPY「PRG vs HAR」 | 7.31 | **7.141** | k880_results.json | `.layer5_dm_tests.HAR_vs_PRG_Extended.t_stat` |
| 197 | Table 2 SPY「Spearman ρ」 | 0.568 | **0.5538** | k880_results.json | `.layer3_spearman.PRG_Extended.rho` |
| 197 | Table 2 SPY「MCS」 | All | **PRG Basic+Ext** | k880_results.json | `.layer2_mcs.surviving` = ["PRG_Basic","PRG_Extended"] |
| 206 | Table 2 note「SPY … becomes −0.57」 | −0.57 | −0.57（**不 stale**，k880v2）| k880v2_results.json | `.layer5_dm_tests.GJR_vs_PRG_Extended.t_stat` = −0.5687 |
| 210 | 內文「DM … 6.69 (SPY)」(PRG vs Sep 範圍上界) | 6.69 | **5.689** | k880_results.json | `.layer5_dm_tests.PRG_Extended_vs_Separate.t_stat` |
| 230 | Table 3 Open row：QLIKE / DM / ρ / MZ R² | 0.748 / 6.00 / 0.568 / 0.464 | **0.7626 / 5.064 / 0.5538 / 0.4906** | k880_results.json | `.layer1_loss_functions.PRG_Extended.QLIKE` / `.layer5_dm_tests.GJR_vs_PRG_Extended.t_stat` / `.layer3_spearman.PRG_Extended.rho` / `.layer1_loss_functions.PRG_Extended.MZ_R2` |
| 231 | Table 3 Close row：QLIKE / DM / ρ / MZ R² | 0.864 / −0.57 / 0.474 / 0.264 | **匹配 k880v2，全部不 stale** | k880v2_results.json | `.layer1…PRG_Extended.QLIKE`=0.8636 / `.layer5…GJR_vs_PRG_Extended.t_stat`=−0.5687 / `.layer3…PRG_Extended.rho`=0.4742 / `.layer1…PRG_Extended.MZ_R2`=0.2640 |
| 241 | 內文「collapses from 6.00 to −0.57」 | 6.00 → −0.57 | **5.064** → −0.57 | k880 / k880v2 | 同 L230 Open / L231 Close |
| 243 | 「Separate … 6.69 (SPY)」 | 6.69 | **5.689** | k880_results.json | `.layer5_dm_tests.PRG_Extended_vs_Separate.t_stat` |
| 315 | §4.5 GJR-X 內文交叉引「Table 2 (t = 6.00)」 | 6.00 | **5.064** | k880_results.json | 同 L197 |
| 346 | 「EEM … 6.63 … QQQ … 4.26」（非 SPY，供 rewrite 對照，不改）| — | — | k881 | 非本 errata 範圍 |
| 362 | Conclusion「PRG-vs-Separate … 6.69」 | 6.69 | **5.689** | k880_results.json | 同上 |

備註 L235（Table 3 note「DM-t gap of 6.57」）：現值 6.57 = 6.00 −(−0.57)。canonical 若採 Open 5.064、Close −0.57，gap 應改為 **5.63**（5.064 −(−0.5687)）。rewrite 需同步改此衍生數字。

### A-2. VaR / ES（Table 4 `tab:var_es` + 附錄 `app:tab:var_5models` + ES 表）

VaR **Open 欄**來源＝現行 K880 `layer4_var`（多處 stale）；**Close 欄**來源＝K880v2 `layer4_var`（**全部匹配、不 stale**，已逐格驗證）。FZ ES DM 來源＝K880b。Acerbi ES 表來源＝K880v2 `layer4b_es`（**匹配、不 stale**）。

| main.tex 行 | 語境 | 現值(stale) | canonical | source / jq path |
|---|---|---|---|---|
| 247 | 內文「SPY … 0.93% (Kupiec p=0.77)」PRG Ext Open 1% | 0.93% / 0.77 | **1.32% / 0.195** | `k880::.layer4_var.PRG_Extended.VaR_1pct.{violation_rate=0.013165, kupiec_p=0.19522}` |
| 247 | 內文「1.92% for GJR (p<0.001)」GJR 1% | 1.92% / <0.001 | **2.08% / <0.001** | `k880::.layer4_var.GJR.VaR_1pct.{violation_rate=0.020845, kupiec_p=4.86e-5}` |
| 247 | footnote「Close … becomes 1.59% … p=0.0196」 | 1.59% / 0.0196 | **匹配 k880v2，不 stale** | `k880v2::.layer4_var.PRG_Extended.VaR_1pct.{0.015908, 0.019573}` |
| 262 | Table 4 SPY(PRG Ext)：VR / p / Basel / FZ / Rank | 0.93 / 0.77 / Green / 3.75 / 1st | **1.32 / 0.195** / Green(見 B) / 3.75(不 stale) / Rank 見 B | VR·p 同 L247；FZ=`k880b::.fz_dm_tests."1pct".parametric.GJR_vs_PRG_Extended.t_stat`=3.7502 |
| 263 | Table 4 SPY(GJR)：VR / p / Basel | 1.92 / <0.01 / Yellow | **2.08 / <0.001** / Basel 見 B | VR·p 同 L247；Basel zone 方法學不一致見 §B |
| 396 | 附錄 reviewer summary「0.93% … p_K=0.77」 | 0.93% / 0.77 | **1.32% / 0.195** | 同 L247 Open |
| 398 | 附錄「PRG Ext … 1.59%, p_K=0.020」(Close) | 1.59% / 0.020 | **匹配 k880v2，不 stale** | `k880v2::.layer4_var.PRG_Extended.VaR_1pct` |
| 401 | 附錄「PRG Basic (1.65%, p_K=0.011)」(Close) | 1.65% / 0.011 | **匹配 k880v2，不 stale** | `k880v2::.layer4_var.PRG_Basic.VaR_1pct.{0.016456, 0.011255}` |

**附錄 5 模型 VaR 表（`app:tab:var_5models`, L420–424）逐格**——Open 半邊 vs 現行 K880 `layer4_var`；Close 半邊 vs K880v2 `layer4_var`：

| 行 | 模型 | Open 1% 稿(rate/p) | Open 1% canonical | Open 5% 稿 | Open 5% canonical | Close 半邊 |
|---|---|---|---|---|---|---|
| 420 | GJR | 1.92% / 0.0005 | **2.08% / 4.9e-5** ⚠stale | 5.65% / 0.21 | 5.65% / 0.212 ✓ | 2.08%/0.0000·6.03%/0.049 ✓ 匹配 k880v2 |
| 421 | HAR | 6.03% / 0.0 | 6.03% / 0.0 ✓ | 11.19% / 0.0 | 11.19% / 0.0 ✓ | ✓ 匹配 |
| 422 | Separate | 1.87% / 0.0009 | 1.87% / 0.00092 ✓ | 4.83% / 0.73 | **4.77% / 0.653** ⚠stale | 1.92%/0.0005·5.21%/0.68 ✓ 匹配 k880v2 |
| 423 | PRG Basic | 1.32% / 0.20 | **1.26% / 0.281** ⚠stale | 4.77% / 0.65 | **4.39% / 0.221** ⚠stale | 1.65%/0.011·5.27%/0.61 ✓ 匹配 k880v2 |
| 424 | PRG Ext | 0.93% / 0.77 | **1.32% / 0.195** ⚠stale | 4.50% / 0.32 | **4.44% / 0.267** ⚠stale | 1.59%/0.020·5.49%/0.35 ✓ 匹配 k880v2 |

Open jq 通式：`k880::.layer4_var.<MODEL>.VaR_1pct.{violation_rate,kupiec_p}` 與 `.VaR_5pct.{…}`（`<MODEL>` ∈ GJR/HAR/Separate/PRG_Basic/PRG_Extended）。Close 通式：`k880v2::.layer4_var.<MODEL>.…`（PRG_Extended 對應 Close 消融）。

**ES 表（`app:tab:es_k880v2`, L471–472 等 5 列）**：GJR 2.74 / HAR 5.70 / Separate 2.55 / PRG Basic 2.31 / PRG Ext 2.36 —— **全部匹配 K880v2，不 stale**。jq：`k880v2::.layer4b_es.<MODEL>.z2_stat`。

### A-3. 不 stale、確認一致（供 rewrite 放心，勿誤改）

| 行 | 項目 | 稿值 | canonical | source |
|---|---|---|---|---|
| 160 | Table 1 SPY overnight share | 34.5% | 34.47% ✓ | `k880::.session_decomposition` / `.cross_market_comparison.spy_k880.overnight_var_share_pct`=34.466 |
| 308,319,337 | §4.5 GJR-X「n=1,823」「OOS 2019-01-02–2026-04-08」 | — | 見 §B（gjrx 表自有來源 k1260/k1544，非 K880 drift）| — |
| 231/398/401/471… | 所有 Close / ES 半邊 | — | 匹配 K880v2 | 見上 |

---

## B. NOT FOUND / 需 rewrite 決策清單

1. **Table 4 Basel zone（L262 SPY PRG Ext = Green；L263 SPY GJR = Yellow）— 方法學不一致，勿直接抄 JSON**。
   - `k880::.layer4_var.GJR.VaR_1pct.basel` 欄位值 = **"Green"**（且 `basel_violations_250d`=4），與稿的 Yellow 衝突。但該 JSON `basel` 欄用「250 日滾動」尺度；稿 note（L271）宣稱用「exact-binomial traffic-light、以各市場 OOS 全樣本評估」。兩者演算法不同 → **不能把 JSON 的 basel 欄當 canonical**。GJR 全樣本 2.08%（38/1823）在 α=1% 下實質應落 Yellow/Red 區，稿的 Yellow 可能才是對的。**建議 rewrite 用稿的全樣本規則重算 Basel，而非取 JSON basel 欄**。掃過：k880 layer4_var（有 basel 欄但為 250d 尺度）、k880v2 layer4_var（同）。全樣本 exact-binomial 的重算結果**兩檔都無現成欄位**。

2. **Table 4 FZ Rank（L262「1st」）與 best-model 衝突**。FZ DM=3.75 本身不 stale，但「Rank 1st」是在模型集合內的排序；若 SPY best 改判 PRG Basic，PRG Ext 的 FZ rank 是否仍 1st 需 rewrite 核對 k880b 的 per-model FZ 排序（`k880b::.fissler_ziegel_scores`）。本考古未逐一核 rank。

3. **§4.5 GJR-X 表（`tab:gjrx`, L319–337：0.7559 / 0.8544 / 0.8607 / DM 7.72 / −0.53）不在 K880 rerun 範圍**。reproduce.py 標其來源為 **K1260**（`PAPER_CLAIMS["K1260 …"]`），與 K1544（fair-info）數字接近但不同（K1544 SPY PRG QLIKE=0.7581、fair-GJR-X=0.7267，見 §E），是另一支實驗。本考古**未開啟 k1260_results.json 驗證** 7.72 / −0.53 是否仍成立。唯一確定要改的是表內/前文對 Table 2 的交叉引「t = 6.00」（L315）→ 5.064。若 rewrite 要一併重跑 fair-info，需另立 K1260/K1544 vintage 對齊。

4. **Table 3 note「gap of 6.57」(L235) 為衍生值**，非獨立 canonical；隨 Open 更新為 5.064 後應改 5.63（見 §A-1 備註）。

掃過但確認不存在的東西：K880/K880v2/K880b 皆**無**「全樣本 exact-binomial Basel zone」現成欄位；k880/data 下**無** pinned snapshot CSV（見 §D）。

---

## C. reproduce.py 現況與待改 assertion

檔：`paper/prg-periodic-garch/reproduce.py`（18.5KB, mtime Jun 11）。
資料來源：預設**跑 live `.py`（yfinance 即時）**，或 `--skip-live` 時只驗證已存 JSON；`find_result_file` 先找 `paper/prg-periodic-garch/experiments/<name>_results.json`，退回 `experiments/<kid>/`。**未讀任何 pinned snapshot CSV**。

`PAPER_CLAIMS` dict（L54–89）目前 assert 的 SPY / K880 相關 target（全部對舊值）：

| key（行） | 現 assert paper 值 | tol | 現行 K880 canonical | 判定 |
|---|---|---|---|---|
| `SPY PRG_Extended QLIKE`(61) | 0.748 | 0.05 | 0.7626（或 best=0.7546 PRG Basic）| 相對差 1.95% 勉強過；**建議改 0.7626 並考慮改判 best model** |
| `SPY DM_t (PRG vs GJR)`(62) | 6.00 | 0.15 | 5.064 | 相對差 −15.6% **超出 0.15 tol → 會 FAIL；必改 6.00→5.064** |
| `SPY DM_t (PRG vs Separate)`(63) | 6.69 | 0.15 | 5.689 | 相對差 −15% 邊界；**改 6.69→5.689** |
| `SPY DM_t (PRG vs HAR)`(64) | 7.31 | 0.15 | 7.141 | 差 −2.3% 過但值 stale；**改 7.31→7.141** |
| k880v2 ablation block（L331-334）| `paper_ablated_qlike`=0.864 / `paper_ablated_dm_vs_gjr`=−0.57 | 硬編 | 匹配 k880v2 | **不用改**（k880v2 未重跑）|
| `K1260 …`(86-92) | 0.8544/0.8607/0.7559/−0.53/7.72/… | 各 tol | 見 §B-3（另一 vintage）| 本考古未驗證 |

其它市場 target（QQQ/GLD/EEM/0050.TW/TAIFEX，L66-85）不在 SPY errata 範圍，但注意 reproduce.py 的整體策略是「靠 loose tol 容忍 yfinance 漂移」，這正是為何漂移沒被擋下。**根本修法**：改讀 snapshot（§D）後才能把 tol 收緊、把 target 釘死到 canonical。

待改 assertion 清單（P0-1 範圍）：
- L61 `0.748` → `0.7626`（或連同 best-model 敘事一起處理）
- L62 `6.00` → `5.064`（**否則 test FAIL**）
- L63 `6.69` → `5.689`
- L64 `7.31` → `7.141`
- 另建議：新增 SPY Spearman ρ（0.5538）、SPY MCS surviving（["PRG_Basic","PRG_Extended"]）、SPY VaR-1% PRG Ext（1.32%/0.195）、GJR（2.08%）的 assertion，讓 rerun 能機械擋下未來漂移。
- L180-181 的 provenance NOTE（Table 4 VaR 標 0.93%/0.77、1.92%/<0.001 source K880）已 stale，需同步改成 1.32%/0.195、2.08%。

---

## D. snapshot pin 現況

**現況＝無 snapshot pin（待建，且是根因）**。
- `experiments/k880/data/` 只有一個 0-byte `.gitkeep`，**無 CSV**。
- `paper/prg-periodic-garch/` 下**無 `data/` 目錄、無任何 SPY 價格 CSV**（`find … -name "*.csv"` 僅命中 `reproducibility_audit/main_tex_numbers.csv`，那是稽核表不是價格快照）。
- `experiments/k880/k880_prg_spy_validation.py` L236：`yf.download("SPY", start="2000-01-01", end="2026-04-05", auto_adjust=True)` —— **live 抓、`auto_adjust=True`**。yfinance 對 SPY 的除息回溯調整會隨抓取日改變歷史序列，這是 6.00→5.064、QLIKE 0.748→0.7626 漂移的機械根因。
- reproduce.py L58-59 註解已自認「preferred path 是 pin `paper/prg-periodic-garch/data/` snapshot」，但**從未落地**，反而用放寬 tol 掩蓋。

**建議（rewrite/重構）**：
1. 建 `experiments/k880/data/spy_ohlc_snapshot.csv`（或 `paper/prg-periodic-garch/data/`），用 `auto_adjust=False` 凍結一次抓取，記錄抓取日與 yfinance 版本。
2. k880 / k880v2 / k880b **同一 snapshot 重跑**，消除 Open(k880 Jun14) 與 Close(k880v2 Apr18) 的 vintage 落差（§0 第 3 點）。
3. reproduce.py 改讀 snapshot、收緊 tol、target 釘 canonical。
4. K1544 / K1699（§E）data_source 也走 `k880 load_spy_data`，同 snapshot 才能與主表同源（k1699 已有 `data_snapshots` 欄，可核對是否已凍結）。

---

## E. rewrite 用數據 reference（六市場 open-time / close-time DM）

`.markets` 在兩檔皆為 **object**（非 array）；`.markets[]` 迭代其 values，每個 value 帶 `.market` 欄。安全存取式：`.markets[] | select(.market=="<M>") | …`。

### E-1. K1544 open-time DM（PRG_Extended vs Fair-info GJR-X，含當日已實現 overnight）
檔：`experiments/k1544_prg_fair_info_gjr/k1544_prg_fair_info_gjr_results.json`
jq path（每市場）：`.markets[] | select(.market=="<M>") | .dm_fair_gjr_minus_prg.t_stat`
方向：正值利 PRG（fair-GJR loss − PRG loss）。**注意結果反轉**：fair-info GJR-X 在六市場全勝 PRG canonical（DM 全負），僅「PRG open-known 診斷變體」才轉正（另一 path `.diagnostic_prg_open_known_overnight.dm_fair_gjr_minus_prg_open_known.t_stat`）。

| market | K1544 open-time DM (fair−PRG) t | Harvey |
|---|---|---|
| SPY | −2.803 | 未過 |
| QQQ | −2.501 | 未過 |
| GLD | −11.060 | (負向)過 |
| EEM | −9.434 | (負向)過 |
| 0050.TW | −6.567 | (負向)過 |
| TAIFEX | −6.256 | (負向)過 |

（PRG open-known 診斷 DM，`.diagnostic_prg_open_known_overnight.dm_fair_gjr_minus_prg_open_known.t_stat`：SPY 2.115 / QQQ 2.967 / GLD 3.625 / EEM 10.130 / 0050.TW 3.870 / TAIFEX 5.608）

### E-2. K1699 close-time DM（PRG_tminus1_exp vs GJR，Close 慣例六市場替代）
檔：`experiments/k1699/k1699_results.json`
jq path（每市場）：`.markets[] | select(.market=="<M>") | .dm_tests.PRG_tminus1_exp_vs_GJR.t_stat`
方向：JSON orientation「negative t means PRG better」；稿慣例（正利 PRG）需視情況翻號。

| market | K1699 close-time DM (exp vs GJR) t |
|---|---|
| SPY | 0.741 |
| QQQ | 2.282 |
| GLD | −0.436 |
| EEM | −0.541 |
| 0050.TW | −0.318 |
| TAIFEX | −0.492 |

（同檔另有 `.dm_tests.PRG_tminus1_exp_vs_HAR.t_stat`：SPY −6.489 等；`.dm_tests.PRG_tminus1_lag_vs_GJR.t_stat`：SPY 1.252 等，供 rewrite 需要時取用。）

> 提醒：K1699 SPY close-DM=0.741 與 K880v2 的 SPY close DM=−0.57 是**不同 Close 定義**（K1699 用 `PRG_tminus1_exp`，K880v2 用 lookahead-fixed ablation），rewrite 若要跨市場推廣 Close 結論，須言明採哪一支、避免混口徑。

---

## 附：本考古實際跑過的驗證命令（節錄，均唯讀）
- `jq '.cross_market_comparison.spy_k880' experiments/k880/k880_results.json` → DM 5.064
- `jq '.layer1_loss_functions|to_entries|map({m:.key,QLIKE:.value.QLIKE})' experiments/k880/k880_results.json` → PRG_Basic 0.7546 < PRG_Ext 0.7626
- `jq '.layer2_mcs.surviving' experiments/k880/k880_results.json` → ["PRG_Basic","PRG_Extended"]
- `jq '.layer4_var.PRG_Extended.VaR_1pct' experiments/k880/k880_results.json` → 1.32% / p=0.195
- `jq '.layer1_loss_functions.PRG_Extended.QLIKE,.layer5_dm_tests.GJR_vs_PRG_Extended.t_stat' experiments/k880v2/k880v2_results.json` → 0.8636 / −0.5687（Close 匹配稿）
- `jq '.fz_dm_tests."1pct".parametric.GJR_vs_PRG_Extended.t_stat' experiments/k880b/k880b_results.json` → 3.7502
- `jq -r '.markets[]|"\(.market): \(.dm_fair_gjr_minus_prg.t_stat)"' …k1544…` / `…\(.dm_tests.PRG_tminus1_exp_vs_GJR.t_stat)…k1699…`
- `grep -n auto_adjust experiments/k880/k880_prg_spy_validation.py` → L236 `auto_adjust=True`（live）
