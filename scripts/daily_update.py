"""Daily research update script — multi-strategy.

Produces independent recommendations for each strategy,
each with its own paper trading record.

Run: uv run python scripts/daily_update.py
"""
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from arch import arch_model

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from volpred.data.manager import DataManager
from volpred.publisher.publisher import Publisher

# ──────────────────────────────────────────────────────────────────────
# Single source of truth for strategy metadata.
# All downstream consumers (feed article, Supabase signals, paper trading)
# MUST read from this registry. To add/modify a strategy, edit HERE only.
# ──────────────────────────────────────────────────────────────────────
STRATEGY_REGISTRY = {
    # key             → (display_name,                    is_active, supabase_order)
    "slow_vt":            ("GARCH VT (SPY)",              True,  0),
    "risk_parity":        ("Risk Parity (SPY+GLD)",       True,  1),
    "simple_12vix":       ("12/VIX (SPY)",                True,  2),
    "recommended_5050":   ("50/50 SPY/GLD",                True,  3),
    "taiwan_8.63vix":     ("台灣 VT (0050.TW)",           True,  4),
    # ⚠️ I8: TZ strategies — o2o FAIL Harvey, kept for paper trading only
    "taiwan_spy_momentum": ("台股動量 (0050.TW)",          False, 5),
    "tz_tw_jp_5050":       ("TW+JP 50/50 TZ",             False, 6),
    "global_vt_tz":        ("Global US VT + TW TZ",       False, 7),
    "vix_leading_guard":   ("VIX+景氣領先 (0050.TW)",     True,  8),
    "vix_cond_leverage":   ("VIX 條件槓桿（月頻）",        True,  9),
    "taiwan_hybrid_leverage": ("台股混合槓桿",              True, 10),
    "piecewise_conservative": ("保守型 VT（Piecewise）",    True, 11),
    # K552: Fear DCA — signal-only strategy (recommended monthly contribution multiplier)
    "fear_dca":               ("恐慌加碼定期定額",            True, 12),
    # K595: Adaptive Tier — VIX regime switching (leverage / standard / piecewise exit)
    "adaptive_tier":          ("自適應三階 VT",               True, 13),
}


def fit_garch(returns_pct, vol_type="GARCH", p=1, o=0, q=1):
    result = arch_model(returns_pct, vol=vol_type, p=p, o=o, q=q,
                        dist="normal", mean="Zero", rescale=False
                        ).fit(disp="off", show_warning=False)
    sigma = float(np.sqrt(result.forecast(horizon=1).variance.iloc[-1, 0]) / 100)
    return sigma


def _vix_regime(vix_level):
    """Classify VIX into regime and return (regime_name, emoji, advice)."""
    if vix_level is None:
        return ("無法取得", "❓", "VIX 數據暫時無法取得，建議維持保守配置。")
    if vix_level < 15:
        return ("低波動", "🟢",
                "市場處於低波動狀態（VIX<15），歷史上此區間延續時間較長。"
                "VT 策略建議較高權重，條件槓桿策略啟動 1.5 倍槓桿。"
                "但須留意均值回歸風險——低 VIX 不代表零風險。")
    if vix_level < 20:
        return ("正常", "🟡",
                "市場波動處於正常範圍（15-20），VT 策略以 12/VIX 標準模式運作。"
                "維持紀律性配置即可，不需特別加碼或減碼。")
    if vix_level < 25:
        return ("偏高", "🟠",
                "波動率偏高（20-25），市場不確定性增加。"
                "保守型策略（Piecewise）已開始降低曝險，建議減少非必要部位。"
                "定期定額投資人可正常投入。")
    if vix_level < 30:
        return ("高波動", "🔴",
                "市場處於高波動狀態（25-30），風險顯著上升。"
                "保守型策略已進入全現金模式。恐慌加碼 DCA 建議增加投入至 1.5 倍——"
                "歷史上高 VIX 買入的長期報酬優於低 VIX 買入。")
    return ("極端恐慌", "🔴🔴",
            "市場處於極端恐慌（VIX≥30），短期波動劇烈。"
            "所有保守型策略已降至最低曝險或全現金。"
            "恐慌加碼 DCA 建議 1.5 倍投入——歷史上 VIX>30 後 12 個月平均報酬 +22%。"
            "但要做好短期帳面虧損的心理準備。")


def generate_daily_article(pub, strat_list, vix_level, sigma_gjr_ann, spy_close,
                           gld_close, spy_date, today, gap_alert_level=None,
                           gap_alert_text=None, overnight_gap=None,
                           tw50_close=None, spy_ret=None, gld_ret=None):
    """Generate a rich 每日建議 article with chart, VIX interpretation, and advice.

    This runs as part of daily_update.py (system crontab) and requires zero
    Claude session dependency.  It creates a draft article that the hourly
    release-pool cron will publish.

    Returns the pub_id of the created article, or None if skipped.
    """
    # --- Build active strategy data for chart + table ---
    active_strats = []
    for sid, w_info in strat_list:
        display_name, is_active, _ = STRATEGY_REGISTRY.get(sid, (sid, True, 99))
        if not is_active:
            continue
        total_equity = sum(w_info.values())
        cash = max(0, 1 - total_equity)
        active_strats.append({
            "id": sid,
            "name": display_name,
            "weights": w_info,
            "total_equity": round(total_equity * 100, 1),
            "cash": round(cash * 100, 1),
        })

    # --- Generate bar chart of equity exposure ---
    chart_url = None
    try:
        from volpred.charts import generate_bar_chart, upload_chart

        labels = [s["name"] for s in active_strats]
        values = [s["total_equity"] for s in active_strats]
        chart_path = generate_bar_chart(
            labels=labels,
            values=values,
            title=f"各策略股票曝險比例（{spy_date}）",
            ylabel="股票曝險 (%)",
            filename=f"daily_equity_{today}",
            figsize=(12, 6),
            highlight_best=False,
        )
        chart_url = upload_chart(chart_path)
        print(f"  Daily article chart uploaded: {chart_url[:60]}...")
    except Exception as e:
        print(f"  Daily article chart failed (will publish without chart): {e}")

    # --- VIX regime analysis ---
    regime_name, regime_emoji, regime_advice = _vix_regime(vix_level)
    vix_display = round(vix_level, 2) if vix_level is not None else "N/A"

    # --- Build strategy table ---
    table_rows = []
    for s in active_strats:
        assets_parts = []
        for asset, w in s["weights"].items():
            if w > 0:
                assets_parts.append(f"{asset} {w*100:.0f}%")
        assets_str = " + ".join(assets_parts) if assets_parts else "CASH 100%"
        table_rows.append(
            f"| {s['name']} | {assets_str} | {s['total_equity']:.0f}% | {s['cash']:.0f}% |"
        )
    strat_table = "\n".join(table_rows)

    # --- Build market snapshot ---
    spy_chg = f" ({spy_ret*100:+.2f}%)" if spy_ret is not None else ""
    gld_chg = f" ({gld_ret*100:+.2f}%)" if gld_ret is not None else ""
    tw_line = ""
    if tw50_close is not None:
        tw_line = f"\n- **0050.TW**: NT${tw50_close}"

    # --- Gap alert section ---
    gap_section = ""
    if gap_alert_level:
        gap_section = f"""

---

### Overnight Gap 警報

{gap_alert_text}

建議根據警報等級調整風險預算。詳見 Phase I4 研究成果。
"""

    # --- Compose full article ---
    content = f"""# {today} 每日策略建議

> 基於 {spy_date} 收盤數據，預測下一交易日最佳持倉配置。

## 市場快照

- **SPY**: ${spy_close}{spy_chg}
- **GLD**: ${gld_close}{gld_chg}{tw_line}
- **VIX**: {vix_display} {regime_emoji}（{regime_name}）
- **GARCH 年化波動率**: {sigma_gjr_ann}%

"""

    # Insert chart if available
    if chart_url:
        content += f"![各策略股票曝險比例]({chart_url})\n\n"

    content += f"""## 今日策略配置

| 策略 | 資產配置 | 總曝險 | 現金 |
|------|---------|--------|------|
{strat_table}

## VIX 情境分析 {regime_emoji}

**當前 VIX 區間：{regime_name}（{vix_display}）**

{regime_advice}
{gap_section}
## 操作建議

"""

    # Generate regime-specific actionable advice
    if vix_level is None:
        content += "VIX 數據暫時無法取得，建議維持上一交易日的配置不變。\n"
    elif vix_level < 15:
        content += (
            "1. **VT 策略投資人**：依建議權重配置，條件槓桿策略可啟動 1.5x。\n"
            "2. **定期定額投資人**：本月建議投入正常金額的 50%（低 VIX 時保留現金）。\n"
            "3. **台股投資人**：0050.TW 權重較高，可正常持有。\n"
        )
    elif vix_level < 20:
        content += (
            "1. **VT 策略投資人**：依建議權重配置，標準 12/VIX 模式。\n"
            "2. **定期定額投資人**：正常投入，無需調整。\n"
            "3. **台股投資人**：0050.TW 維持正常配置。\n"
        )
    elif vix_level < 25:
        content += (
            "1. **VT 策略投資人**：波動偏高，保守型策略已開始降低曝險。\n"
            "2. **定期定額投資人**：正常投入即可，不建議恐慌停扣。\n"
            "3. **風險控管**：檢查部位大小，確保單一策略虧損不超過總資產 2%。\n"
        )
    else:
        content += (
            "1. **VT 策略投資人**：高波動環境，保守型策略已降至低曝險或全現金。\n"
            "2. **定期定額投資人**：恐慌加碼策略建議增加投入至 1.5 倍——歷史上這是長期報酬最佳的買點。\n"
            "3. **風險控管**：不建議使用槓桿，保持充足現金緩衝。\n"
        )

    content += f"""
---

*本文由 VolPred 研究系統自動產生。策略權重基於 GJR-GARCH(1,1) 波動率預測與 VIX 情境分析。*
*數據來源：yfinance（SPY/GLD/VIX/0050.TW），更新頻率：每個交易日。*
*免責聲明：本文僅供研究參考，不構成投資建議。*
"""

    # --- Publish as draft (hourly cron will release) ---
    title = f"每日策略建議：VIX {vix_display}（{regime_name}）— {today}"
    pub_id = pub.publish_milestone(
        title=title,
        tags=["每日建議", "VIX", "策略配置"],
        description=content,
        phase="daily_recommendation",
        status="draft",
        audience="daily",
        category="general",
        details={
            "date": today,
            "spy_date": spy_date,
            "spy_close": spy_close,
            "gld_close": gld_close,
            "tw50_close": tw50_close,
            "sigma_annual": sigma_gjr_ann,
            "vix_level": round(vix_level, 2) if vix_level is not None else None,
            "vix_regime": regime_name,
            "overnight_gap": round(overnight_gap, 6) if overnight_gap is not None else None,
            "gap_alert_level": gap_alert_level,
            "chart_url": chart_url,
            "strategies": {s["id"]: s["weights"] for s in active_strats},
            "auto_generated": True,
        },
    )

    print(f"  Daily recommendation article created: {pub_id} (status=draft)")
    return pub_id


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"=== Daily Update: {today} ===")

    dm = DataManager()
    pub = Publisher()

    # --- Fetch data (force_refresh ensures latest from yfinance) ---
    spy = dm.get_model_data("SPY", "2016-01-01", "2026-12-31", force_refresh=True)
    gld = dm.get_model_data("GLD", "2016-01-01", "2026-12-31", force_refresh=True)

    spy_close = round(float(spy.iloc[-1]["close"]), 2)
    spy_open = round(float(spy.iloc[-1]["open"]), 2)
    spy_ret = round(float(spy.iloc[-1]["returns"]), 6)
    gld_close = round(float(gld.iloc[-1]["close"]), 2)
    gld_open = round(float(gld.iloc[-1]["open"]), 2)
    gld_ret = round(float(gld.iloc[-1]["returns"]), 6)
    spy_date = str(spy.index[-1].date())

    # Overnight gap tiered alert (Phase I4 findings)
    # | Level    | Condition              | VaR Lift | Action       |
    # | Yellow   | |gap| > 1%            | 3.1x     | 注意          |
    # | Orange   | |gap| > 1.5%          | 4.3x     | 減碼準備       |
    # | Red      | |gap| > 2%            | 4.2x     | 執行減碼       |
    # | Critical | consecutive 2d gap<-0.5% | 5/5 crises | 危機模式  |
    overnight_gap = None
    gap_alert_level = None   # None / "yellow" / "orange" / "red" / "critical"
    gap_alert_text = None
    if len(spy) >= 2:
        overnight_gap = float(spy.iloc[-1]["open"]) / float(spy.iloc[-2]["close"]) - 1
        gap_pct = overnight_gap * 100

        # Check consecutive 2-day negative gap (crisis detection)
        consecutive_neg = False
        if len(spy) >= 3:
            prev_gap = float(spy.iloc[-2]["open"]) / float(spy.iloc[-3]["close"]) - 1
            if overnight_gap < -0.005 and prev_gap < -0.005:
                consecutive_neg = True

        # Determine alert level (highest matching level wins)
        if consecutive_neg:
            gap_alert_level = "critical"
            gap_alert_text = (
                f"🔴🔴 CRITICAL: 連續 2 日負缺口 (today {gap_pct:+.2f}%, "
                f"prev {prev_gap*100:+.2f}%) — 5/5 歷史危機均出現此信號，啟動危機模式"
            )
        elif abs(overnight_gap) > 0.02:
            gap_alert_level = "red"
            gap_alert_text = (
                f"🔴 RED ALERT: |gap| = {abs(gap_pct):.2f}% (>2%) — "
                f"VaR Lift 4.2x，建議執行減碼"
            )
        elif abs(overnight_gap) > 0.015:
            gap_alert_level = "orange"
            gap_alert_text = (
                f"🟠 ORANGE ALERT: |gap| = {abs(gap_pct):.2f}% (>1.5%) — "
                f"VaR Lift 4.3x，建議減碼準備"
            )
        elif abs(overnight_gap) > 0.01:
            gap_alert_level = "yellow"
            gap_alert_text = (
                f"🟡 YELLOW ALERT: |gap| = {abs(gap_pct):.2f}% (>1%) — "
                f"VaR Lift 3.1x，注意觀察"
            )

        if gap_alert_level:
            print(f"  {gap_alert_text}")
        else:
            overnight_gap = None  # no alert — clear the value

    # TLT momentum monitor (J2: add TLT to portfolio when 66d momentum turns positive)
    tlt = dm.get_model_data("TLT", "2024-01-01", "2026-12-31", force_refresh=True)
    tlt_mom_66 = float(tlt.iloc[-66:]["returns"].sum()) if len(tlt) >= 66 else 0
    if tlt_mom_66 > 0:
        print(f"  📈 TLT 66d momentum POSITIVE ({tlt_mom_66*100:+.1f}%) — consider adding TLT to portfolio")
    else:
        print(f"  TLT 66d momentum: {tlt_mom_66*100:+.1f}% (negative, SPY-only recommended)")

    # GLD regime monitor (Phase K: leverage direction is regime-dependent)
    if len(gld) >= 252:
        gld_trailing_ret = float(gld.iloc[-1]["close"]) / float(gld.iloc[-252]["close"]) - 1
        gld_regime = "BULL (inverted leverage → GARCH)" if gld_trailing_ret > 0 else "BEAR (standard leverage → GJR)"
        print(f"  GLD regime: {gld_regime} (252d ret={gld_trailing_ret*100:+.1f}%)")

    # VIX/GARCH ratio alert (94% VaR violations occur when ratio > 1.5)
    try:
        vix_data = dm.get_model_data("^VIX", "2025-01-01", "2026-12-31", force_refresh=True)
        if len(vix_data) > 0:
            vix_level = float(vix_data.iloc[-1]["close"])
            # Will compute ratio after GARCH fit below
    except Exception:
        vix_level = None

    # Phase M: upgraded to w=2000 (better VaR: 0.8% vs 1.1%, +4ms cost)
    # Larger window reduces persistence bias (-3% → ~0%), improves tail coverage.
    # GJR advantage actually LARGER at w=2000 (-6.1% vs -3.8% at w=504).
    # Run scripts/check_persistence_stability.py monthly to verify
    spy_train = spy.iloc[-2000:]["returns"].values * 100
    gld_train = gld.iloc[-2000:]["returns"].values * 100

    sigma_gjr = fit_garch(spy_train, "GARCH", p=1, o=1, q=1)
    sigma_garch = fit_garch(spy_train, "GARCH", p=1, o=0, q=1)
    sigma_gld = fit_garch(gld_train, "GARCH", p=1, o=0, q=1)

    sigma_gjr_ann = round(sigma_gjr * np.sqrt(252) * 100, 1)
    sigma_gld_ann = round(sigma_gld * np.sqrt(252) * 100, 1)
    sigma_floor = max(sigma_gjr, 0.9 * sigma_garch)
    target_daily = 0.12 / np.sqrt(252)

    # VIX/GARCH ratio check
    if vix_level is not None:
        vix_garch_ratio = round(vix_level / sigma_gjr_ann, 2)
        if vix_garch_ratio > 1.5:
            print(f"  ⚠️ VIX/GARCH ratio = {vix_garch_ratio} (>1.5, VaR may be unreliable!)")
        else:
            print(f"  VIX/GARCH ratio: {vix_garch_ratio} (normal)")

    # VIX term structure backwardation check (P37: Harvey-significant signal)
    try:
        vix3m_data = dm.get_model_data("^VIX3M", "2025-01-01", "2026-12-31", force_refresh=True)
        if len(vix3m_data) > 0:
            vix3m_level = float(vix3m_data.iloc[-1]["close"])
            ts_ratio = vix_level / vix3m_level if vix3m_level > 0 else 1.0
            if ts_ratio > 1.0:
                print(f"  ⚠️ VIX BACKWARDATION (ratio={ts_ratio:.3f}) — preemptive reduction recommended!")
            else:
                print(f"  VIX term structure: contango ({ts_ratio:.3f})")
    except Exception:
        pass

    print(f"  SPY: ${spy_close} ({spy_ret*100:+.2f}%), σ={sigma_gjr_ann}%")
    print(f"  GLD: ${gld_close}, σ={sigma_gld_ann}%")

    # --- Strategy 1: Slow VT (SPY only) --- with Hybrid VIX switch
    if vix_level is not None and vix_garch_ratio > 1.3:
        # Hybrid mode: use VIX-implied vol (forward-looking, more conservative)
        vix_sigma_daily = vix_level / 100 / np.sqrt(252)
        w_spy_only = round(min(max(target_daily / vix_sigma_daily, 0), 2.0), 2)
        print(f"  🔄 Hybrid VT active (VIX-based weight, ratio={vix_garch_ratio})")
    else:
        w_spy_only = round(min(max(target_daily / sigma_floor, 0), 2.0), 2)
    cash_spy_only = round(max(0, 1 - w_spy_only), 2)

    # --- Strategy 2: Risk Parity (SPY + GLD) ---
    inv_s = 1 / sigma_gjr + 1 / sigma_gld
    rp_spy = (1 / sigma_gjr) / inv_s
    rp_gld = (1 / sigma_gld) / inv_s
    port_sigma = np.sqrt((rp_spy * sigma_gjr) ** 2 + (rp_gld * sigma_gld) ** 2)
    scale = target_daily / port_sigma
    w_rp_spy = round(min(rp_spy * scale, 2.0), 2)
    w_rp_gld = round(min(rp_gld * scale, 2.0), 2)
    w_rp_cash = round(max(0, 1 - w_rp_spy - w_rp_gld), 2)

    # --- Strategy 3: 12/VIX Simple (for non-professional investors) ---
    if vix_level is not None:
        w_12vix = round(min(12.0 / vix_level, 1.0), 2)
        cash_12vix = round(1 - w_12vix, 2)
    else:
        w_12vix = w_spy_only  # Fallback to GARCH
        cash_12vix = cash_spy_only

    # --- Strategy 5: ★ 50/50 SPY/GLD 12/VIX (Q21 recommended) ---
    if vix_level is not None:
        w_5050 = round(min(12.0 / vix_level, 1.0), 2)
        w_5050_spy = round(0.5 * w_5050, 2)
        w_5050_gld = round(0.5 * w_5050, 2)
        w_5050_cash = round(max(0, 1 - w_5050_spy - w_5050_gld), 2)
    else:
        w_5050_spy = round(0.5 * w_spy_only, 2)
        w_5050_gld = round(0.5 * w_spy_only, 2)
        w_5050_cash = round(max(0, 1 - w_5050_spy - w_5050_gld), 2)

    # --- Strategy 4: Taiwan 0050.TW 8.63/VIX (Q1 finding: adjusted for VIXTWN ratio 1.39) ---
    try:
        tw50 = dm.get_model_data("0050.TW", "2024-01-01", "2026-12-31", force_refresh=True)
        tw50_close = round(float(tw50.iloc[-1]["close"]), 2)
        tw50_open = round(float(tw50.iloc[-1]["open"]), 2)
        tw50_date = str(tw50.index[-1].date())
        tw50_ret = round(float(tw50.iloc[-1]["returns"]), 6)
        if vix_level is not None:
            # 8.63/VIX = 12/(VIX×1.39), adjusted for VIXTWN amplification
            w_tw50 = round(min(8.63 / vix_level, 1.0), 2)
        else:
            # Fallback to EWMA if VIX unavailable
            tw50_ret_pct = tw50.iloc[-252:]["returns"] if len(tw50) >= 252 else tw50["returns"]
            sigma_tw = float(np.sqrt(tw50_ret_pct.ewm(span=50).var().iloc[-1])) * np.sqrt(252)
            w_tw50 = round(min(max(0.10 / sigma_tw, 0), 1.0), 2)
        cash_tw50 = round(max(0, 1 - w_tw50), 2)
    except Exception:
        tw50_close = None; tw50_date = None; tw50_ret = None; w_tw50 = None; cash_tw50 = None

    print(f"  Slow VT: {w_spy_only*100:.0f}% SPY, {cash_spy_only*100:.0f}% cash")
    print(f"  Risk Parity: {w_rp_spy*100:.0f}% SPY, {w_rp_gld*100:.0f}% GLD, {w_rp_cash*100:.0f}% cash")
    print(f"  12/VIX Simple: {w_12vix*100:.0f}% SPY, {cash_12vix*100:.0f}% cash (SHY)")
    print(f"  ★ 50/50 SPY/GLD: {w_5050_spy*100:.0f}% SPY, {w_5050_gld*100:.0f}% GLD, {w_5050_cash*100:.0f}% SHY")
    if w_tw50 is not None:
        print(f"  台灣 8.63/VIX: {w_tw50*100:.0f}% 0050.TW, {cash_tw50*100:.0f}% 短債 (NT${tw50_close})")

    # --- Paper Trading ---
    pt_file = Path("storage/paper_trading.json")
    pt = json.loads(pt_file.read_text()) if pt_file.exists() else {}

    strat_list = [
        ("slow_vt", {"SPY": w_spy_only}),
        ("risk_parity", {"SPY": w_rp_spy, "GLD": w_rp_gld}),
        ("simple_12vix", {"SPY": w_12vix}),
    ]
    strat_list.append(("recommended_5050", {"SPY": w_5050_spy, "GLD": w_5050_gld}))
    if w_tw50 is not None:
        strat_list.append(("taiwan_8.63vix", {"0050.TW": w_tw50}))

    # --- Strategy 6: 10d SPY Momentum for Taiwan (U4: 10d > 5d) ---
    # ⚠️ I8: c2c Sharpe contains timing bias (opening gap captures 78% of alpha).
    #    o2o Sharpe = 0.87, FAILS Harvey t>3. Kept for tracking, marked biased.
    try:
        spy_10d_mean = float(spy["simple_return"].iloc[-10:].mean())
        spy_10d_signal = 1.0 if spy_10d_mean > 0 else 0.0
        w_tw_mom = round(spy_10d_signal, 2)
        strat_list.append(("taiwan_spy_momentum", {"0050.TW": w_tw_mom}))
        signal_text = "HOLD 0050" if spy_10d_signal > 0 else "CASH"
        print(f"  ⚠️ 10d SPY Momentum [BIASED c2c, o2o FAIL]: SPY 10d avg={spy_10d_mean*100:+.3f}% → {signal_text}")
    except Exception as e:
        print(f"  10d SPY Momentum: error ({e})")

    # Actual returns per asset (for backfilling previous entry)
    asset_returns = {"SPY": spy_ret, "GLD": gld_ret}
    if tw50_ret is not None:
        asset_returns["0050.TW"] = tw50_ret

    # --- Strategy 7: TW+JP 50/50 TZ Arbitrage (U2) ---
    # ⚠️ I8: Based on biased c2c Sharpe. o2o FAILS Harvey. Kept for tracking.
    try:
        nk225 = dm.get_model_data("^N225", "2016-01-01", "2026-12-31", force_refresh=True)
        spy_10d_mean_jp = float(spy["simple_return"].iloc[-10:].mean())
        jp_signal = 1.0 if spy_10d_mean_jp > 0 else 0.0
        # 50/50 split between TW and JP (reuse spy_10d_signal from Strategy 6)
        w_tw_half = round(0.5 * spy_10d_signal, 2)
        w_jp_half = round(0.5 * jp_signal, 2)
        strat_list.append(("tz_tw_jp_5050", {"0050.TW": w_tw_half, "^N225": w_jp_half}))
        nk225_close = round(float(nk225.iloc[-1]["close"]), 2)
        nk225_ret = round(float(nk225.iloc[-1]["returns"]), 6)
        asset_returns["^N225"] = nk225_ret
        signal_tw = "TW ON" if spy_10d_signal > 0 else "TW OFF"
        signal_jp = "JP ON" if jp_signal > 0 else "JP OFF"
        print(f"  ⚠️ TW+JP 50/50 TZ [BIASED]: {signal_tw}, {signal_jp} (^N225 ¥{nk225_close})")
    except Exception as e:
        print(f"  TW+JP TZ: error ({e})")

    # --- Strategy 8: Global US VT + TW TZ (50% 50/50 SPY/GLD 12/VIX + 50% TW 10d Mom) ---
    # ⚠️ I8: 50% of this strategy is based on biased TZ momentum (o2o FAIL Harvey).
    #    US VT component is unaffected. Kept for tracking.
    try:
        w_global_spy = round(0.5 * w_5050_spy, 2)
        w_global_gld = round(0.5 * w_5050_gld, 2)
        w_global_tw = round(0.5 * spy_10d_signal, 2)
        strat_list.append(("global_vt_tz", {"SPY": w_global_spy, "GLD": w_global_gld, "0050.TW": w_global_tw}))
        print(f"  ⚠️ Global VT+TZ [50% BIASED]: SPY {w_global_spy*100:.0f}%, GLD {w_global_gld*100:.0f}%, 0050 {w_global_tw*100:.0f}%")
    except Exception as e:
        print(f"  Global VT+TZ: error ({e})")

    # --- Strategy 9: VIX+景氣領先 k=10/6 (G21: DM p=0.0005 vs pure VIX) ---
    try:
        import pandas as pd
        bci_path = Path("storage/macro/tw_dgbas_bci_m.csv")
        if bci_path.exists():
            bci_df = pd.read_csv(bci_path)
            # Find leading indicator column and compute MoM
            lead_cols = [c for c in bci_df.columns if '領先' in c and '綜合' in c]
            if lead_cols:
                bci_df['lead_val'] = pd.to_numeric(bci_df[lead_cols[0]], errors='coerce')
                bci_df['lead_mom'] = bci_df['lead_val'].diff()
                latest_mom = bci_df['lead_mom'].dropna().iloc[-1] if len(bci_df['lead_mom'].dropna()) > 0 else 0
            else:
                latest_mom = 0
        else:
            latest_mom = 0
        k_leading = 10.0 if latest_mom > 0 else 6.0
        if vix_level is not None:
            w_vix_lead = round(min(k_leading / vix_level, 1.0), 2)
        else:
            w_vix_lead = w_tw50 if w_tw50 is not None else 0.37
        strat_list.append(("vix_leading_guard", {"0050.TW": w_vix_lead}))
        lead_dir = "↑積極k=10" if latest_mom > 0 else "↓保守k=6"
        print(f"  VIX+景氣領先: {w_vix_lead*100:.0f}% 0050.TW ({lead_dir}, MoM={latest_mom:+.1f})")
    except Exception as e:
        print(f"  VIX+景氣領先: error ({e})")

    # --- Strategy 10: VIX 條件槓桿（月頻）(K548/K551 t=7.90, K577 monthly hybrid t=5.16) ---
    # 50/50 SPY/GLD base, 12/VIX sizing, VIX<15 → 1.5x leverage, VIX>=15 → 1.0x
    # Monthly rebalance with daily VIX monitoring for leverage switch
    try:
        if vix_level is not None:
            vcl_base_weight = 12.0 / vix_level / 2  # 50% equity allocation via 12/VIX
            vcl_leverage = 1.5 if vix_level < 15 else 1.0
            vcl_spy = round(min(vcl_base_weight * vcl_leverage, 1.0), 2)
            vcl_gld = round(min(vcl_base_weight * vcl_leverage, 1.0), 2)
        else:
            # Fallback: conservative 50/50 at half weight
            vcl_spy = 0.25
            vcl_gld = 0.25
            vcl_leverage = 1.0
        vcl_cash = round(max(0, 1 - vcl_spy - vcl_gld), 2)
        strat_list.append(("vix_cond_leverage", {"SPY": vcl_spy, "GLD": vcl_gld}))
        lev_label = "1.5x 槓桿" if vix_level is not None and vix_level < 15 else "1.0x 標準"
        print(f"  VIX條件槓桿: SPY {vcl_spy*100:.0f}%, GLD {vcl_gld*100:.0f}%, cash {vcl_cash*100:.0f}% ({lev_label}, VIX={vix_level:.1f})")
    except Exception as e:
        print(f"  VIX條件槓桿: error ({e})")

    # --- Strategy 11: 台股混合槓桿 (K553/K558 t=4.79, 18/18 OOS) ---
    # 0050.TW with 8.63/VIX base sizing + conditional 1.5x leverage
    # Leverage ON when: RV22_TW < 20% AND VIX 252d percentile < 0.30
    # Monthly rebalance with daily condition monitoring
    try:
        if tw50_close is not None and vix_level is not None:
            # Compute 0050.TW 22-day realized volatility (annualized)
            tw50_rets = tw50["returns"].dropna()
            rv22_tw = float(tw50_rets.iloc[-22:].std() * np.sqrt(252)) if len(tw50_rets) >= 22 else 0.25

            # Compute VIX 252-day rolling percentile
            vix_hist = vix_data["close"].dropna()
            if len(vix_hist) >= 252:
                vix_252 = vix_hist.iloc[-252:]
                vix_percentile = float((vix_252 < vix_level).sum() / len(vix_252))
            else:
                vix_percentile = 0.5  # conservative fallback

            # Base weight: 8.63/VIX (same as taiwan_8.63vix)
            thl_base = 8.63 / vix_level

            # Conditional leverage
            thl_leverage = 1.5 if rv22_tw < 0.20 and vix_percentile < 0.30 else 1.0
            w_thl = round(min(thl_base * thl_leverage, 1.0), 2)
            cash_thl = round(max(0, 1 - w_thl), 2)

            strat_list.append(("taiwan_hybrid_leverage", {"0050.TW": w_thl}))
            lev_label_tw = "1.5x 槓桿" if thl_leverage > 1.0 else "1.0x 標準"
            print(f"  台股混合槓桿: {w_thl*100:.0f}% 0050.TW, {cash_thl*100:.0f}% cash ({lev_label_tw}, RV22={rv22_tw*100:.1f}%, VIX pctl={vix_percentile:.2f})")
        else:
            print(f"  台股混合槓桿: skipped (tw50 or VIX unavailable)")
    except Exception as e:
        print(f"  台股混合槓桿: error ({e})")

    # --- Strategy 12: 保守型 VT（Piecewise）(K569/K574: Sharpe 1.875, MDD -4.9%) ---
    # Piecewise linear VIX → weight mapping on 50/50 SPY/GLD:
    #   VIX < 12  → w = 1.0  (fully invested)
    #   12 ≤ VIX ≤ 20 → w = (20 - VIX) / 8  (linear ramp-down)
    #   VIX > 20  → w = 0.0  (fully cash — conservative by design)
    try:
        if vix_level is not None:
            if vix_level < 12:
                pw_w = 1.0
            elif vix_level <= 20:
                pw_w = (20 - vix_level) / 8
            else:
                pw_w = 0.0
            pw_spy = round(0.5 * pw_w, 2)
            pw_gld = round(0.5 * pw_w, 2)
        else:
            # Fallback: conservative 25/25 when VIX unavailable
            pw_spy = 0.25
            pw_gld = 0.25
            pw_w = 0.5
        pw_cash = round(max(0, 1 - pw_spy - pw_gld), 2)
        strat_list.append(("piecewise_conservative", {"SPY": pw_spy, "GLD": pw_gld}))
        if vix_level is not None:
            vix_zone = "全倉" if vix_level < 12 else ("漸退" if vix_level <= 20 else "全現金")
            print(f"  保守型VT(Piecewise): SPY {pw_spy*100:.0f}%, GLD {pw_gld*100:.0f}%, cash {pw_cash*100:.0f}% (VIX={vix_level:.1f}, {vix_zone})")
        else:
            print(f"  保守型VT(Piecewise): SPY {pw_spy*100:.0f}%, GLD {pw_gld*100:.0f}%, cash {pw_cash*100:.0f}% (VIX unavailable, fallback)")
    except Exception as e:
        print(f"  保守型VT(Piecewise): error ({e})")

    # --- Strategy 13: 恐慌加碼定期定額 (K552: Fear DCA, 3/3 cross-OOS, MDD -9pp) ---
    # Signal-only strategy: tells retail DCA investors how much to invest THIS MONTH.
    # VIX > 25 → 1.5x normal contribution (buy the fear)
    # VIX 15-25 → 1.0x normal contribution
    # VIX < 15 → 0.5x normal contribution (market complacent, save cash)
    # Budget neutral over time. Weights display as % of normal monthly amount.
    try:
        if vix_level is not None:
            if vix_level > 25:
                dca_multiplier = 1.5
                dca_regime = "恐慌加碼 1.5x"
            elif vix_level < 15:
                dca_multiplier = 0.5
                dca_regime = "低波減碼 0.5x"
            else:
                dca_multiplier = 1.0
                dca_regime = "正常投入 1.0x"
            # Display as multiplier (1.50 = invest 150% of normal amount)
            # Frontend shows weight×100 as percentage, so 1.50 → "150%"
            strat_list.append(("fear_dca", {"SPY": round(dca_multiplier, 2)}))
            print(f"  恐慌加碼DCA: {dca_regime} (VIX={vix_level:.1f}, 本月建議投入 {dca_multiplier:.0%} 正常金額)")
        else:
            strat_list.append(("fear_dca", {"SPY": 1.0}))
            print(f"  恐慌加碼DCA: VIX 無法取得，預設正常投入 100%")
    except Exception as e:
        print(f"  恐慌加碼DCA: error ({e})")

    # --- Strategy 14: 自適應三階 VT (K595: Harvey pass, 5/5 OOS, CAGR 14.7%, MDD -8.7%) ---
    # VIX regime switching on 50/50 SPY/GLD:
    #   VIX < 15  → VIX-Conditional Leverage mode (1.5x on 12/VIX base)
    #   15 ≤ VIX ≤ 20 → Standard 12/VIX mode
    #   VIX > 20  → Piecewise exit (fully cash)
    # Monthly rebalance
    try:
        if vix_level is not None:
            if vix_level < 15:
                # VIX-Conditional Leverage mode
                at_base = 12.0 / vix_level / 2  # 50% equity via 12/VIX
                at_leverage = 1.5
                at_w = min(at_base * at_leverage, 1.0)
                at_regime = f"槓桿 1.5x (VIX={vix_level:.1f}<15)"
            elif vix_level <= 20:
                # Standard 12/VIX mode
                at_w = 12.0 / vix_level / 2
                at_regime = f"標準 12/VIX (15≤VIX={vix_level:.1f}≤20)"
            else:
                # Piecewise exit mode
                at_w = 0.0
                at_regime = f"退出 (VIX={vix_level:.1f}>20)"
            at_spy = round(at_w, 2)
            at_gld = round(at_w, 2)
        else:
            # Fallback: conservative
            at_spy = 0.25
            at_gld = 0.25
            at_regime = "VIX 無法取得，保守配置"
        at_cash = round(max(0, 1 - at_spy - at_gld), 2)
        strat_list.append(("adaptive_tier", {"SPY": at_spy, "GLD": at_gld}))
        print(f"  自適應三階VT: SPY {at_spy*100:.0f}%, GLD {at_gld*100:.0f}%, cash {at_cash*100:.0f}% ({at_regime})")
    except Exception as e:
        print(f"  自適應三階VT: error ({e})")

    for strat_id, w_info in strat_list:
        if strat_id not in pt:
            pt[strat_id] = {"entries": [], "initial_capital": 1000000}
        entries = pt[strat_id]["entries"]

        # Skip if already have entry for today's data_date
        existing_dates = {e.get("data_date") for e in entries}
        if spy_date in existing_dates:
            continue

        # Backfill ALL entries with missing portfolio_return (multi-day recovery)
        # When system was down for N days, multiple entries may lack returns.
        # We can only compute returns for the most recent missing entry (needs
        # today's prices), but for older gaps we mark them with actual_returns
        # so recalc_metrics.py can handle them properly.
        for i, ent in enumerate(entries):
            if ent.get("portfolio_return") is not None:
                continue
            if ent.get("data_date") == spy_date:
                continue  # Today's entry — will be filled tomorrow
            ent_weights = ent.get("weights", {})
            # Try to compute return from the NEXT entry's prices
            if i + 1 < len(entries):
                next_ent = entries[i + 1]
                # Compute return using market data (from entry or _market_daily)
                market = pt.get("_market_daily", {})
                td0 = ent.get("trade_date", "")
                td1 = next_ent.get("trade_date", "")
                md0 = market.get(td0, ent)  # fallback to entry for backward compat
                md1 = market.get(td1, next_ent)
                ent_ret = {}
                for asset in ent_weights:
                    if asset == "SPY":
                        p0 = md0.get("spy_close") or ent.get("spy_close")
                        p1 = md1.get("spy_close") or next_ent.get("spy_close")
                    elif asset == "GLD":
                        p0 = md0.get("gld_close") or ent.get("gld_close")
                        p1 = md1.get("gld_close") or next_ent.get("gld_close")
                    elif asset == "0050.TW":
                        p0 = md0.get("tw50_close") or ent.get("tw50_close")
                        p1 = md1.get("tw50_close") or next_ent.get("tw50_close")
                    else:
                        p0 = p1 = None
                    if p0 and p1 and p0 > 0:
                        ent_ret[asset] = round(p1 / p0 - 1, 6)
                if ent_ret:
                    port_ret = sum(ent_weights.get(a, 0) * ent_ret.get(a, 0) for a in ent_weights)
                    ent["actual_returns"] = ent_ret
                    ent["portfolio_return"] = round(port_ret, 6)
            elif entries[-1] is ent:
                # Last entry before today — use today's asset_returns
                prev_actual = {a: asset_returns[a] for a in ent_weights if a in asset_returns}
                port_ret = sum(ent_weights.get(a, 0) * asset_returns.get(a, 0) for a in ent_weights)
                ent["actual_returns"] = prev_actual
                ent["portfolio_return"] = round(port_ret, 6)

        # Today's entry — strategy-specific only (market data in _market_daily)
        total_w = sum(w_info.values())
        entry = {
            "trade_date": today,
            "data_date": spy_date,
            "weights": w_info,
            "cash_weight": round(max(0, 1 - total_w), 2),
            "portfolio_return": None,
        }
        entries.append(entry)

    # Store shared market data in _market_daily (once, not per strategy)
    if "_market_daily" not in pt:
        pt["_market_daily"] = {}
    pt["_market_daily"][today] = {
        "spy_close": spy_close,
        "spy_open": spy_open,
        "gld_close": gld_close,
        "gld_open": gld_open,
        "tw50_close": tw50_close if locals().get('tw50_close') is not None else None,
        "tw50_open": tw50_open if locals().get('tw50_open') is not None else None,
        "sigma_spy_ann": sigma_gjr_ann,
        "sigma_gld_ann": sigma_gld_ann,
        "overnight_gap": round(overnight_gap, 6) if overnight_gap is not None else None,
        "gap_alert_level": gap_alert_level,
    }

    pt_file.write_text(json.dumps(pt, indent=2, ensure_ascii=False))

    # --- Check if data is fresh (skip publish if spy_date unchanged since last run) ---
    feed_path = Path("storage/reports/feed.json")
    last_spy_date = None
    if feed_path.exists():
        feed = json.loads(feed_path.read_text())
        for p in feed:
            if p.get("phase") == "daily_update" and p.get("details", {}).get("spy_date"):
                last_spy_date = p["details"]["spy_date"]
                break
        if last_spy_date == spy_date:
            print(f"  ⚠️ 數據未更新（spy_date={spy_date} 與上次相同），跳過發布")
            # Still do Supabase sync + metrics recalc, just skip feed publish
            feed = feed  # keep existing
        else:
            # Remove old daily_update for today
            feed = [p for p in feed if not (p.get("phase") == "daily_update" and today in p.get("title", ""))]
            feed_path.write_text(json.dumps(feed, indent=2, ensure_ascii=False))
    else:
        feed = []

    skip_publish = (last_spy_date == spy_date)

    # --- Publish signal for each strategy (skip if data unchanged) ---
    if skip_publish:
        print(f"  跳過發布（數據與上次相同）")
    else:
        # Build strategy table (only active strategies, using display names from STRATEGY_REGISTRY)
        strat_rows = []
        for sid, w_info in strat_list:
            display_name, is_active, _ = STRATEGY_REGISTRY.get(sid, (sid, True, 99))
            if not is_active:
                continue
            assets_str = " + ".join(f"**{a} {w*100:.0f}%**" for a, w in w_info.items() if w > 0)
            cash = max(0, 1 - sum(w_info.values()))
            if not assets_str:
                assets_str = "**CASH 100%**"
            strat_rows.append(f"| {display_name} | {assets_str} | {cash*100:.0f}% |")
        strat_table = "\n".join(strat_rows)

        gap_section = ""
        if gap_alert_level:
            gap_section = f"\n---\n\n### Overnight Gap 警報 (I4)\n{gap_alert_text}\n"

        desc = f"""## 策略建議（{spy_date} 數據 → 預測下一交易日）

σ = {sigma_gjr_ann}% · VIX = {round(vix_level, 2) if vix_level else 'N/A'}

| 策略 | 配置 | 現金 |
|------|------|------|
{strat_table}
{gap_section}
"""
        pub.publish_milestone(
            title=f"{today} 本日持倉比率建議（依據 {spy_date} 收盤數據）",
            tags=["持倉建議", "daily-update", "12/VIX", "SPY", "GLD", "0050.TW", "VT策略"],
            description=desc,
            phase="daily_update",
            details={
                "date": today,
                "spy_date": spy_date,
                "spy_close": spy_close,
                "gld_close": gld_close,
                "sigma_annual": sigma_gjr_ann,
                "vix_level": round(vix_level, 2) if vix_level else None,
                "overnight_gap": round(overnight_gap, 6) if overnight_gap is not None else None,
                "gap_alert_level": gap_alert_level,
                "strategies": {sid: dict(w_info) for sid, w_info in strat_list},
            },
        )

        # --- Auto-generate 每日建議 article (rich content + chart) ---
        try:
            generate_daily_article(
                pub=pub,
                strat_list=strat_list,
                vix_level=vix_level,
                sigma_gjr_ann=sigma_gjr_ann,
                spy_close=spy_close,
                gld_close=gld_close,
                spy_date=spy_date,
                today=today,
                gap_alert_level=gap_alert_level,
                gap_alert_text=gap_alert_text if gap_alert_level else None,
                overnight_gap=overnight_gap,
                tw50_close=tw50_close if locals().get('tw50_close') is not None else None,
                spy_ret=spy_ret,
                gld_ret=gld_ret,
            )
        except Exception as e:
            print(f"  Daily recommendation article failed: {e}")

    # --- Sync static data ---
    storage = Path("storage")
    pub_data = Path("frontend/public/data")
    pub_data.mkdir(parents=True, exist_ok=True)
    for src, dst in [
        ("memory/research_log.json", "research_log.json"),
        ("memory/knowledge.json", "knowledge.json"),
        ("memory/experiments.json", "experiments.json"),
        ("memory/thinking_journal.json", "thinking_journal.json"),
        ("memory/open_questions.json", "open_questions.json"),
        ("reports/feed.json", "feed.json"),
    ]:
        s = storage / src
        if s.exists():
            shutil.copy2(s, pub_data / dst)
    (pub_data / "reports").mkdir(exist_ok=True)
    for f in (storage / "reports").glob("*.json"):
        shutil.copy2(f, pub_data / "reports" / f.name)
    # Sort feed
    fp = pub_data / "feed.json"
    feed = json.loads(fp.read_text())
    feed.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    fp.write_text(json.dumps(feed, indent=2, ensure_ascii=False, default=str))

    print(f"  Published + synced locally. Feed: {len(feed)} items")

    # --- Sync to Mirror API ---
    mirror_url = os.environ.get("VOLPRED_MIRROR_URL", "https://mirror-api.zeabur.app")
    mirror_token = os.environ.get("RESEARCH_MIRROR_TOKEN", "")
    if mirror_url and mirror_token:
        import urllib.request
        # Memory files → PUT /api/mirror/memory/{filename}
        # Mirror API only supports these 4 files (see /api/mirror/manifest)
        memory_files = [
            "memory/knowledge.json",
            "memory/thinking_journal.json",
            "memory/research_log.json",
            "memory/experiments.json",
        ]
        mirror_ok = 0
        for sf in memory_files:
            local = storage / sf
            if not local.exists():
                continue
            try:
                payload = local.read_bytes()
                filename = sf.split("/")[-1]  # e.g. "knowledge.json"
                req = urllib.request.Request(
                    f"{mirror_url}/api/mirror/memory/{filename}",
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "x-research-mirror-token": mirror_token,
                    },
                    method="PUT",
                )
                urllib.request.urlopen(req, timeout=30)
                mirror_ok += 1
            except Exception as e:
                print(f"  Mirror sync {sf}: {e}")
        print(f"  Mirror API: {mirror_ok}/{len(memory_files)} synced")
    elif mirror_url and not mirror_token:
        print("  Mirror API: RESEARCH_MIRROR_TOKEN not set, skipping")
    else:
        print("  Mirror API URL not configured")

    # --- Sync to Supabase (v2 website) ---
    try:
        from article_backups import ensure_local_article_backups
        from supabase_sync import sync_article, sync_risk_forecast, sync_strategy_signal, sync_paper_trade
        backup_audit = ensure_local_article_backups("storage", repair=True)
        if backup_audit.get("created_count"):
            print(f"  Local article backups: repaired {backup_audit['created_count']} missing report files")
        if backup_audit.get("bodyless_ids"):
            print(f"  Local article backups: WARNING {len(backup_audit['bodyless_ids'])} article(s) still missing body content")
        # Heartbeat is in collect_us_data.py (runs 30min earlier at 05:30)
        # Retry any failed syncs from publish_milestone
        failed_path = Path("storage/.failed_supabase_syncs.json")
        if failed_path.exists():
            failed_ids = json.loads(failed_path.read_text())
            if failed_ids:
                feed_all = json.loads(Path("storage/reports/feed.json").read_text())
                feed_map = {item['id']: item for item in feed_all}
                retried = 0
                for fid in failed_ids:
                    if fid in feed_map:
                        report_path = Path(f"storage/reports/{fid}.json")
                        article = feed_map[fid]
                        if report_path.exists():
                            report = json.loads(report_path.read_text())
                            if report.get('description'):
                                article['content'] = report['description']
                        if sync_article(article):
                            retried += 1
                if retried:
                    print(f"  Supabase: retried {retried} failed syncs")
                failed_path.unlink()
        # Sync the daily signal article
        if feed and feed[0]:
            sync_article(feed[0])
            print("  Supabase: article synced")
        # Sync risk forecast
        rf_path = storage / "risk_forecast.json"
        if rf_path.exists():
            sync_risk_forecast(json.loads(rf_path.read_text()))
            print("  Supabase: risk_forecast synced")
        # Sync ALL 7 strategy signals
        # Names MUST match strategyNames in portfolio page.tsx
        # Sync all strategies to Supabase using STRATEGY_REGISTRY as single source of truth
        synced_count = 0
        for sid, w_info in strat_list:
            display_name, is_active, display_order = STRATEGY_REGISTRY.get(sid, (sid, True, 99))
            sig_weights = {a: round(w * 100) for a, w in w_info.items()}
            sync_strategy_signal(display_name, sig_weights,
                                 vix_level=round(vix_level, 2) if vix_level else None,
                                 sigma_ann=sigma_gjr_ann,
                                 display_order=display_order,
                                 is_active=is_active,
                                 strategy_key=sid)
            synced_count += 1
        print(f"  Supabase: {synced_count} strategy signals synced")
        # Sync paper trades (last 30 entries per strategy, covers backfill + today)
        # Merge _market_daily into entry for Supabase (frontend expects market data in entry)
        market = pt.get("_market_daily", {})
        pt_synced = 0
        for strat_id, _ in strat_list:
            if strat_id in pt and pt[strat_id]["entries"]:
                recent_entries = pt[strat_id]["entries"][-30:]
                for entry in recent_entries:
                    trade_date = entry.get("trade_date") or entry.get("data_date") or entry.get("date", "")
                    if trade_date:
                        # Merge market data for backward compatibility with frontend
                        enriched = {**market.get(trade_date, {}), **entry}
                        sync_paper_trade(strat_id, enriched, trade_date)
                        pt_synced += 1
        print(f"  Supabase: {pt_synced} paper trades synced (last 30d × {len(strat_list)} strategies)")
    except Exception as e:
        print(f"  Supabase sync skipped: {e}")

    # --- Generate risk forecast ---
    try:
        from risk_forecast import main as generate_risk_forecast
        print("\n--- Generating risk forecast ---")
        generate_risk_forecast()
        print("  ✓ risk_forecast.json updated")
    except Exception as e:
        print(f"  Risk forecast skipped: {e}")

    # --- Recalculate strategy metrics (Sharpe/MDD/etc.) ---
    try:
        from recalc_metrics import recalc_all
        print("\n--- Recalculating strategy metrics ---")
        recalc_all()
    except Exception as e:
        print(f"  Metrics recalc skipped: {e}")

    print(f"\n✓ Done!")


if __name__ == "__main__":
    main()
