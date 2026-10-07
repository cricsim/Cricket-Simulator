"""Parse /mcenter/v1/{matchId}/scard into innings records."""

from __future__ import annotations

from dataclasses import dataclass, field

from cricsim.ingest.parse_dismissal import Dismissal, parse_dismissal


@dataclass
class BattingEntry:
    player_id: int
    name: str
    position: int  # 1-based batting position (row order)
    runs: int
    balls: int
    fours: int
    sixes: int
    dismissal: Dismissal
    is_keeper: bool = False


@dataclass
class BowlingEntry:
    player_id: int
    name: str
    overs: float
    runs: int
    wickets: int


@dataclass
class FallOfWicket:
    batter_id: int
    ball_nbr: int  # legal-ball number, joins to Delivery via ballsGraph ballNbr


@dataclass
class Innings:
    innings_id: int
    team: str
    score: int
    wickets: int
    overs: float
    batting: list[BattingEntry] = field(default_factory=list)
    bowling: list[BowlingEntry] = field(default_factory=list)
    fow: list[FallOfWicket] = field(default_factory=list)
    extras: dict[str, int] = field(default_factory=dict)

    @property
    def xi(self) -> list[int]:
        """All 11 listed batters, including those who did not bat."""
        return [b.player_id for b in self.batting]


@dataclass
class Scorecard:
    complete: bool
    status: str
    innings: list[Innings]


def parse_scorecard(data: dict) -> Scorecard:
    innings: list[Innings] = []
    for inn in data.get("scorecard", []):
        rec = Innings(
            innings_id=int(inn["inningsid"]),
            team=inn.get("batteamsname", ""),
            score=int(inn.get("score", 0)),
            wickets=int(inn.get("wickets", 0)),
            overs=float(inn.get("overs", 0)),
            extras={k: int(v) for k, v in (inn.get("extras") or {}).items()},
        )
        for pos, b in enumerate(inn.get("batsman", []), start=1):
            rec.batting.append(
                BattingEntry(
                    player_id=int(b["id"]),
                    name=b.get("name", ""),
                    position=pos,
                    runs=int(b.get("runs", 0)),
                    balls=int(b.get("balls", 0)),
                    fours=int(b.get("fours", 0)),
                    sixes=int(b.get("sixes", 0)),
                    dismissal=parse_dismissal(b.get("outdec")),
                    is_keeper=bool(b.get("iskeeper")),
                )
            )
        for w in inn.get("bowler", []):
            rec.bowling.append(
                BowlingEntry(
                    player_id=int(w["id"]),
                    name=w.get("name", ""),
                    overs=float(w.get("overs", 0)),
                    runs=int(w.get("runs", 0)),
                    wickets=int(w.get("wickets", 0)),
                )
            )
        for f in (inn.get("fow") or {}).get("fow", []):
            rec.fow.append(FallOfWicket(int(f["batsmanid"]), int(f["ballnbr"])))
        innings.append(rec)
    return Scorecard(bool(data.get("ismatchcomplete")), data.get("status", ""), innings)


def dismissed_batters(inn: Innings, deliveries) -> dict[int, int]:
    """Map each wicket delivery (by `seq`) to the batter dismissed on it.

    Fall-of-wicket entries record the legal-ball count at the time, so a wicket off a
    wide or no-ball has a fow number one below the delivery's ballNbr, and retirements
    appear in fow with no wicket delivery at all. Pairing wicket deliveries with
    non-retirement fow entries in order handles both.
    """
    retired = {b.player_id for b in inn.batting if b.dismissal.is_retirement}
    fow = [f for f in sorted(inn.fow, key=lambda f: f.ball_nbr) if f.batter_id not in retired]
    wickets = [d for d in deliveries if d.innings == inn.innings_id and d.wicket]
    if len(fow) == len(wickets):
        return {d.seq: f.batter_id for d, f in zip(wickets, fow)}
    # Counts disagree (missing deliveries): fall back to matching ball numbers.
    by_nbr = {f.ball_nbr: f.batter_id for f in fow}
    out = {}
    for d in wickets:
        pid = by_nbr.get(d.ball_nbr) or (by_nbr.get(d.ball_nbr - 1) if not d.legal else None)
        out[d.seq] = pid or d.batter_id
    return out
