from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parent
RESULTS_PATH = ROOT / "k1459_results.json"

SEED = 42
ROUND_HORIZON = 120
MC_REPS = 400


@dataclass
class Scenario:
    name: str
    promised_return: float
    entrant_growth: float
    withdrawal_rate: float
    initial_investors: int
    horizon: int = ROUND_HORIZON


def flat_new_entrant_requirement(active_investors: float, r: float, w: float) -> float:
    return (r + w) * active_investors


def active_investors_flat_path(n0: float, r: float, periods: int) -> np.ndarray:
    idx = np.arange(periods + 1, dtype=float)
    return n0 * np.power(1.0 + r, idx)


def cumulative_participants_flat_path(n0: float, r: float, w: float, periods: int) -> float:
    if math.isclose(r, 0.0):
        return n0 + periods * (r + w) * n0
    return n0 * (1.0 + ((r + w) * (np.power(1.0 + r, periods) - 1.0) / r))


def deterministic_path(s: Scenario) -> dict:
    reserve = float(s.initial_investors)
    active = float(s.initial_investors)
    entrants_round1 = flat_new_entrant_requirement(active, s.promised_return, s.withdrawal_rate)

    reserve_path = [reserve]
    active_path = [active]
    entrant_path = [float(s.initial_investors)]
    payout_path = [0.0]
    collapse_round = None

    for t in range(1, s.horizon + 1):
        entrants = entrants_round1 * np.power(1.0 + s.entrant_growth, t - 1)
        payouts = (s.promised_return + s.withdrawal_rate) * active
        reserve = reserve + entrants - payouts
        active = (1.0 - s.withdrawal_rate) * active + entrants

        reserve_path.append(float(reserve))
        active_path.append(float(active))
        entrant_path.append(float(entrants))
        payout_path.append(float(payouts))

        if collapse_round is None and reserve < 0:
            collapse_round = t

    return {
        "collapse_round": collapse_round,
        "survives_horizon": collapse_round is None,
        "reserve_path": reserve_path,
        "active_path": active_path,
        "entrant_path": entrant_path,
        "payout_path": payout_path,
        "final_reserve": reserve_path[-1],
        "final_active_investors": active_path[-1],
    }


def stochastic_collapse_stats(s: Scenario, rng: np.random.Generator, reps: int = MC_REPS) -> dict:
    collapse_rounds = []
    final_reserves = []

    base_round1 = flat_new_entrant_requirement(
        s.initial_investors, s.promised_return, s.withdrawal_rate
    )

    for _ in range(reps):
        reserve = float(s.initial_investors)
        active = int(s.initial_investors)
        collapse_round = None

        for t in range(1, s.horizon + 1):
            expected_entrants = base_round1 * np.power(1.0 + s.entrant_growth, t - 1)
            entrants = int(rng.poisson(max(expected_entrants, 0.0)))
            withdrawals = int(rng.binomial(active, min(max(s.withdrawal_rate, 0.0), 1.0)))
            payouts = (s.promised_return * active) + withdrawals

            reserve = reserve + entrants - payouts
            active = active - withdrawals + entrants

            if collapse_round is None and reserve < 0:
                collapse_round = t
                break

        collapse_rounds.append(collapse_round)
        final_reserves.append(reserve)

    valid_rounds = [x for x in collapse_rounds if x is not None]
    return {
        "reps": reps,
        "collapse_probability": len(valid_rounds) / reps,
        "median_collapse_round_conditional": float(np.median(valid_rounds)) if valid_rounds else None,
        "mean_final_reserve": float(np.mean(final_reserves)),
    }


def build_grids() -> dict:
    r_grid = np.array([0.005, 0.01, 0.02, 0.05, 0.10], dtype=float)
    g_grid = np.array([0.00, 0.005, 0.01, 0.015, 0.02, 0.03, 0.05, 0.08, 0.10], dtype=float)
    w_grid = np.array([0.00, 0.01, 0.02, 0.05, 0.10], dtype=float)
    return {"r_grid": r_grid, "g_grid": g_grid, "w_grid": w_grid}


def run_grid_analysis() -> dict:
    grids = build_grids()
    rng = np.random.default_rng(SEED)
    summary: dict[str, dict] = {}

    for w in grids["w_grid"]:
        collapse_round_matrix = []
        collapse_prob_matrix = []
        for r in grids["r_grid"]:
            row_round = []
            row_prob = []
            for g in grids["g_grid"]:
                s = Scenario(
                    name=f"r{r:.3f}_g{g:.3f}_w{w:.3f}",
                    promised_return=float(r),
                    entrant_growth=float(g),
                    withdrawal_rate=float(w),
                    initial_investors=100,
                )
                det = deterministic_path(s)
                mc = stochastic_collapse_stats(s, rng)
                row_round.append(det["collapse_round"] or s.horizon + 1)
                row_prob.append(mc["collapse_probability"])
            collapse_round_matrix.append(row_round)
            collapse_prob_matrix.append(row_prob)
        summary[f"w={w:.3f}"] = {
            "collapse_round_matrix": collapse_round_matrix,
            "collapse_probability_matrix": collapse_prob_matrix,
        }

    return {
        "r_grid": grids["r_grid"].tolist(),
        "g_grid": grids["g_grid"].tolist(),
        "w_grid": grids["w_grid"].tolist(),
        "slices": summary,
    }


def madoff_scale_examples() -> dict:
    outstanding_capital = 17.5e9
    promised_monthly_return = 0.01
    examples = {}
    for w in [0.00, 0.02, 0.05]:
        monthly_need = (promised_monthly_return + w) * outstanding_capital
        annual_need = monthly_need * 12.0
        examples[f"withdrawal_{int(w*100):02d}pct"] = {
            "outstanding_capital_usd": outstanding_capital,
            "promised_monthly_return": promised_monthly_return,
            "withdrawal_rate": w,
            "monthly_new_money_needed_usd": monthly_need,
            "annualized_new_money_needed_usd": annual_need,
        }
    return examples


def charles_ponzi_style_examples() -> dict:
    n0 = 100.0
    r = 0.50
    results = {}
    for w in [0.00, 0.10]:
        rounds = {}
        for horizon in [3, 5, 10]:
            entrants_this_round = flat_new_entrant_requirement(
                active_investors=n0 * np.power(1.0 + r, horizon - 1),
                r=r,
                w=w,
            )
            cumulative_people = cumulative_participants_flat_path(n0, r, w, horizon)
            rounds[str(horizon)] = {
                "new_entrants_needed_that_round_per_100_initial": entrants_this_round,
                "cumulative_participants_per_100_initial": cumulative_people,
            }
        results[f"withdrawal_{int(w*100):02d}pct"] = rounds
    return results


def make_figures(grid_results: dict, scenario_outputs: dict) -> list[str]:
    figure_paths = []

    r_grid = np.array(grid_results["r_grid"])
    g_grid = np.array(grid_results["g_grid"])
    w_key = "w=0.020"
    rounds = np.array(grid_results["slices"][w_key]["collapse_round_matrix"], dtype=float)
    probs = np.array(grid_results["slices"][w_key]["collapse_probability_matrix"], dtype=float)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    im0 = axes[0].imshow(rounds, aspect="auto", origin="lower", cmap="viridis")
    axes[0].set_title("Deterministic Collapse Round (w=2%)")
    axes[0].set_xticks(range(len(g_grid)), [f"{x:.1%}" for x in g_grid], rotation=45, ha="right")
    axes[0].set_yticks(range(len(r_grid)), [f"{x:.1%}" for x in r_grid])
    axes[0].set_xlabel("Entrant growth g")
    axes[0].set_ylabel("Promised return r")
    fig.colorbar(im0, ax=axes[0], shrink=0.85)

    im1 = axes[1].imshow(probs, aspect="auto", origin="lower", cmap="magma", vmin=0, vmax=1)
    axes[1].set_title("Monte Carlo Collapse Probability (w=2%)")
    axes[1].set_xticks(range(len(g_grid)), [f"{x:.1%}" for x in g_grid], rotation=45, ha="right")
    axes[1].set_yticks(range(len(r_grid)), [f"{x:.1%}" for x in r_grid])
    axes[1].set_xlabel("Entrant growth g")
    axes[1].set_ylabel("Promised return r")
    fig.colorbar(im1, ax=axes[1], shrink=0.85)
    fig.tight_layout()
    path = ROOT / "k1459_collapse_heatmaps.png"
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    figure_paths.append(path.name)

    fig, ax = plt.subplots(figsize=(8, 4.8))
    for key in ["stable_1pct", "critical_1pct", "aggressive_10pct"]:
        out = scenario_outputs[key]["deterministic"]
        ax.plot(out["entrant_path"][1:], label=f"{key} new entrants")
    ax.set_title("New Entrants Required/Observed by Scenario")
    ax.set_xlabel("Round")
    ax.set_ylabel("Investors")
    ax.legend()
    ax.grid(alpha=0.25)
    fig.tight_layout()
    path = ROOT / "k1459_scenario_entrants.png"
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    figure_paths.append(path.name)

    fig, ax = plt.subplots(figsize=(8, 4.8))
    for key in ["stable_1pct", "critical_1pct", "aggressive_10pct"]:
        out = scenario_outputs[key]["deterministic"]
        ax.plot(out["reserve_path"], label=f"{key} reserve")
    ax.axhline(0.0, color="black", linewidth=1, linestyle="--")
    ax.set_title("Reserve Path by Scenario")
    ax.set_xlabel("Round")
    ax.set_ylabel("Reserve (principal units)")
    ax.legend()
    ax.grid(alpha=0.25)
    fig.tight_layout()
    path = ROOT / "k1459_scenario_reserves.png"
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    figure_paths.append(path.name)

    return figure_paths


def main() -> None:
    analytical = {
        "critical_condition": "Asymptotically, entrant growth must exceed promised return growth: g > r.",
        "critical_growth_formula": "g* = r (independent of withdrawal rate w in the long-run; w changes the level, not the asymptotic slope).",
        "flat_reserve_round_requirement_formula": "E_t^flat = (r + w) * A_{t-1}",
        "active_investor_path_under_flat_reserve": "A_t = N0 * (1 + r)^t",
        "cumulative_participants_under_flat_reserve": (
            "C_T = N0 * [1 + ((r + w) / r) * ((1 + r)^T - 1)] for r > 0"
        ),
    }

    scenarios = [
        Scenario("stable_1pct", 0.01, 0.02, 0.01, 100),
        Scenario("critical_1pct", 0.01, 0.01, 0.02, 100),
        Scenario("aggressive_10pct", 0.10, 0.05, 0.05, 100),
    ]
    rng = np.random.default_rng(SEED)
    scenario_outputs = {}
    for s in scenarios:
        scenario_outputs[s.name] = {
            "parameters": asdict(s),
            "flat_requirements": {
                "round_1": flat_new_entrant_requirement(
                    s.initial_investors, s.promised_return, s.withdrawal_rate
                ),
                "round_12": flat_new_entrant_requirement(
                    active_investors_flat_path(s.initial_investors, s.promised_return, 11)[-1],
                    s.promised_return,
                    s.withdrawal_rate,
                ),
                "round_60": flat_new_entrant_requirement(
                    active_investors_flat_path(s.initial_investors, s.promised_return, 59)[-1],
                    s.promised_return,
                    s.withdrawal_rate,
                ),
                "cumulative_participants_round_60": cumulative_participants_flat_path(
                    s.initial_investors, s.promised_return, s.withdrawal_rate, 60
                ),
            },
            "deterministic": deterministic_path(s),
            "stochastic": stochastic_collapse_stats(s, rng),
        }

    grid_results = run_grid_analysis()
    figure_paths = make_figures(grid_results, scenario_outputs)

    results = {
        "experiment_id": "k1459",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "seed": SEED,
        "round_horizon": ROUND_HORIZON,
        "mc_reps": MC_REPS,
        "analytical_findings": analytical,
        "scenario_outputs": scenario_outputs,
        "grid_analysis": grid_results,
        "historical_scale_examples": {
            "madoff_scale": madoff_scale_examples(),
            "charles_ponzi_style": charles_ponzi_style_examples(),
        },
        "figures": figure_paths,
    }

    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"Wrote {RESULTS_PATH}")


if __name__ == "__main__":
    main()
