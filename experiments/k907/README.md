# K907: Volatility Spillover Network Analysis (Diebold-Yilmaz Connectedness)

## 問題
跨資產波動率如何互相傳播？這個「網絡結構」維度是否和 VIX 捕捉的資訊相同？

## 動機
- 現有研究集中在單資產波動率預測（GARCH/HAR），跨資產 spillover 尚未探索
- Face G 跳躍式探索方向，與 GARCH/VT 顯著不同
- Diebold & Yilmaz (2012, 2014) connectedness 是標準分析框架

## 方法
- 9 資產：SPY, QQQ, IWM, EFA, EEM, 0050.TW, GLD, TLT, USO
- 4476 交易日（2009-01-02 ~ 2026-04-01）
- Garman-Klass vol proxy
- VAR(5) + Generalized FEVD (Pesaran & Shin 1998)
- Rolling 250 天 windows（4227 windows）

## 結果（★★ 重大發現）
- **TCI-VIX Pearson r = 0.001 (p=0.93)**——完全正交！
- TCI = 50.0%：半數波動率來自跨資產溢出
- SPY 是最大 net transmitter (+34.8%)
- 0050.TW 是 net receiver (-18.4%)
- GLD 最孤立 (-5.5%)，支持分散化角色
- COVID 時 TCI-VIX r=0.74，正常時分離

## 結論
TCI 不是又一個 VIX proxy——它代表全新的風險維度（網絡結構 vs vol 水平）。衍生方向：TCI 作為 VT overlay（K910 測試中）。

## 數據來源
yfinance（9 assets + VIX），2009-2026

## 參考文獻
- Diebold & Yilmaz (2012) IJF
- Diebold & Yilmaz (2014) JFE
- Pesaran & Shin (1998)
