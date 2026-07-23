#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

k1257_result="experiments/k1257/k1257_results.json"
k1258_result="experiments/k1258/k1258_results.json"

k1257_headline_before="$(
  jq -c '{
    per_asset: (.per_asset | with_entries(
      .value |= {
        n_common_sample,
        bma_qlike,
        equal_weight_qlike,
        gjr_t_qlike,
        dm_bma_vs_gjr,
        dm_bma_vs_equal
      }
    )),
    hypothesis_verdicts
  }' "$k1257_result"
)"
k1258_headline_before="$(
  jq -c '{
    results: (.results | with_entries(
      .value |= with_entries(
        .value |= {
          qlike,
          harvey_dm_vs_lambda1,
          harvey_p_vs_lambda1,
          harvey_pass_vs_lambda1
        }
      )
    )),
    hypothesis_verdicts
  }' "$k1258_result"
)"

uv run python experiments/k1257/k1257_bma_volatility.py
uv run python experiments/k1258/k1258_forgetting_factor_bma.py

k1257_headline_after="$(
  jq -c '{
    per_asset: (.per_asset | with_entries(
      .value |= {
        n_common_sample,
        bma_qlike,
        equal_weight_qlike,
        gjr_t_qlike,
        dm_bma_vs_gjr,
        dm_bma_vs_equal
      }
    )),
    hypothesis_verdicts
  }' "$k1257_result"
)"
k1258_headline_after="$(
  jq -c '{
    results: (.results | with_entries(
      .value |= with_entries(
        .value |= {
          qlike,
          harvey_dm_vs_lambda1,
          harvey_p_vs_lambda1,
          harvey_pass_vs_lambda1
        }
      )
    )),
    hypothesis_verdicts
  }' "$k1258_result"
)"

if [[ "$k1257_headline_before" != "$k1257_headline_after" ]]; then
  echo "K1257 headline regression after posterior-semantics rerun" >&2
  exit 1
fi
if [[ "$k1258_headline_before" != "$k1258_headline_after" ]]; then
  echo "K1258 headline regression after posterior-semantics rerun" >&2
  exit 1
fi

jq -e '
  all(.per_asset[];
    has("absorbing_dropped_models")
    and has("ever_invalid_models")
    and has("final_weight_status")
    and all(.forecast_diagnostics[];
      has("invalid_forecast_days")
      and has("drop_events")
      and has("posterior_excluded_days")
      and (has("dropped_model_days") | not)
    )
  )
' "$k1257_result" >/dev/null

jq -e '
  (.posterior_semantics.revival_policy == "floor_revival")
  and all(.results[][];
    has("absorbing_dropped_models")
    and has("ever_invalid_models")
    and has("final_weight_status")
    and has("posterior_diagnostics")
  )
  and all(.forecast_diagnostics[];
    all(.[];
      has("invalid_forecast_days")
      and has("drop_events")
      and (has("dropped_model_days") | not)
    )
  )
' "$k1258_result" >/dev/null

echo "K1257/K1258 semantic schema rerun passed with unchanged headlines"
