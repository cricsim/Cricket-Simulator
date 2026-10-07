"""Fetch matches (scorecard + ball-by-ball) through the cached API client."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from cricsim.api import Cricbuzz
from cricsim.ingest.parse_balls import Delivery, UnknownBallLabel, innings_total, parse_balls_graph
from cricsim.ingest.parse_scorecard import Scorecard, parse_scorecard


@dataclass
class MatchRecord:
    match_id: int
    series_id: int | None
    series_name: str
    start_ms: int
    venue: str
    scorecard: Scorecard
    deliveries: list[Delivery]


@dataclass
class FetchReport:
    matches: int = 0
    skipped: list[tuple[int, str]] = field(default_factory=list)
    unknown_labels: Counter = field(default_factory=Counter)
    run_mismatches: list[tuple[int, int, int, int]] = field(default_factory=list)


def match_infos_from_series(data: dict) -> list[dict]:
    """Flatten /series/v1/{id} into matchInfo dicts."""
    out = []
    for group in data.get("matchDetails", []):
        for m in (group.get("matchDetailsMap") or {}).get("match", []):
            out.append(m["matchInfo"])
    return out


def match_infos_from_results(data: dict) -> list[dict]:
    """Flatten /teams/v1/{id}/results into matchInfo dicts (newest first)."""
    out = []
    for group in data.get("teamMatchesData", []):
        for m in (group.get("matchDetailsMap") or {}).get("match", []):
            out.append(m["matchInfo"])
    return out


def match_infos_from_list(data: dict) -> list[dict]:
    """Flatten /matches/v1/{live|upcoming|recent} into matchInfo dicts."""
    out = []
    for t in data.get("typeMatches", []):
        for s in t.get("seriesMatches", []):
            for m in (s.get("seriesAdWrapper") or {}).get("matches", []):
                out.append(m["matchInfo"])
    return out


def is_complete(info: dict) -> bool:
    return str(info.get("state", "")).lower() == "complete"


def fetch_match(api: Cricbuzz, info: dict, report: FetchReport | None = None) -> MatchRecord | None:
    """Scorecard + ballsGraph for each innings of one completed match."""
    match_id = int(info["matchId"])
    report = report or FetchReport()
    card = parse_scorecard(api.scorecard(match_id, complete=is_complete(info)))
    if not card.complete or not card.innings:
        report.skipped.append((match_id, "not complete or no innings"))
        return None
    deliveries: list[Delivery] = []
    for inn in card.innings:
        graph = api.balls_graph(match_id, inn.innings_id, complete=True)
        try:
            balls = parse_balls_graph(graph, inn.innings_id)
        except UnknownBallLabel as exc:
            report.unknown_labels[str(exc)] += 1
            report.skipped.append((match_id, f"unknown ball label {exc}"))
            return None
        total = innings_total(balls)
        if total != inn.score:
            report.run_mismatches.append((match_id, inn.innings_id, total, inn.score))
        deliveries.extend(balls)
    report.matches += 1
    return MatchRecord(
        match_id=match_id,
        series_id=info.get("seriesId"),
        series_name=info.get("seriesName", ""),
        start_ms=int(info.get("startDate", 0)),
        venue=(info.get("venueInfo") or {}).get("ground", ""),
        scorecard=card,
        deliveries=deliveries,
    )


def fetch_matches(
    api: Cricbuzz,
    infos: Iterable[dict],
    report: FetchReport | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> list[MatchRecord]:
    infos = [i for i in infos if is_complete(i) and i.get("matchFormat", "T20") == "T20"]
    report = report or FetchReport()
    records = []
    for n, info in enumerate(infos, start=1):
        rec = fetch_match(api, info, report)
        if rec:
            records.append(rec)
        if progress:
            progress(n, len(infos))
    return records


def fetch_series(api: Cricbuzz, series_id: int, report: FetchReport | None = None,
                 progress: Callable[[int, int], None] | None = None) -> list[MatchRecord]:
    infos = match_infos_from_series(api.series_matches(series_id))
    return fetch_matches(api, infos, report, progress)


def estimate_series_calls(api: Cricbuzz, series_id: int) -> int:
    """Calls still needed to ingest a series (cached matches cost nothing)."""
    infos = [i for i in match_infos_from_series(api.series_matches(series_id)) if is_complete(i)]
    return sum(
        0 if api.client.is_cached(f"/mcenter/v1/{i['matchId']}/scard", ttl=-1) else 3
        for i in infos
    )
