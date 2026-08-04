# K1714 認證審查 round 2（delta 覆核，read-only）

你在 round 1（2026-08-04，raw log 已存檔）對 K1714 判 FAIL，唯一 blocking defect：
test_K1714.py::test_logm_unvec_is_pd_for_any_real_vector 執行失敗 —— K1714.py:208 的
logm_unvec 在特徵值動態範圍 ±20 時，float64 捨入使 ~2e-9 的真特徵值翻負（-1.18e-8），
np.linalg.cholesky 檢定炸掉。

## 修復內容（唯一程式碼變更）

experiments/K1714/K1714.py 的 logm_unvec（現約 L198-224）：
1. 重建 s 後做精確對稱化 (s+s.T)/2；
2. 特徵值 clip 於捨入 floor（np.finfo(float).eps * max(exp(w))）—— 只在極端動態範圍
   觸發（真實 pipeline 的矩陣遠高於 floor，clip 是 no-op）；docstring 誠實改寫
   「exact arithmetic 才保證 PD，float64 需在捨入 floor 處修復契約」。

## 修復後實測（你要覆核的證據）

- pytest experiments/K1714/test_K1714.py → 33 passed（round 1 失敗的測試已綠）。
- 全實驗重跑（凍結資料 + seed 42）：headline 與 primary 檢定**逐位元不變**；
  唯一 drift 在 matrix_log secondary spec 的 1e-13~1e-15 相對尾數（對稱化改變浮點
  運算順序的預期現象），無任何印出位數/判定/校正結論改變。
- verdict template 已對新 bytes 重釘 8 檔。

## 你要回答的

A. Blocking defect 是否已正確關閉（修法是否誠實、是否引入新問題）？
B. 檢視 logm_unvec 新實作本身（clip 的數學正當性、floor 選擇、對 secondary spec 推論
   的影響是否如上所述可忽略）。
C. round 1 你已全面審過其餘 surface；除非上述變更波及，不必重審全部 —— 但若 round 1
   有你當時想標而未標的問題，現在標。
D. round 1 的 RESIDUAL_RISKS（Cholesky 排序全距 0.767pp、matrix-log post-hoc 定位、
   10d 初始訓練列少、condition number）是否維持原判、仍屬非 blocking？

## 輸出格式（嚴格，最後一段照此）

VERDICT: PASS 或 FAIL
REVIEWER: <你的真實身分> (fallback path; round 2)
BLOCKING_DEFECTS:（無則 none）
RESIDUAL_RISKS:
