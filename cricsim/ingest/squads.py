"""Player metadata (role, batting and bowling style) from series squads."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from cricsim.api import Cricbuzz

SPIN_WORDS = ("spin", "break", "orthodox", "googly", "chinaman", "leg", "off", "wrist")


@dataclass
class PlayerMeta:
    player_id: int
    name: str
    role: str = ""  # "Batsman", "Bowler", "Batting Allrounder", "WK-Batsman", ...
    batting_style: str = ""
    bowling_style: str = ""
    team: str = ""

    @property
    def bowl_type(self) -> str | None:
        """'pace', 'spin' or None (doesn't bowl / unknown)."""
        style = self.bowling_style.lower()
        if not style:
            return None
        if "medium" in style or "fast" in style:
            return "pace"
        if any(w in style for w in SPIN_WORDS):
            return "spin"
        return "pace"

    @property
    def is_keeper(self) -> bool:
        return self.role.lower().startswith("wk")

    def to_dict(self) -> dict:
        return asdict(self)


def series_squads(api: Cricbuzz, series_id: int) -> dict[str, list[PlayerMeta]]:
    """{team name: [PlayerMeta, ...]} for every squad in a series."""
    out: dict[str, list[PlayerMeta]] = {}
    for sq in api.series_squads(series_id).get("squads", []):
        if not sq.get("squadId"):
            continue  # header row
        team = sq.get("squadType", "")
        players = []
        for p in api.squad_players(series_id, int(sq["squadId"])).get("player", []):
            if p.get("isHeader") or "id" not in p:
                continue
            players.append(PlayerMeta(
                player_id=int(p["id"]), name=p.get("name", ""), role=p.get("role", ""),
                batting_style=p.get("battingStyle", ""), bowling_style=p.get("bowlingStyle", ""),
                team=team,
            ))
        out[team] = players
    return out
