"""Engine tests on synthetic players with the bundled priors (no API key needed)."""

import random

from cricsim.engine.ball import OutcomeModel
from cricsim.engine.match import Team, simulate_innings, simulate_match
from cricsim.model.profiles import PlayerProfile, Priors


def _team(name: str, base_id: int, priors: Priors) -> Team:
    players = []
    for i in range(11):
        bowls = i >= 6
        btype = "spin" if i in (9, 10) else "pace"
        players.append(PlayerProfile(
            player_id=base_id + i, name=f"{name}{i + 1}", role="Bowler" if bowls else "Batsman",
            bowl_type=btype if bowls else None, is_keeper=i == 0,
            bat=priors.pos_bat[min(i // 3, 3)],
            position=i + 1, bowl_balls=500 if bowls else 0, bowl=priors.type_bowl[btype],
            overs_per_match=3.8 if bowls else 0.0, over_pref=priors.type_overs[btype],
            wide_rate=priors.wide_rate))
    return Team(name, players)


def test_innings_respects_laws():
    priors = Priors.bundled()
    model = OutcomeModel(priors)
    a, b = _team("A", 0, priors), _team("B", 100, priors)
    rng = random.Random(1)
    for _ in range(200):
        inn = simulate_innings(model, a, b, rng)
        assert inn.balls <= 120 and inn.wickets <= 10
        assert inn.balls == 120 or inn.wickets == 10
        assert all(c.balls <= 24 for c in inn.bowling.values())  # 4-over cap
        assert inn.runs == sum(c.runs for c in inn.batting.values()) + inn.extras


def test_chase_stops_at_target():
    priors = Priors.bundled()
    model = OutcomeModel(priors)
    a, b = _team("A", 0, priors), _team("B", 100, priors)
    rng = random.Random(2)
    for _ in range(200):
        inn = simulate_innings(model, a, b, rng, target=150)
        if inn.runs >= 150:
            assert inn.runs <= 150 + 6 + 5  # last ball can overshoot by a boundary (+ no-ball)


def test_scores_are_t20_like():
    priors = Priors.bundled()
    model = OutcomeModel(priors)
    a, b = _team("A", 0, priors), _team("B", 100, priors)
    rng = random.Random(3)
    totals = [simulate_match(model, a, b, rng).innings[0].runs for _ in range(400)]
    mean = sum(totals) / len(totals)
    assert 140 < mean < 230
