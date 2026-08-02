K1583 的數值結論已於 2026-08-02 撤回，等待以修正後 K1380_v4 loss matrix 重跑。

原因不是 MCS helper 本身，而是 K1583 的輸入矩陣繼承兩個上游模型實作缺陷：

1. A5 的外層最佳化宣告了正向 VIX slope bounds，卻未把 bounds 傳給 optimizer，並接受
   失敗／越界 iterate；實際首個 rolling window 選到 theta1=-0.35099。
2. C1/C2/C3 把只有 K+1 列的月頻 lag matrix 配給日報酬 likelihood（K=6/12/24 時分別
   只有 7/13/25 列），C1 因 `<10` gate 永遠無 forecast，C2/C3 則以極小樣本估計，且
   沒有把短期 GARCH state 濾到 training tail。

因此原條目的 16/16 retained、p=0.438、regime 與 sequential MCS 數字只能作歷史稽核，
不能作為「GARCH-X / MIDAS 變體統計不可區分」的研究證據。修正流程已建立 bounded、
fail-closed optimizer 契約，以及將每筆 eligible 日報酬對齊前 K 個完整月份 VIX 的
fixed-span MIDAS likelihood。K1583 必須吃新矩陣完整重跑並重新審查後，才能形成新結論。
