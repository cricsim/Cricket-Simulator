"""Out-of-sample win-probability backtest on a completed season.

For every match in date order, priors and profiles are rebuilt from the earlier seasons
plus the matches already played, so nothing from the match itself (or later) leaks in.
Teams use the real XIs; the toss is simulated. Scores are compared with a coin flip and
with Cricbuzz's own pre-match forecast (partnerPredictions).

    python scripts/backtest.py --season 9241 --history 9237 --runs 1000
"""

from __future__ import annotations

import argparse
import math
import random
import re

from cricsim.api import Cricbuzz
from cricsim.dataset import load_seasons
from cricsim.engine.ball import OutcomeModel
from cricsim.engine.match import simulate_match
from cricsim.model.profiles import build_priors, build_profiles
from cricsim.model.teams import teams_from_record

PRED_RE = re.compile(r"^(?P<team>\w+) Wins \((?P<pct>\d+(?:\.\d+)?)% Probability\)")


def cricbuzz_prob(api: Cricbuzz, match_id: int, team1: str) -> float | None:
    """Cricbuzz's pre-match probability that `team1` wins, if published."""
    data = api.forecast_prediction(match_id) or {}
    m = PRED_RE.match((data.get("cbPrediction") or {}).get("value", ""))
    if not m:
        return None
    p = float(m["pct"]) / 100
    return p if m["team"] == team1 else 1 - p


def scores(probs: list[float], outcomes: list[int]) -> dict[str, float]:
    eps = 1e-6
    n = len(probs)
    return {
        "log_loss": -sum(math.log(max(p if y else 1 - p, eps))
                         for p, y in zip(probs, outcomes)) / n,
        "brier": sum((p - y) ** 2 for p, y in zip(probs, outcomes)) / n,
        "accuracy": (sum((p > 0.5) == bool(y) for p, y in zip(probs, outcomes) if p != 0.5)
                     / decided) if (decided := sum(p != 0.5 for p in probs)) else float("nan"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=9241, help="series to evaluate (IPL 2026)")
    ap.add_argument("--history", type=int, nargs="*", default=[9237], help="earlier series")
    ap.add_argument("--runs", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    api = Cricbuzz.from_env()
    history, meta = load_seasons(api, args.history)
    season, season_meta = load_seasons(api, [args.season])
    meta.update(season_meta)
    season.sort(key=lambda r: r.start_ms)
    rng = random.Random(args.seed)

    rows = []
    for i, rec in enumerate(season):
        inns = [x for x in rec.scorecard.innings if x.innings_id in (1, 2)]
        if len(inns) < 2 or inns[0].score == inns[1].score:
            continue  # no result or tie decided by super over
        past = history + season[:i]
        priors = build_priors(past, meta, "backtest")
        profiles = build_profiles(past, meta, priors, latest_ms=rec.start_ms)
        # Debutants with no earlier balls get a priors-only profile from squad metadata.
        missing = {b.player_id for x in inns for b in x.batting} - set(profiles)
        debut_meta = {m: meta[m] for m in missing if m in meta}
        profiles.update(build_profiles([], debut_meta, priors))
        try:
            first, second = teams_from_record(rec, profiles)
        except ValueError:
            continue
        model = OutcomeModel(priors)
        wins = sum(simulate_match(model, first, second, rng).winner == first.name
                   for _ in range(args.runs))
        ours = wins / args.runs
        cb = cricbuzz_prob(api, rec.match_id, first.name)
        won = int(inns[0].score > inns[1].score)
        rows.append((rec.match_id, first.name, second.name, ours, cb, won))
        print(f"{rec.match_id} {first.name:>5} v {second.name:<5} ours {ours:.2f}  "
              f"cricbuzz {'  - ' if cb is None else f'{cb:.2f}'}  {'won' if won else 'lost'}")

    outcomes = [r[5] for r in rows]
    print(f"\n{len(rows)} matches, {api.client.calls_made} API calls")
    report = {"coin flip": [0.5] * len(rows), "cricsim": [r[3] for r in rows]}
    for name, probs in report.items():
        result = scores(probs, outcomes)
        print(f"{name:>12}: " + "  ".join(f"{k} {v:.3f}" for k, v in result.items()))
    both = [r for r in rows if r[4] is not None]
    if both:
        y = [r[5] for r in both]
        print(f"\nOn the {len(both)} matches with a Cricbuzz forecast:")
        for name, probs in (("coin flip", [0.5] * len(both)), ("cricsim", [r[3] for r in both]),
                            ("cricbuzz", [r[4] for r in both])):
            print(f"{name:>12}: " + "  ".join(f"{k} {v:.3f}" for k, v in scores(probs, y).items()))


if __name__ == "__main__":
    main()
