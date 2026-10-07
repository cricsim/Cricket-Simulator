"""Live and upcoming matches.

    curl -H "x-rapidapi-key: $RAPIDAPI_KEY" -H "x-rapidapi-host: cricbuzz-cricket.p.rapidapi.com" \
         https://cricbuzz-cricket.p.rapidapi.com/matches/v1/live

Run: python examples/01_live_scores.py [live|upcoming|recent]
"""

import sys

from cricsim.api import Cricbuzz

kind = sys.argv[1] if len(sys.argv) > 1 else "live"
api = Cricbuzz.from_env()
for group in api.matches(kind).get("typeMatches", []):
    for series in group.get("seriesMatches", []):
        for m in (series.get("seriesAdWrapper") or {}).get("matches", []):
            info = m["matchInfo"]
            print(f"{info['matchId']:>7}  {info['matchFormat']:<5} "
                  f"{info['team1']['teamSName']} v {info['team2']['teamSName']:<8} "
                  f"{info.get('status', '')}")
