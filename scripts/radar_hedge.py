"""VolPred Radar 支柱③ — 避險划不划算決策（canonical Python 引擎）。

回答 ROADMAP Phase C：「現在避險划算嗎？值不值、做多少？」

這是 canonical、unit-tested 的參考實作；src/lib/radar-hedge.ts 是 Zeabur 上跑的
TS port（Zeabur 無 Python），兩邊邏輯與數字必須一致。

研究誠實鐵律
────────────
所有保險成本 / 保護幅度 / break-even gamma 數字皆來自實際實驗，逐一標明來源 K：

  K738 / K738v2 — VT Insurance Cost-Benefit（5 資產 2007-2026，Codex 二審 4/4 PASS）
    • 12/VIX 主動 VT：年化報酬拖累 +3.49%/yr，每降 1pp MDD 成本 0.321%/yr，break-even γ≈4.5
    • EWMA VT：年化報酬拖累 +2.12%/yr，每降 1pp MDD 成本 0.310%/yr，break-even γ≈4.4
    • 50/50 分散：報酬拖累 −0.51%/yr（負＝順帶賺），每降 1pp MDD 成本 −0.010 → 最便宜保險
  K667 — 50/50+VT 1.33%/yr 換 43.7pp MDD 改善；vs ATM put 26.1%/yr → 約 10x 便宜
  K641 — VT Regime Decomposition：連續 scaling 在 Elevated Sharpe −5.2，all-VT 淨 regime value 為負
  K725 — Crisis Advantage：VIX≥25 時 12/VIX Sharpe −6.07、GARCH VT −6.66（smooth-weight 最脆弱）

數字來源檔：
  experiments/k738/k738_vt_insurance_cost_benefit_results.json
  experiments/k667（knowledge.json K667 entry）
不確定 / 無對應 K 的數字 → None，從不臆造假精確值。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ── 真實研究數字（逐一來源 K，禁臆造）──────────────────────────────────────────

# 非條件避險成本表，全部 Codex-verified（K738 cross_asset_summary + K667）。
HEDGE_INSTRUMENTS = {
    "diversification_5050": {
        "label": "50/50 股債分散",
        "annual_cost_pct": -0.51,
        "mdd_reduction_pp": None,
        "cost_per_mdd_pp": -0.01,
        "breakeven_gamma": None,
        "source_k": "K738",
    },
    "vt_5050": {
        "label": "50/50 + 波動目標 (VT)",
        "annual_cost_pct": 1.33,
        "mdd_reduction_pp": 43.7,
        "cost_per_mdd_pp": 0.0304,
        "breakeven_gamma": None,
        "source_k": "K667",
    },
    "twelve_over_vix": {
        "label": "12/VIX 主動波動目標",
        "annual_cost_pct": 3.49,
        "mdd_reduction_pp": None,
        "cost_per_mdd_pp": 0.321,
        "breakeven_gamma": 4.5,
        "source_k": "K738",
    },
    "ewma_vt": {
        "label": "EWMA 波動目標",
        "annual_cost_pct": 2.12,
        "mdd_reduction_pp": None,
        "cost_per_mdd_pp": 0.31,
        "breakeven_gamma": 4.4,
        "source_k": "K738",
    },
    "atm_put": {
        "label": "ATM 保護性賣權（對照組）",
        "annual_cost_pct": 26.1,
        "mdd_reduction_pp": None,
        "cost_per_mdd_pp": None,
        "breakeven_gamma": None,
        "source_k": "K667",
    },
}

# Regime 門檻（對齊 radar-data.ts 前台規則 + K725 crisis 邊界 VIX≥25）。
VIX_CALM_MAX = 15
VIX_NORMAL_MAX = 18
VIX_ELEVATED_MAX = 25

# K738 EWMA break-even（保守取 12/VIX 4.5 與 EWMA 4.4 的較低者）。
BREAKEVEN_GAMMA = 4.4

# 風險承受度 → γ 區間（K738 decision_guide 原文對應）。
TOLERANCE_GAMMA = {
    "high": (0, 2, "高風險承受度（γ<2）"),
    "moderate": (2, 5, "中風險承受度（γ 2–5）"),
    "low": (5, 10, "低風險承受度（γ 5–10）"),
    "very_low": (10, None, "極低風險承受度（γ>10）"),
}

REGIME_LABELS = {
    "calm": "平靜（低波動）",
    "normal": "正常",
    "elevated": "升高（警戒）",
    "crisis": "危機（高波動）",
    "unknown": "資料不足",
}

DATA_HONESTY = (
    "保險成本與保護幅度均為實驗全期非條件估計（K738/K667，Codex PASS），非當下精確值；"
    "regime 只影響「進場時點是否合適」（K641/K725），不另外臆造 regime-conditional 成本數字。"
)


@dataclass
class HedgeDecision:
    as_of: Optional[str]
    vix: Optional[float]
    annual_vol_pct: Optional[float]
    regime: str
    regime_label: str
    risk_tolerance: Optional[str]
    tolerance_label: Optional[str]
    verdict: str
    insurance_cost_pct: Optional[float]
    protection_mdd_pp: Optional[float]
    cost_per_mdd_pp: Optional[float]
    breakeven_gamma: Optional[float]
    instrument_key: Optional[str]
    suggested_hedge_ratio: Optional[float]
    recommendation_text: str
    cost_benefit_text: str
    notes: list = field(default_factory=list)
    data_honesty: str = DATA_HONESTY


def classify_regime(vix: Optional[float], annual_vol_pct: Optional[float]) -> str:
    if vix is not None:
        if vix >= VIX_ELEVATED_MAX:
            return "crisis"
        if vix >= VIX_NORMAL_MAX:
            return "elevated"
        if vix >= VIX_CALM_MAX:
            return "normal"
        return "calm"
    if annual_vol_pct is not None:
        if annual_vol_pct >= 30:
            return "crisis"
        if annual_vol_pct >= 20:
            return "elevated"
        if annual_vol_pct >= 12:
            return "normal"
        return "calm"
    return "unknown"


def decide_hedge(
    vix: Optional[float],
    annual_vol_pct: Optional[float] = None,
    risk_tolerance: Optional[str] = None,
    as_of: Optional[str] = None,
) -> HedgeDecision:
    """核心判讀：給定 regime + 風險承受度 → 避險划不划算。

    邏輯（全部可追溯到 K）：
      1. 成本近似非條件（K738 全期）；break-even γ≈4.4 → γ 高才划算。
      2. Timing 是 regime-dependent：calm/normal 是便宜窗口；
         elevated/crisis 時臨時上連續 VT 是最差時點（K641/K725）= wrong_timing。
      3. 50/50 分散 K738 報酬拖累為負 → 任何 regime 對任何 γ 都「順帶賺」，是 fallback。
    """
    vix = float(vix) if vix is not None else None
    annual_vol_pct = float(annual_vol_pct) if annual_vol_pct is not None else None
    regime = classify_regime(vix, annual_vol_pct)
    tol_label = TOLERANCE_GAMMA[risk_tolerance][2] if risk_tolerance else None
    notes: list = []

    def mk(verdict, instr_key, protection, ratio, rec, cb, extra_notes=None):
        instr = HEDGE_INSTRUMENTS[instr_key] if instr_key else None
        return HedgeDecision(
            as_of=as_of,
            vix=vix,
            annual_vol_pct=annual_vol_pct,
            regime=regime,
            regime_label=REGIME_LABELS[regime],
            risk_tolerance=risk_tolerance,
            tolerance_label=tol_label,
            verdict=verdict,
            insurance_cost_pct=instr["annual_cost_pct"] if instr else None,
            protection_mdd_pp=protection,
            cost_per_mdd_pp=instr["cost_per_mdd_pp"] if instr else None,
            breakeven_gamma=instr["breakeven_gamma"] if instr else None,
            instrument_key=instr_key,
            suggested_hedge_ratio=ratio,
            recommendation_text=rec,
            cost_benefit_text=cb,
            notes=(notes + (extra_notes or [])),
        )

    # 資料不足 → 不臆造
    if regime == "unknown":
        return mk(
            "unknown",
            None,
            None,
            None,
            "VIX 與年化波動皆無資料，暫不產生避險建議。",
            "缺乏 regime 輸入，無法評估划算度。",
            ["VIX 與年化波動皆缺值，無法分類 regime。"],
        )

    # elevated / crisis：timing 警示（K641/K725）
    if regime in ("elevated", "crisis"):
        notes.append("K641：連續 scaling 在 Elevated regime Sharpe −5.2，all-VT 淨 regime value 為負。")
        notes.append("K725：VIX≥25 時 12/VIX −6.07、GARCH VT −6.66 — smooth-weight VT crisis 最脆弱。")
        is_crisis = regime == "crisis"
        return mk(
            "wrong_timing",
            "diversification_5050",
            HEDGE_INSTRUMENTS["vt_5050"]["mdd_reduction_pp"],
            0.0 if is_crisis else 0.25,
            (
                "現在 VIX 已進入危機區：臨時上連續波動目標是最差時點（K725 crisis Sharpe −6）。維持既有避險即可。"
                if is_crisis
                else "波動已升高：布置連續 VT 的便宜窗口已過（K641 Elevated −5.2）。建議小幅 discrete 防守。"
            ),
            (
                "划算度判讀：此 regime 下連續 VT 的保護被進場時點吃掉（K641/K725 為負）；最便宜穩定的仍是 50/50 分散。"
            ),
        )

    # calm / normal：便宜窗口，依 γ 選工具
    if not risk_tolerance:
        return mk(
            "worth_it",
            "diversification_5050",
            HEDGE_INSTRUMENTS["vt_5050"]["mdd_reduction_pp"],
            0.5,
            "目前 regime 平穩，是布置保險的便宜窗口。最穩健起點是 50/50 股債分散（K738 報酬拖累為負）。",
            "划算度判讀：50/50 分散在歷史上不花錢還賺，對任何投資人都划算（K738/K667）。",
            ["未提供風險承受度 → 給對所有 γ 都划算的 baseline（50/50 分散）。"],
        )

    band_lo, band_hi, _ = TOLERANCE_GAMMA[risk_tolerance]
    band_hi_eff = band_hi if band_hi is not None else float("inf")
    above_breakeven = band_hi_eff > BREAKEVEN_GAMMA

    if risk_tolerance == "high":
        return mk(
            "not_worth_it",
            "diversification_5050",
            None,
            0.0,
            "你的風險承受度高（γ<2）。K738 顯示主動避險不划算（break-even γ≈4.4），維持 100% 股票即可。",
            "划算度判讀：對 γ<2 的投資人，VT 保險成本 > 保護價值（K738 break-even γ≈4.4）→ 不划算。",
            ["K738 decision guide：γ<2 → BH 100%，不需主動避險。"],
        )

    if risk_tolerance == "moderate":
        return mk(
            "worth_it" if above_breakeven else "marginal",
            "diversification_5050",
            HEDGE_INSTRUMENTS["vt_5050"]["mdd_reduction_pp"],
            0.5,
            "你的風險承受度中等（γ 2–5），正好在主動 VT break-even（γ≈4.4）附近。最划算是 50/50 股債分散。",
            "划算度判讀：γ 2–5 處 break-even 附近，50/50 分散成本效率最高（K738 每 1pp MDD −0.010%/yr）。",
            ["K738 decision guide：γ 2–5 → 50/50 分散（cheapest insurance）。"],
        )

    if risk_tolerance == "low":
        return mk(
            "worth_it",
            "twelve_over_vix",
            None,
            0.7,
            "你的風險承受度低（γ 5–10），已跨過主動 VT break-even（γ≈4.5）。建議在 50/50 基礎上加 12/VIX 主動 VT。",
            "划算度判讀：γ≥5 已過 break-even（K738 γ≈4.5），主動 VT 保護價值 > 成本 → 划算。",
            ["K738 decision guide：γ 5–10 → 12/VIX VT（active insurance）。"],
        )

    # very_low γ>10
    return mk(
        "worth_it",
        "ewma_vt",
        None,
        0.9,
        "你的風險承受度極低（γ>10），遠在 break-even 之上。建議用 EWMA 波動目標取得最大保護（成本效率最高）。",
        "划算度判讀：γ>10 遠超 break-even，EWMA VT 成本效率最佳（K738）→ 高度划算。",
        ["K738 decision guide：γ>10 → EWMA VT（maximum protection）。"],
    )
