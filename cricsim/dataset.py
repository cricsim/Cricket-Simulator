"""Season-level data: find series, load matches and squads, build profiles and priors."""

from __future__ import annotations

from datetime import date

from cricsim.api import Cricbuzz
from cricsim.ingest.fetch import FetchReport, MatchRecord, fetch_series
from cricsim.ingest.squads import PlayerMeta, series_squads


def find_series(api: Cricbuzz, query: str, year: int | None = None,
                kind: str = "league") -> list[tuple[int, str, int]]:
    """[(series_id, name, year)] whose name contains every word of `query`."""
    words = query.lower().split()
    years = [year] if year else [date.today().year, date.today().year - 1]
    out = []
    for y in years:
        data = api.series_archives(kind, y)  # type: ignore[arg-type]
        for group in data.get("seriesMapProto", []):
            for s in group.get("series", []):
                if all(w in s["name"].lower() for w in words):
                    out.append((int(s["id"]), s["name"], y))
    return out


def latest_ipl(api: Cricbuzz) -> tuple[int, str]:
    found = find_series(api, "indian premier league")
    if not found:
        raise RuntimeError("could not find an Indian Premier League series in the archives")
    sid, name, _ = max(found, key=lambda x: (x[2], x[0]))
    return sid, name


def load_seasons(api: Cricbuzz, series_ids: list[int], report: FetchReport | None = None,
                 progress=None) -> tuple[list[MatchRecord], dict[int, PlayerMeta]]:
    """Matches and player metadata for several series (later series win on conflicts)."""
    records: list[MatchRecord] = []
    meta: dict[int, PlayerMeta] = {}
    for sid in series_ids:
        records += fetch_series(api, sid, report, progress)
        for players in series_squads(api, sid).values():
            for p in players:
                meta[p.player_id] = p
    return records, meta
