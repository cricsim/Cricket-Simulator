"""Points table of a league season.

    curl -H "x-rapidapi-key: $RAPIDAPI_KEY" -H "x-rapidapi-host: cricbuzz-cricket.p.rapidapi.com" \
         https://cricbuzz-cricket.p.rapidapi.com/stats/v1/series/9241/points-table

Run: python examples/05_points_table.py 9241   (IPL 2026)
"""

import sys

from cricsim.api import Cricbuzz

series_id = int(sys.argv[1]) if len(sys.argv) > 1 else 9241
data = Cricbuzz.from_env().points_table(series_id)
for group in data.get("pointsTable", []):
    print(group.get("groupName", ""))
    for t in group.get("pointsTableInfo", []):
        print(f"  {t['teamName']:<6} P{t.get('matchesPlayed', 0):>3} W{t.get('matchesWon', 0):>3} "
              f"Pts {t.get('points', 0):>3}  NRR {t.get('nrr', '')}")
