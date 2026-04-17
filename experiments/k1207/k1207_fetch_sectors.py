"""K1207 — Fetch GICS sector classifications for K1171 N=13 × stocks pool.

Source priority:
  1. yfinance Ticker(...).info['sector']  (Yahoo 11-sector scheme; mapped to GICS)
  2. Hand-coded fallback from company disclosure (source='HAND')

Output: k1207_stock_sectors.csv with columns
  market, ticker, yahoo_sector, yahoo_industry, gics_sector, source

Random seed: 42
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

np.random.seed(42)

ROOT = Path(__file__).resolve().parent
K1171_TABLE = Path(
    "/Users/yhlai0911/Desktop/volpred-research/experiments/k1171/k1171_per_stock_table.csv"
)

# Yahoo → GICS 11 sector mapping (Yahoo uses their own labels; GICS is the
# canonical industry taxonomy).
YAHOO_TO_GICS = {
    "Technology": "Information Technology",
    "Financial Services": "Financials",
    "Healthcare": "Health Care",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Industrials": "Industrials",
    "Energy": "Energy",
    "Basic Materials": "Materials",
    "Communication Services": "Communication Services",
    "Real Estate": "Real Estate",
    "Utilities": "Utilities",
}

# Hand-coded fallback map: (market, ticker) -> gics_sector
# Based on each company's public classification (Bloomberg / company website /
# MSCI GICS disclosure). Use ONLY when yfinance returns no sector or rate-
# limits. Each entry cites the source rationale inline.
HAND_CODED: dict[tuple[str, str], tuple[str, str]] = {
    # (market, ticker) -> (gics_sector, rationale_tag)
    # Pre-filled common Taiwan ID/KR/JP/TW cases where yfinance sometimes
    # drops the sector field. Will be used only if yfinance lookup fails.
    ("TW", "1210.TW"): ("Consumer Staples", "HAND_uni-president"),
    ("TW", "1215.TW"): ("Consumer Staples", "HAND_charoen-pokphand"),
    ("TW", "1301.TW"): ("Materials", "HAND_formosa-plastics"),
    ("TW", "1303.TW"): ("Materials", "HAND_nan-ya-plastics"),
    ("TW", "1326.TW"): ("Materials", "HAND_formosa-chem"),
    ("TW", "2002.TW"): ("Materials", "HAND_china-steel"),
    ("TW", "2027.TW"): ("Materials", "HAND_ta-ya-steel"),
    ("TW", "2303.TW"): ("Information Technology", "HAND_umc"),
    ("TW", "2317.TW"): ("Information Technology", "HAND_hon-hai"),
    ("TW", "2330.TW"): ("Information Technology", "HAND_tsmc"),
    ("TW", "2347.TW"): ("Information Technology", "HAND_synnex-tech"),
    ("TW", "2379.TW"): ("Information Technology", "HAND_realtek"),
    ("TW", "2382.TW"): ("Information Technology", "HAND_quanta"),
    ("TW", "2454.TW"): ("Information Technology", "HAND_mediatek"),
    ("TW", "2603.TW"): ("Industrials", "HAND_evergreen-marine"),
    ("TW", "2609.TW"): ("Industrials", "HAND_yang-ming"),
    ("TW", "2615.TW"): ("Industrials", "HAND_wan-hai-lines"),
    ("TW", "2637.TW"): ("Industrials", "HAND_taiwan-high-speed"),
    ("TW", "2881.TW"): ("Financials", "HAND_fubon-fhc"),
    ("TW", "2882.TW"): ("Financials", "HAND_cathay-fhc"),
    ("TW", "2883.TW"): ("Financials", "HAND_capital-securities"),
    ("TW", "2886.TW"): ("Financials", "HAND_mega-fhc"),
    ("TW", "2887.TW"): ("Financials", "HAND_taishin-fhc"),
    ("TW", "2892.TW"): ("Financials", "HAND_first-fhc"),
    ("TW", "2912.TW"): ("Consumer Staples", "HAND_president-chain-7e"),
    ("TW", "3034.TW"): ("Information Technology", "HAND_novatek"),
    ("TW", "3035.TW"): ("Information Technology", "HAND_faraday-tech"),
    ("TW", "3045.TW"): ("Communication Services", "HAND_taiwan-mobile"),
    ("TW", "3443.TW"): ("Information Technology", "HAND_global-unichip"),
    ("TW", "6239.TW"): ("Information Technology", "HAND_powertech"),
    # ID
    ("ID", "BBCA.JK"): ("Financials", "HAND_bank-central-asia"),
    ("ID", "BBRI.JK"): ("Financials", "HAND_bank-rakyat"),
    ("ID", "BMRI.JK"): ("Financials", "HAND_bank-mandiri"),
    ("ID", "TLKM.JK"): ("Communication Services", "HAND_telkom-indonesia"),
    ("ID", "ASII.JK"): ("Consumer Discretionary", "HAND_astra-intl"),
    ("ID", "UNVR.JK"): ("Consumer Staples", "HAND_unilever-id"),
    ("ID", "GGRM.JK"): ("Consumer Staples", "HAND_gudang-garam"),
    ("ID", "ICBP.JK"): ("Consumer Staples", "HAND_indofood-cbp"),
    ("ID", "INDF.JK"): ("Consumer Staples", "HAND_indofood"),
    ("ID", "ADRO.JK"): ("Energy", "HAND_adaro-energy"),
    # KR
    ("KR", "005930.KS"): ("Information Technology", "HAND_samsung-electronics"),
    ("KR", "000660.KS"): ("Information Technology", "HAND_sk-hynix"),
    ("KR", "005380.KS"): ("Consumer Discretionary", "HAND_hyundai-motor"),
    ("KR", "005490.KS"): ("Materials", "HAND_posco"),
    ("KR", "035420.KS"): ("Communication Services", "HAND_naver"),
    ("KR", "035720.KS"): ("Communication Services", "HAND_kakao"),
    ("KR", "028260.KS"): ("Industrials", "HAND_samsung-cnt"),
    ("KR", "055550.KS"): ("Financials", "HAND_shinhan-financial"),
    ("KR", "105560.KS"): ("Financials", "HAND_kb-financial"),
    ("KR", "207940.KS"): ("Health Care", "HAND_samsung-biologics"),
    # HK
    ("HK", "0005.HK"): ("Financials", "HAND_hsbc"),
    ("HK", "0388.HK"): ("Financials", "HAND_hkex"),
    ("HK", "0700.HK"): ("Communication Services", "HAND_tencent"),
    ("HK", "0939.HK"): ("Financials", "HAND_ccb"),
    ("HK", "1398.HK"): ("Financials", "HAND_icbc"),
    # MX
    ("MX", "AMXB.MX"): ("Communication Services", "HAND_america-movil"),
    ("MX", "BIMBOA.MX"): ("Consumer Staples", "HAND_grupo-bimbo"),
    ("MX", "CEMEXCPO.MX"): ("Materials", "HAND_cemex"),
    ("MX", "FEMSAUBD.MX"): ("Consumer Staples", "HAND_femsa"),
    ("MX", "GFNORTEO.MX"): ("Financials", "HAND_banorte"),
    ("MX", "GMEXICOB.MX"): ("Materials", "HAND_grupo-mexico"),
    ("MX", "KOFUBL.MX"): ("Consumer Staples", "HAND_coca-cola-femsa"),
    ("MX", "TLEVISACPO.MX"): ("Communication Services", "HAND_televisa"),
    ("MX", "WALMEX.MX"): ("Consumer Staples", "HAND_walmex"),
    # AU
    ("AU", "BHP.AX"): ("Materials", "HAND_bhp"),
    ("AU", "CBA.AX"): ("Financials", "HAND_commonwealth-bank"),
    ("AU", "CSL.AX"): ("Health Care", "HAND_csl-limited"),
    ("AU", "NAB.AX"): ("Financials", "HAND_nab"),
    ("AU", "ANZ.AX"): ("Financials", "HAND_anz"),
    ("AU", "WBC.AX"): ("Financials", "HAND_westpac"),
    ("AU", "WES.AX"): ("Consumer Staples", "HAND_wesfarmers"),
    ("AU", "MQG.AX"): ("Financials", "HAND_macquarie"),
    ("AU", "TLS.AX"): ("Communication Services", "HAND_telstra"),
    ("AU", "RIO.AX"): ("Materials", "HAND_rio-tinto"),
    # IN
    ("IN", "RELIANCE.NS"): ("Energy", "HAND_reliance"),
    ("IN", "TCS.NS"): ("Information Technology", "HAND_tcs"),
    ("IN", "HDFCBANK.NS"): ("Financials", "HAND_hdfc-bank"),
    ("IN", "INFY.NS"): ("Information Technology", "HAND_infosys"),
    ("IN", "ICICIBANK.NS"): ("Financials", "HAND_icici-bank"),
    ("IN", "HINDUNILVR.NS"): ("Consumer Staples", "HAND_hindustan-unilever"),
    ("IN", "BHARTIARTL.NS"): ("Communication Services", "HAND_bharti-airtel"),
    ("IN", "ITC.NS"): ("Consumer Staples", "HAND_itc-limited"),
    ("IN", "SBIN.NS"): ("Financials", "HAND_state-bank-india"),
    ("IN", "KOTAKBANK.NS"): ("Financials", "HAND_kotak-mahindra"),
    # BR
    ("BR", "VALE3.SA"): ("Materials", "HAND_vale"),
    ("BR", "PETR4.SA"): ("Energy", "HAND_petrobras"),
    ("BR", "ITUB4.SA"): ("Financials", "HAND_itau"),
    ("BR", "BBDC4.SA"): ("Financials", "HAND_bradesco"),
    ("BR", "BBAS3.SA"): ("Financials", "HAND_banco-do-brasil"),
    ("BR", "B3SA3.SA"): ("Financials", "HAND_b3-exchange"),
    ("BR", "ITSA4.SA"): ("Financials", "HAND_itausa"),
    ("BR", "ABEV3.SA"): ("Consumer Staples", "HAND_ambev"),
    ("BR", "MGLU3.SA"): ("Consumer Discretionary", "HAND_magazine-luiza"),
    ("BR", "RENT3.SA"): ("Industrials", "HAND_localiza-rent"),
    # CA
    ("CA", "RY.TO"): ("Financials", "HAND_royal-bank"),
    ("CA", "TD.TO"): ("Financials", "HAND_td-bank"),
    ("CA", "BMO.TO"): ("Financials", "HAND_bmo"),
    ("CA", "BNS.TO"): ("Financials", "HAND_scotiabank"),
    ("CA", "MFC.TO"): ("Financials", "HAND_manulife"),
    ("CA", "CNQ.TO"): ("Energy", "HAND_cnq"),
    ("CA", "ENB.TO"): ("Energy", "HAND_enbridge"),
    ("CA", "CP.TO"): ("Industrials", "HAND_cp-rail"),
    ("CA", "CSU.TO"): ("Information Technology", "HAND_constellation-software"),
    ("CA", "BCE.TO"): ("Communication Services", "HAND_bce"),
    # JP (30 — heavy; only shortlist hand-coded; yfinance will fill rest)
    ("JP", "7203.T"): ("Consumer Discretionary", "HAND_toyota"),
    ("JP", "6758.T"): ("Consumer Discretionary", "HAND_sony"),
    ("JP", "7974.T"): ("Communication Services", "HAND_nintendo"),
    ("JP", "6861.T"): ("Information Technology", "HAND_keyence"),
    ("JP", "8306.T"): ("Financials", "HAND_mufg"),
    ("JP", "8316.T"): ("Financials", "HAND_sumitomo-mitsui"),
    ("JP", "8411.T"): ("Financials", "HAND_mizuho"),
    ("JP", "9984.T"): ("Communication Services", "HAND_softbank"),
    ("JP", "9432.T"): ("Communication Services", "HAND_ntt"),
    ("JP", "9433.T"): ("Communication Services", "HAND_kddi"),
    ("JP", "4063.T"): ("Materials", "HAND_shin-etsu-chemical"),
    ("JP", "4502.T"): ("Health Care", "HAND_takeda"),
    ("JP", "4503.T"): ("Health Care", "HAND_astellas"),
    ("JP", "6098.T"): ("Industrials", "HAND_recruit-holdings"),
    ("JP", "6178.T"): ("Industrials", "HAND_japan-post"),
    ("JP", "6273.T"): ("Industrials", "HAND_smc-corp"),
    ("JP", "6367.T"): ("Industrials", "HAND_daikin"),
    ("JP", "6501.T"): ("Industrials", "HAND_hitachi"),
    ("JP", "6594.T"): ("Industrials", "HAND_nidec"),
    ("JP", "6701.T"): ("Information Technology", "HAND_nec"),
    ("JP", "6902.T"): ("Consumer Discretionary", "HAND_denso"),
    ("JP", "6981.T"): ("Information Technology", "HAND_murata"),
    ("JP", "7267.T"): ("Consumer Discretionary", "HAND_honda"),
    ("JP", "7741.T"): ("Health Care", "HAND_hoya"),
    ("JP", "8001.T"): ("Industrials", "HAND_itochu"),
    ("JP", "8002.T"): ("Industrials", "HAND_marubeni"),
    ("JP", "8031.T"): ("Industrials", "HAND_mitsui-co"),
    ("JP", "8035.T"): ("Information Technology", "HAND_tokyo-electron"),
    ("JP", "8058.T"): ("Industrials", "HAND_mitsubishi-corp"),
    ("JP", "8801.T"): ("Real Estate", "HAND_mitsui-fudosan"),
    # EU (18)
    ("EU", "SAP.DE"): ("Information Technology", "HAND_sap"),
    ("EU", "ADS.DE"): ("Consumer Discretionary", "HAND_adidas"),
    ("EU", "ALV.DE"): ("Financials", "HAND_allianz"),
    ("EU", "AIR.PA"): ("Industrials", "HAND_airbus"),
    ("EU", "AZN.L"): ("Health Care", "HAND_astrazeneca"),
    ("EU", "BAS.DE"): ("Materials", "HAND_basf"),
    ("EU", "BMW.DE"): ("Consumer Discretionary", "HAND_bmw"),
    ("EU", "BNP.PA"): ("Financials", "HAND_bnp-paribas"),
    ("EU", "BP.L"): ("Energy", "HAND_bp"),
    ("EU", "DTE.DE"): ("Communication Services", "HAND_deutsche-telekom"),
    ("EU", "HSBA.L"): ("Financials", "HAND_hsbc-uk"),
    ("EU", "MBG.DE"): ("Consumer Discretionary", "HAND_mercedes-benz"),
    ("EU", "MRK.DE"): ("Health Care", "HAND_merck-kgaa"),
    ("EU", "SAN.PA"): ("Health Care", "HAND_sanofi"),
    ("EU", "SHEL.L"): ("Energy", "HAND_shell"),
    ("EU", "SIE.DE"): ("Industrials", "HAND_siemens"),
    ("EU", "TTE.PA"): ("Energy", "HAND_totalenergies"),
    ("EU", "VOW3.DE"): ("Consumer Discretionary", "HAND_volkswagen"),
    # US (30)
    ("US", "AAPL"): ("Information Technology", "HAND_apple"),
    ("US", "MSFT"): ("Information Technology", "HAND_microsoft"),
    ("US", "NVDA"): ("Information Technology", "HAND_nvidia"),
    ("US", "GOOGL"): ("Communication Services", "HAND_alphabet"),
    ("US", "AMZN"): ("Consumer Discretionary", "HAND_amazon"),
    ("US", "META"): ("Communication Services", "HAND_meta"),
    ("US", "BRK-B"): ("Financials", "HAND_berkshire"),
    ("US", "JPM"): ("Financials", "HAND_jpmorgan"),
    ("US", "V"): ("Financials", "HAND_visa"),
    ("US", "MA"): ("Financials", "HAND_mastercard"),
    ("US", "UNH"): ("Health Care", "HAND_unitedhealth"),
    ("US", "JNJ"): ("Health Care", "HAND_jnj"),
    ("US", "ABBV"): ("Health Care", "HAND_abbvie"),
    ("US", "MRK"): ("Health Care", "HAND_merck"),
    ("US", "ABT"): ("Health Care", "HAND_abbott"),
    ("US", "TMO"): ("Health Care", "HAND_thermo-fisher"),
    ("US", "PG"): ("Consumer Staples", "HAND_procter-gamble"),
    ("US", "KO"): ("Consumer Staples", "HAND_coca-cola"),
    ("US", "PEP"): ("Consumer Staples", "HAND_pepsico"),
    ("US", "COST"): ("Consumer Staples", "HAND_costco"),
    ("US", "WMT"): ("Consumer Staples", "HAND_walmart"),
    ("US", "MCD"): ("Consumer Discretionary", "HAND_mcdonalds"),
    ("US", "HD"): ("Consumer Discretionary", "HAND_home-depot"),
    ("US", "TSLA"): ("Consumer Discretionary", "HAND_tesla"),
    ("US", "XOM"): ("Energy", "HAND_exxon"),
    ("US", "CVX"): ("Energy", "HAND_chevron"),
    ("US", "ADBE"): ("Information Technology", "HAND_adobe"),
    ("US", "CRM"): ("Information Technology", "HAND_salesforce"),
    ("US", "CSCO"): ("Information Technology", "HAND_cisco"),
    ("US", "AVGO"): ("Information Technology", "HAND_broadcom"),
}


def fetch_yahoo_sector(ticker: str) -> tuple[str | None, str | None]:
    """Return (yahoo_sector, yahoo_industry) or (None, None) on failure."""
    try:
        info = yf.Ticker(ticker).info
        sector = info.get("sector")
        industry = info.get("industry")
        return sector, industry
    except Exception as e:  # pylint: disable=broad-except
        print(f"  [{ticker}] yfinance error: {e}")
        return None, None


def main() -> None:
    tbl = pd.read_csv(K1171_TABLE)
    rows = []
    n_total = len(tbl)
    for idx, r in tbl.iterrows():
        market = r["market"]
        ticker = r["ticker"]
        yahoo_sector, yahoo_industry = fetch_yahoo_sector(ticker)
        gics_from_yahoo = YAHOO_TO_GICS.get(yahoo_sector) if yahoo_sector else None
        if gics_from_yahoo is not None:
            rows.append(
                {
                    "market": market,
                    "ticker": ticker,
                    "yahoo_sector": yahoo_sector,
                    "yahoo_industry": yahoo_industry,
                    "gics_sector": gics_from_yahoo,
                    "source": "yfinance",
                }
            )
        else:
            # Fall back to hand-coded
            hand = HAND_CODED.get((market, ticker))
            if hand is not None:
                rows.append(
                    {
                        "market": market,
                        "ticker": ticker,
                        "yahoo_sector": yahoo_sector,
                        "yahoo_industry": yahoo_industry,
                        "gics_sector": hand[0],
                        "source": f"HAND_{hand[1]}",
                    }
                )
            else:
                rows.append(
                    {
                        "market": market,
                        "ticker": ticker,
                        "yahoo_sector": yahoo_sector,
                        "yahoo_industry": yahoo_industry,
                        "gics_sector": None,
                        "source": "MISSING",
                    }
                )
        if (idx + 1) % 10 == 0:
            print(f"Fetched {idx+1}/{n_total}")
        time.sleep(0.1)  # polite rate-limit

    out = pd.DataFrame(rows)
    out_path = ROOT / "k1207_stock_sectors.csv"
    out.to_csv(out_path, index=False)
    covered = out["gics_sector"].notna().sum()
    print(f"\nWrote {out_path}: {covered}/{n_total} covered ({covered/n_total:.1%})")
    print("\nBy source:")
    print(out["source"].apply(lambda s: "yfinance" if s == "yfinance" else ("HAND" if s.startswith("HAND") else "MISSING")).value_counts())
    print("\nBy GICS sector:")
    print(out["gics_sector"].value_counts(dropna=False))
    print("\nBy market coverage:")
    print(out.groupby("market")["gics_sector"].apply(lambda s: f"{s.notna().sum()}/{len(s)}"))


if __name__ == "__main__":
    main()
