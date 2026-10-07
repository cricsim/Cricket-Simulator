"""Build simulator teams from real scorecards."""

from __future__ import annotations

from cricsim.engine.match import Team
from cricsim.ingest.fetch import MatchRecord
from cricsim.model.profiles import PlayerProfile


def teams_from_record(rec: MatchRecord, profiles: dict[int, PlayerProfile]) -> tuple[Team, Team]:
    """(team batting first, team batting second) with the real batting order and attack."""
    inns = [i for i in rec.scorecard.innings if i.innings_id in (1, 2)]
    if len(inns) < 2:
        raise ValueError(f"match {rec.match_id} has fewer than two innings")
    first, second = inns[0], inns[1]

    def team(bat_inn, bowl_inn) -> Team:
        order = [profiles[b.player_id] for b in bat_inn.batting if b.player_id in profiles]
        attack = [profiles[b.player_id] for b in bowl_inn.bowling if b.player_id in profiles]
        # Include other XI members so part-timers are available if needed.
        attack += [p for p in order if p not in attack]
        return Team(bat_inn.team, order, attack)

    return team(first, second), team(second, first)


def latest_xi(team: str, records: list[MatchRecord], profiles: dict[int, PlayerProfile]) -> Team:
    """The team's most recent XI in `records`, matched by short name (e.g. "RCB")."""
    key = team.lower()
    for rec in sorted(records, key=lambda r: -r.start_ms):
        inns = [i for i in rec.scorecard.innings if i.innings_id in (1, 2)]
        if len(inns) < 2:
            continue
        for bat, bowl in ((inns[0], inns[1]), (inns[1], inns[0])):
            if bat.team.lower() == key:
                order = [profiles[b.player_id] for b in bat.batting if b.player_id in profiles]
                attack = [profiles[b.player_id] for b in bowl.bowling if b.player_id in profiles]
                attack += [p for p in order if p not in attack]
                return Team(bat.team, order, attack)
    names = sorted({i.team for r in records for i in r.scorecard.innings})
    raise ValueError(f"team {team!r} not found; choose from {', '.join(names)}")
