# Codex 24h Review

- Article ID: `mile_ea4b38b7`
- Task ID: `paper_review_mile_ea4b38b7`
- Reviewed At: `2026-06-09`
- Reviewer: `Codex`
- Verdict: `CONDITIONAL_PASS`

## Summary

這篇文章的主要數字與 `K575` 結果檔基本對得上：年輕 profile 下 `VCL` 的終值中位數約 `$23.68M`，相對 `PW_Cons` 的 `$4.79M` 為 `4.94x`；退休 profile 下 `PW_Cons` 的 ruin rate 為 `0.0%`，`BH_SPY` 為 `5.2%`。所以文中最醒目的兩組數字不是憑空寫出來的。

但文章把一個「預先指定人生階段 + 主觀風險偏好」的 Monte Carlo 情境模擬，寫成近似普遍性的策略推薦規則，證據強度略高於方法本身。`K575` 的 recommendation 不是從正式效用函數、福利準則或估計出的最佳化問題推出，而是先在 `PROFILES` 中指定推薦策略與 `wrong_strategy`，再比較終值、回撤與破產率。這種設計適合做 illustration，不適合寫成「投資策略真的要看年齡」式的硬結論。

## Numeric Verification

- 年輕累積者：
  - `VCL` terminal wealth median = `$23,675,722`
  - `PW_Cons` terminal wealth median = `$4,789,950`
  - ratio = `4.94x`
- 退休族：
  - `PW_Cons` ruin rate = `0.0%`
  - `BH_SPY` ruin rate = `5.2%`
  - `PW_Cons` terminal wealth median = `$13,065,462`
- 文章提到 mid-career：
  - `VCL` terminal wealth median 約 `$4.64M`
  - `VT_12VIX` terminal wealth median 約 `$2.02M`
  - `VT_12VIX` median MDD 約 `-9.2%`
  - `VCL` median MDD 約 `-12.2%`
- 文章提到 pre-retirement：
  - `VCL` terminal wealth median 約 `$520K`
  - `PW_Cons` terminal wealth median 約 `$285K`
  - `VCL` median MDD 約 `-11.2%`
  - `PW_Cons` median MDD 約 `-4.8%`

來源：
- [k575_life_stage_vt_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k575/k575_life_stage_vt_results.json:1)
- [k575_life_stage_vt.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k575/k575_life_stage_vt.py:1)

## Findings

1. **SEVERITY 2 — 推薦矩陣不是由最佳化或正式決策函數推出，而是事先寫死。**  
   `PROFILES` 先指定 `young -> VCL`、`mid_career -> VT_12VIX`、`pre_retirement/retiree -> PW_Cons`；`recommendation_matrix` 也是在 script 中直接 hard-code。之後才拿模擬結果回填「wrong strategy cost」。因此這不是「模型算出哪個年齡該用哪個策略」，而是「先定義幾種人生情境，再展示幾組情境下某種偏好對應的後果」。文章若寫成一般性的策略選擇規則，會過度外推。  
   參考：[k575_life_stage_vt.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k575/k575_life_stage_vt.py:88), [k575_life_stage_vt.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k575/k575_life_stage_vt.py:640), [k575_life_stage_vt.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k575/k575_life_stage_vt.py:853)

2. **SEVERITY 2 — Mid-career 與 pre-retirement 的「推薦」本質上是主觀風險偏好，不是報酬主導的結果。**  
   在這兩組情境裡，文中自己也承認 `wrong_strategy` (`VCL`) 的終值中位數更高，只是回撤更深。這表示推薦依賴隱含效用函數，但實驗沒有明確定義效用、破產懲罰權重、或可接受 MDD threshold。文章如果要保留現在的敘事，應明講這是「以回撤容忍度為核心的規劃建議」，不是客觀最優策略排序。  
   參考：[k575_life_stage_vt_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k575/k575_life_stage_vt_results.json:172), [k575_life_stage_vt_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k575/k575_life_stage_vt_results.json:319)

3. **SEVERITY 2 — 實驗三件套不完整。**  
   `README.md` 仍是 planning stub，沒有正式方法、樣本、限制與結論段。這削弱可審核性。  
   參考：[README.md](/Users/yhlai0911/Desktop/volpred-research/experiments/k575/README.md:1)

4. **SEVERITY 3 — Article artifact completeness 有缺口。**  
   published feed entry 有內容，但缺對應 single-file `storage/reports/mile_ea4b38b7.json`，且 feed entry 的 `experiment_refs` 為 `None`，只在內文 footer 提到 K575。這會讓 downstream audit / sync 變弱。  

5. **SEVERITY 3 — Local chart artifacts 未隨實驗目錄保存。**  
   script 會產出 `k575_charts/` 多張圖，但目前本地目錄不存在該資料夾。文章雖有遠端圖片，但 repo 內實驗資產不完整。

## Lookahead Audit

- 策略報酬生成使用同日可得的 `vix`、`spy_ret`、`gld_ret`，這裡是歷史情境模擬而非訊號預測，不是典型 same-day alpha 回測。
- block bootstrap 使用固定 `seed = 42`，這點合規。
- 沒看到明顯的同日訊號乘同日報酬型 lookahead claim；本 review 的主要問題不是 lookahead，而是 recommendation inference 強度。

## Recommended Tweaks

1. 把文章主論點降級成：`人生階段 × 風險承受度 會改變你對終值 / 回撤 / 破產率的權衡`，不要寫成單純由年齡決定最佳策略。
2. 明寫 `mid-career` 與 `pre-retirement` 的推薦是以較低回撤為優先，不是因為終值最高。
3. 若要維持「推薦矩陣」口吻，應在實驗層加入正式決策準則，例如 utility / downside-penalized objective / ruin-constrained optimization，而不是 hard-coded matrix。
4. 補齊 `experiments/k575/README.md`。
5. 用正式 publish/update 流程補回 `storage/reports/mile_ea4b38b7.json` 與 `experiment_refs=[K575]`。
