#!/usr/bin/env python3
"""Generate risk forecast data for the web dashboard.

Produces next-day, next-week, next-month volatility and VaR forecasts
using GJR-GARCH(1,1) w=2000 + Student-t(df=5).

Run: uv run python scripts/risk_forecast.py
Output: storage/risk_forecast.json
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from arch import arch_model
from arch.univariate.distribution import SkewStudent
from scipy import stats

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from volpred.data.manager import DataManager


def get_regime(sigma_ann: float) -> dict:
    """Classify volatility regime."""
    if sigma_ann < 0.12:
        return {"level": "low", "label": "低波動", "color": "emerald"}
    elif sigma_ann < 0.20:
        return {"level": "normal", "label": "正常", "color": "gray"}
    elif sigma_ann < 0.30:
        return {"level": "high", "label": "高波動", "color": "amber"}
    else:
        return {"level": "extreme", "label": "極端", "color": "red"}


def cornish_fisher_quantile(alpha: float, skew: float, excess_kurt: float) -> float:
    """Cornish-Fisher expansion for VaR quantile.

    z_cf = z + (z²-1)*S/6 + (z³-3z)*K/24 - (2z³-5z)*S²/36
    Uses actual residual skewness/kurtosis — asset-specific and time-varying.
    Passes Kupiec test for 5/5 assets at 1% (Phase O, 2026-03-16).
    """
    z = stats.norm.ppf(alpha)
    z_cf = (z
            + (z**2 - 1) * skew / 6
            + (z**3 - 3 * z) * excess_kurt / 24
            - (2 * z**3 - 5 * z) * skew**2 / 36)
    return z_cf


def compute_var_es(sigma: float, horizon: int = 1, df: float = 5.0,
                   confidence: float = 0.01,
                   sigma_unc: float | None = None,
                   persistence: float = 0.95,
                   skew: float | None = None,
                   excess_kurt: float | None = None,
                   skewt_eta: float | None = None,
                   skewt_lambda: float | None = None) -> dict:
    """Compute VaR and ES for given horizon.

    Methods: Student-t(fixed df), CF-VaR (Cornish-Fisher), Skewed-t (MLE fitted).
    Skewed-t is the best method (6/6 assets pass Kupiec, Phase O8).

    For h > 1, uses proper GARCH multi-step formula:
    σ²_h = h×σ²_∞ + (σ²_1 - σ²_∞) × (1-ρ^h)/(1-ρ)
    """
    scale = np.sqrt((df - 2) / df)
    q = stats.t.ppf(confidence, df)  # Raw Student-t quantile (negative)

    # Multi-step variance
    if horizon == 1 or sigma_unc is None:
        sigma_h = sigma * np.sqrt(horizon)
    else:
        sigma2_1 = sigma ** 2
        sigma2_unc = sigma_unc ** 2
        if persistence < 0.999:
            var_h = horizon * sigma2_unc + (sigma2_1 - sigma2_unc) * (1 - persistence ** horizon) / (1 - persistence)
        else:
            var_h = sigma2_1 * horizon
        sigma_h = np.sqrt(max(var_h, 0))

    # Student-t VaR (standardized)
    var_pct = -q * scale * sigma_h * 100

    # ES for Student-t (standardized)
    f_q = stats.t.pdf(q, df)
    es_raw = (f_q / confidence) * ((df + q ** 2) / (df - 1))
    es_pct = es_raw * scale * sigma_h * 100

    result = {
        "var_pct": round(var_pct, 2),
        "es_pct": round(es_pct, 2),
        "var_dollar": round(var_pct * 10000, 0),  # per $1M
        "es_dollar": round(es_pct * 10000, 0),
    }

    # CF-VaR (if residual stats provided)
    if skew is not None and excess_kurt is not None:
        z_cf = cornish_fisher_quantile(confidence, skew, excess_kurt)
        cf_var_pct = -z_cf * sigma_h * 100
        # CF-ES approximation: integrate CF density beyond VaR
        # Use simple scaling from Student-t ES/VaR ratio
        cf_es_pct = cf_var_pct * (es_pct / var_pct) if var_pct > 0 else cf_var_pct * 1.3
        result["cf_var_pct"] = round(cf_var_pct, 2)
        result["cf_es_pct"] = round(cf_es_pct, 2)
        result["cf_var_dollar"] = round(cf_var_pct * 10000, 0)
        result["cf_es_dollar"] = round(cf_es_pct * 10000, 0)

    # Skewed-t VaR (best method: 6/6 Kupiec pass, Phase O8)
    if skewt_eta is not None and skewt_lambda is not None:
        skewt_dist = SkewStudent()
        q_skewt = skewt_dist.ppf(confidence, parameters=np.array([skewt_eta, skewt_lambda]))
        skewt_var_pct = -q_skewt * sigma_h * 100
        skewt_es_pct = skewt_var_pct * (es_pct / var_pct) if var_pct > 0 else skewt_var_pct * 1.3
        result["skewt_var_pct"] = round(skewt_var_pct, 2)
        result["skewt_es_pct"] = round(skewt_es_pct, 2)
        result["skewt_var_dollar"] = round(skewt_var_pct * 10000, 0)
        result["skewt_es_dollar"] = round(skewt_es_pct * 10000, 0)

    return result


def compute_basel_ytd(returns: np.ndarray, sigmas: np.ndarray,
                      df: float = 5.0) -> dict:
    """Compute Basel III zone for current year."""
    scale = np.sqrt((df - 2) / df)
    z = -stats.t.ppf(0.01, df) * scale
    var_thresholds = z * sigmas
    violations = (returns < -var_thresholds).astype(int)
    n_viol = int(violations.sum())
    n_days = len(returns)
    if n_viol <= 4:
        zone = "GREEN"
    elif n_viol <= 9:
        zone = "YELLOW"
    else:
        zone = "RED"
    return {
        "year": datetime.now().year,
        "violations": n_viol,
        "days": n_days,
        "zone": zone,
        "rate": round(n_viol / max(n_days, 1) * 100, 1),
    }


def main():
    dm = DataManager()
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"=== Risk Forecast: {today} ===")

    assets_config = {
        "SPY": {
            "window": 2000, "name": "S&P 500 ETF",
            "model_note": "GJR-GARCH 是 MCS superior (DM p<0.001)，γ=0.20 顯著不對稱",
            "articles": [
                {"id": "mile_777940c3", "title": "Gamma Taxonomy 完美預測 VT Alpha 機制：17 資產跨資產驗證"},
            ],
        },
        "QQQ": {
            "window": 2000, "name": "Nasdaq 100 ETF",
            "model_note": "高 γ 資產（γ>0.10），GJR 優於 GARCH",
            "articles": [
                {"id": "mile_ab209264", "title": "GJR-GARCH 的隱藏優勢：預測天數越長，優勢越大"},
            ],
        },
        "GLD": {
            "window": 2000, "name": "Gold ETF",
            "model_note": "γ<0.10（反向槓桿），GARCH 與 GJR 無顯著差異",
            "articles": [
                {"id": "mile_f7b710f3", "title": "2026 Q1 即時驗證：50/50 SPY/GLD 在 Hormuz 危機中的完美對沖"},
            ],
        },
        "TLT": {
            "window": 2000, "name": "20+ Year Treasury ETF",
            "model_note": "γ<0.10，債券波動率受利率政策驅動",
            "articles": [
                {"id": "mile_e073501e", "title": "TLT 首測：模型過度保守，利率轉折期的 Regime Change"},
            ],
        },
        "0050.TW": {
            "window": 2000, "name": "元大台灣50 ETF",
            "model_note": "台灣波動率放大 4.6x（vs US 2.8x），VIX proxy 有效",
            "articles": [
                {"id": "mile_66c30b90", "title": "12/VIX 策略跨市場驗證：台灣 0050.TW 的 8.63/VIX 調整公式"},
            ],
        },
        "EEM": {
            "window": 2000, "name": "新興市場 ETF",
            "model_note": "高 γ 資產，GJR-GARCH 適用",
            "articles": [],
        },
    }

    forecasts = {}
    for ticker, cfg in assets_config.items():
        try:
            data = dm.get_model_data(ticker, "2016-01-01", "2026-12-31")
            if len(data) < cfg["window"] + 10:
                print(f"  {ticker}: insufficient data ({len(data)} < {cfg['window']})")
                continue

            close = float(data.iloc[-1]["close"])
            last_date = str(data.index[-1].date())
            returns_pct = data["returns"].dropna() * 100
            window = cfg["window"]

            # Fit GJR-GARCH
            train = returns_pct.iloc[-window:]
            am = arch_model(train, vol="GARCH", p=1, o=1, q=1,
                           dist="normal", mean="Zero", rescale=False)
            res = am.fit(disp="off", show_warning=False)

            # 1-step ahead forecast
            fcast = res.forecast(horizon=1)
            sigma_daily = float(np.sqrt(fcast.variance.iloc[-1, 0]) / 100)
            sigma_ann = sigma_daily * np.sqrt(252)

            # Compute unconditional sigma for proper multi-step formula
            alpha_p = res.params.get("alpha[1]", 0)
            gamma_p = res.params.get("gamma[1]", 0)
            beta_p = res.params.get("beta[1]", 0)
            omega_p = res.params.get("omega", 0)
            pers = alpha_p + gamma_p / 2 + beta_p
            sigma_unc = float(np.sqrt(omega_p / (1 - pers)) / 100) if pers < 0.999 else sigma_daily

            # Standardized residual stats for CF-VaR
            std_resid = res.std_resid.dropna()
            resid_skew = float(stats.skew(std_resid))
            resid_kurt = float(stats.kurtosis(std_resid))  # excess kurtosis

            # Fit Skewed-t model for best VaR (6/6 Kupiec, Phase O8)
            skewt_eta, skewt_lam = None, None
            try:
                am_skewt = arch_model(train, vol="GARCH", p=1, o=1, q=1,
                                      dist="skewt", mean="Zero", rescale=False)
                res_skewt = am_skewt.fit(disp="off", show_warning=False)
                skewt_eta = float(res_skewt.params["eta"])
                skewt_lam = float(res_skewt.params["lambda"])
            except Exception:
                pass  # Fallback: skewt fields won't be in output

            # Multi-horizon VaR/ES (Student-t + CF-VaR + Skewed-t)
            daily = compute_var_es(sigma_daily, horizon=1,
                                   skew=resid_skew, excess_kurt=resid_kurt,
                                   skewt_eta=skewt_eta, skewt_lambda=skewt_lam)
            weekly = compute_var_es(sigma_daily, horizon=5,
                                   sigma_unc=sigma_unc, persistence=pers,
                                   skew=resid_skew, excess_kurt=resid_kurt,
                                   skewt_eta=skewt_eta, skewt_lambda=skewt_lam)
            monthly = compute_var_es(sigma_daily, horizon=22,
                                    sigma_unc=sigma_unc, persistence=pers,
                                    skew=resid_skew, excess_kurt=resid_kurt,
                                    skewt_eta=skewt_eta, skewt_lambda=skewt_lam)

            # Regime
            regime = get_regime(sigma_ann)

            # Historical sigma for chart (last 60 trading days)
            sigma_history = []
            raw_returns = data["returns"].dropna()
            for i in range(min(60, len(raw_returns) - window)):
                idx = len(raw_returns) - 60 + i
                if idx < window:
                    continue
                t = returns_pct.iloc[idx - window:idx]
                try:
                    am_h = arch_model(t, vol="GARCH", p=1, o=1, q=1,
                                     dist="normal", mean="Zero", rescale=False)
                    res_h = am_h.fit(disp="off", show_warning=False)
                    s = float(np.sqrt(res_h.forecast(horizon=1).variance.iloc[-1, 0]) / 100)
                    d = str(raw_returns.index[idx].date())
                    sigma_history.append({"date": d, "sigma_ann": round(s * np.sqrt(252) * 100, 1)})
                except Exception:
                    continue

            # Basel III YTD
            year_start = f"{datetime.now().year}-01-01"
            ytd_mask = data.index >= year_start
            if ytd_mask.sum() > 0:
                ytd_returns = data.loc[ytd_mask, "returns"].dropna().values
                # Need sigma forecasts for YTD — approximate with rolling
                ytd_sigmas = []
                ytd_dates = data.index[ytd_mask]
                for dt in ytd_dates:
                    idx = data.index.get_loc(dt)
                    if idx < window:
                        continue
                    t = returns_pct.iloc[idx - window:idx]
                    try:
                        am_y = arch_model(t, vol="GARCH", p=1, o=1, q=1,
                                         dist="normal", mean="Zero", rescale=False)
                        res_y = am_y.fit(disp="off", show_warning=False)
                        s = float(np.sqrt(res_y.forecast(horizon=1).variance.iloc[-1, 0]) / 100)
                        ytd_sigmas.append(s)
                    except Exception:
                        ytd_sigmas.append(sigma_daily)  # fallback
                if ytd_sigmas:
                    ytd_sigmas_arr = np.array(ytd_sigmas[:len(ytd_returns)])
                    ytd_returns_arr = ytd_returns[:len(ytd_sigmas_arr)]
                    basel = compute_basel_ytd(ytd_returns_arr, ytd_sigmas_arr)
                else:
                    basel = {"year": datetime.now().year, "violations": 0, "days": 0, "zone": "GREEN", "rate": 0}
            else:
                basel = {"year": datetime.now().year, "violations": 0, "days": 0, "zone": "GREEN", "rate": 0}

            # 5-year average sigma for comparison
            hist_data = dm.get_model_data(ticker, "2021-01-01", "2026-12-31")
            hist_sigma_ann = float(hist_data["returns"].dropna().std() * np.sqrt(252))
            sigma_vs_avg = (sigma_ann - hist_sigma_ann) / hist_sigma_ann

            # Alerts
            alerts = []
            last_return = float(data.iloc[-1]["returns"])
            if abs(last_return) > 3 * sigma_daily:
                alerts.append({
                    "type": "jump",
                    "message": f"昨日報酬 {last_return*100:+.2f}% 超過 3σ（{sigma_daily*100:.2f}%）",
                    "severity": "high"
                })
            if len(data) >= 2:
                gap = float(data.iloc[-1]["open"]) / float(data.iloc[-2]["close"]) - 1
                if abs(gap) > 0.015:
                    alerts.append({
                        "type": "overnight_gap",
                        "message": f"隔夜跳空 {gap*100:+.2f}%（>1.5% 門檻）",
                        "severity": "high"
                    })
            if regime["level"] in ("high", "extreme"):
                alerts.append({
                    "type": "regime",
                    "message": f"當前處於{regime['label']}環境（{sigma_ann*100:.1f}%）",
                    "severity": "medium" if regime["level"] == "high" else "high"
                })

            # VIX/GARCH ratio alert (94% of VaR violations occur when ratio > 1.5)
            if ticker == "SPY":
                try:
                    vix_data = dm.get_model_data("^VIX", "2025-01-01", "2026-12-31")
                    if len(vix_data) > 0:
                        vix_level = float(vix_data.iloc[-1]["close"])
                        vix_garch_ratio = vix_level / (sigma_ann * 100)
                        if vix_garch_ratio > 1.5:
                            alerts.append({
                                "type": "vix_garch_gap",
                                "message": f"VIX/GARCH ratio {vix_garch_ratio:.2f}（>1.5，VaR 可能不可靠）",
                                "severity": "high"
                            })
                except Exception:
                    pass

            # GARCH params
            params = {k: round(float(v), 6) for k, v in res.params.items()}

            forecasts[ticker] = {
                "name": cfg["name"],
                "price": round(close, 2),
                "last_date": last_date,
                "sigma_daily_pct": round(sigma_daily * 100, 2),
                "sigma_ann_pct": round(sigma_ann * 100, 1),
                "regime": regime,
                "forecasts": {
                    "daily": daily,
                    "weekly": weekly,
                    "monthly": monthly,
                },
                "residual_stats": {
                    "skewness": round(resid_skew, 4),
                    "excess_kurtosis": round(resid_kurt, 4),
                    "cf_1pct_quantile": round(cornish_fisher_quantile(0.01, resid_skew, resid_kurt), 4),
                    "skewt_eta": round(skewt_eta, 2) if skewt_eta else None,
                    "skewt_lambda": round(skewt_lam, 4) if skewt_lam else None,
                },
                "basel_zone": basel,
                "sigma_history": sigma_history,
                "sigma_vs_5y_avg": round(sigma_vs_avg * 100, 1),
                "hist_avg_sigma_ann": round(hist_sigma_ann * 100, 1),
                "alerts": alerts,
                "model": f"GJR-GARCH(1,1) w={window}",
                "params": params,
                "model_note": cfg.get("model_note", ""),
                "articles": cfg.get("articles", []),
            }

            skewt_daily = daily.get("skewt_var_pct", daily["var_pct"])
            cf_daily = daily.get("cf_var_pct", daily["var_pct"])
            print(f"  {ticker}: σ_ann={sigma_ann*100:.1f}% | regime={regime['label']} | "
                  f"VaR(skewt) 1d={skewt_daily:.2f}% | VaR(CF) 1d={cf_daily:.2f}% | VaR(t) 1d={daily['var_pct']:.2f}% | "
                  f"Basel {basel['zone']} ({basel['violations']}/{basel['days']})")

        except Exception as e:
            print(f"  {ticker}: ERROR - {e}")

    # Save
    output = {
        "generated_at": datetime.now().isoformat(),
        "model": "GJR-GARCH(1,1) + Skewed-t(MLE) + CF-VaR + Student-t(df=5)",
        "assets": forecasts,
    }
    output_path = Path("storage/risk_forecast.json")
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    print(f"\nSaved to {output_path}")


if __name__ == "__main__":
    main()
