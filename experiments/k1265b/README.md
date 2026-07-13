# K1265b：K1265 的「MDD 改善」是真效應還是 scale artifact？

**Verdict：K1265 的 MDD claim 不成立（NOT SUPPORTED），須降級措辭。**

1. 用 raw MDD 講的「50–62% 改善」把效果**大幅誇大** —— 那個分母是曝險完全不同的 buy & hold。
2. 換成同實現波動的基準後，gap 是 +9.8 / +11.3 / +22.1 pp。**但正的 gap 不能證明擇時能力**
   （見下方 §4.3 與 §5.4 —— 這是本實驗最重要的發現，也推翻了本 README 的前一個版本）。
3. 對**正確的虛無假設**（同一條權重路徑、隨機化相位）檢定後，Holm 校正 **0/3 存活**。
4. K1265 原文寫「4/4 managed specs 都**顯著** MDD 改善」—— **「顯著」二字從未經過任何檢定**，
   原實驗根本沒對 MDD 做過檢定。（附帶：只有 3 個 managed spec，「4/4」是誤數。）

| | K1265 原始說法 | K1265b 重驗 |
|---|---|---|
| 比較基準 | buy & hold（**曝險不同**） | 同實現波動的常數槓桿對照組 |
| 效果大小 | MDD 改善 **50–62%** | 同風險 gap +9.8 / +11.3 / +22.1 pp（**但此數字不足以證明擇時**） |
| 統計檢定 | **無**（但寫了「顯著」） | circular-shift randomization + Holm → **0/3 存活** |

---

## 一、為什麼要重驗

K1702 §5.4 證明：在 long-short 因子動物園上，「vol-managing 壓低回撤」是 scale artifact ——
raw MDD 改善 5/6 個因子，但除以實現波動後只剩 1/6。機制是 managed 組合的曝險較低，回撤機械性偏淺。

**K1702 明確表示它沒有測試 K1265 的設計**（不同資產、不同訊號、不同 scaling rule），
因此**不宣稱推翻 K1265**，只列為待重驗。本實驗把它做完。

K1265 的原始 headline：

> **Moreira-Muir 主要 effect 是壓 MDD 不是提 Sharpe** — 4/4 managed specs 都顯著 MDD 改善
> (50-62% reduction)，但 ΔSharpe 全 < 0.15 threshold

（附帶一提，「4/4 managed specs」本身是誤數 —— 只有 3 個 managed spec，buy_hold 不是 managed。）

## 二、複製檢查：先證明重跑的是同一個東西

用 K1265 的權重建構逐行照抄，只換評分口徑。OOS 數字完全吻合：

| spec | K1265 published Sharpe / MDD | K1265b reproduced |
|---|---|---|
| buy_hold | 0.639 / −0.552 | **0.639 / −0.552** |
| vol_target_static | 0.768 / −0.338 | **0.768 / −0.338** |
| mm_rv_managed | 0.670 / −0.467 | **0.670 / −0.467** |
| mm_vix_managed | 0.743 / −0.276 | **0.743 / −0.276** |

**所以後面任何結論的差異都來自口徑，不是來自不同的回測。**

## 三、方法

### 3.1 主檢定：曝險匹配統計量 + circular-shift randomization

**統計量**：`gap = MDD(managed) − MDD(λ-matched buy&hold)`，其中 `λ = vol(managed)/vol(buy&hold)`。

這條「常數槓桿」對照組**依定義帶有與 managed 完全相同的實現波動**，而且**零擇時能力**（每天同一個 λ）。
gap > 0 才代表「回撤變淺不只是因為少冒險」。

**虛無假設**：權重路徑對「報酬何時變差」沒有任何資訊。實作為**枚舉全部 n 個 circular shift**：
把權重序列在時間上旋轉，報酬路徑完全不動。circular shift **精確保留權重值**（它只是時間的置換）
與**完整的循環自相關結構**，只破壞它與報酬的對齊。

**p 值**：`(#{null gap ≥ actual} + 1)/(n+1)`，單尾；三個 spec 做 Holm 校正 @ α=0.10。

### 3.2 次要：paired stationary bootstrap，block 長度階梯

Δ(MDD/vol) vs buy&hold，mean block ∈ {22, 126, 252, 504, 1000}。**全部報告，不挑不丟。**

## 四、結果

### 4.1 描述統計

| spec | Sharpe | 年化波動 | raw MDD | MDD/vol | Calmar |
|---|---|---|---|---|---|
| buy_hold | 0.639 | 18.7% | −0.552 | −2.951 | 0.217 |
| vol_target_static | 0.768 | 13.8% | −0.338 | −2.447 | 0.314 |
| mm_rv_managed | 0.670 | **20.0%** | −0.467 | −2.330 | 0.287 |
| mm_vix_managed | 0.743 | 16.3% | −0.276 | −1.697 | 0.438 |

注意 `mm_rv_managed` 的波動**比 buy&hold 還高**（20.0% vs 18.7%）卻回撤更淺 —— 這個 spec
的改善在定義上就不可能純粹來自「曝險變低」。

### 4.2 曝險匹配對照組（精確，同實現波動，零擇時）

| spec | λ | managed MDD | 同風險對照組 MDD | gap |
|---|---|---|---|---|
| vol_target_static | 0.739 | −0.338 | −0.436 | **+9.8 pp** |
| mm_rv_managed | 1.072 | −0.467 | −0.580 | **+11.3 pp** |
| mm_vix_managed | 0.871 | −0.276 | −0.497 | **+22.1 pp** |

3/3 為正。**但這不能拿來宣稱「效果不是機械性的」** —— 見 §4.3。把 raw 的「50–62% 改善」
拿來跟這裡的 9.8–22.1pp 對照，先看出原始說法誇大了多少。

### 4.3 主檢定：circular-shift randomization（**這是結論的來源**）

| spec | 實際 gap | null 中位數 | null p95 | p | Holm @10% |
|---|---|---|---|---|---|
| vol_target_static | +9.8 pp | −0.6 pp | +8.6 pp | 0.0347 | ❌（門檻 .0333） |
| mm_rv_managed | +11.3 pp | **+6.1 pp** | +24.4 pp | 0.3174 | ❌ |
| mm_vix_managed | +22.1 pp | **+5.4 pp** | +25.3 pp | 0.1250 | ❌ |

**0/3 存活。** `vol_target_static` 差一點（p=.0347 vs 門檻 .0333）。

**這裡有一個比主結論更重要的方法論發現，它推翻了本實驗自己 v2 草稿的推論**：

`vol_target` 的 null 中位數 gap ≈ **−0.6pp**（≈0 —— 這正是理論值：沒有擇時能力的降槓桿，
同風險 gap 應為零）。但兩個 **Moreira-Muir 凸性 spec 的 null 中位數是 +6.1pp / +5.4pp** ——
**即使把時機完全打亂，正的 gap 依然出現**。

受控實驗確認（`scripts/tests/test_mdd_scale_artifact_ratchet.py::
test_a_positive_exposure_matched_gap_is_not_by_itself_evidence_of_timing`）：
建一個**時機完全相反**的策略（動盪時**加**槓桿、平靜時減碼，劑量相同），它**仍然**拿到
**+0.85pp 的正 gap**。而在它自己的 shift-null 下，p=0.74 —— 被正確判為沒有能力。

**機制**：匹配「無條件實現波動」**沒有匹配到波動的路徑**。高度離散的權重會把風險**集中成爆發**，
而回撤是**持續失血**累積出來的，不是被單日尖峰打出來的。爆發式路徑在相同的無條件波動下，
peak-to-trough 反而較淺。

**推論**：`gap > 0` 是**必要但不充分**條件。**唯一誠實的判準是 gap 對照它自己的 shift-null，
不是對照 0。** 只匹配二階動差（波動）不夠 —— 這是連 K1702 的口徑（除以波動）也擋不住的第二層 artifact。

### 4.4 次要：bootstrap block 階梯

p(no improvement)：

| spec | L=22 | L=126 | L=252 | L=504 | L=1000 |
|---|---|---|---|---|---|
| vol_target_static | 0.418 | 0.209 | 0.161 | 0.105 | **0.065** |
| mm_rv_managed | 0.415 | 0.271 | 0.250 | 0.255 | 0.222 |
| mm_vix_managed | 0.322 | 0.169 | 0.120 | 0.077 | **0.041** |

結論**高度依賴 block 長度**。MDD 是路徑相依的極值統計量，由 2008/2020 這種**長而連續**的
episode 產生；短 block 會把它打碎。這是**必須揭露的 caveat**，不是「丟掉不喜歡的 block 長度」的許可證
（見 §六）。

## 五、結論（強度嚴格不超過證據）

1. **K1265 的 MDD claim 不成立。** 「顯著 MDD 改善 50–62%」有三個問題：(a) 50–62% 是拿曝險完全
   不同的 buy&hold 當分母算出來的；(b)「顯著」**沒有任何檢定支撐** —— 原實驗從未對 MDD 做過檢定；
   (c) 本實驗補上正確的檢定後，Holm 校正 **0/3 通過**。
2. **不要用「3/3 gap 為正」去救它。** 正的 exposure-matched gap **不是**擇時能力的證據 ——
   時機完全相反的策略也拿得到（§4.3）。
3. **正確說法**：*raw MDD 的表述大幅誇大了效果；「顯著」二字從未被檢驗；在正確的檢定下，
   回撤效益統計上未獲證實。* 但**「未證實」不等於「不存在」** —— MDD 是單一極值統計量，檢定 power 有限。
   結論是**這個 claim 不能照現在的寫法成立**，不是「VT 完全沒有壓低回撤的效果」。
4. **可推廣的方法論教訓（比 K1265 本身更重要）**：
   - `MDD ÷ 實現波動` **不是真正的 scale-invariant**。財富是複利的，MDD 對槓桿不具一次齊次性。
     同一條 buy&hold 路徑在 λ=0.739/1.072/0.871 下，比率從 −2.951 變成 −3.157/−2.895/−3.052。
     它是有用的**正規化**，不是**不變量**。
   - **匹配波動仍不足以中和高度離散的權重分佈**（§4.3）。
   - **Calmar 不能救 MDD claim。** K1265 三個 managed spec 的 Calmar 全部改善，但它仍然沒通過本檢定。

## 六、審查歷史（v1 → v2，這段不可刪）

**v1 被 Codex（gpt-5.6-sol, ultra）判 FAIL，理由正確，且 FAIL 的是作者的動機而不只是代碼。**

v1 做錯三件事，**三件都朝著作者的先驗方向錯**：

1. **把 `MDD/vol` 標成 "scale-invariant"** —— 它不是（§5.4）。
2. **宣稱 block-22 洗牌「保留自相關」** —— 實測權重的 lag-22 ACF 從 0.69/0.45/0.77 被打到約 0。
3. **最嚴重的一條**：v1 跑出 paired bootstrap 不支持顯著性（p≈0.32–0.42），於是把它標成
   **"BROKEN INSTRUMENT"** 並排除。Codex 實測：換成合理的 block 長度（L=504/1000），
   **同一個檢定的 p 值掉到 0.041–0.077，反而變顯著**。
   → 那不是發現了壞掉的儀器，那是**拿「儀器壞了」當藉口丟掉一個不利的檢定**。

   這正是 K1702 §2 親手寫下的警告 —— *「製造出 null 的 artifact，和製造出勝利的 artifact，一樣不可信」* ——
   只是這次方向相反。v2 把全部 block 長度列出來（§4.4），不丟任何一個。

其他已修正：MDD 未 prepend 初始財富 1.0（首期虧損看不見）；Monte Carlo p 應為 `(count+1)/(B+1)`
而非可以等於 0 的原始比例；v1 的單一 +500 日 placebo 在有效檢定下本來就有約 90% 機率「通過」，
沒有 size/power 驗證力 —— v2 的全枚舉 circular-shift 已經把它包含成分佈中的一個點。

## 七、限制

- **λ 用全樣本實現波動計算** → 曝險匹配對照組是**回溯歸因工具，不是可交易的 benchmark**。
  它排除「純粹曝險較低」這個解釋，但**不能單獨證明擇時能力**，且只匹配了二階動差。
- **circular-shift randomization 假設權重過程近似循環平穩**。權重是 lagged 波動的函數（高度持續、
  非嚴格平穩），所以這是**強診斷，不是尺度精確的檢定**。
- **全部 gross，未計交易成本。** K1265 已報 turnover（mm_rv 9.3x/yr）；計入成本後 Sharpe 只會更差，
  但對 MDD 的影響方向未測。
- **單一資產（SPY）、單一 OOS 期間**。

## 八、檔案

- `k1265b.py` — 全部程式碼（seed=42）
- `k1265b_results.json` — 完整結果
- `k1265b_scale_artifact.png` — 左：raw vs 同風險對照；右：circular-shift null 分佈
- `data/k1265b_spy_vix_1993_2026.csv` — yfinance snapshot（SPY auto_adjust=True + ^VIX Close）

## 九、回溯更正範圍

本實驗是 `raw-MDD-improvement claim class` 全量掃描的一部分。
掃描結果、逐條判定與機械 gate 見 **`docs/governance/2026-07/raw_mdd_claim_class_sweep.md`**。
