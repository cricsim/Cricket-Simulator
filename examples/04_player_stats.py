"""Search a player and print career batting by format.

    curl -H "x-rapidapi-key: $RAPIDAPI_KEY" -H "x-rapidapi-host: cricbuzz-cricket.p.rapidapi.com" \
         https://cricbuzz-cricket.p.rapidapi.com/stats/v1/player/1413/batting

Run: python examples/04_player_stats.py 1413
"""

import sys

from cricsim.api import Cricbuzz

player_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1413  # Virat Kohli
api = Cricbuzz.from_env()
info = api.player_info(player_id)
print(f"{info.get('name')} ({info.get('role')}): {info.get('bat')}, {info.get('bowl')}")
table = api.player_batting(player_id)
headers = table.get("headers", [])
print("  ".join(f"{h:>8}" for h in headers))
for row in table.get("values", []):
    print("  ".join(f"{v:>8}" for v in row["values"]))
