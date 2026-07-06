# vix-sufficiency v5 修訂進度（承接 v4 REJECT）

**Base**: `main_v4.tex`（v4 Codex review = REJECT，3 SEVERE + 8 MAJOR）
**Working file**: `main_v5.tex`
**v5 建立**: 2026-07-06（台灣時間，hourly-12 fire）

---

## ✅ SEVERE-1 已修（研究誠實 critical）— 2026-07-06

**問題**：Table 6（`tab:competing_eras`）數字與自家來源實驗 K752 完全對不上，且無 `% source` 綁定。
- v4 報：三 signal 各 era incremental $R^2$ 全 0.000x、Harvey pass **0/5**、note 稱「no signal in any era」「not an artifact of any regime」。
- K752 真數據（`experiments/k752/k752_vix_sufficiency_eras_results.json` `.part_d_competing_signals_by_era`）：
  - **GFC (Era3)**：Overnight VIX incR²=0.0039 (t=-3.15)、VRP 0.0160 (t=-6.51)、Vol-mom 0.0216 (t=7.60) — 全 3 個 harvey_pass=true
  - **COVID (Era5)**：Vol-mom incR²=**0.0372 (t=9.30)** — harvey_pass=true
  - 平靜期（DotCom/PostDC/QE）全 null（與 v4 敘事一致）
- v4 的 0/5 是虛構/placeholder（COVID vol-mom 差 186×）。

**修法（honest reconciliation，非刪資料）**：
1. Table 6 換上 K752 真數字，Harvey-pass cell 加粗，Pass 欄改 1/5 / 1/5 / 2/5。
2. 補 `% source:` 綁定到 K752 逐欄位 + t-stat 明細。
3. 改 intro 明示這是 **in-sample** 診斷（非 OOS 主結果）。
4. 改 note + 後段敘事為 **regime-dependent**：平靜期充分、危機期有顯著 in-sample 增量，但**不存活於 OOS**（vol-mom/VRP/overnight VIX 皆在 13 families 主 horse race 內、已為 null）→ in-sample crisis significance 消失於 OOS = overfitting to episodic vol clustering。VIX sufficiency 定位為 robust **OOS** property，非「任何 era 無任何 in-sample association」。

**驗證**：`xelatex ×2` 乾淨（0 undefined citation / 0 undefined ref / 0 error / 60 頁 PDF）。`\ref{sec:results}` 已解析。

---

## ⏳ 待修（下班 fire 從此接續，勿重做 SEVERE-1）

**SEVERE-2**：Nested forecast inference（VIX-only vs VIX+signal）用普通 DM，缺 Clark-West / West nested-MSFE correction；主段缺 HLN small-sample correction。→ 需 recompute（走 compute_queue）或引用既有 nested-CW 結果。

**SEVERE-3**：Publication-delay / lag convention 前後不一致（Table1 note 197 shift(2)/shift(1) 混、pub-delay 340、method 359、robustness 851）；Family 10 overnight VIX 用 VIX_open,t (240) 需明示 forecast origin。→ 逐 signal 鎖定 lag 表 + 統一敘事。

**8 MAJOR**（見 `review_history/v4/round_readme.md`）：Holm/DM/MCS family 不一致、Harvey over-attribution、VaR/ES Basel 口徑、CRRA welfare overclaim、abstract time-invariance 措辭、41.8% QLIKE 方向、pre-spec registry、citation gaps（Clark-West/West/HLN/Acerbi-Szekely 等）。

**完成全部 SEVERE+MAJOR 後**才跑 `uv run volpred ops paper-update --paper-id vix-sufficiency` 同步平台 + 下一輪 paper-review-cycle。**現在不 sync**（仍 REJECT）。
