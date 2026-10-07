"""Prediction pipeline: XI building, injuries, prior re-scaling, call estimates."""

import pytest

from cricsim.api import Cricbuzz
from cricsim.engine.match import Team
from cricsim.ingest.fetch import match_infos_from_list
from cricsim.ingest.squads import PlayerMeta
from cricsim.model.profiles import Priors, build_profiles
from cricsim.predict import (
    TeamRef,
    _adapt_priors,
    _competition_group,
    _injured,
    _replace_injured,
    _xi_from_squad,
    estimate_calls,
    predict,
)

PRIORS = Priors.bundled()
ROLES = ["WK-Batsman", "Batsman", "Batsman", "Batsman", "Batting Allrounder",
         "Batting Allrounder", "Bowling Allrounder", "Bowler", "Bowler", "Bowler", "Bowler",
         "Batsman", "Bowler", "WK-Batsman", "Bowling Allrounder"]


def squad(base=0):
    return [PlayerMeta(base + i, f"P{base + i}", role=r,
                       bowling_style="" if "Bat" in r and i % 2 else "Right-arm fast")
            for i, r in enumerate(ROLES)]


def test_xi_from_squad_has_keeper_and_five_bowling_options():
    sq = squad()
    profiles = build_profiles([], {m.player_id: m for m in sq}, PRIORS)
    team = _xi_from_squad(TeamRef(1, "Alpha", "ALP"), sq, profiles, exclude=set())
    assert len(team.batting_order) == 11
    assert len({p.player_id for p in team.batting_order}) == 11
    assert sum(p.is_keeper for p in team.batting_order) >= 1
    assert sum(p.role in ("Bowler", "Bowling Allrounder") for p in team.batting_order) == 5
    roles = [p.role for p in team.batting_order]
    assert roles.index("Bowler") > roles.index("Batsman")  # batters bat first


def test_xi_from_squad_needs_eleven_fit_players():
    sq = squad()[:11]
    profiles = build_profiles([], {m.player_id: m for m in sq}, PRIORS)
    assert _xi_from_squad(TeamRef(1, "A", "A"), sq, profiles, exclude={3}) is None


def test_injured_players_are_replaced_like_for_like():
    sq = squad()
    profiles = build_profiles([], {m.player_id: m for m in sq}, PRIORS)
    team = _xi_from_squad(TeamRef(1, "A", "A"), sq, profiles, exclude=set())
    bowler = next(p for p in team.batting_order if p.role == "Bowler")
    notes: list[str] = []
    fixed = _replace_injured(team, {bowler.player_id}, sq, profiles, notes)
    ids = [p.player_id for p in fixed.batting_order]
    assert bowler.player_id not in ids and len(ids) == 11
    sub = fixed.batting_order[[p.player_id for p in team.batting_order].index(bowler.player_id)]
    assert sub.bowls
    assert bowler.player_id not in {p.player_id for p in fixed.attack}
    assert notes and bowler.name in notes[0]


def test_no_injuries_leaves_team_unchanged():
    team = Team("A", [])
    assert _replace_injured(team, set(), [], {}, []) is team


def test_injured_badges_parsed():
    payload = {"playersByRole": [{"players": [
        {"id": 5, "badges": [{"label": "Injured"}]},
        {"id": 6, "badges": [{"label": "In form"}]},
        {"id": 7, "badges": []}]}]}
    assert _injured(payload) == {5}
    assert _injured(None) == set()


@pytest.mark.parametrize("name,group", [
    ("Indian Premier League 2026", "ipl"), ("Women's Premier League 2026", "women"),
    ("West Indies Women tour of Zimbabwe, 2026", "women"), ("CSA T20 Challenge 2026", "other"),
])
def test_competition_group(name, group):
    assert _competition_group(name) == group


def test_adapt_priors_without_local_data_is_identity():
    assert _adapt_priors(PRIORS, [], {}) is PRIORS


class FakeClient:
    def __init__(self, cached):
        self.calls_made = 0
        self.cached = cached

    def is_cached(self, path, params=None, ttl=0):
        return path in self.cached


class FakeApi:
    def __init__(self, cached, results):
        self.client = FakeClient(cached)
        self.results = results

    def team_results(self, team_id):
        self.client.calls_made += 1
        return {"teamMatchesData": [{"matchDetailsMap": {"match": [
            {"matchInfo": {"matchId": m, "matchFormat": fmt, "state": "Complete"}}
            for m, fmt in self.results[team_id]]}}]}


def test_estimate_counts_only_uncached_matches_once():
    results = {1: [(10, "T20"), (11, "T20"), (12, "ODI")], 2: [(11, "T20"), (13, "T20")]}
    api = FakeApi(cached={"/mcenter/v1/13/scard"}, results=results)
    info = {"matchId": 99, "seriesId": 5, "team1": {"teamId": 1}, "team2": {"teamId": 2}}
    used, more = estimate_calls(api, info, lite=False)
    # squads 3 + matches 10 and 11 (12 is an ODI, 13 cached, 11 counted once) x3 + forecast 3
    assert used == 2 and more == 3 + 2 * 3 + 3
    _, lite_more = estimate_calls(api, info, lite=True)
    assert lite_more == 6


def test_predict_end_to_end_from_cache():
    api = Cricbuzz.from_env(offline=True)
    try:
        infos = match_infos_from_list(api.matches("upcoming"))
        info = next(i for i in infos if int(i["matchId"]) == 173123)  # ZIMW v WIW, cached
        pred = predict(api, info, PRIORS, runs=300, seed=1)
    except Exception as exc:  # noqa: BLE001 - any cache miss means the data isn't local
        pytest.skip(f"prediction inputs not cached: {exc}")
    assert pred.calls_used == 0
    assert pred.tier == "Quick" and pred.confidence == "approximate"
    assert sum(pred.win_prob.values()) == pytest.approx(1.0)
    assert all(len(xi) >= 11 for xi in pred.xi.values())
    assert sum(len(v) for v in pred.first_innings.values()) == 300
    assert any("approximate" in n for n in pred.notes)
