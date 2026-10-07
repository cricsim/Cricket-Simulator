"""Build player profiles and league priors from ball-by-ball match records.

Outcomes of a ball faced are bucketed as OUTCOMES = 0, 1, 2, 3, 4, 6, W.
- Batter view: every ball faced (wides excluded); W when the striker is dismissed.
- Bowler view: legal balls only; W only for dismissals credited to the bowler.
Byes and leg byes count as dots for both; they are modelled as team extras instead.

Player distributions are shrunk toward a role prior (batting-position group or bowling
type) with weight k, so a player with a handful of balls stays close to the prior.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from cricsim.ingest.fetch import MatchRecord
from cricsim.ingest.parse_dismissal import BOWLER_KINDS
from cricsim.ingest.parse_scorecard import dismissed_batters
from cricsim.ingest.squads import PlayerMeta

OUTCOMES = ("0", "1", "2", "3", "4", "6", "W")
N_OUT = len(OUTCOMES)
W = OUTCOMES.index("W")
RUNS = (0, 1, 2, 3, 4, 6, 0)

PHASES = ("powerplay", "middle", "death")
WKT_BUCKETS = (2, 4, 6, 11)  # wickets lost < 2, < 4, < 6, else
RRR_BUCKETS = (7.0, 9.0, 11.0, 13.0, math.inf)  # required run rate upper bounds
POS_BOUNDS = (4, 6, 8, 99)  # batting positions 1-3, 4-5, 6-7, 8-11

K_BAT = 90.0  # prior weight in balls
K_BOWL = 150.0
K_FACTOR = 400.0  # shrinkage for context factors
K_OVERS = 3.0  # prior weight (in overs) for over-by-over usage


def phase_of(over: int) -> int:
    return 0 if over < 6 else (1 if over < 15 else 2)


def bucket_index(value: float, bounds: tuple) -> int:
    for i, b in enumerate(bounds):
        if value < b:
            return i
    return len(bounds) - 1


def run_bucket(runs: int) -> int:
    if runs >= 6:
        return 5
    if runs >= 4:
        return 4
    return runs


def normalise(v: list[float]) -> list[float]:
    s = sum(v)
    return [x / s for x in v] if s > 0 else [1.0 / len(v)] * len(v)


def shrink(counts: list[float], prior: list[float], k: float) -> list[float]:
    n = sum(counts)
    return [(c + k * p) / (n + k) for c, p in zip(counts, prior)]


def recency_weight(start_ms: int, latest_ms: int, half_life_days: float = 365.0) -> float:
    age_days = max(latest_ms - start_ms, 0) / 86_400_000
    return 0.5 ** (age_days / half_life_days)


@dataclass
class Priors:
    """League-level parameters. Aggregates only, safe to ship with the package."""

    name: str
    balls: int
    bat: list[float]  # batter-view outcome distribution, all phases
    bowl: list[float]  # bowler-view outcome distribution, all phases
    phase_factor: list[list[float]]  # [phase][outcome] multiplier vs `bat`
    wkt_factor: list[list[list[float]]]  # [phase][wkt bucket][outcome]
    rrr_factor: list[list[list[float]]]  # [phase][rrr bucket][outcome], 2nd innings
    inn2_factor: list[list[float]]  # [phase][outcome] 2nd-innings multiplier (dew, chasing)
    pos_bat: list[list[float]]  # [position group][outcome]
    type_bowl: dict[str, list[float]]  # {"pace"|"spin": outcome dist}
    type_overs: dict[str, list[float]]  # {"pace"|"spin": share of overs by over index}
    wide_rate: float  # wides per legal ball
    wide_runs: list[float]  # P(1..5 runs | wide)
    noball_rate: float  # no-balls per legal ball
    bye_rate: float  # byes + leg byes per legal ball
    bye_runs: list[float]  # P(1..4 runs | bye)
    dismissal_kinds: dict[str, float]  # share of each dismissal kind
    first_innings_avg: float
    bat_first_win_rate: float
    toss_field_rate: float = 0.75

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=1)

    @classmethod
    def load(cls, path: Path) -> Priors:
        return cls(**json.loads(path.read_text()))

    @classmethod
    def bundled(cls, name: str = "ipl") -> Priors:
        return cls.load(Path(__file__).resolve().parent.parent / "priors" / f"{name}.json")


@dataclass
class PlayerProfile:
    player_id: int
    name: str
    team: str = ""
    role: str = ""
    bowl_type: str | None = None
    is_keeper: bool = False
    matches: float = 0.0
    bat_balls: float = 0.0
    bat: list[float] = field(default_factory=list)  # shrunk outcome distribution
    position: float = 6.0  # weighted average batting position
    bowl_balls: float = 0.0
    bowl: list[float] = field(default_factory=list)
    overs_per_match: float = 0.0  # when selected and bowling
    over_pref: list[float] = field(default_factory=list)  # share of their overs by index
    wide_rate: float = 0.0

    @property
    def bowls(self) -> bool:
        return self.bowl_balls >= 6 or (self.bowl_type is not None and
                                        self.role.lower().startswith(("bowl", "bowling")))


# ---- building -----------------------------------------------------------------------------


@dataclass
class _Acc:
    """Weighted counts collected while scanning deliveries."""

    name: str = ""
    bat: list[float] = field(default_factory=lambda: [0.0] * N_OUT)
    bowl: list[float] = field(default_factory=lambda: [0.0] * N_OUT)
    wides: float = 0.0
    pos_sum: float = 0.0
    pos_n: float = 0.0
    matches: float = 0.0
    overs_by_idx: list[float] = field(default_factory=lambda: [0.0] * 20)
    bowl_matches: float = 0.0
    keeper: float = 0.0


def _scan(records: Iterable[MatchRecord], latest_ms: int, half_life: float):
    acc: dict[int, _Acc] = defaultdict(_Acc)
    lg_bat = [[0.0] * N_OUT for _ in PHASES]
    lg_bowl = [0.0] * N_OUT
    wkt = [[[0.0] * N_OUT for _ in WKT_BUCKETS] for _ in PHASES]
    rrr = [[[0.0] * N_OUT for _ in RRR_BUCKETS] for _ in PHASES]
    inn2_phase = [[0.0] * N_OUT for _ in PHASES]
    pos_bat = [[0.0] * N_OUT for _ in POS_BOUNDS]
    ex = defaultdict(float)
    wide_runs = [0.0] * 5
    bye_runs = [0.0] * 4
    kinds = defaultdict(float)
    first_inn, bat_first_wins, results = [], 0, 0

    for rec in records:
        w = recency_weight(rec.start_ms, latest_ms, half_life)
        card = rec.scorecard
        inns = {i.innings_id: i for i in card.innings if i.innings_id in (1, 2)}
        if 1 in inns:
            first_inn.append(inns[1].score)
        if 1 in inns and 2 in inns:
            results += 1
            bat_first_wins += inns[1].score > inns[2].score
        pos_group_of: dict[int, int] = {}
        kind_of: dict[int, str] = {}
        for inn in inns.values():
            for b in inn.batting:
                a = acc[b.player_id]
                a.name = b.name
                a.matches += w
                a.keeper += w * b.is_keeper
                pos_group_of[b.player_id] = bucket_index(b.position, POS_BOUNDS)
                if b.balls > 0 or b.dismissal.is_out:
                    a.pos_sum += w * b.position
                    a.pos_n += w
                kind_of[b.player_id] = b.dismissal.kind
                if b.dismissal.is_out:
                    kinds[b.dismissal.kind] += w
        bowled_overs: dict[int, set] = defaultdict(set)
        for inn_id, inn in inns.items():
            dismissed_on = dismissed_batters(inn, rec.deliveries)
            target = inns[1].score + 1 if inn_id == 2 and 1 in inns else None
            runs = wickets = legal = 0
            for d in (x for x in rec.deliveries if x.innings == inn_id):
                ph = phase_of(d.over)
                dismissed = dismissed_on.get(d.seq, d.batter_id) if d.wicket else None
                kind = kind_of.get(dismissed, "unknown") if dismissed else None
                if d.faced:
                    o = W if dismissed == d.batter_id else run_bucket(d.bat_runs)
                    acc[d.batter_id].bat[o] += w
                    lg_bat[ph][o] += w
                    wkt[ph][bucket_index(wickets, WKT_BUCKETS)][o] += w
                    pos_bat[pos_group_of.get(d.batter_id, 3)][o] += w
                    if target is not None:
                        inn2_phase[ph][o] += w
                        balls_left = max(120 - legal, 1)
                        need_rate = (target - runs) * 6 / balls_left
                        rrr[ph][bucket_index(need_rate, RRR_BUCKETS)][o] += w
                if d.legal:
                    credited = dismissed is not None and kind in BOWLER_KINDS
                    o = W if credited else run_bucket(d.bat_runs)
                    acc[d.bowler_id].bowl[o] += w
                    lg_bowl[o] += w
                    bowled_overs[d.bowler_id].add((inn_id, d.over))
                    ex["legal"] += w
                    if d.extra in ("b", "lb"):
                        ex["byes"] += w
                        bye_runs[min(d.extra_runs, 4) - 1] += w
                if d.extra == "wd":
                    acc[d.bowler_id].wides += w
                    ex["wides"] += w
                    wide_runs[min(max(d.total_runs, 1), 5) - 1] += w
                elif d.extra == "nb":
                    ex["noballs"] += w
                runs += d.total_runs
                wickets += d.wicket
                legal += d.legal
        for pid, overs in bowled_overs.items():
            a = acc[pid]
            a.bowl_matches += w
            for _inn, ov in overs:
                a.overs_by_idx[min(ov, 19)] += w

    return dict(acc=acc, lg_bat=lg_bat, lg_bowl=lg_bowl, wkt=wkt, rrr=rrr,
                inn2_phase=inn2_phase, pos_bat=pos_bat, ex=ex, wide_runs=wide_runs,
                bye_runs=bye_runs, kinds=kinds, first_inn=first_inn,
                bat_first_wins=bat_first_wins, results=results)


def _factor(counts: list[float], base: list[float]) -> list[float]:
    """Shrunk multiplier of a context's distribution relative to `base`."""
    dist = shrink(counts, base, K_FACTOR)
    return [d / b if b > 0 else 1.0 for d, b in zip(dist, base)]


def build_priors(records: list[MatchRecord], meta: dict[int, PlayerMeta], name: str,
                 half_life: float = 365.0) -> Priors:
    latest = max(r.start_ms for r in records)
    s = _scan(records, latest, half_life)
    bat_all = normalise([sum(p[o] for p in s["lg_bat"]) for o in range(N_OUT)])
    phase_dist = [normalise(p) for p in s["lg_bat"]]
    inn2_dist = [normalise(p) for p in s["inn2_phase"]]

    type_bowl = {t: [0.0] * N_OUT for t in ("pace", "spin")}
    type_overs = {t: [0.0] * 20 for t in ("pace", "spin")}
    for pid, a in s["acc"].items():
        t = meta[pid].bowl_type if pid in meta else None
        if t:
            type_bowl[t] = [x + y for x, y in zip(type_bowl[t], a.bowl)]
            type_overs[t] = [x + y for x, y in zip(type_overs[t], a.overs_by_idx)]
    ex = s["ex"]
    total_kinds = sum(s["kinds"].values())
    return Priors(
        name=name,
        balls=int(ex["legal"]),
        bat=bat_all,
        bowl=normalise(s["lg_bowl"]),
        phase_factor=[[d / b for d, b in zip(phase_dist[p], bat_all)] for p in range(3)],
        wkt_factor=[[_factor(c, phase_dist[p]) for c in s["wkt"][p]] for p in range(3)],
        rrr_factor=[[_factor(c, inn2_dist[p]) for c in s["rrr"][p]] for p in range(3)],
        inn2_factor=[_factor(s["inn2_phase"][p], phase_dist[p]) for p in range(3)],
        pos_bat=[normalise(c) if sum(c) else bat_all for c in s["pos_bat"]],
        type_bowl={t: normalise(v) if sum(v) else normalise(s["lg_bowl"])
                   for t, v in type_bowl.items()},
        type_overs={t: normalise(v) for t, v in type_overs.items()},
        wide_rate=ex["wides"] / ex["legal"],
        wide_runs=normalise(s["wide_runs"]),
        noball_rate=ex["noballs"] / ex["legal"],
        bye_rate=ex["byes"] / ex["legal"],
        bye_runs=normalise(s["bye_runs"]),
        dismissal_kinds={k: v / total_kinds for k, v in sorted(s["kinds"].items())},
        first_innings_avg=sum(s["first_inn"]) / max(len(s["first_inn"]), 1),
        bat_first_win_rate=s["bat_first_wins"] / max(s["results"], 1),
    )


def build_profiles(records: list[MatchRecord], meta: dict[int, PlayerMeta], priors: Priors,
                   half_life: float = 365.0, latest_ms: int | None = None
                   ) -> dict[int, PlayerProfile]:
    """Profiles for every player appearing in `records` (and any extra player in `meta`)."""
    latest = latest_ms or (max(r.start_ms for r in records) if records else 0)
    s = _scan(records, latest, half_life)
    profiles: dict[int, PlayerProfile] = {}
    for pid in set(s["acc"]) | set(meta):
        a = s["acc"].get(pid, _Acc())
        m = meta.get(pid)
        position = a.pos_sum / a.pos_n if a.pos_n else (9.0 if m and m.role == "Bowler" else 5.0)
        pos_prior = priors.pos_bat[bucket_index(round(position), POS_BOUNDS)]
        bowl_type = m.bowl_type if m else ("pace" if sum(a.bowl) else None)
        type_key = bowl_type or "pace"
        bowl_balls = sum(a.bowl)
        n_overs = sum(a.overs_by_idx)
        over_pref = shrink(a.overs_by_idx, priors.type_overs[type_key], K_OVERS)
        profiles[pid] = PlayerProfile(
            player_id=pid,
            name=(m.name if m else a.name) or str(pid),
            team=m.team if m else "",
            role=m.role if m else "",
            bowl_type=bowl_type,
            is_keeper=(m.is_keeper if m else a.keeper > a.matches / 2),
            matches=round(a.matches, 2),
            bat_balls=round(sum(a.bat), 1),
            bat=shrink(a.bat, pos_prior, K_BAT),
            position=round(position, 2),
            bowl_balls=round(bowl_balls, 1),
            bowl=shrink(a.bowl, priors.type_bowl[type_key], K_BOWL),
            overs_per_match=round(n_overs / a.bowl_matches, 2) if a.bowl_matches else 0.0,
            over_pref=over_pref,
            wide_rate=(a.wides + 60 * priors.wide_rate) / (bowl_balls + 60),
        )
    return profiles


def save_profiles(profiles: dict[int, PlayerProfile], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({str(k): asdict(v) for k, v in profiles.items()}))


def load_profiles(path: Path) -> dict[int, PlayerProfile]:
    data = json.loads(path.read_text())
    return {int(k): PlayerProfile(**v) for k, v in data.items()}
