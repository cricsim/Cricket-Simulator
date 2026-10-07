"""Checks against saved live responses in tests/fixtures/ (skipped when absent).

Fixtures are raw API responses, so they are not committed until the API publisher
allows it. Run `python scripts/save_fixtures.py` to create them locally.
"""

import json
from pathlib import Path

import pytest

from cricsim.ingest.parse_balls import innings_total, parse_balls_graph
from cricsim.ingest.parse_scorecard import parse_scorecard

FIX = Path(__file__).parent / "fixtures"
MATCH = 149618  # IPL 2026, 1st match

pytestmark = pytest.mark.skipif(not (FIX / f"scard_{MATCH}.json").exists(),
                                reason="live fixtures not present")


def test_balls_graph_reconciles_with_scorecard():
    card = parse_scorecard(json.loads((FIX / f"scard_{MATCH}.json").read_text()))
    assert card.complete and len(card.innings) == 2
    for inn in card.innings:
        balls = parse_balls_graph(json.loads((FIX / f"balls_{MATCH}_{inn.innings_id}.json")
                                             .read_text()), inn.innings_id)
        assert innings_total(balls) == inn.score
        faced: dict[int, int] = {}
        for b in balls:
            if b.faced:
                faced[b.batter_id] = faced.get(b.batter_id, 0) + 1
        for bat in inn.batting:
            assert faced.get(bat.player_id, 0) == bat.balls, bat.name
        wickets = {b.ball_nbr: b.batter_id for b in balls if b.wicket}
        assert wickets == {f.ball_nbr: f.batter_id for f in inn.fow}
