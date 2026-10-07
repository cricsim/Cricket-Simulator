"""Pre-match prediction for an upcoming T20.

Quick tier: each team's last few completed T20s (scorecard + ball-by-ball) build light
profiles, blended with bundled priors that are re-scaled to the competition's scoring level.
Lite tier: no match history; players come from squad roles and the bundled priors only.
Fantasy data (§6), when Cricbuzz publishes it for the match, removes injured players and
shows Cricbuzz's own forecast next to ours.
"""

from __future__ import annotations

import random
import re
import statistics
from dataclasses import dataclass, field

from cricsim.api import Cricbuzz
from cricsim.engine.ball import OutcomeModel
from cricsim.engine.match import MatchResult, Team, simulate_match
from cricsim.ingest.fetch import (
    MatchRecord,
    fetch_match,
    is_complete,
    match_infos_from_list,
    match_infos_from_results,
)
from cricsim.ingest.squads import PlayerMeta, series_squads
from cricsim.model.profiles import PlayerProfile, Priors, build_priors, build_profiles

QUICK_MATCHES_PER_TEAM = 5
LOCAL_PRIOR_WEIGHT = 500.0  # balls of local data that count as much as the bundled priors


@dataclass
class TeamRef:
    team_id: int
    name: str
    short: str


@dataclass
class Prediction:
    match_id: int
    title: str
    tier: str
    team1: TeamRef
    team2: TeamRef
    runs: int
    win_prob: dict[str, float]
    first_innings: dict[str, list[int]]  # batting-first team -> simulated totals
    sample: MatchResult
    profiles: dict[int, PlayerProfile]
    xi: dict[str, list[str]]
    confidence: str
    notes: list[str] = field(default_factory=list)
    cricbuzz_forecast: str | None = None
    calls_used: int = 0


def upcoming_t20s(api: Cricbuzz) -> list[dict]:
    infos = match_infos_from_list(api.matches("upcoming"))
    t20 = [i for i in infos if i.get("matchFormat") == "T20" and not is_complete(i)]
    return sorted(t20, key=lambda i: int(i.get("startDate", 0)))


def _team_ref(t: dict) -> TeamRef:
    return TeamRef(int(t["teamId"]), t.get("teamName", ""), t.get("teamSName", ""))


def _adapt_priors(base: Priors, records: list[MatchRecord], meta: dict[int, PlayerMeta]) -> Priors:
    """Re-scale outcome priors to the competition's scoring level using local data.

    Data-hungry context factors (phase, wickets, chase) keep the bundled values.
    """
    if not records:
        return base
    local = build_priors(records, meta, "local")
    w = local.balls / (local.balls + LOCAL_PRIOR_WEIGHT)

    def mix(a: list[float], b: list[float]) -> list[float]:
        return [(1 - w) * x + w * y for x, y in zip(a, b)]

    return Priors(**{
        **base.__dict__,
        "name": f"{base.name}+local",
        "bat": mix(base.bat, local.bat),
        "bowl": mix(base.bowl, local.bowl),
        "pos_bat": [mix(a, b) for a, b in zip(base.pos_bat, local.pos_bat)],
        "type_bowl": {t: mix(base.type_bowl[t], local.type_bowl[t]) for t in base.type_bowl},
        "first_innings_avg": (1 - w) * base.first_innings_avg + w * local.first_innings_avg,
    })


def _forecast(api: Cricbuzz, match_id: int) -> tuple[dict | None, str | None]:
    """(allPlayers payload, Cricbuzz prediction text) when forecast tabs exist."""
    idx = api.forecast_index(match_id) or {}
    tabs = {t.get("path") for t in (idx.get("tabs") or [])}
    players = api.forecast_players(match_id) if "allPlayers" in tabs else None
    prediction = None
    if tabs:
        pred = api.forecast_prediction(match_id) or {}
        prediction = (pred.get("cbPrediction") or {}).get("value")
    return players, prediction


def _injured(players: dict | None) -> set[int]:
    out = set()
    for group in (players or {}).get("playersByRole", []):
        for p in group.get("players", []):
            if any(b.get("label") == "Injured" for b in p.get("badges", [])):
                out.add(int(p["id"]))
    return out


def _xi_from_records(team: TeamRef, records: list[MatchRecord],
                     profiles: dict[int, PlayerProfile]) -> Team | None:
    """Batting order and attack from the team's most recent match."""
    for rec in sorted(records, key=lambda r: -r.start_ms):
        inns = {i.innings_id: i for i in rec.scorecard.innings if i.innings_id in (1, 2)}
        bat = next((i for i in inns.values() if i.team == team.short), None)
        bowl = next((i for i in inns.values() if i.team != team.short), None)
        if bat is None or bowl is None:
            continue
        order = [profiles[b.player_id] for b in bat.batting if b.player_id in profiles]
        attack = [profiles[b.player_id] for b in bowl.bowling if b.player_id in profiles]
        attack += [p for p in order if p not in attack]
        return Team(team.short or team.name, order, attack)
    return None


_ROLE_ORDER = {"wk-batsman": 0, "batsman": 1, "batting allrounder": 2,
               "bowling allrounder": 3, "bowler": 4}


def _xi_from_squad(team: TeamRef, squad: list[PlayerMeta],
                   profiles: dict[int, PlayerProfile], exclude: set[int]) -> Team | None:
    """Pick an XI by role when there is no recent match: 1 keeper, 5 batters/all-rounders
    and 5 bowling options, batting order by role."""
    pool = [m for m in squad if m.player_id not in exclude]
    if len(pool) < 11:
        return None
    by_role = sorted(pool, key=lambda m: _ROLE_ORDER.get(m.role.lower(), 2))
    keeper = [m for m in by_role if m.is_keeper][:1]
    bowlers = [m for m in by_role if m.role.lower() in ("bowler", "bowling allrounder")][:5]
    rest = [m for m in by_role if m not in keeper and m not in bowlers]
    xi = (keeper + rest)[: 11 - len(bowlers)] + bowlers
    xi = sorted(xi[:11], key=lambda m: _ROLE_ORDER.get(m.role.lower(), 2))
    order = [profiles[m.player_id] for m in xi]
    return Team(team.short or team.name, order, order)


def _replace_injured(team: Team, injured: set[int], squad: list[PlayerMeta],
                     profiles: dict[int, PlayerProfile], notes: list[str]) -> Team:
    if not injured:
        return team
    in_xi = {p.player_id for p in team.batting_order}
    bench = [profiles[m.player_id] for m in squad
             if m.player_id not in in_xi and m.player_id not in injured and m.player_id in profiles]
    subs: dict[int, PlayerProfile] = {}
    for p in team.batting_order:
        if p.player_id in injured:
            sub = next((b for b in bench if b.bowls == p.bowls), bench[0] if bench else None)
            if sub:
                bench.remove(sub)
                subs[p.player_id] = sub
                notes.append(f"{p.name} is marked injured by Cricbuzz; replaced by {sub.name}")
    order = [subs.get(p.player_id, p) for p in team.batting_order]
    attack = [subs.get(p.player_id, p) for p in team.attack]
    return Team(team.name, order, [p for p in attack if p.player_id not in injured])


def _competition_group(series_name: str) -> str:
    name = series_name.lower()
    if "indian premier league" in name:
        return "ipl"
    if re.search(r"women|wpl", name):
        return "women"
    return "other"


def predict(api: Cricbuzz, info: dict, priors: Priors, runs: int = 2000, lite: bool = False,
            seed: int | None = None) -> Prediction:
    calls_before = api.client.calls_made
    match_id = int(info["matchId"])
    t1, t2 = _team_ref(info["team1"]), _team_ref(info["team2"])
    notes: list[str] = []

    # Squads: bowling styles and roles (2-3 calls, cached for a day).
    meta: dict[int, PlayerMeta] = {}
    squads_by_team: dict[str, list[PlayerMeta]] = {}
    if info.get("seriesId"):
        for name, players in series_squads(api, int(info["seriesId"])).items():
            squads_by_team[name] = players
            for p in players:
                meta[p.player_id] = p

    def squad_for(team: TeamRef) -> list[PlayerMeta]:
        for name, players in squads_by_team.items():
            n = name.lower()
            if n in (team.name.lower(), team.short.lower()) or team.name.lower() in n:
                return players
        return []

    records: list[MatchRecord] = []
    if not lite:
        seen: set[int] = set()
        for team in (t1, t2):
            results = match_infos_from_results(api.team_results(team.team_id))
            recent = [r for r in results if r.get("matchFormat") == "T20" and is_complete(r)]
            for r in recent[:QUICK_MATCHES_PER_TEAM]:
                if int(r["matchId"]) in seen:
                    continue
                seen.add(int(r["matchId"]))
                rec = fetch_match(api, r)
                if rec:
                    records.append(rec)
        if not records:
            notes.append("No recent completed T20s found for these teams; using the Lite model.")
            lite = True

    forecast_players, cb_forecast = _forecast(api, match_id)
    injured = _injured(forecast_players)

    tuned = _adapt_priors(priors, records, meta)
    profiles = build_profiles(records, meta, tuned)

    teams = []
    for team in (t1, t2):
        squad = squad_for(team)
        xi = None if lite else _xi_from_records(team, records, profiles)
        if xi is None:
            xi = _xi_from_squad(team, squad, profiles, injured)
        if xi is None:
            raise RuntimeError(f"could not build an XI for {team.name}: no recent matches or squad")
        teams.append(_replace_injured(xi, injured, squad, profiles, notes))

    group = _competition_group(info.get("seriesName", ""))
    confidence = "calibrated" if group == "ipl" and not lite else "approximate"
    if group != "ipl":
        notes.append("Priors are calibrated on the IPL and re-scaled with this competition's "
                     "recent matches; treat the numbers as approximate.")

    model = OutcomeModel(tuned)
    rng = random.Random(seed)
    wins = {teams[0].name: 0, teams[1].name: 0}
    first_innings: dict[str, list[int]] = {teams[0].name: [], teams[1].name: []}
    sample = None
    for _ in range(runs):
        m = simulate_match(model, teams[0], teams[1], rng)
        if m.winner:
            wins[m.winner] += 1
        first_innings[m.team1].append(m.innings[0].runs)
        sample = sample or m
    return Prediction(
        match_id=match_id,
        title=f"{info.get('seriesName', '')}, {info.get('matchDesc', '')}",
        tier="Lite" if lite else "Quick",
        team1=t1, team2=t2, runs=runs,
        win_prob={k: v / runs for k, v in wins.items()},
        first_innings=first_innings,
        sample=sample,
        profiles=profiles,
        xi={t.name: [p.name for p in t.batting_order] for t in teams},
        confidence=confidence,
        notes=notes,
        cricbuzz_forecast=cb_forecast,
        calls_used=api.client.calls_made - calls_before,
    )


def summarise_totals(totals: list[int]) -> str:
    if not totals:
        return "-"
    q = statistics.quantiles(totals, n=4) if len(totals) > 1 else [totals[0]] * 3
    return f"{statistics.median(totals):.0f} (middle 50%: {q[0]:.0f}–{q[2]:.0f})"


def estimate_calls(api: Cricbuzz, info: dict, lite: bool) -> tuple[int, int]:
    """(discovery calls made now, further calls the prediction would make).

    Discovery fetches each team's results list (cached for 6h) so the estimate can count
    exactly which matches are not cached yet.
    """
    before = api.client.calls_made
    cached = api.client.is_cached
    more = 0
    if info.get("seriesId") and not cached(f"/series/v1/{info['seriesId']}/squads", ttl=86400):
        more += 3  # squads list + two team squads
    if not lite:
        seen: set[int] = set()
        for key in ("team1", "team2"):
            results = match_infos_from_results(api.team_results(int(info[key]["teamId"])))
            recent = [r for r in results if r.get("matchFormat") == "T20" and is_complete(r)]
            for r in recent[:QUICK_MATCHES_PER_TEAM]:
                mid = int(r["matchId"])
                if mid in seen:
                    continue
                seen.add(mid)
                if not cached(f"/mcenter/v1/{mid}/scard", ttl=-1):
                    more += 3  # scorecard + two ballsGraph innings
    if not cached(f"/forecast/v1/index/{info['matchId']}", ttl=6 * 3600):
        more += 3  # index, then allPlayers + prediction when Cricbuzz has a forecast
    return api.client.calls_made - before, more
