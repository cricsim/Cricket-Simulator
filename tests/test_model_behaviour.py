"""Simulated players should look like their real selves (needs the cached IPL seasons)."""

import random
import statistics
from collections import defaultdict

import pytest

from cricsim.api import Cricbuzz
from cricsim.dataset import load_seasons
from cricsim.engine.ball import OutcomeModel
from cricsim.engine.match import simulate_match
from cricsim.model.profiles import Priors, build_profiles
from cricsim.model.teams import teams_from_record

SIMS_PER_MATCH = 25


def _corr(xs, ys):
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
    return num / den


@pytest.fixture(scope="module")
def season():
    api = Cricbuzz.from_env(offline=True)
    if not (api.client.is_cached("/series/v1/9241") and api.client.is_cached("/series/v1/9237")):
        pytest.skip("IPL seasons not cached")
    history, meta = load_seasons(api, [9237, 9241])
    records = [r for r in history if r.series_id == 9241]
    priors = Priors.bundled()
    profiles = build_profiles(history, meta, priors)
    real_bat, real_bowl = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    sim_bat, sim_bowl = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    model, rng = OutcomeModel(priors), random.Random(9)
    for rec in records:
        try:
            a, b = teams_from_record(rec, profiles)
        except ValueError:
            continue
        for inn in rec.scorecard.innings[:2]:
            for x in inn.batting:
                real_bat[x.player_id][0] += x.runs
                real_bat[x.player_id][1] += x.balls
        for d in rec.deliveries:
            if d.innings in (1, 2):
                real_bowl[d.bowler_id][0] += d.total_runs if d.extra not in ("b", "lb") else 0
                real_bowl[d.bowler_id][1] += d.legal
        for _ in range(SIMS_PER_MATCH):
            m = simulate_match(model, a, b, rng, bat_first=a.name)
            for inn in m.innings:
                for pid, c in inn.batting.items():
                    sim_bat[pid][0] += c.runs
                    sim_bat[pid][1] += c.balls
                for pid, c in inn.bowling.items():
                    sim_bowl[pid][0] += c.runs
                    sim_bowl[pid][1] += c.balls
    return real_bat, real_bowl, sim_bat, sim_bowl


def test_strike_rates_track_real_strike_rates(season):
    real_bat, _, sim_bat, _ = season
    players = [p for p, (r, b) in real_bat.items() if b >= 150 and sim_bat[p][1] > 0]
    real = [100 * real_bat[p][0] / real_bat[p][1] for p in players]
    sim = [100 * sim_bat[p][0] / sim_bat[p][1] for p in players]
    assert len(players) >= 40
    assert _corr(real, sim) > 0.6
    assert statistics.mean(abs(r - s) for r, s in zip(real, sim)) < 15


def test_economy_tracks_real_economy(season):
    _, real_bowl, _, sim_bowl = season
    players = [p for p, (r, b) in real_bowl.items() if b >= 180 and sim_bowl[p][1] > 0]
    real = [6 * real_bowl[p][0] / real_bowl[p][1] for p in players]
    sim = [6 * sim_bowl[p][0] / sim_bowl[p][1] for p in players]
    assert len(players) >= 30
    assert _corr(real, sim) > 0.5
    assert statistics.mean(abs(r - s) for r, s in zip(real, sim)) < 1.0


def test_main_bowlers_get_their_overs(season):
    _, real_bowl, _, sim_bowl = season
    # Share of legal balls bowled by the real regulars should be similar in simulation.
    regulars = [p for p, (_, b) in real_bowl.items() if b >= 180]
    real_share = sum(real_bowl[p][1] for p in regulars) / sum(b for _, b in real_bowl.values())
    sim_share = sum(sim_bowl[p][1] for p in regulars) / sum(b for _, b in sim_bowl.values())
    assert abs(real_share - sim_share) < 0.08
