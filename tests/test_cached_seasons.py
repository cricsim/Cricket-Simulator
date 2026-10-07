"""Every parser check, run over all cached IPL matches (skipped when there is no cache).

Run `cricsim data fetch --series-id 9241 --series-id 9237` once to populate data/cache.
"""

from collections import Counter

import pytest

from cricsim.api import Cricbuzz
from cricsim.ingest.fetch import FetchReport, fetch_series, is_complete, match_infos_from_series
from cricsim.ingest.parse_dismissal import BOWLER_KINDS
from cricsim.ingest.parse_scorecard import dismissed_batters
from cricsim.ingest.squads import series_squads

SERIES = (9241, 9237)  # IPL 2026, IPL 2025


@pytest.fixture(scope="module")
def api():
    a = Cricbuzz.from_env(offline=True)
    if not all(a.client.is_cached(f"/series/v1/{s}") for s in SERIES):
        pytest.skip("IPL seasons not cached")
    return a


@pytest.fixture(scope="module")
def records(api):
    report = FetchReport()
    recs = [r for s in SERIES for r in fetch_series(api, s, report)]
    assert not report.unknown_labels, report.unknown_labels
    return recs


def _innings(records) -> int:
    return sum(len(r.scorecard.innings) for r in records)


def test_every_completed_match_parsed(api, records):
    infos = [i for s in SERIES for i in match_infos_from_series(api.series_matches(s))]
    complete = [i for i in infos if is_complete(i)]
    assert len(records) >= len(complete) - 3  # 3 abandoned matches have no innings


def test_every_dismissal_text_parses(records):
    unknown = [(r.match_id, b.name, b.dismissal) for r in records for i in r.scorecard.innings
               for b in i.batting if b.dismissal.kind == "unknown"]
    assert not unknown, unknown[:10]


def test_balls_faced_match_scorecard(records):
    bad = []
    for r in records:
        for inn in r.scorecard.innings:
            faced = Counter(d.batter_id for d in r.deliveries if d.innings == inn.innings_id
                            and d.faced)
            bad += [(r.match_id, inn.innings_id, b.name, b.balls, faced[b.player_id])
                    for b in inn.batting if b.balls != faced[b.player_id]]
    assert len(bad) <= 0.01 * sum(len(i.batting) for r in records for i in r.scorecard.innings), \
        bad[:10]


def test_every_wicket_maps_to_a_dismissed_batter(records):
    bad = []
    for r in records:
        for inn in r.scorecard.innings:
            outs = {b.player_id for b in inn.batting
                    if b.dismissal.is_out and not b.dismissal.is_retirement}
            mapped = dismissed_batters(inn, r.deliveries)
            wickets = [d for d in r.deliveries if d.innings == inn.innings_id and d.wicket]
            if set(mapped.values()) != outs or len(wickets) != len(outs):
                bad.append((r.match_id, inn.innings_id, len(wickets), len(outs)))
    # Upstream gap: ballsGraph occasionally drops a wicket row (1 innings in IPL 2025-26).
    assert len(bad) <= 0.01 * _innings(records), bad


def test_bowler_legal_balls_match_scorecard_overs(records):
    bad = []
    for r in records:
        for inn in r.scorecard.innings:
            legal = Counter(d.bowler_id for d in r.deliveries if d.innings == inn.innings_id
                            and d.legal)
            for w in inn.bowling:
                whole, part = divmod(round(w.overs * 10), 10)
                if legal[w.player_id] != whole * 6 + part:
                    bad.append((r.match_id, inn.innings_id, w.name, w.overs, legal[w.player_id]))
    # Upstream: missing deliveries or a ball tagged with the wrong bowler ID (6 spells of
    # ~1,700 in IPL 2025-26). More than 1% would point at a parser bug.
    spells = sum(len(i.bowling) for r in records for i in r.scorecard.innings)
    assert len(bad) <= 0.01 * spells, bad


def test_bowler_wickets_match_scorecard(records):
    bad = []
    for r in records:
        for inn in r.scorecard.innings:
            kinds = {b.player_id: b.dismissal for b in inn.batting}
            mapped = dismissed_batters(inn, r.deliveries)
            credited = Counter()
            for d in r.deliveries:
                if d.innings == inn.innings_id and d.wicket:
                    out = kinds.get(mapped[d.seq])
                    if out and out.kind in BOWLER_KINDS:
                        credited[d.bowler_id] += 1
            bad += [(r.match_id, w.name, w.wickets, credited[w.player_id]) for w in inn.bowling
                    if w.wickets != credited[w.player_id]]
    assert len(bad) <= 0.01 * sum(len(i.bowling) for r in records
                                  for i in r.scorecard.innings), bad


def test_runs_reconcile_in_almost_every_innings(records):
    innings = [(r.match_id, i.innings_id, i.score,
                sum(d.total_runs for d in r.deliveries if d.innings == i.innings_id))
               for r in records for i in r.scorecard.innings]
    off = [x for x in innings if x[2] != x[3]]
    assert len(off) <= 0.03 * len(innings), off


def test_legal_balls_never_exceed_six_per_over(records):
    bad = []
    for r in records:
        per_over = Counter((d.innings, d.over) for d in r.deliveries if d.legal)
        bad += [(r.match_id, k, n) for k, n in per_over.items() if n > 6]
    assert not bad, bad[:10]


def test_every_scorecard_player_has_squad_metadata(api, records):
    meta = {p.player_id for s in SERIES for ps in series_squads(api, s).values() for p in ps}
    players = {b.player_id for r in records for i in r.scorecard.innings for b in i.batting}
    missing = players - meta
    assert len(missing) <= 0.05 * len(players), sorted(missing)[:20]
