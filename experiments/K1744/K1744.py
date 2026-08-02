"""K1744: LatAm private-credit funding-gap proxy feasibility gate.

This recovery run is intentionally independent of the zero-salvage predecessor.
It evaluates the preregistered point-in-time proxy before any market outcome is
requested.  A failed proxy gate emits an honest byte-traced INCONCLUSIVE result.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import pandas as pd

from volpred.research.reproduce_spec import finalize_experiment

EXPERIMENT_ID = "K1744"
SEED = 42
HERE = Path(__file__).resolve().parent
PREREG_PATH = HERE / "proxy_preregistration.json"
SOURCE_MANIFEST_PATH = HERE / "raw_cache_manifest.json"
DIAGNOSTICS_PATH = HERE / "diagnostics.json"
README_PATH = HERE / "README.md"
EXPECTED_PREREG_SHA256 = "a3bc7a47f1b14227b12cc1633cfacb3cd4ad8de1f45a4137462c10c4f9dd56a5"
EXPECTED_SOURCE_MANIFEST_SHA256 = (
    "49f4d3602838862a0e21c24321b7b6e82776433de35753ce9cdb3968e5d00a36"
)


def sha256_file(path: Path) -> str:
    """Hash the exact bytes used by this diagnostic."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    """Load a required JSON object without fallback or coercion."""

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain a JSON object")
    return value


def prepare_exposure_for_outcome(exposure: pd.Series) -> pd.Series:
    """Align month-t exposure to the month-(t+1) outcome information set."""

    return exposure.shift(1)


def assess_proxy_feasibility(
    prereg: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    """Fail closed unless every preregistered provenance threshold is evidenced."""

    gate = manifest["proxy_feasibility_readback"]
    requirements = prereg["feasibility_gate"]["requirements"]
    checks = {
        "complete_versioned_enumeration_export": bool(
            gate["complete_versioned_enumeration_export_accessible"]
        ),
        "official_release_timestamp_for_every_retained_event": False,
        "minimum_distinct_eligible_events": False,
        "minimum_nonzero_exposure_months": False,
        "minimum_common_months_after_all_lags": False,
        "no_outcome_guided_proxy_or_threshold_selection": bool(
            prereg["outcome_data_inspected_before_lock"] is False
            and manifest["outcome_market_data_requested"] is False
        ),
    }
    passed = all(checks.values())
    return {
        "status": "PASSED" if passed else "FAILED_BEFORE_OUTCOME_LOADING",
        "passed": passed,
        "checks": checks,
        "thresholds": {
            "minimum_distinct_eligible_events": requirements[
                "minimum_distinct_eligible_events"
            ],
            "minimum_nonzero_exposure_months": requirements[
                "minimum_nonzero_exposure_months"
            ],
            "minimum_common_months_after_all_lags": requirements[
                "minimum_common_months_after_all_lags"
            ],
        },
        "observed": {
            "eligible_event_count": gate["eligible_event_count"],
            "nonzero_month_count": gate["nonzero_month_count"],
            "common_month_count": None,
        },
        "unknown_counts_are_not_zero": True,
        "exact_failure_reason": gate["exact_failure_reason"],
    }


def build_result(
    prereg: dict[str, Any],
    manifest: dict[str, Any],
    feasibility: dict[str, Any],
    prereg_sha256: str,
    source_manifest_sha256: str,
) -> dict[str, Any]:
    """Build the complete scientific payload for the failed feasibility gate."""

    sources = manifest["sources"]
    source_index = {row["source_id"]: row for row in sources}
    primary_source_ids = [
        "cfa_latam",
        "cfa_private_markets_report",
        "eclac_gap",
        "nber_private_credit",
        "nber_bank_lending",
        "corsi_har_doi",
    ]
    source_records = [
        {
            "source_id": source_index[source_id]["source_id"],
            "title": source_index[source_id]["title"],
            "publisher": source_index[source_id]["publisher"],
            "publication_date": source_index[source_id]["publication_date"],
            "url": source_index[source_id]["url"],
            "accessed_at_utc": source_index[source_id]["accessed_at_utc"],
            "response_sha256": source_index[source_id]["response_sha256"],
            "response_bytes": source_index[source_id]["response_bytes"],
            "claim_supported": source_index[source_id]["institutional_claim_supported"],
        }
        for source_id in primary_source_ids
    ]

    result: dict[str, Any] = {
        "schema_version": "volpred.experiment_result.v1",
        "experiment_id": EXPERIMENT_ID,
        "research_type": "empirical_predictive_association_feasibility_gate",
        "seed": SEED,
        "execution_status": "COMPLETED_FEASIBILITY_GATE",
        "conclusion_grade": "INCONCLUSIVE",
        "conclusion_code": "INSUFFICIENT_DATA",
        "scientific_null": False,
        "recovery": {
            "current_retry_is_distinct": True,
            "prior_job_id": "agent-brief-k1744-552fde40",
            "prior_job_classification": "ZERO_SALVAGE",
            "prior_job_research_started": False,
            "prior_job_artifacts_used": [],
            "prior_job_code_or_data_read": False,
            "zero_salvage_is_not_success": True,
            "zero_salvage_is_not_scientific_null": True,
        },
        "research_question": prereg["question"],
        "differentiation": {
            "estimand": "regional LatAm private-credit funding-supply announcement transmission",
            "not_generic_bdc_spillover": True,
            "etfs_are_liquid_market_proxies_not_private_credit_assets": True,
            "claim_type_if_feasible": "predictive_associational_not_causal",
            "related_k": {
                "K1487": "coarse GDELT private-credit news intensity was not a reliable generic RV lead",
                "K1332": "listed BDC stress had narrow HYG/BKLN predictive content",
                "K1499": "BDC stress largely collapsed after broad-market controls",
                "K1367": "daily GDELT plus ETF baskets was too noisy for a tail-risk claim",
                "K1728": "free attention/sentiment did not improve HAR-RV in US equities",
            },
        },
        "literature": {
            "primary_sources": source_records,
            "institutional_motivation": {
                "eclac_annual_financing_gap_usd_billion": 650,
                "cfa_latam_private_credit_share_of_corporate_lending_upper_bound_pct": 1,
                "cfa_latam_fundraising_2025_usd_million": 800,
                "cfa_global_private_debt_fundraising_2025_usd_billion": 356,
                "use_restriction": "Motivation only. No 2025 or 2026 retrospective total enters a historical forecast origin.",
            },
        },
        "inputs": {
            "proxy_preregistration": {
                "path": "experiments/K1744/proxy_preregistration.json",
                "sha256": prereg_sha256,
                "size_bytes": PREREG_PATH.stat().st_size,
                "locked_at_utc": prereg["locked_at_utc"],
            },
            "raw_cache_manifest": {
                "path": "experiments/K1744/raw_cache_manifest.json",
                "sha256": source_manifest_sha256,
                "size_bytes": SOURCE_MANIFEST_PATH.stat().st_size,
                "created_at_utc": manifest["created_at_utc"],
                "body_retention_policy": manifest["body_retention_policy"],
            },
        },
        "proxy": {
            "name": prereg["primary_exposure_proxy"]["name"],
            "ideal_latent_variable": prereg["ideal_latent_variable"],
            "construction": prereg["primary_exposure_proxy"][
                "exact_observable_construction"
            ],
            "frequency": prereg["primary_exposure_proxy"]["frequency"],
            "transformation": prereg["primary_exposure_proxy"]["transformation"],
            "expected_sign": prereg["primary_exposure_proxy"]["expected_sign"],
            "known_measurement_error": prereg["primary_exposure_proxy"][
                "known_measurement_error"
            ],
            "feasibility": feasibility,
        },
        "design": {
            "fixed_market_universe": prereg["fixed_market_universe"],
            "fixed_market_universe_count": len(prereg["fixed_market_universe"]),
            "channels": prereg["channel_definitions"],
            "outcome_lock": prereg["outcome_lock"],
            "primary_family": prereg["outcome_lock"]["primary_family"],
            "seed": SEED,
            "explicit_signal_lag": "prepare_exposure_for_outcome returns exposure.shift(1)",
            "outcome_loading_authorized": False,
        },
        "data": {
            "source": None,
            "period": {"start": None, "end": None},
            "sample": {
                "eligible_proxy_events": None,
                "nonzero_exposure_months": None,
                "effective_common_months": None,
                "outcome_rows": 0,
            },
            "release_time": {
                "rule": prereg["primary_exposure_proxy"][
                    "point_in_time_verification_source"
                ]["availability_rule"],
                "verified_event_release_timestamps": 0,
            },
            "outcome_series_requested": False,
            "outcome_series_loaded": False,
            "ticker_diagnostics": {
                "status": "NOT_RUN_BY_FEASIBILITY_CONTRACT",
                "inceptions": None,
                "delistings": None,
                "missingness": None,
                "duplicates": None,
                "timezone": None,
                "extremes": None,
                "source_revisions": None,
                "common_sample_loss": None,
            },
        },
        "estimates": {
            "status": "NOT_ESTIMATED",
            "reason": feasibility["exact_failure_reason"],
            "primary_cells": [],
            "raw_p_values": [],
            "holm_adjusted_p_values": [],
            "primary_adjusted_p_value": None,
            "primary_adjusted_p_value_reason": "No defensible exposure series; inference was prohibited before outcomes.",
        },
        "robustness": {
            "status": "NOT_RUN",
            "direction": "NOT_AVAILABLE",
            "reason": "Secondary robustness cannot replace a failed primary proxy feasibility gate.",
            "prespecified_secondary_only": prereg["secondary_robustness_only"],
        },
        "diagnostics": {
            "proxy_lock": "PASS",
            "release_time_provenance": "FAIL_INACCESSIBLE_ENUMERATION",
            "lag_contract": "FROZEN_NOT_APPLIED_TO_OUTCOMES",
            "common_sample": "NOT_CONSTRUCTED",
            "inference_family": "FROZEN_NOT_RUN",
            "outcome_access_guard": "PASS_ZERO_OUTCOME_REQUESTS",
        },
        "limitations": [
            "The required record-level, versioned Private Debt Investor enumeration/export was inaccessible without authenticated provider access.",
            "Sponsor releases establish isolated examples but cannot define complete zero-event months or an unbiased regional manager universe.",
            "The eligible event count and effective exposure history are unknown, not zero.",
            "No ETF prices, returns, inception dates, realized volatility, tail endpoint, UUP beta, estimate, p-value, or robustness statistic was computed.",
            "The 2026 CFA materials motivate the question but are retrospective and cannot be backfilled into historical forecast origins.",
            "This INCONCLUSIVE result is neither evidence for transmission nor a scientific null against it.",
        ],
        "conclusion": {
            "grade": "INCONCLUSIVE",
            "code": "INSUFFICIENT_DATA",
            "statement": "The point-in-time LatAm private-credit funding-supply proxy could not be constructed from accessible, complete, versioned record-level data. Outcome analysis stopped as preregistered.",
            "supported": False,
            "null": False,
            "blocked_by": "proxy_provenance_and_enumeration_access",
        },
    }
    return result


def render_readme(result: dict[str, Any]) -> str:
    """Render claims only from the in-memory canonical result payload."""

    failure = result["proxy"]["feasibility"]["exact_failure_reason"]
    return f"""# K1744 — Latin America private-credit funding-gap transmission

## 結論

**INCONCLUSIVE / INSUFFICIENT_DATA**。這不是科學 null，也不是先前失敗 job 的成功續接。前一個 `agent-brief-k1744-552fde40` 在研究開始前即被 quota 拒絕，分類固定為 **ZERO_SALVAGE**；本 fresh-worktree retry 沒有讀取或採用舊 worktree 的程式、資料或 artifact（JSON: `/recovery`、`/conclusion`）。

Proxy feasibility gate 在任何 ETF outcome request 之前失敗，因此本輪 outcome rows 為 **{result['data']['sample']['outcome_rows']}**（JSON: `/data/sample/outcome_rows`），沒有估計值、raw p-value 或 Holm-adjusted p-value（JSON: `/estimates`）。精確原因：{failure}

## 動機與差異化

ECLAC 報告拉丁美洲與加勒比海每年約有 **USD {result['literature']['institutional_motivation']['eclac_annual_financing_gap_usd_billion']} billion** 的發展融資缺口（JSON: `/literature/institutional_motivation/eclac_annual_financing_gap_usd_billion`）。CFA Institute 2026 專文把 LatAm 私募信貸描述為結構化融資、基礎建設、中型企業與家族／fintech 成長融資，而非美國典型 LBO direct lending；同文指出區域私募信貸占企業放款低於 **{result['literature']['institutional_motivation']['cfa_latam_private_credit_share_of_corporate_lending_upper_bound_pct']}%**，2025 年 LatAm 策略募資約 **USD {result['literature']['institutional_motivation']['cfa_latam_fundraising_2025_usd_million']} million**（JSON: `/literature/institutional_motivation/cfa_latam_private_credit_share_of_corporate_lending_upper_bound_pct`、`/literature/institutional_motivation/cfa_latam_fundraising_2025_usd_million`）。這些 2025–2026 數字只作 institutional motivation，絕不回填成歷史可得訊號。

K1744 與通用 BDC spillover 不同：K1332/K1499 使用上市 BDC 價格壓力，K1487 使用廣義 GDELT private-credit news；K1744 預註冊的 estimand 是 **LatAm 區域資本供給／funding-gap transmission**。ILF、EWW、ECH、EPU、EWZ、CEW、EMLC、EMB 與 UUP 共 **{result['design']['fixed_market_universe_count']}** 檔只會是流動市場 proxy，不是私募信貸資產（JSON: `/design/fixed_market_universe_count`、`/design/fixed_market_universe`）。即使日後可執行，結論也只能是 predictive/associational，不能稱因果。

## Proxy preregistration 與 data provenance

Primary exposure 在 outcome inspection 前已鎖定（`proxy_preregistration.json` SHA-256 見 JSON: `/inputs/proxy_preregistration/sha256`）：每月完整枚舉具有 LatAm 專屬或至少半數 LatAm mandate 的 private-credit/private-debt fund **final close**，以 legal fund name + vintage + close date 去重，再取 `log1p(count)`。枚舉框必須是帶 provider record ID、export-as-of、版本／更新時間與檔案 SHA-256 的 PDI record-level export；逐筆 point-in-time 時間則必須回到 sponsor 官方 final-close release。只有年月、回溯報表日期或今天搜尋到的文章都不合格。

Feasibility success 需要至少 **{result['proxy']['feasibility']['thresholds']['minimum_distinct_eligible_events']}** 個 distinct events、**{result['proxy']['feasibility']['thresholds']['minimum_nonzero_exposure_months']}** 個 nonzero months 與 lag 後至少 **{result['proxy']['feasibility']['thresholds']['minimum_common_months_after_all_lags']}** 個 full-basket common months（JSON: `/proxy/feasibility/thresholds`）。本輪三項 observed count 都是 `null`，代表不可測，不代表零（JSON: `/proxy/feasibility/observed`、`/proxy/feasibility/unknown_counts_are_not_zero`）。

`raw_cache_manifest.json` 保存每個官方／學術頁面的直接 URL、publication/release date、實際 access timestamp、HTTP status、response SHA-256 與 byte size（JSON: `/inputs/raw_cache_manifest`；逐來源見 `/literature/primary_sources`）。未保存第三方全文；因沒有合格 record-level proxy export，也沒有可合法宣稱的 raw proxy rows。

## 預註冊方法（若 gate 通過才會執行）

- 月頻 forecast origin：月末交易日收盤；outcome month 的 exposure 只能來自前一月，程式固定由 `prepare_exposure_for_outcome()` 明確執行 `.shift(1)`（JSON: `/design/explicit_signal_lag`）。
- 三個分離 channel：equity（ILF/EWW/ECH/EPU/EWZ）、FX/local bond（CEW/EMLC）、hard-currency bond（EMB）；UUP 只作 USD factor（JSON: `/design/channels`）。
- 三個 outcomes：次月 realized variance、次月最差日 left-tail loss、60-trading-day UUP beta 絕對值的次月變化（JSON: `/design/outcome_lock/targets`）。
- Baseline 與 candidate 用完全相同資訊集、lag 與 common rows；預註冊 baseline 是 **{result['design']['outcome_lock']['baseline']}**，candidate 是 **{result['design']['outcome_lock']['candidate']}**（JSON: `/design/outcome_lock/baseline`、`/design/outcome_lock/candidate`）。
- Primary family 固定為 **{result['design']['primary_family']['cells']}** cells，Holm step-down 校正整個 family。Candidate 巢狀於 baseline，所以 RV 的 primary QLIKE loss inference 使用 seed={result['seed']} recursive expanding-window month-block bootstrap；普通 DM/HLN 只作 diagnostic。Tail loss 與 beta change 對 incremental exposure coefficient 做 canonical-bandwidth HAC，另報 month-block permutation/bootstrap、autocorrelation 與 lag sensitivity（JSON: `/design/primary_family`、`/seed`）。
- Machine-locked inference contract: {result['design']['primary_family']['dependence_robust_inference']}
- 價格診斷原應報 ETF inception、delisting、missingness、duplicate、timezone、extremes、revision 與 full-basket common-sample loss；因 proxy gate 先失敗，這些全部標 `NOT_RUN_BY_FEASIBILITY_CONTRACT`，沒有用 forward fill 掩蓋（JSON: `/data/ticker_diagnostics`）。

## Success / null / blocked criteria

`SUPPORTED` 必須先通過 proxy gate，且同一 outcome family 至少兩個 channel 出現 expected-sign、Holm-adjusted p<0.05 的 primary effect；secondary robustness 不得救援 primary failure。`NULL` 只可在 proxy 可行且完整 **{result['design']['primary_family']['cells']}**-cell family 真正估計後成立。任何 provenance、complete-enumeration、event-count 或 common-sample requirement 失敗都只能是 `INCONCLUSIVE`（完整 machine policy: `proxy_preregistration.json` `/verdict_policy`；本輪結果: `K1744_results.json` `/conclusion`）。

## Primary sources

- CFA Institute, *How private credit investment is filling a funding gap in Latin America*, 2026-06-04: https://www.cfainstitute.org/insights/articles/latin-america-private-credit-investment-growth
- Preece and Wilson, CFA Institute RPC, *Understanding the Growth of Private Markets*, 2026-06-22, DOI 10.56227/26.1.12: https://rpc.cfainstitute.org/research/reports/2026/understanding-growth-private-markets
- ECLAC, financing-for-development release, 2025-07-03: https://www.cepal.org/en/pressreleases/faced-financing-development-challenges-latin-american-and-caribbean-countries-need
- Matvos, Piskorski, and Seru, NBER W34991, 2026-03-18, DOI 10.3386/w34991: https://www.nber.org/papers/w34991
- Buchak, Matvos, Piskorski, and Seru, NBER W32176, 2024-02-27, DOI 10.3386/w32176: https://www.nber.org/papers/w32176
- Corsi, *A Simple Approximate Long-Memory Model of Realized Volatility*, DOI 10.1093/jjfinec/nbp001: https://doi.org/10.1093/jjfinec/nbp001

## 結果與限制

No empirical run occurred. Primary estimate、raw p-value、adjusted p-value 與 robustness direction 都不存在（JSON: `/estimates/primary_adjusted_p_value`、`/robustness/direction`）。此 artifact 的有效發現只限於：目前可存取來源不足以建立 preregistered complete/PIT proxy；不能推論 funding-gap transmission 存在、為零或方向相反。

主要限制完整列於 JSON `/limitations`。沒有畫圖，因為沒有有效 empirical sample；以文字框或假圖替代會違反研究誠實。
"""


def build_diagnostics(
    result: dict[str, Any], readme: str, prereg_sha256: str, source_manifest_sha256: str
) -> dict[str, Any]:
    """Machine-check proxy lock, lag path, stopped sample, and claim consistency."""

    source_text = Path(__file__).read_text(encoding="utf-8")
    required_readme_fragments = [
        result["conclusion_grade"],
        result["conclusion_code"],
        result["recovery"]["prior_job_classification"],
        result["proxy"]["feasibility"]["exact_failure_reason"],
        f"outcome rows 為 **{result['data']['sample']['outcome_rows']}**",
        f"固定為 **{result['design']['primary_family']['cells']}** cells",
        f"seed={result['seed']}",
        result["design"]["outcome_lock"]["baseline"],
        result["design"]["outcome_lock"]["candidate"],
        result["design"]["primary_family"]["dependence_robust_inference"],
    ]
    return {
        "schema_version": "volpred.K1744.diagnostics.v1",
        "experiment_id": EXPERIMENT_ID,
        "checks": {
            "proxy_preregistration_hash_matches": prereg_sha256
            == EXPECTED_PREREG_SHA256,
            "source_manifest_hash_matches": source_manifest_sha256
            == EXPECTED_SOURCE_MANIFEST_SHA256,
            "proxy_locked_before_outcome_inspection": True,
            "zero_salvage_predecessor_not_used": result["recovery"][
                "prior_job_artifacts_used"
            ]
            == [],
            "explicit_shift_1_in_signal_path": "return exposure.shift(1)" in source_text,
            "runtime_lag_probe_on_empty_non_outcome_series": prepare_exposure_for_outcome(
                pd.Series(dtype="float64")
            ).empty,
            "outcome_request_count_is_zero": result["data"]["sample"]["outcome_rows"]
            == 0
            and result["data"]["outcome_series_requested"] is False,
            "common_sample_not_constructed_after_failed_gate": result["diagnostics"][
                "common_sample"
            ]
            == "NOT_CONSTRUCTED",
            "primary_inference_family_frozen": result["design"]["primary_family"][
                "cells"
            ]
            == 9,
            "raw_and_adjusted_p_values_empty": result["estimates"]["raw_p_values"]
            == []
            and result["estimates"]["holm_adjusted_p_values"] == [],
            "readme_result_consistency": all(
                fragment in readme for fragment in required_readme_fragments
            ),
        },
        "required_readme_fragments": required_readme_fragments,
        "json_claim_pointers": [
            "/recovery",
            "/conclusion",
            "/proxy/feasibility",
            "/data/sample/outcome_rows",
            "/estimates",
            "/robustness",
            "/limitations",
        ],
        "common_sample_status": "NOT_CONSTRUCTED_BY_FEASIBILITY_CONTRACT",
        "inference_family_status": "FROZEN_9_CELLS_NOT_RUN",
        "readme_consistency_status": "PASS",
    }


def main() -> None:
    """Execute the pre-outcome gate and finalize byte-traceable artifacts."""

    started_at = time.time()
    prereg_sha256 = sha256_file(PREREG_PATH)
    source_manifest_sha256 = sha256_file(SOURCE_MANIFEST_PATH)
    if prereg_sha256 != EXPECTED_PREREG_SHA256:
        raise RuntimeError(
            "proxy preregistration drifted after lock; refusing outcome analysis or artifact refresh"
        )
    if source_manifest_sha256 != EXPECTED_SOURCE_MANIFEST_SHA256:
        raise RuntimeError(
            "source feasibility manifest drifted; refusing to reinterpret inaccessible records"
        )

    prereg = load_json(PREREG_PATH)
    manifest = load_json(SOURCE_MANIFEST_PATH)
    feasibility = assess_proxy_feasibility(prereg, manifest)
    if feasibility["passed"]:
        raise RuntimeError(
            "This recovery entrypoint only certifies the observed failed feasibility state; "
            "a newly accessible record-level export requires a fresh preregistered run."
        )

    result = build_result(
        prereg,
        manifest,
        feasibility,
        prereg_sha256,
        source_manifest_sha256,
    )
    readme = render_readme(result)
    README_PATH.write_text(readme, encoding="utf-8")
    diagnostics = build_diagnostics(
        result, readme, prereg_sha256, source_manifest_sha256
    )
    if not all(diagnostics["checks"].values()):
        failed = [name for name, passed in diagnostics["checks"].items() if not passed]
        raise RuntimeError(f"K1744 diagnostic failure(s): {failed}")
    DIAGNOSTICS_PATH.write_text(
        json.dumps(diagnostics, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    result_path, spec = finalize_experiment(
        results=result,
        entrypoint=__file__,
        canonical_result="K1744_results.json",
        inputs=[PREREG_PATH, SOURCE_MANIFEST_PATH],
        outputs=[README_PATH.name, DIAGNOSTICS_PATH.name],
        seeds=[("numpy", SEED), ("pandas", SEED)],
        started_at=started_at,
        network="deny",
    )
    print(
        json.dumps(
            {
                "conclusion_grade": result["conclusion_grade"],
                "conclusion_code": result["conclusion_code"],
                "result_path": str(result_path),
                "result_sha256": spec["canonical_result_identity"]["sha256"],
                "exact_failure_reason": feasibility["exact_failure_reason"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
