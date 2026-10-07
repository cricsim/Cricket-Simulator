"""Profile building on hand-made matches where the right counts are known."""

from pathlib import Path

import pytest

from cricsim.ingest.fetch import MatchRecord
from cricsim.ingest.parse_balls import Delivery, parse_label
from cricsim.ingest.parse_dismissal import parse_dismissal
from cricsim.ingest.parse_scorecard import (
    BattingEntry,
    BowlingEntry,
    FallOfWicket,
    Innings,
    Scorecard,
)
from cricsim.ingest.squads import PlayerMeta
from cricsim.model.profiles import (
    OUTCOMES,
    W,
    _scan,
    build_profiles,
    load_profiles,
    recency_weight,
    save_profiles,
)

BAT1, BAT2, BAT3, BOWL1, BOWL2 = 1, 2, 3, 11, 12
IDX = {o: i for i, o in enumerate(OUTCOMES)}


def deliveries(spec):
    """spec: [(over, batter, bowler, label, total, ball_nbr)]"""
    out = []
    for seq, (over, bat, bowl, label, total, nbr) in enumerate(spec):
        bat_runs, extra, extra_runs, wicket = parse_label(label, total)
        out.append(Delivery(1, seq, nbr, over, bat, bowl, label, total, bat_runs, extra,
                            extra_runs, wicket))
    return out


def record(spec, batting, fow=(), start_ms=1_700_000_000_000):
    balls = deliveries(spec)
    inn = Innings(1, "AAA", sum(d.total_runs for d in balls), len(fow), 1.0,
                  batting=[BattingEntry(pid, f"B{pid}", pos, 0, 0, 0, 0, parse_dismissal(how))
                           for pos, (pid, how) in enumerate(batting, start=1)],
                  bowling=[BowlingEntry(BOWL1, "Bowl1", 1, 0, 0),
                           BowlingEntry(BOWL2, "Bowl2", 1, 0, 0)],
                  fow=[FallOfWicket(pid, nbr) for pid, nbr in fow])
    return MatchRecord(1, 1, "Test", start_ms, "Ground", Scorecard(True, "", [inn]), balls)


def test_extras_are_counted_from_the_right_point_of_view():
    rec = record([
        (0, BAT1, BOWL1, "Wd", 1, 1),    # wide: not faced, bowler wide, not a legal ball
        (0, BAT1, BOWL1, "N4", 5, 1),    # no-ball hit for four: faced, 4 to batter, not legal
        (0, BAT1, BOWL1, "B4", 4, 1),    # four byes: faced dot for batter, dot for bowler
        (0, BAT1, BOWL1, "6", 6, 2),
        (0, BAT1, BOWL1, "L1", 1, 3),    # leg bye: faced dot, bowler dot
        (0, BAT2, BOWL1, "•", 0, 4),
    ], batting=[(BAT1, "not out"), (BAT2, "not out")])
    s = _scan([rec], rec.start_ms, 365)
    b1, bowler = s["acc"][BAT1], s["acc"][BOWL1]
    assert b1.bat == [2, 0, 0, 0, 1, 1, 0]  # B4 and L1 are dots; N4 is a four; then the six
    assert sum(b1.bat) == 4  # the wide is not a ball faced
    assert bowler.bowl == [3, 0, 0, 0, 0, 1, 0]  # B4, L1, dot as dots; 6; no-ball/wide excluded
    assert bowler.wides == 1
    assert s["ex"]["noballs"] == 1 and s["ex"]["byes"] == 2 and s["ex"]["legal"] == 4


def test_wickets_and_run_outs():
    rec = record([
        (0, BAT1, BOWL1, "W", 0, 1),     # BAT1 caught: W for both
        (0, BAT3, BOWL1, "W1", 1, 2),    # BAT3 run out going for a run: W for batter only
        (0, BAT2, BOWL1, "W", 0, 3),     # BAT2 on strike; fow says the non-striker (4) is out
    ], batting=[(BAT1, "c X b Bowl1"), (BAT3, "run out (X)"), (BAT2, "not out"),
                (4, "run out (Y)")],
       fow=[(BAT1, 1), (BAT3, 2), (4, 3)])
    s = _scan([rec], rec.start_ms, 365)
    acc = s["acc"]
    assert acc[BAT1].bat[W] == 1
    assert acc[BAT3].bat[W] == 1
    # Third wicket: non-striker (4) run out while BAT2 faced a dot.
    assert acc[BAT2].bat[W] == 0 and acc[BAT2].bat[IDX["0"]] == 1
    # Only the catch is credited to the bowler; the run-outs count by runs scored.
    assert acc[BOWL1].bowl[W] == 1
    assert acc[BOWL1].bowl[IDX["1"]] == 1 and acc[BOWL1].bowl[IDX["0"]] == 1


def test_overs_by_index_counts_distinct_overs():
    spec = [(o, BAT1, BOWL1 if o % 2 == 0 else BOWL2, "1", 1, o * 6 + b + 1)
            for o in range(4) for b in range(6)]
    rec = record(spec, batting=[(BAT1, "not out")])
    s = _scan([rec], rec.start_ms, 365)
    assert s["acc"][BOWL1].overs_by_idx[:4] == [1, 0, 1, 0]
    assert s["acc"][BOWL2].overs_by_idx[:4] == [0, 1, 0, 1]
    assert s["acc"][BOWL1].bowl_matches == 1


def test_recency_weight_halves_each_half_life():
    day = 86_400_000
    assert recency_weight(0, 0) == 1
    assert recency_weight(0, 365 * day) == pytest.approx(0.5)
    assert recency_weight(0, 730 * day, half_life_days=365) == pytest.approx(0.25)


def test_profiles_round_trip_and_cover_debutants(tmp_path: Path):
    from cricsim.model.profiles import Priors

    priors = Priors.bundled()
    rec = record([(0, BAT1, BOWL1, "4", 4, 1)], batting=[(BAT1, "not out")])
    meta = {99: PlayerMeta(99, "Debut", role="Bowler", bowling_style="Right-arm legbreak")}
    profiles = build_profiles([rec], meta, priors)
    assert profiles[99].bowl_type == "spin" and profiles[99].bat_balls == 0
    assert abs(sum(profiles[99].bat) - 1) < 1e-9 and abs(sum(profiles[99].over_pref) - 1) < 1e-9
    path = tmp_path / "p.json"
    save_profiles(profiles, path)
    assert load_profiles(path) == profiles


@pytest.mark.parametrize("style,expected", [
    ("Right-arm fast", "pace"), ("Right-arm fast-medium", "pace"), ("Left-arm medium", "pace"),
    ("Right-arm offbreak", "spin"), ("Right-arm legbreak", "spin"),
    ("Left-arm orthodox", "spin"), ("Left-arm wrist-spin", "spin"), ("", None),
])
def test_bowl_type_classification(style, expected):
    assert PlayerMeta(1, "x", bowling_style=style).bowl_type == expected
