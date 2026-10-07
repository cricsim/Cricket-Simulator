"""Innings and match simulation."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from cricsim.engine.ball import OutcomeModel
from cricsim.engine.bowling_plan import BowlingPlan
from cricsim.model.profiles import RUNS, PlayerProfile, W


@dataclass
class Team:
    name: str
    batting_order: list[PlayerProfile]  # 11 (or 12 with an impact player)
    bowlers: list[PlayerProfile] | None = None  # defaults to batting_order

    @property
    def attack(self) -> list[PlayerProfile]:
        return self.bowlers or self.batting_order


@dataclass
class BatCard:
    runs: int = 0
    balls: int = 0
    fours: int = 0
    sixes: int = 0
    how_out: str = "not out"


@dataclass
class BowlCard:
    balls: int = 0
    runs: int = 0
    wickets: int = 0
    wides: int = 0
    noballs: int = 0


@dataclass
class InningsResult:
    team: str
    runs: int = 0
    wickets: int = 0
    balls: int = 0  # legal balls
    extras: int = 0
    batting: dict[int, BatCard] = field(default_factory=dict)
    bowling: dict[int, BowlCard] = field(default_factory=dict)
    fall_of_wickets: list[tuple[int, int, int]] = field(default_factory=list)  # (runs, wkt, pid)

    @property
    def overs(self) -> str:
        return f"{self.balls // 6}.{self.balls % 6}" if self.balls % 6 else str(self.balls // 6)


@dataclass
class MatchResult:
    team1: str  # batted first
    team2: str
    innings: list[InningsResult]
    winner: str | None
    margin: str
    toss: str
    super_over: list[InningsResult] | None = None


def _dismissal(kind_probs: dict[str, float], bowler: PlayerProfile, fielders: list[PlayerProfile],
               rng: random.Random) -> tuple[str, bool]:
    """Sample a dismissal description; returns (text, credited_to_bowler)."""
    kinds = {k: v for k, v in kind_probs.items() if k != "unknown"}
    if bowler.bowl_type != "spin":
        kinds.pop("stumped", None)
    kind = rng.choices(list(kinds), weights=list(kinds.values()))[0]
    keeper = next((p for p in fielders if p.is_keeper), None)
    others = [p for p in fielders if p.player_id != bowler.player_id]
    if kind == "caught":
        if rng.random() < 0.06:
            return f"c & b {bowler.name}", True
        catcher = keeper if keeper and rng.random() < 0.18 else rng.choice(others)
        return f"c {catcher.name} b {bowler.name}", True
    if kind == "stumped":
        return f"st {keeper.name if keeper else 'keeper'} b {bowler.name}", True
    if kind == "run out":
        return f"run out ({rng.choice(others).name})", False
    if kind == "lbw":
        return f"lbw b {bowler.name}", True
    if kind == "hit wicket":
        return f"hit wicket b {bowler.name}", True
    return f"b {bowler.name}", True


def simulate_innings(model: OutcomeModel, batting: Team, fielding: Team, rng: random.Random,
                     target: int | None = None, max_overs: int = 20,
                     max_wickets: int = 10) -> InningsResult:
    pr = model.priors
    order = batting.batting_order
    res = InningsResult(team=batting.name)
    plan = BowlingPlan(fielding.attack, max_overs=max_overs)
    striker, non_striker, next_in = 0, 1, 2
    for p in order[:2]:
        res.batting[p.player_id] = BatCard()
    free_hit = False
    wide_k = list(range(1, len(pr.wide_runs) + 1))
    bye_k = list(range(1, len(pr.bye_runs) + 1))

    def done() -> bool:
        return res.wickets >= max_wickets or (target is not None and res.runs >= target)

    for over in range(max_overs):
        bowler = plan.next_bowler(over, rng)
        bc = res.bowling.setdefault(bowler.player_id, BowlCard())
        legal = 0
        while legal < 6 and not done():
            bat = order[striker]
            card = res.batting[bat.player_id]
            required = None
            if target is not None:
                balls_left = max(max_overs * 6 - res.balls, 1)
                required = (target - res.runs) * 6 / balls_left
            u = rng.random()
            if u < bowler.wide_rate:
                runs = rng.choices(wide_k, weights=pr.wide_runs)[0]
                res.runs += runs
                res.extras += runs
                bc.runs += runs
                bc.wides += 1
                continue
            if u < bowler.wide_rate + pr.noball_rate:
                cum = model.cumulative(bat, bowler, over, res.wickets, required, free_hit=True)
                k = model.sample(cum, rng)
                bat_runs = RUNS[k]
                res.runs += 1 + bat_runs
                res.extras += 1
                bc.runs += 1 + bat_runs
                bc.noballs += 1
                card.runs += bat_runs
                card.balls += 1
                card.fours += bat_runs == 4
                card.sixes += bat_runs == 6
                if bat_runs % 2:
                    striker, non_striker = non_striker, striker
                free_hit = True
                continue
            legal += 1
            res.balls += 1
            bc.balls += 1
            card.balls += 1
            if rng.random() < pr.bye_rate:
                runs = rng.choices(bye_k, weights=pr.bye_runs)[0]
                res.runs += runs
                res.extras += runs
                if runs % 2:
                    striker, non_striker = non_striker, striker
                free_hit = False
                continue
            cum = model.cumulative(bat, bowler, over, res.wickets, required, free_hit)
            k = model.sample(cum, rng)
            free_hit = False
            if k == W:
                text, credited = _dismissal(pr.dismissal_kinds, bowler, fielding.batting_order, rng)
                card.how_out = text
                bc.wickets += credited
                res.wickets += 1
                res.fall_of_wickets.append((res.runs, res.wickets, bat.player_id))
                if res.wickets < max_wickets and next_in < len(order):
                    striker = next_in
                    res.batting[order[next_in].player_id] = BatCard()
                    next_in += 1
                elif res.wickets < max_wickets:
                    res.wickets = max_wickets  # ran out of batters
                continue
            runs = RUNS[k]
            res.runs += runs
            bc.runs += runs
            card.runs += runs
            card.fours += runs == 4
            card.sixes += runs == 6
            if runs % 2:
                striker, non_striker = non_striker, striker
        striker, non_striker = non_striker, striker
        if done():
            break
    return res


def _super_over_team(team: Team) -> Team:
    best_bat = sorted(team.batting_order, key=lambda p: -(p.bat[4] + p.bat[5]))[:3]
    death = sorted((p for p in team.attack if p.bowls),
                   key=lambda p: -sum(p.over_pref[15:]) if p.over_pref else 0)
    return Team(team.name, best_bat, death[:1] or team.attack[:1])


def simulate_match(model: OutcomeModel, team_a: Team, team_b: Team,
                   rng: random.Random | None = None, bat_first: str | None = None) -> MatchResult:
    rng = rng or random.Random()
    toss_winner = team_a if rng.random() < 0.5 else team_b
    other = team_b if toss_winner is team_a else team_a
    field_first = rng.random() < model.priors.toss_field_rate
    first, second = (other, toss_winner) if field_first else (toss_winner, other)
    if bat_first is not None:
        first, second = (team_a, team_b) if team_a.name == bat_first else (team_b, team_a)
    toss = f"{toss_winner.name} won the toss and chose to {'field' if field_first else 'bat'}"

    inn1 = simulate_innings(model, first, second, rng)
    inn2 = simulate_innings(model, second, first, rng, target=inn1.runs + 1)
    if inn2.runs > inn1.runs:
        winner, margin = second.name, f"{10 - inn2.wickets} wkts"
    elif inn1.runs > inn2.runs:
        winner, margin = first.name, f"{inn1.runs - inn2.runs} runs"
    else:
        so_first = simulate_innings(model, _super_over_team(second), _super_over_team(first), rng,
                                    max_overs=1, max_wickets=2)
        so_second = simulate_innings(model, _super_over_team(first), _super_over_team(second), rng,
                                     target=so_first.runs + 1, max_overs=1, max_wickets=2)
        if so_second.runs > so_first.runs:
            winner = first.name
        elif so_first.runs > so_second.runs:
            winner = second.name
        else:
            winner = rng.choice([first.name, second.name])
        return MatchResult(first.name, second.name, [inn1, inn2], winner, "super over", toss,
                           [so_first, so_second])
    return MatchResult(first.name, second.name, [inn1, inn2], winner, margin, toss)
