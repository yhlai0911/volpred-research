---
name: Lai PRS Paper (APFM 2024)
description: 用戶（Yi-Hao Lai）自己的論文，PRS model for TAIFEX session volatility。方法有問題但概念可延伸。
type: reference
---

**論文**: Forecasting Trading-Session Return Volatility in Taiwan Futures Market: A Periodic Regime Switching with Jump Approach
**作者**: Yi-Hao Lai, Yi-Chiuan Wang, Yu-Ching Chang
**期刊**: Asia-Pacific Financial Markets, 31(2), 285-305, 2024
**DOI**: 10.1007/s10690-023-09415-w
**本地路徑**: ~/Dropbox/歷年研究與博士論文/Forecasting Trading‑Session Return Volatility in Taiwan Futures Market APFM 2024.pdf

## 核心概念
- 將台灣期貨的 return 分成 non-trading + trading sessions（2-session 或 4-session）
- 用 periodic regime switching + Markov + jump（PRS-JUMP）建模
- 不同 session 有不同 GARCH 動態和 jump 強度

## 用戶認為的問題
- 方法有問題但概念可延伸（用戶原話）

## 分析後發現的方法論問題
1. 沒有 QLIKE 和 DM test（只有 MAE/MAPE/RMSE）
2. 過度參數化（8 regime × 各自 GARCH 參數）
3. 比較不公平（PRS 用 session 級頻率 vs HAR/GJR 用日級）
4. 樣本到 2019（缺 COVID/升息/關稅）

## 可延伸方向
1. Session-Level HAR：用 HAR 框架 + session RV 作為 separate regressors（簡化 PRS）
2. Time-Varying Session Weight：夜盤重要性 24%→57% 是時變的，PRS 假設固定
3. 用 2017-2026 TAIFEX tick 重做，QLIKE + DM + Harvey
4. 加入轉倉處理
