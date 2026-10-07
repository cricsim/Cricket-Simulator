"""Randomised tests: label grammar and engine invariants over random players."""

import random
import string

import pytest

from cricsim.engine.ball import OutcomeModel
from cricsim.engine.match import Team, simulate_match
from cricsim.ingest.parse_balls import UnknownBallLabel, parse_label
from cricsim.model.profiles import N_OUT, PlayerProfile, Priors

PRIORS = Priors.bundled()


def test_every_grammar_label_conserves_runs():
    for wicket in ("", "W"):
        for kind in ("", "Wd", "N", "NB", "NL", "B", "L"):
            for n in range(0, 7):
                label = f"{wicket}{kind}{n if n or kind else ''}" or "•"
                if label in ("", "W0"):
                    continue
                total = n + (1 if kind in ("N", "NB", "NL") else 0) if kind != "Wd" else max(n, 1)
                bat, extra, extra_runs, out = parse_label(label, total)
                assert bat + extra_runs == total, label
                assert out == (wicket == "W"), label
                assert (extra is None) == (kind == ""), label


def test_garbage_labels_only_raise_unknown_label():
    rng = random.Random(0)
    alphabet = string.ascii_letters + string.digits + "•-+ "
    for _ in range(5000):
        label = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 5)))
        try:
            parse_label(label, rng.randint(0, 7))
        except UnknownBallLabel:
            pass


def random_dist(rng, wicket_scale=1.0):
    v = [rng.random() ** 2 + 0.01 for _ in range(N_OUT)]
    v[-1] *= wicket_scale
    s = sum(v)
    return [x / s for x in v]


def random_team(rng, name, base):
    size = rng.choice([11, 11, 12])  # 12 = impact player
    n_bowlers = rng.randint(3, 8)
    players = []
    for i in range(size):
        bowls = i >= size - n_bowlers
        pref = random_dist(rng) * 3
        pref = [x / sum(pref[:20]) for x in pref[:20]]
        players.append(PlayerProfile(
            player_id=base + i, name=f"{name}{i}", role="Bowler" if bowls else "Batsman",
            bowl_type=rng.choice(["pace", "spin"]) if bowls else None, is_keeper=i == 0,
            bat=random_dist(rng, rng.uniform(0.2, 3)), position=i + 1,
            bowl_balls=rng.randint(0, 900) if bowls else 0,
            bowl=random_dist(rng, rng.uniform(0.2, 3)),
            overs_per_match=rng.uniform(0.5, 4) if bowls else 0.0, over_pref=pref,
            wide_rate=rng.uniform(0, 0.2)))
    return Team(name, players)


@pytest.mark.parametrize("seed", range(6))
def test_engine_invariants_with_random_players(seed):
    rng = random.Random(seed)
    model = OutcomeModel(PRIORS)
    for _ in range(60):
        a, b = random_team(rng, "A", 0), random_team(rng, "B", 100)
        m = simulate_match(model, a, b, rng)
        for k, inn in enumerate(m.innings):
            assert inn.balls <= 120 and inn.wickets <= 10
            assert inn.runs == sum(c.runs for c in inn.batting.values()) + inn.extras
            assert sum(c.balls for c in inn.bowling.values()) == inn.balls
            assert max(c.balls for c in inn.bowling.values()) <= 24
            assert sum(c.wickets for c in inn.bowling.values()) <= inn.wickets
            if k == 1:
                assert inn.runs <= m.innings[0].runs + 1 + 6 + 5 or inn.balls == 120
        assert m.winner in ("A", "B")
