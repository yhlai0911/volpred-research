# K1583: Conditional / Sequential MCS meta-evaluation of K1380_v4 SPY 17-spec horse race

> **狀態（2026-08-05 重跑）**：本份結果由**修正後**的 K1380_v4 loss matrix 產生。
> 先前那一版消費了已證實錯誤的 loss matrix，其 knowledge 條目已由 canonical writer 標為
> **SUPERSEDED**。本次重跑依 `k1583_corrected_k1380_matrix_rerun_20260802` 執行。
> **尚未經審查**：舊的 `CONDITIONAL_PASS`（Codex 82/100, 2026-06-30）只對舊 bytes 有效，
> 本份 bytes 沒有任何有效裁決（Codex 訂閱額度用盡至 2026-08-08，見 §Lineage）。

## Motivation

K1380_v4 跑了 17 個 SPY vol forecast spec（GARCH-X / MIDAS A1-A5, A2f/A4f, A3f, A2n/A4n,
B1-B3, C2-C3, B0）。原報告用 pointwise QLIKE 排名，但**沒有 multiple-testing**，無法說
「哪些 spec 顯著優於其他」。

K1583 補上 **Model Confidence Set (MCS)** 的三層分析：
1. **Unconditional MCS** — 全期 16 specs（C1 因 0 valid samples 排除）的 set selection
2. **Conditional MCS** — VIX regime (high≥20 / mid / low<15) + recession (NBER USRECD) 各自
   subsample MCS（Liu-Pelger-Yang 2025 JRSS-B kernel-weighted approach 的粗近似）
3. **Sequential drift** — Rolling 252-day window MCS，stride 21 days，看 top-1 spec 是否隨時間漂移

References:
- Hansen, Lunde, Nason (2011) — original MCS T_R statistic
- Liu, Pelger, Yang (2025) JRSS-B qkag066 — conditional MCS kernel-weighted approach
- Hansen (2005) — Sequential SPA
- arXiv 2505.21278 — Online/sequential MCS

## Method

### Loss inventory
- 來源：`experiments/K1380_v4/k1380_v4_losses_all.npy`（**corrected** matrix，shape `(17, 1900)`）
- Loss proxy：Patton (2011) QLIKE = `r²/σ² - log(r²/σ²) - 1`
- OOS sample：**2019-01-02 → 2026-07-21**（1900 個交易日）
- 日期對齊：位置對齊到 `spy_vix_qqq_eem_fez_2000-2026.csv` 的前 1900 個 OOS 列。
  **本次重跑前已獨立驗證該 CSV 的 OOS 區段沒有重複日期**（1908 列去重後仍 1908），
  所以舊版註解描述的「重複列 → 去重後錯位」風險在現行資料上不成立。

### MCS implementation
- Routine：`src/volpred/stats/mcs.py::model_confidence_set` (HLN T_R variant, stationary
  bootstrap, HAC SE)
- α = 0.10（保留 90% confidence set）
- Bootstrap：B = 1000（static）、B = 500（rolling — 預算限制）
- Seed = 42（重跑兩次數字完全一致）

### Conditioning variables
- VIX：`spy_vix_qqq_eem_fez_2000-2026.csv` `vix_close`（contemporaneous — 描述當日 regime，
  不是預測子）
- Recession：FRED `USRECD` daily，ffill across non-trading days
- VIX thresholds：high ≥ 20、low < 15、mid 15-20

### Cross-asset pooling: DISABLED
依 K1355 禁 asset-day stacked panel 規則，K1258 multi-asset losses 只 inventoried 不 pooled。

### Lookahead policy
- Ex-post meta-analysis on already-realized losses
- Conditioning variables 描述**當日已實現的狀態**，不是未來
- Rolling MCS at origin t 只用**過去 252 天**的 loss differentials → 無 forward leak

## Key Results

### 樣本可用性：修正後的 matrix 砍掉一半以上的可用列

這是新舊之間**最大的單一差異**，先講，因為底下所有數字都受它影響：

| spec | n_obs_valid（1900 中） |
|---|---|
| A1–A5, A2f, A4f, A3f, A2n, A4n, C1, C2, C3, B0 | 1898 |
| **B3** | **1772** |
| **B1** | **1457** |
| **B2** | **1395** |

MCS 需要所有 16 個 eligible spec 在同一天都有值（listwise deletion），因此
**1900 → T=1017（883 列被丟）**。

對照：superseded 版本的每個 spec 都是 `n_obs_valid=1854`（1866 中只丟 12），listwise 後幾乎
不損失。也就是說**舊 matrix 在 B1/B2/B3 沒有有效樣本的日子仍填了值**——這正是它被判定為錯誤
的那一類問題。修正後這些日子誠實地變成 NaN，代價是共同可用樣本從約 1854 降到 1017。

### Unconditional MCS（α=0.10, B=1000）

**16/16 specs 全部保留**，set-level p = **0.221**（T=1017）。

⚠️ p 值是 MCS survivor-set p（停止淘汰時 worst-model 的 bootstrap p），**不是每個 spec 的個別
分數**。全部相同代表演算法在第一輪就無法拒絕，整個 set 共享同一個 stopping p。

（superseded 版本：同樣 16/16 全保留，p = 0.438，T≈1854。）

### Conditional MCS

| Regime | T | MCS size | 被淘汰者 |
|---|---|---|---|
| VIX high (≥20) | 335 | 16 | — |
| VIX mid (15–20) | 520 | 16 | — |
| **VIX low (<15)** | **162** | **15** | **B0（p = 0.012）** |
| NBER recession | 20 | 16（trivial） | 檢定力不足，演算法回傳 trivial set |
| NBER expansion | 997 | 16 | — |

**唯一與「全部不可區分」相左的結果是低波動期的 B0 出局。** 這是新結果——superseded 版本的
三個 VIX regime 全是 16/16。

**但不要把它讀成穩健發現**，三個理由：
1. **T=162 對 M=16 個模型偏小**，MCS 在小樣本下的淘汰行為不穩定
2. **本實驗跑了 6 個 MCS family**（unconditional + 3 個 VIX regime + 2 個 NBER state）
   而**沒有做跨 family 的多重性校正**。p=0.012 在 6 個 family 下 Bonferroni 後是 0.072；
   雖然仍低於本實驗的 α=0.10，但已不是「乾淨的 1% 級證據」
3. B0 是 baseline spec，低波動期它被淘汰的方向合理（低波動時 VIX 外生資訊最有價值），
   但**方向合理不是證據**

### Sequential drift（rolling 252-day, stride 21 days）

- **38 個 rolling window**（superseded 版本有 77 個——差異來自上面的 listwise deletion，
  可用的連續 252 天視窗少了一半）
- **16 次 top-1 winner 切換**：2021-07-01→A5、2023-03-03→A3f、2023-04-03→A5、2023-09-05→A3f、
  2024-05-06→B0、2024-06-05→A3f、2025-04-08→A4f、2025-05-08→A3f、2025-09-09→A4f、
  2025-10-08→A2、2025-11-06→A1、2026-01-08→A2、2026-04-10→A5、2026-05-11→A2、2026-06-09→A5、
  2026-07-20→A2
- 切換頻繁且在少數 spec 之間來回，這**多半是同 p-value 下用 mean QLIKE tie-break 的結果，
  不是真的 regime shift 證據**（見 Limitations 5）

## Verdict

**NULL（主結論），帶一個未經多重性校正的條件例外。**

在無條件、VIX high、VIX mid、NBER expansion 四個口徑下，K1380_v4 的 16 個 GARCH-X / MIDAS 變體
在 QLIKE loss 上**統計不可區分**。唯一的例外是低波動期（VIX<15）B0 被淘汰，而該結果受制於
小樣本與未校正的多重比較，強度不足以支撐「低波動期某些 spec 確實較優」的宣稱。

**這與 superseded 版本的主結論方向一致**（都是 NULL），但**證據基礎不同**：舊版的 NULL 建立在
一個把缺值填成有值的 loss matrix 上，新版建立在誠實標記缺值、共同樣本因此腰斬的矩陣上。
兩者結論相同不代表舊版是對的——它是**用錯的資料得到了碰巧相同的方向**。

**認證狀態：未經審查。** 本份 bytes 沒有有效的 `review_verdict.json`。

### Limitations（誠實揭露）

1. **單資產（SPY only）**：K1258 multi-asset panels inventoried but NOT pooled（K1355 rule）。
   跨市場 conditional 需 per-asset MCS 或 panel-HAC，out of scope。
2. **Subsample MCS = 粗近似**：proper conditional MCS（Liu-Pelger-Yang 2025）用 kernel-weighted
   loss differentials，本實驗未實作。
3. **Recession N 極小**：**T=20**（superseded 版本是 43），MCS 回傳 trivial set，
   **這一格沒有任何推論價值**，只保留在表中以示已檢查。
4. **Sequential drift ≠ formal break test**：rolling MCS top-1 是 visualization aid，
   非 Inoue-Jin-Rossi online SPA。
5. **Tie-breaking**：top-1 用 tied MCS p-value 內的 min mean QLIKE，會偏向 low-mean models；
   換一種 tie-break 會改變整條 timeline。上面 16 次切換要在這個前提下讀。
6. **跨 family 多重性未校正**：6 個 MCS family 各自用 α=0.10，沒有 family-wise 控制。
   VIX-low 的 B0 淘汰是唯一受此影響的結論。
7. **與 superseded 版本無法做逐點數值對比**：舊 loss matrix（`storage/k1380_v4/spy_losses.npy`）
   已不存在於 repo，只能比對結論層級與已記錄的摘要數字。

## Implication

主結論不變：K1380_v4 的 QLIKE 差異在 MCS 統計上**不可區分**，pointwise QLIKE ranking 可能反映
noise 而非真正的模型優越性。未來比較 GARCH-X / MIDAS 變體的 K-experiment 應預期差異難以被 MCS
區別，effort 應投向 **conceptually distinct models**（jump 軸 / regime-switching / 外生 regressor），
而不是 GARCH parameterization 的再一次變體。

本次重跑另外提供一個方法論教訓：**loss matrix 的缺值處理會決定 meta-evaluation 的樣本量**。
把缺值填成有值可以讓共同樣本看起來很大（1854），但那是虛的；誠實標記後只剩 1017，而 rolling
分析的視窗數直接腰斬（77→38）。任何建立在 pooled loss matrix 上的 MCS / SPA / Reality Check，
都應該先報告 listwise 後的共同樣本數，而不是只報 raw 天數。

## Files

- `k1583.py` — main script
- `k1583_results.json` — full results JSON
- `k1583_conditional_mcs_heatmap.png` — regime heatmap（unconditional + VIX high/mid/low + recession）
- `k1583_sequential_winner_timeline.png` — top_model timeline + mcs_size annotation

## Lineage

- 原始 task：`K1583`（next_tasks.json, source=research_backlog_auto, source_line=484）
- 原始執行：2026-06-30 hourly-11 claim / hourly-12 close，Codex review CONDITIONAL_PASS 82/100
  （`codex-cli 0.142.3`）——**該裁決只對當時的 bytes 有效，已失效**
- SUPERSEDED 原因：結論消費了已證實錯誤的 K1380_v4 loss matrix
- 重跑 task：`k1583_corrected_k1380_matrix_rerun_20260802`（parent `assign_b8abe71a`）
- 重跑執行：2026-08-05 由 research 部門，corrected matrix
  `experiments/K1380_v4/k1380_v4_losses_all.npy`
- 重跑時同步修掉一個 claim-surface 缺陷：`metadata.primary_inventory` 原本硬編
  「OOS 2019-01-02 → 2026-05-20」，在 matrix 已延伸到 1900 天（2026-07-21）之後仍宣稱舊區間，
  等於結果 JSON 描述了一個它沒有評估過的樣本。現改為從載入的矩陣推導。
- **待辦**：Codex primary-path 審查。Codex 訂閱額度用盡至 **2026-08-08**
  （見 `codex_primary_reverify_k1714_k1735_20260808` 的 `blocked_until`），在那之前
  `experiment_gates.py certify` 無法通過，也不得用 canonical knowledge writer 建立替代結論。
