#!/usr/bin/env python3
"""K1306 — SEC EDGAR 10-K fetcher (pilot scope).

Pilot sample (reduced from 30-firm README design):
    Tickers: AAPL, MSFT, GOOGL, NVDA, TSM   (5 firms)
    Filing years: 2020-2024                 (5 years)
    Expected: 25 filings

Rate-limit policy: <=10 req/sec to SEC EDGAR per
    https://www.sec.gov/os/accessing-edgar-data
User-Agent header is mandatory per SEC API ToS.

Outputs:
    experiments/k1306/data/filings_index.json  — list of {ticker, cik, accession, filing_date, primary_doc, local_path}
    experiments/k1306/data/raw/<ticker>_<filing_date>.txt — extracted text (MD&A + risk factors)

Lookahead discipline:
    No market data touched here. Filing dates are SEC-reported; downstream code
    uses filing_date + 1bd embargo for prediction targets.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
RAW_DIR = DATA_DIR / "raw"
DATA_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)

# SEC requires a descriptive User-Agent: "Sample Company Name AdminContact@samplecompany.com"
USER_AGENT = "VolPred Research (Yi-Hao Lai, yihao.lai@gmail.com)"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
    "Host": "www.sec.gov",
}
SUBMISSIONS_HEADERS = {
    **HEADERS,
    "Host": "data.sec.gov",
}

# Rate limit: SEC allows up to 10 req/sec; we use 5 req/sec for safety.
REQ_INTERVAL_SEC = 0.20

# Pilot sample — keeping small so the pipeline can complete within rate budget.
TICKER_CIK = {
    "AAPL":  "0000320193",
    "MSFT":  "0000789019",
    "GOOGL": "0001652044",
    "NVDA":  "0001045810",
    # TSM ADR has no 10-K; it files 20-F. Substitute META (largest tech 10-K filer).
    "META":  "0001326801",
}
TARGET_YEARS = list(range(2020, 2025))  # filing years 2020-2024 inclusive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_last_req_t = 0.0

def _sleep_for_rate_limit() -> None:
    global _last_req_t
    dt = time.monotonic() - _last_req_t
    if dt < REQ_INTERVAL_SEC:
        time.sleep(REQ_INTERVAL_SEC - dt)
    _last_req_t = time.monotonic()


def _get(url: str, headers: dict = HEADERS, timeout: int = 30) -> requests.Response:
    _sleep_for_rate_limit()
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp


def get_submissions(cik: str) -> dict:
    """Fetch ticker submission index from data.sec.gov."""
    cik_padded = cik.zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    return _get(url, headers=SUBMISSIONS_HEADERS).json()


def filter_10k(submissions: dict, years: Iterable[int]) -> list[dict]:
    """Return list of {accession, filing_date, primary_doc} for 10-K filings in target years."""
    recent = submissions["filings"]["recent"]
    keys = ["accessionNumber", "filingDate", "primaryDocument", "form"]
    rows = list(zip(*(recent[k] for k in keys)))
    yrs = set(int(y) for y in years)
    out = []
    for accession, filing_date, primary_doc, form in rows:
        if form != "10-K":
            continue
        yr = int(filing_date[:4])
        if yr in yrs:
            out.append({
                "accession": accession,
                "filing_date": filing_date,
                "primary_doc": primary_doc,
                "form": form,
            })
    return out


def build_filing_url(cik: str, accession: str, primary_doc: str) -> str:
    cik_int = int(cik)
    acc_nodash = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{primary_doc}"


def extract_sections(html: str) -> dict:
    """Extract MD&A and Risk Factors text from a 10-K HTML body.

    Heuristic: look for section anchors / heading text matching
    'Item 7' (MD&A) and 'Item 1A' (Risk Factors). We strip to plain text and
    take ~30,000 chars per section as a cap (most 10-K MD&A sections fit).
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove script/style/inline-XBRL noise
    for bad in soup(["script", "style"]):
        bad.decompose()

    # ix:* (inline XBRL) tags often contain financial numbers — keep their text
    # but remove the XBRL namespace markup.
    full_text = soup.get_text(separator=" ", strip=True)
    full_text = re.sub(r"\s+", " ", full_text)

    def _grab(start_pats: list[str], end_pats: list[str]) -> str:
        # Strategy: find ALL occurrences of start patterns; take the LARGEST
        # span between any start match and the next end match. This skips TOC
        # entries (which yield ~tiny spans) and lands on the actual section body.
        best_section = ""
        for sp in start_pats:
            for m in re.finditer(sp, full_text, flags=re.IGNORECASE):
                start = m.end()
                best_end = len(full_text)
                for ep in end_pats:
                    em = re.search(ep, full_text[start:start + 200000], flags=re.IGNORECASE)
                    if em:
                        cand = start + em.start()
                        if cand < best_end:
                            best_end = cand
                section = full_text[start:best_end]
                # Skip very-short spans (TOC artifacts) — section bodies are 10k+ chars
                if len(section) > len(best_section):
                    best_section = section
            if best_section:
                break  # don't fall through to less-specific start patterns
        # cap at 60000 chars to keep file size manageable while preserving signal
        return best_section[:60000]

    risk = _grab(
        start_pats=[r"item\s*1a[\.\s]*risk\s*factors", r"risk\s*factors\s*\n"],
        end_pats=[r"item\s*1b[\.\s]", r"item\s*2[\.\s]*properties", r"unresolved\s*staff\s*comments"],
    )
    mdna = _grab(
        start_pats=[
            r"item\s*7[\.\s]*management.?s\s*discussion",
            r"management.?s\s*discussion\s*and\s*analysis",
        ],
        end_pats=[r"item\s*7a[\.\s]", r"item\s*8[\.\s]*financial\s*statements"],
    )
    return {"risk_factors": risk, "mdna": mdna}


def fetch_one(ticker: str, cik: str, row: dict) -> dict:
    url = build_filing_url(cik, row["accession"], row["primary_doc"])
    resp = _get(url)
    sections = extract_sections(resp.text)
    local_path = RAW_DIR / f"{ticker}_{row['filing_date']}.json"
    local_path.write_text(json.dumps({
        "ticker": ticker,
        "cik": cik,
        "accession": row["accession"],
        "filing_date": row["filing_date"],
        "source_url": url,
        "risk_factors": sections["risk_factors"],
        "mdna": sections["mdna"],
        "risk_chars": len(sections["risk_factors"]),
        "mdna_chars": len(sections["mdna"]),
    }, ensure_ascii=False, indent=1))
    return {
        "ticker": ticker,
        "cik": cik,
        "accession": row["accession"],
        "filing_date": row["filing_date"],
        "primary_doc": row["primary_doc"],
        "source_url": url,
        "local_path": str(local_path.relative_to(HERE.parent.parent)),
        "risk_chars": len(sections["risk_factors"]),
        "mdna_chars": len(sections["mdna"]),
    }


def main() -> None:
    index = []
    failures = []
    for ticker, cik in TICKER_CIK.items():
        try:
            subs = get_submissions(cik)
        except Exception as e:
            failures.append({"ticker": ticker, "stage": "submissions", "err": str(e)})
            continue
        filings = filter_10k(subs, TARGET_YEARS)
        # Deduplicate by year — keep first filing per year (10-K is annual)
        by_year = {}
        for f in filings:
            yr = int(f["filing_date"][:4])
            by_year.setdefault(yr, f)
        for yr in TARGET_YEARS:
            row = by_year.get(yr)
            if row is None:
                failures.append({"ticker": ticker, "year": yr, "stage": "no_filing"})
                continue
            try:
                rec = fetch_one(ticker, cik, row)
                index.append(rec)
                print(f"[OK] {ticker} {row['filing_date']} risk={rec['risk_chars']} mdna={rec['mdna_chars']}")
            except Exception as e:
                failures.append({"ticker": ticker, "year": yr, "stage": "fetch", "err": str(e)})
                print(f"[FAIL] {ticker} {row['filing_date']}: {e}")

    out = DATA_DIR / "filings_index.json"
    out.write_text(json.dumps({
        "n_success": len(index),
        "n_failure": len(failures),
        "tickers": list(TICKER_CIK),
        "years": TARGET_YEARS,
        "filings": index,
        "failures": failures,
    }, ensure_ascii=False, indent=2))
    print(f"\nSaved {len(index)} filings to {out}; failures={len(failures)}")


if __name__ == "__main__":
    main()
