"""Live API schema checks: every field cricsim relies on (opt-in, ~9 calls).

    CRICSIM_LIVE=1 pytest tests/test_live_api.py

Run nightly in CI with a repository secret so response-shape changes are caught early.
Responses are fetched with NO_CACHE, so this always talks to the API.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from cricsim.api import Cricbuzz
from cricsim.api.client import NO_CACHE
from cricsim.ingest.parse_balls import parse_balls_graph
from cricsim.ingest.parse_scorecard import parse_scorecard

pytestmark = pytest.mark.skipif(os.environ.get("CRICSIM_LIVE") != "1",
                                reason="set CRICSIM_LIVE=1 to call the live API")
MATCH, SERIES, FORECAST_MATCH = 149618, 9241, 155409  # IPL 2026 opener, season, final
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def api():
    a = Cricbuzz.from_env()
    if not a.client.api_key:
        pytest.skip("RAPIDAPI_KEY not set")
    return a


def live(api, path, params=None):
    return api.client.get(path, params, ttl=NO_CACHE)


def test_quota_header_reported(api):
    live(api, "/matches/v1/upcoming")
    assert api.client.quota.remaining is not None and api.client.quota.limit


def test_match_list_shape(api):
    data = live(api, "/matches/v1/upcoming")
    info = data["typeMatches"][0]["seriesMatches"][0]["seriesAdWrapper"]["matches"][0]["matchInfo"]
    for key in ("matchId", "seriesId", "seriesName", "matchFormat", "state", "team1", "team2"):
        assert key in info, key
    assert {"teamId", "teamSName", "teamName"} <= set(info["team1"])


def test_scorecard_shape(api):
    data = live(api, f"/mcenter/v1/{MATCH}/scard")
    inn = data["scorecard"][0]
    assert {"inningsid", "batteamsname", "score", "wickets", "overs", "batsman", "bowler",
            "fow", "extras"} <= set(inn)
    assert {"id", "name", "runs", "balls", "fours", "sixes", "outdec"} <= set(inn["batsman"][0])
    assert {"batsmanid", "ballnbr"} <= set(inn["fow"]["fow"][0])
    assert data["ismatchcomplete"] is True
    assert parse_scorecard(data).innings[0].score == 201


def test_balls_graph_shape_and_reconciliation(api):
    data = live(api, f"/mcenter/v1/{MATCH}/ballsGraph", {"iid": 1})
    ball = data["balls"][0]
    assert {"timestamp", "ballNbr", "overNum", "batsmanStrikerId", "bowlerStrikerId",
            "totalRuns", "ballLabel"} <= set(ball)
    balls = parse_balls_graph(data, 1)  # raises on any unknown label
    assert sum(b.total_runs for b in balls) == 201 and sum(b.legal for b in balls) == 120


def test_series_and_squads_shape(api):
    matches = live(api, f"/series/v1/{SERIES}")
    first = matches["matchDetails"][0]["matchDetailsMap"]["match"][0]["matchInfo"]
    assert {"matchId", "state", "matchFormat", "startDate"} <= set(first)
    squads = live(api, f"/series/v1/{SERIES}/squads")["squads"]
    squad = next(s for s in squads if s.get("squadId"))
    players = live(api, f"/series/v1/{SERIES}/squads/{squad['squadId']}")["player"]
    rows = [p for p in players if not p.get("isHeader")]
    assert {"id", "name", "role", "battingStyle"} <= set(rows[0])
    assert any("bowlingStyle" in p for p in rows)


def test_forecast_shape(api):
    index = live(api, f"/forecast/v1/index/{FORECAST_MATCH}")
    assert {t["path"] for t in index["tabs"]} >= {"allPlayers"}
    players = live(api, f"/forecast/v1/allPlayers/{FORECAST_MATCH}")
    p = players["playersByRole"][0]["players"][0]
    assert {"id", "name", "badges"} <= set(p)
    pred = live(api, f"/forecast/v1/{FORECAST_MATCH}/partnerPredictions")
    assert "Probability" in pred["cbPrediction"]["value"]


@pytest.mark.parametrize("script", sorted(p.name for p in (ROOT / "examples").glob("0*.py")))
def test_examples_run(script):
    result = subprocess.run([sys.executable, str(ROOT / "examples" / script)], cwd=ROOT,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip()
