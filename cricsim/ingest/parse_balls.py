"""Parse /mcenter/v1/{matchId}/ballsGraph into a list of deliveries.

Verified against live IPL 2025-26 responses:
- `balls[]` comes newest first; sort by `timestamp`.
- `ballNbr` counts legal balls; a wide or no-ball shares the number of the next legal ball.
- `totalRuns` of all deliveries sums to the innings total.
- Labels: `•` or `0` dot, `1`-`6` runs off the bat, `Wd`/`WdN` wides, `NN` no-ball
  (+ runs off the bat), `NBN`/`NLN` no-ball + byes/leg byes, `BN` byes, `LN` leg byes.
  A leading `W` marks a wicket on that delivery: `W`, `W1` (run-out after a completed
  run), `WWd` (stumped/run out off a wide), `WB1`. Boundary byes carry a `FOUR` event,
  so the event field must not be used to credit the batter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LABEL_RE = re.compile(r"^(W(?!d))?(Wd|NB|NL|N|B|L)?(\d*)(W)?$")


class UnknownBallLabel(ValueError):
    pass


@dataclass(frozen=True)
class Delivery:
    innings: int
    seq: int  # 0-based order within the innings
    ball_nbr: int  # legal-ball number; joins to the scorecard's fall of wickets
    over: int  # 0-based over index (overNum 13.4 -> 13)
    batter_id: int
    bowler_id: int
    label: str
    total_runs: int
    bat_runs: int  # runs credited to the batter
    extra: str | None  # None, "wd", "nb", "b", "lb"
    extra_runs: int
    wicket: bool

    @property
    def legal(self) -> bool:
        """Counts towards the over (wides and no-balls don't)."""
        return self.extra not in ("wd", "nb")

    @property
    def faced(self) -> bool:
        """Counts as a ball faced by the batter (everything except wides)."""
        return self.extra != "wd"


def parse_label(label: str, total_runs: int) -> tuple[int, str | None, int, bool]:
    """Return (bat_runs, extra_type, extra_runs, wicket) for one ballLabel.

    `totalRuns` is treated as authoritative for the delivery's total, because the
    number inside labels like `Wd4` is not always the full total.
    """
    if label in ("•", "0", ""):
        return 0, None, 0, False
    m = LABEL_RE.match(label)
    if not m:
        raise UnknownBallLabel(label)
    lead_w, kind, num, trail_w = m.groups()
    wicket = lead_w is not None or trail_w is not None
    if kind is None:
        if not num and not wicket:
            raise UnknownBallLabel(label)
        # Plain runs, or a wicket (runs completed before a run-out count to the batter).
        return total_runs, None, 0, wicket
    if kind == "Wd":
        return 0, "wd", total_runs, wicket
    if kind == "N":
        # One no-ball extra; the rest was scored off the bat.
        return max(total_runs - 1, 0), "nb", 1, wicket
    if kind in ("NB", "NL"):
        # No-ball plus byes / leg byes: nothing to the batter.
        return 0, "nb", total_runs, wicket
    extra = "b" if kind == "B" else "lb"
    return 0, extra, total_runs, wicket


def _fill_missing_ids(balls: list[dict]) -> list[dict]:
    """Handle rows that arrive without striker/bowler IDs.

    Seen in IPL 2026: a phantom 0-run row duplicating the ballNbr and overNum of a real
    delivery. Those are dropped. Any other ID-less row keeps its runs, with the bowler
    taken from the same over and the batter from the neighbouring delivery.
    """
    complete = {(x["ballNbr"], x["overNum"]) for x in balls
                if "batsmanStrikerId" in x and "bowlerStrikerId" in x}
    balls = [x for x in balls if "batsmanStrikerId" in x and "bowlerStrikerId" in x
             or (x.get("ballNbr"), x.get("overNum")) not in complete]
    for i, b in enumerate(balls):
        if "batsmanStrikerId" in b and "bowlerStrikerId" in b:
            continue
        over = int(float(b["overNum"]))
        same_over = [x for x in balls
                     if int(float(x["overNum"])) == over and "bowlerStrikerId" in x]
        neighbours = [balls[j] for j in (i + 1, i - 1) if 0 <= j < len(balls)
                      and "batsmanStrikerId" in balls[j]]
        if same_over:
            b.setdefault("bowlerStrikerId", same_over[0]["bowlerStrikerId"])
        if neighbours:
            b.setdefault("batsmanStrikerId", neighbours[0]["batsmanStrikerId"])
        b["_imputed"] = True
    return balls


def parse_balls_graph(data: dict, innings: int) -> list[Delivery]:
    balls = sorted((dict(b) for b in data.get("balls", [])), key=lambda b: b["timestamp"])
    balls = _fill_missing_ids(balls)
    out: list[Delivery] = []
    for seq, b in enumerate(balls):
        label = str(b.get("ballLabel", ""))
        total = int(b.get("totalRuns", 0))
        bat_runs, extra, extra_runs, wicket = parse_label(label, total)
        out.append(
            Delivery(
                innings=innings,
                seq=seq,
                ball_nbr=int(b.get("ballNbr", 0)),
                over=int(float(b["overNum"])),
                batter_id=int(b["batsmanStrikerId"]),
                bowler_id=int(b["bowlerStrikerId"]),
                label=label,
                total_runs=total,
                bat_runs=bat_runs,
                extra=extra,
                extra_runs=extra_runs,
                wicket=wicket,
            )
        )
    return out


def innings_total(deliveries: list[Delivery]) -> int:
    return sum(d.total_runs for d in deliveries)
