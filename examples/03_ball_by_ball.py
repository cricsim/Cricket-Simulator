"""Every delivery of an innings, with striker and bowler IDs.

    curl -H "x-rapidapi-key: $RAPIDAPI_KEY" -H "x-rapidapi-host: cricbuzz-cricket.p.rapidapi.com" \
         "https://cricbuzz-cricket.p.rapidapi.com/mcenter/v1/149618/ballsGraph?iid=1"

Run: python examples/03_ball_by_ball.py 149618 1
"""

import sys
from collections import Counter

from cricsim.api import Cricbuzz

match_id = int(sys.argv[1]) if len(sys.argv) > 1 else 149618
innings = int(sys.argv[2]) if len(sys.argv) > 2 else 1
data = Cricbuzz.from_env().balls_graph(match_id, innings, complete=True)
balls = sorted(data.get("balls", []), key=lambda b: b["timestamp"])  # API returns newest first
overs: dict[int, list[str]] = {}
for b in balls:
    overs.setdefault(int(b["overNum"]), []).append(b["ballLabel"])
for over, labels in overs.items():
    print(f"over {over + 1:>2}: {' '.join(labels)}")
print("\noutcomes:", dict(Counter(b["ballLabel"] for b in balls)))
print("total runs:", sum(b["totalRuns"] for b in balls))
