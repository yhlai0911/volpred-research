# vt-insurance-cost 審查修正 log（2026-06-10/11，主線程 fable-5）

## HIGH（3/3 處置）
1. DM 註腳不實 spec → 改為實際實作（negative-return loss, Bartlett NW, lag ceil(T^1/3), strategy_dm_test K811v2）
2. cross-OOS 跳窗 → 揭露 2017-18/2021-22 缺窗 + Volmageddon/2022 熊市意義 + 標 re-run queued
3. structural premium 過強 → abstract/intro/§3.3/§5 四處改 full-sample average + K846 子期間 2/4 翻負揭露（−95/−56 bps）

編譯 exit 0 + paper-update 上傳 ✅。殘項：補跑 2017-18/2021-22 兩窗（compute 批次）。
