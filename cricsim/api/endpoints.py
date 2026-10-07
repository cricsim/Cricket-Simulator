"""One method per Cricbuzz Cricket API endpoint used by cricsim.

Usable on its own, without the simulator:

    from cricsim.api import Cricbuzz
    api = Cricbuzz.from_env()
    print(api.matches("upcoming"))

Each method picks a cache rule: finished-match data is cached
permanently, slowly changing data for hours or days, live data not at all.
"""

from __future__ import annotations

from typing import Any, Literal

from cricsim.api.client import NO_CACHE, PERMANENT, CricbuzzClient
from cricsim.config import get_settings

HOUR = 3600
DAY = 24 * HOUR

MatchList = Literal["live", "upcoming", "recent"]
SeriesType = Literal["international", "league", "domestic", "women"]


def _match_complete(data: Any) -> bool:
    return bool(data) and bool(data.get("ismatchcomplete"))


class Cricbuzz:
    def __init__(self, client: CricbuzzClient):
        self.client = client

    @classmethod
    def from_env(cls, offline: bool = False) -> Cricbuzz:
        s = get_settings()
        return cls(CricbuzzClient(s.api_key, s.api_host, s.cache_dir, offline=offline))

    # ---- matches ------------------------------------------------------------------------

    def matches(self, kind: MatchList) -> dict:
        """GET /matches/v1/{live|upcoming|recent}"""
        ttl = NO_CACHE if kind == "live" else HOUR
        return self.client.get(f"/matches/v1/{kind}", ttl=ttl) or {}

    def match_info(self, match_id: int) -> dict:
        """GET /mcenter/v1/{matchId}: teams, venue, toss, state."""
        return self.client.get(
            f"/mcenter/v1/{match_id}", ttl=PERMANENT,
            store_if=lambda d: bool(d) and str(d.get("state", "")).lower() == "complete",
        ) or {}

    def scorecard(self, match_id: int, complete: bool = False) -> dict:
        """GET /mcenter/v1/{matchId}/scard: cached permanently once the match is complete.

        Pass complete=True when the match list already says so; abandoned matches never
        set `ismatchcomplete` and would otherwise be re-fetched on every run.
        """
        return self.client.get(
            f"/mcenter/v1/{match_id}/scard", ttl=PERMANENT,
            store_if=None if complete else _match_complete,
        ) or {}

    def balls_graph(self, match_id: int, innings: int, complete: bool) -> dict:
        """GET /mcenter/v1/{matchId}/ballsGraph?iid=N: every delivery of one innings.

        `complete` must come from the scorecard or match list; a ballsGraph fetched while
        the match is live is never cached (it would be stored half-finished).
        """
        return self.client.get(
            f"/mcenter/v1/{match_id}/ballsGraph", {"iid": innings},
            ttl=PERMANENT if complete else NO_CACHE,
        ) or {}

    def livescore(self, match_id: int) -> dict:
        """GET /mcenter/v1/{matchId}/livescore: never cached."""
        return self.client.get(f"/mcenter/v1/{match_id}/livescore", ttl=NO_CACHE) or {}

    def live_scorecard(self, match_id: int) -> dict:
        """Scorecard of a live match: never cached."""
        return self.client.get(f"/mcenter/v1/{match_id}/scard", ttl=NO_CACHE) or {}

    # ---- series -------------------------------------------------------------------------

    def series_archives(self, kind: SeriesType, year: int, last_id: int | None = None) -> dict:
        """GET /series/v1/archives/{type}?year=YYYY"""
        return self.client.get(
            f"/series/v1/archives/{kind}", {"year": year, "lastId": last_id}, ttl=7 * DAY
        ) or {}

    def series_matches(self, series_id: int) -> dict:
        """GET /series/v1/{seriesId}: fixtures and results."""
        return self.client.get(f"/series/v1/{series_id}", ttl=6 * HOUR) or {}

    def series_squads(self, series_id: int) -> dict:
        """GET /series/v1/{seriesId}/squads"""
        return self.client.get(f"/series/v1/{series_id}/squads", ttl=DAY) or {}

    def squad_players(self, series_id: int, squad_id: int) -> dict:
        """GET /series/v1/{seriesId}/squads/{squadId}"""
        return self.client.get(f"/series/v1/{series_id}/squads/{squad_id}", ttl=DAY) or {}

    def points_table(self, series_id: int) -> dict:
        """GET /stats/v1/series/{seriesId}/points-table"""
        return self.client.get(f"/stats/v1/series/{series_id}/points-table", ttl=6 * HOUR) or {}

    # ---- teams and players --------------------------------------------------------------

    def team_results(self, team_id: int) -> dict:
        """GET /teams/v1/{teamId}/results"""
        return self.client.get(f"/teams/v1/{team_id}/results", ttl=6 * HOUR) or {}

    def player_info(self, player_id: int) -> dict:
        """GET /stats/v1/player/{playerId}: role, batting and bowling style."""
        return self.client.get(f"/stats/v1/player/{player_id}", ttl=7 * DAY) or {}

    def player_batting(self, player_id: int) -> dict:
        """GET /stats/v1/player/{playerId}/batting: Test/ODI/T20/IPL career table."""
        return self.client.get(f"/stats/v1/player/{player_id}/batting", ttl=7 * DAY) or {}

    def player_bowling(self, player_id: int) -> dict:
        """GET /stats/v1/player/{playerId}/bowling"""
        return self.client.get(f"/stats/v1/player/{player_id}/bowling", ttl=7 * DAY) or {}

    # ---- fantasy / forecast ------------------------------------------------------------

    def forecast_index(self, match_id: int) -> dict | None:
        """GET /forecast/v1/index/{matchId}: which forecast tabs exist."""
        return self.client.get(f"/forecast/v1/index/{match_id}", ttl=6 * HOUR)

    def forecast_players(self, match_id: int) -> dict | None:
        """GET /forecast/v1/allPlayers/{matchId}: squads, badges, playing styles."""
        return self.client.get(f"/forecast/v1/allPlayers/{match_id}", ttl=6 * HOUR)

    def forecast_matchups(self, match_id: int) -> dict | None:
        """GET /forecast/v1/matchUps/{matchId}"""
        return self.client.get(f"/forecast/v1/matchUps/{match_id}", ttl=6 * HOUR)

    def forecast_venue(self, match_id: int) -> dict | None:
        """GET /forecast/v1/venueInfo/{matchId}"""
        return self.client.get(f"/forecast/v1/venueInfo/{match_id}", ttl=6 * HOUR)

    def forecast_prediction(self, match_id: int) -> dict | None:
        """GET /forecast/v1/{matchId}/partnerPredictions: Cricbuzz's own win forecast."""
        return self.client.get(f"/forecast/v1/{match_id}/partnerPredictions", ttl=6 * HOUR)
