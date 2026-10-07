"""Edge cases for bowling plans, profiles and match outcomes (no API key needed)."""

import random
from collections import Counter

import pytest

from cricsim.engine.ball import OutcomeModel
from cricsim.engine.bowling_plan import BowlingPlan
from cricsim.engine.match import Team, simulate_innings, simulate_match
from cricsim.model.profiles import N_OUT, PlayerProfile, Priors, shrink

PRIORS = Priors.bundled()


def player(pid, *, bowls=False, btype="pace", keeper=False, opm=3.8, pref=None, bat=None):
    return PlayerProfile(
        player_id=pid, name=f"P{pid}", role="Bowler" if bowls else "Batsman",
        bowl_type=btype if bowls else None, is_keeper=keeper,
        bat=bat or PRIORS.pos_bat[1], position=pid % 11 + 1,
        bowl_balls=400 if bowls else 0, bowl=PRIORS.type_bowl[btype],
        overs_per_match=opm if bowls else 0.0,
        over_pref=pref or PRIORS.type_overs[btype], wide_rate=PRIORS.wide_rate)


def xi(base, n_bowlers=5):
    return [player(base + i, keeper=i == 0, bowls=i >= 11 - n_bowlers) for i in range(11)]


@pytest.mark.parametrize("n_bowlers", [5, 6, 7])
def test_plan_always_completes_20_overs_within_rules(n_bowlers):
    rng = random.Random(n_bowlers)
    for _ in range(300):
        plan = BowlingPlan(xi(0, n_bowlers))
        seq = [plan.next_bowler(o, rng).player_id for o in range(20)]
        counts = Counter(seq)
        assert max(counts.values()) <= 4
        assert all(a != b for a, b in zip(seq, seq[1:])), seq


def test_four_bowlers_forces_a_part_timer():
    rng = random.Random(1)
    for _ in range(100):
        team = xi(0, 4)
        plan = BowlingPlan(team)
        seq = [plan.next_bowler(o, rng) for o in range(20)]
        assert max(Counter(p.player_id for p in seq).values()) <= 4
        assert any(not p.bowls for p in seq)  # someone from outside the 4 bowled
        assert not any(p.is_keeper for p in seq)


def test_death_specialist_bowls_at_the_death():
    death = [0.0] * 15 + [0.2] * 5
    team = xi(0, 5)
    team[10] = player(10, bowls=True, pref=death)
    rng = random.Random(3)
    late = 0
    for _ in range(200):
        plan = BowlingPlan(team)
        late += sum(plan.next_bowler(o, rng).player_id == 10 and o >= 15 for o in range(20))
    assert late / 200 > 2.5  # most of their overs come in 16-20


def test_one_over_super_over_cap():
    plan = BowlingPlan(xi(0), max_overs=1)
    assert plan.cap == 1
    plan.next_bowler(0, random.Random(0))


def test_shrinkage_moves_with_sample_size():
    prior = [1 / N_OUT] * N_OUT
    few = shrink([0, 0, 0, 0, 0, 10, 0], prior, 90)
    many = shrink([0, 0, 0, 0, 0, 1000, 0], prior, 90)
    assert few[5] < many[5]
    assert abs(sum(few) - 1) < 1e-9 and abs(sum(many) - 1) < 1e-9
    assert shrink([0] * N_OUT, prior, 90) == prior


def test_better_batters_score_more():
    strong = [0.2, 0.35, 0.06, 0.0, 0.2, 0.15, 0.04]
    weak = [0.45, 0.33, 0.04, 0.0, 0.08, 0.03, 0.07]
    rng = random.Random(5)
    model = OutcomeModel(PRIORS)
    bowl = Team("B", xi(100))

    def team(dist):
        return Team("A", [player(i, keeper=i == 0, bowls=i >= 6, bat=dist) for i in range(11)])

    s = sum(simulate_innings(model, team(strong), bowl, rng).runs for _ in range(300))
    w = sum(simulate_innings(model, team(weak), bowl, rng).runs for _ in range(300))
    assert s > w * 1.3


def test_free_hit_has_no_wicket():
    model = OutcomeModel(PRIORS)
    p, b = player(1), player(2, bowls=True)
    cum = model.cumulative(p, b, 18, 3, None, free_hit=True)
    assert cum[-2] == pytest.approx(1.0)  # all mass before W


def test_chasing_pressure_raises_risk():
    model = OutcomeModel(PRIORS)
    p, b = player(1), player(2, bowls=True)

    def dist(rr):
        cum = model.cumulative(p, b, 17, 4, rr)
        return [cum[0]] + [c - a for a, c in zip(cum, cum[1:])]

    easy, hard = dist(5.0), dist(16.0)
    assert hard[6] > easy[6]  # more wickets when the required rate is high


def test_match_always_has_winner_and_consistent_margin():
    model = OutcomeModel(PRIORS)
    a, b = Team("A", xi(0)), Team("B", xi(100))
    rng = random.Random(11)
    for _ in range(500):
        m = simulate_match(model, a, b, rng)
        assert m.winner in ("A", "B")
        i1, i2 = m.innings
        if m.margin.endswith("wkts"):
            assert i2.runs > i1.runs and m.winner == m.team2
        elif m.margin.endswith("runs"):
            assert i1.runs > i2.runs and m.winner == m.team1
        else:
            assert m.margin == "super over" and i1.runs == i2.runs and m.super_over


def test_seed_makes_runs_reproducible():
    model = OutcomeModel(PRIORS)
    a, b = Team("A", xi(0)), Team("B", xi(100))
    r1 = simulate_match(model, a, b, random.Random(42))
    r2 = simulate_match(OutcomeModel(PRIORS), a, b, random.Random(42))
    assert [i.runs for i in r1.innings] == [i.runs for i in r2.innings]
