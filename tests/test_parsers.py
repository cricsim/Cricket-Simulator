"""Parser tests that need no API key or fixtures (they run in CI)."""

import pytest

from cricsim.ingest.parse_balls import UnknownBallLabel, parse_balls_graph, parse_label
from cricsim.ingest.parse_dismissal import parse_dismissal


@pytest.mark.parametrize(
    "label,total,expected",
    [
        ("•", 0, (0, None, 0, False)),
        ("0", 0, (0, None, 0, False)),
        ("4", 4, (4, None, 0, False)),
        ("6", 6, (6, None, 0, False)),
        ("W", 0, (0, None, 0, True)),
        ("W1", 1, (1, None, 0, True)),  # run-out after a completed run
        ("Wd", 1, (0, "wd", 1, False)),
        ("Wd4", 4, (0, "wd", 4, False)),
        ("WWd", 1, (0, "wd", 1, True)),  # stumped off a wide
        ("N4", 5, (4, "nb", 1, False)),
        ("NB4", 5, (0, "nb", 5, False)),
        ("NL1", 2, (0, "nb", 2, False)),
        ("B4", 4, (0, "b", 4, False)),
        ("L1", 1, (0, "lb", 1, False)),
        ("WB1", 1, (0, "b", 1, True)),
    ],
)
def test_parse_label(label, total, expected):
    assert parse_label(label, total) == expected


def test_unknown_label_fails_loudly():
    with pytest.raises(UnknownBallLabel):
        parse_label("X3", 3)


def test_balls_sorted_by_timestamp_and_ids_filled():
    data = {"balls": [
        {"timestamp": 3, "ballNbr": 2, "overNum": 0.2, "totalRuns": 0, "ballLabel": "•"},
        {"timestamp": 2, "ballNbr": 1, "overNum": 0.1, "totalRuns": 1, "ballLabel": "1",
         "batsmanStrikerId": 10, "bowlerStrikerId": 20},
        {"timestamp": 1, "ballNbr": 1, "overNum": 0.1, "totalRuns": 1, "ballLabel": "Wd",
         "batsmanStrikerId": 10, "bowlerStrikerId": 20},
    ]}
    balls = parse_balls_graph(data, 1)
    assert [b.label for b in balls] == ["Wd", "1", "•"]
    assert balls[2].bowler_id == 20 and balls[2].batter_id == 10
    assert not balls[0].faced and not balls[0].legal
    assert sum(b.legal for b in balls) == 2


@pytest.mark.parametrize(
    "text,kind,fielder,bowler",
    [
        ("c Phil Salt b Jacob Duffy", "caught", "Phil Salt", "Jacob Duffy"),
        ("c & b Rashid Khan", "caught", "Rashid Khan", "Rashid Khan"),
        ("b Bumrah", "bowled", None, "Bumrah"),
        ("lbw b Chahal", "lbw", None, "Chahal"),
        ("st Dhoni b Jadeja", "stumped", "Dhoni", "Jadeja"),
        ("run out (Jadeja)", "run out", "Jadeja", None),
        ("run out (sub (Rinku)/Pant)", "run out", None, None),
        ("hit wicket b Starc", "hit wicket", None, "Starc"),
        ("hit wkt b Santner", "hit wicket", None, "Santner"),
        ("retd hurt", "retired hurt", None, None),
        ("retd out", "retired out", None, None),
        ("obs", "obstructing", None, None),
        ("not out", "not out", None, None),
        ("", "did not bat", None, None),
    ],
)
def test_parse_dismissal(text, kind, fielder, bowler):
    d = parse_dismissal(text)
    assert (d.kind, d.fielder, d.bowler) == (kind, fielder, bowler)


def test_retirements_are_not_bowler_wickets():
    assert not parse_dismissal("retd hurt").is_out
    out = parse_dismissal("retd out")
    assert out.is_out and out.is_retirement and not out.credited_to_bowler


def test_phantom_row_without_ids_is_dropped():
    data = {"balls": [
        {"timestamp": 1, "ballNbr": 1, "overNum": 0.1, "totalRuns": 2, "ballLabel": "2",
         "batsmanStrikerId": 10, "bowlerStrikerId": 20},
        {"timestamp": 2, "ballNbr": 1, "overNum": 0.1, "totalRuns": 0, "ballLabel": "•"},
    ]}
    balls = parse_balls_graph(data, 1)
    assert [b.label for b in balls] == ["2"]
