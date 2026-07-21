"""AI capex -> debt financing: does credit-market risk show up in tech vol?

Evidence builder for trending_repost 2026-07-22.
All numbers trace to yfinance (ticker + window) or FRED (series id).
"""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf

OUT = Path("/tmp/capex_credit_evidence.json")
START = "2015-01-01"
FRED_KEY = os.environ["FRED_API_KEY"]

TECH = ["META", "MSFT", "GOOGL", "AMZN"]
ETFS = ["SMH", "XLK", "HYG", "LQD", "SPY"]


def fred(series_id, start=START):
    r = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={
            "series_id": series_id,
            "api_key": FRED_KEY,
            "file_type": "json",
            "observation_start": start,
        },
        timeout=60,
    )
    r.raise_for_status()
    obs = r.json()["observations"]
    s = pd.Series(
        {pd.Timestamp(o["date"]): (np.nan if o["value"] == "." else float(o["value"])) for o in obs},
        name=series_id,
    )
    return s.dropna()


def fisher_z_test(r1, n1, r2, n2):
    """Two-sample test for difference of correlations. Returns (z, p)."""
    z1, z2 = np.arctanh(r1), np.arctanh(r2)
    se = np.sqrt(1.0 / (n1 - 3) + 1.0 / (n2 - 3))
    z = (z2 - z1) / se
    from math import erfc

    p = erfc(abs(z) / np.sqrt(2))
    return float(z), float(p)


def main():
    ev = {"as_of": None, "sources": {}}

    # ---------- 1. Prices ----------
    px = yf.download(TECH + ETFS, start=START, auto_adjust=True, progress=False)["Close"]
    px = px.dropna(how="all")
    px.index = pd.DatetimeIndex(px.index).astype("datetime64[ns]")
    ret = np.log(px).diff()
    as_of = str(px.index[-1].date())
    ev["as_of"] = as_of
    ev["sources"]["prices"] = f"yfinance Close (auto_adjust), {START}..{as_of}"

    # ---------- 2. Credit spreads ----------
    # NOTE: FRED's ICE BofA OAS series (BAMLC0A0CM / BAMLH0A0HYM2) are licence-capped
    # to ~3 years via the API, so the long-history test uses BAA10Y instead.
    ig = fred("BAA10Y")        # Moody's Baa yield minus 10Y Treasury, full history
    oas_ig = fred("BAMLC0A0CM")
    oas_hy = fred("BAMLH0A0HYM2")
    ev["sources"]["credit"] = (
        "FRED BAA10Y (Baa - 10Y Treasury, primary, 2015+); "
        "FRED BAMLC0A0CM / BAMLH0A0HYM2 (IG/HY OAS, API-capped to 2023-07-24+)"
    )
    ev["credit_levels"] = {
        "baa10y_latest": {"date": str(ig.index[-1].date()), "value": float(ig.iloc[-1])},
        "baa10y_median_2015_2026": float(ig.median()),
        "baa10y_pct_rank_latest": float((ig <= ig.iloc[-1]).mean()),
        "ig_oas_latest": {"date": str(oas_ig.index[-1].date()), "value": float(oas_ig.iloc[-1])},
        "ig_oas_window": [str(oas_ig.index[0].date()), str(oas_ig.index[-1].date())],
        "ig_oas_pct_rank_in_window": float((oas_ig <= oas_ig.iloc[-1]).mean()),
        "hy_oas_latest": {"date": str(oas_hy.index[-1].date()), "value": float(oas_hy.iloc[-1])},
        "hy_oas_window": [str(oas_hy.index[0].date()), str(oas_hy.index[-1].date())],
        "hy_oas_pct_rank_in_window": float((oas_hy <= oas_hy.iloc[-1]).mean()),
    }
    hy = oas_hy

    # ---------- 3. Mega-cap tech realized vol (21d, annualized) ----------
    rv = ret[TECH].rolling(21).std() * np.sqrt(252) * 100
    tech_rv = rv.mean(axis=1).dropna()
    ev["tech_rv"] = {
        "definition": "equal-weight mean of 21d annualized realized vol (%) of META/MSFT/GOOGL/AMZN",
        "latest": {"date": str(tech_rv.index[-1].date()), "value": float(tech_rv.iloc[-1])},
        "median_full": float(tech_rv.median()),
    }

    # ---------- 4. Core test: d(tech RV) vs d(IG OAS) correlation, early vs recent ----------
    d_rv = tech_rv.diff()
    d_ig = ig.reindex(tech_rv.index).ffill().diff()
    joint = pd.concat([d_rv.rename("d_rv"), d_ig.rename("d_ig")], axis=1).dropna()

    split = pd.Timestamp("2023-07-01")  # pre/post the AI-capex build-out
    early = joint[joint.index < split]
    recent = joint[joint.index >= split]
    r_e = float(early["d_rv"].corr(early["d_ig"]))
    r_r = float(recent["d_rv"].corr(recent["d_ig"]))
    z, p = fisher_z_test(r_e, len(early), r_r, len(recent))
    ev["corr_test_rv_vs_ig"] = {
        "window_early": [str(early.index[0].date()), str(early.index[-1].date())],
        "n_early": int(len(early)), "r_early": r_e,
        "window_recent": [str(recent.index[0].date()), str(recent.index[-1].date())],
        "n_recent": int(len(recent)), "r_recent": r_r,
        "fisher_z": z, "p_value": p,
        "significant_5pct": bool(p < 0.05),
    }

    # ---------- 5. SMH vs credit ETFs rolling correlation ----------
    roll = {}
    for credit in ["HYG", "LQD"]:
        rc = ret["SMH"].rolling(120).corr(ret[credit]).dropna()
        rc_e = rc[rc.index < split]
        rc_r = rc[rc.index >= split]
        # correlation of the underlying returns, per period (for the z-test)
        sub_e = ret.loc[ret.index < split, ["SMH", credit]].dropna()
        sub_r = ret.loc[ret.index >= split, ["SMH", credit]].dropna()
        pe = float(sub_e["SMH"].corr(sub_e[credit]))
        pr = float(sub_r["SMH"].corr(sub_r[credit]))
        zz, pp = fisher_z_test(pe, len(sub_e), pr, len(sub_r))
        roll[credit] = {
            "rolling120_latest": {"date": str(rc.index[-1].date()), "value": float(rc.iloc[-1])},
            "rolling120_mean_early": float(rc_e.mean()),
            "rolling120_mean_recent": float(rc_r.mean()),
            "fullperiod_corr_early": pe, "n_early": int(len(sub_e)),
            "fullperiod_corr_recent": pr, "n_recent": int(len(sub_r)),
            "fisher_z": zz, "p_value": pp, "significant_5pct": bool(pp < 0.05),
        }
        rc.to_frame("corr").to_csv(f"/tmp/roll_SMH_{credit}.csv")
    ev["smh_credit_corr"] = roll

    # ---------- 6. Capex & debt from filings (yfinance statement data) ----------
    fin = {}
    for t in TECH:
        tk = yf.Ticker(t)
        try:
            cf = tk.quarterly_cashflow
            bs = tk.quarterly_balance_sheet
            capex_row = next((r for r in cf.index if "Capital Expenditure" == r), None)
            ocf_row = next((r for r in cf.index if "Operating Cash Flow" == r), None)
            debt_row = next((r for r in bs.index if r == "Total Debt"), None)
            issu_row = next((r for r in cf.index if "Issuance Of Debt" in r), None)
            rec = {}
            if capex_row is not None:
                ser = cf.loc[capex_row].dropna()
                rec["capex_by_quarter"] = {str(k.date()): float(v) for k, v in ser.items()}
            if ocf_row is not None:
                ser = cf.loc[ocf_row].dropna()
                rec["ocf_by_quarter"] = {str(k.date()): float(v) for k, v in ser.items()}
            if debt_row is not None:
                ser = bs.loc[debt_row].dropna()
                rec["total_debt_by_quarter"] = {str(k.date()): float(v) for k, v in ser.items()}
            if issu_row is not None:
                ser = cf.loc[issu_row].dropna()
                rec["debt_issuance_by_quarter"] = {str(k.date()): float(v) for k, v in ser.items()}
            fin[t] = rec
        except Exception as e:  # noqa: BLE001
            fin[t] = {"error": str(e)}
    ev["fundamentals"] = fin
    ev["sources"]["fundamentals"] = "yfinance quarterly_cashflow / quarterly_balance_sheet (from SEC 10-Q/10-K)"

    # ---------- 6b. Aggregate the four names ----------
    def agg(field):
        frames = {t: pd.Series(fin[t].get(field, {})) for t in TECH}
        df = pd.DataFrame(frames)
        df.index = pd.to_datetime(df.index)
        return df.sort_index()

    capex = agg("capex_by_quarter").abs()
    ocf = agg("ocf_by_quarter")
    debt = agg("total_debt_by_quarter")
    common = capex.dropna().index.intersection(ocf.dropna().index)
    capex, ocf = capex.loc[common], ocf.loc[common]

    q_tbl = pd.DataFrame({
        "capex_sum_bn": capex.sum(axis=1) / 1e9,
        "ocf_sum_bn": ocf.sum(axis=1) / 1e9,
    })
    q_tbl["capex_over_ocf"] = q_tbl["capex_sum_bn"] / q_tbl["ocf_sum_bn"]
    q_tbl["fcf_bn"] = q_tbl["ocf_sum_bn"] - q_tbl["capex_sum_bn"]
    debt_sum = (debt.sum(axis=1) / 1e9).dropna()

    first_q, last_q = q_tbl.index[0], q_tbl.index[-1]
    ev["capex_aggregate"] = {
        "companies": TECH,
        "quarters": {str(d.date()): {k: float(v) for k, v in row.items()} for d, row in q_tbl.iterrows()},
        "total_debt_bn_by_quarter": {str(d.date()): float(v) for d, v in debt_sum.items()},
        "yoy_single_quarter": {
            "window": [str(first_q.date()), str(last_q.date())],
            "capex_bn_from": float(q_tbl["capex_sum_bn"].iloc[0]),
            "capex_bn_to": float(q_tbl["capex_sum_bn"].iloc[-1]),
            "capex_growth_pct": float(q_tbl["capex_sum_bn"].iloc[-1] / q_tbl["capex_sum_bn"].iloc[0] - 1) * 100,
            "capex_over_ocf_from": float(q_tbl["capex_over_ocf"].iloc[0]),
            "capex_over_ocf_to": float(q_tbl["capex_over_ocf"].iloc[-1]),
            "total_debt_bn_from": float(debt_sum.iloc[0]),
            "total_debt_bn_to": float(debt_sum.iloc[-1]),
            "total_debt_added_bn": float(debt_sum.iloc[-1] - debt_sum.iloc[0]),
            "total_debt_growth_pct": float(debt_sum.iloc[-1] / debt_sum.iloc[0] - 1) * 100,
        },
        "ttm_latest_4q": {
            "window": [str(q_tbl.index[-4].date()), str(last_q.date())],
            "capex_bn": float(q_tbl["capex_sum_bn"].iloc[-4:].sum()),
            "ocf_bn": float(q_tbl["ocf_sum_bn"].iloc[-4:].sum()),
            "capex_over_ocf": float(q_tbl["capex_sum_bn"].iloc[-4:].sum() / q_tbl["ocf_sum_bn"].iloc[-4:].sum()),
        },
    }
    q_tbl.to_csv("/tmp/capex_quarters.csv")
    debt_sum.to_frame("total_debt_bn").to_csv("/tmp/total_debt.csv")

    # ---------- 6c. Cross-section: leverage dispersion vs equity vol ----------
    per = {}
    for t in TECH:
        cx = (capex[t] / 1e9).dropna()
        oc = (ocf[t] / 1e9).dropna()
        db = (debt[t] / 1e9).dropna()
        ttm_ocf = float(oc.iloc[-4:].sum())
        ttm_cx = float(cx.iloc[-4:].sum())
        per[t] = {
            "debt_bn_first": float(db.iloc[0]), "debt_bn_last": float(db.iloc[-1]),
            "debt_growth_pct": float(db.iloc[-1] / db.iloc[0] - 1) * 100,
            "capex_bn_first": float(cx.iloc[0]), "capex_bn_last": float(cx.iloc[-1]),
            "capex_growth_pct": float(cx.iloc[-1] / cx.iloc[0] - 1) * 100,
            "ttm_capex_bn": ttm_cx, "ttm_ocf_bn": ttm_ocf,
            "ttm_capex_over_ocf_pct": ttm_cx / ttm_ocf * 100,
            "debt_over_ttm_ocf": float(db.iloc[-1]) / ttm_ocf,
            "rv21d_latest": float(rv[t].iloc[-1]),
            "rv_mean_past_1y": float(rv[t].loc["2025-07-22":].mean()),
            "rv_median_full": float(rv[t].median()),
        }
    ev["cross_section"] = {
        "note": "n=4; reported descriptively, too few names for a correlation test",
        "balance_sheet_window": [str(first_q.date()), str(last_q.date())],
        "ttm_window": [str(q_tbl.index[-4].date()), str(last_q.date())],
        "rv_as_of": as_of,
        "by_company": per,
    }
    pd.DataFrame(per).T.to_csv("/tmp/per_company.csv")

    # persist series for charting
    tech_rv.to_frame("tech_rv").to_csv("/tmp/tech_rv.csv")
    ig.to_frame("ig_oas").to_csv("/tmp/ig_oas.csv")
    hy.to_frame("hy_oas").to_csv("/tmp/hy_oas.csv")

    OUT.write_text(json.dumps(ev, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in ev.items() if k != "fundamentals"}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
