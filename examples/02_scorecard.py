"""Full scorecard of a match.

    curl -H "x-rapidapi-key: $RAPIDAPI_KEY" -H "x-rapidapi-host: cricbuzz-cricket.p.rapidapi.com" \
         https://cricbuzz-cricket.p.rapidapi.com/mcenter/v1/149618/scard

Run: python examples/02_scorecard.py 149618
"""

import sys

from cricsim.api import Cricbuzz

match_id = int(sys.argv[1]) if len(sys.argv) > 1 else 149618  # IPL 2026, 1st match
data = Cricbuzz.from_env().scorecard(match_id)
print(data.get("status", ""))
for inn in data.get("scorecard", []):
    print(f"\n{inn['batteamsname']} {inn['score']}/{inn['wickets']} ({inn['overs']} ov)")
    for b in inn["batsman"]:
        if b.get("balls"):
            print(f"  {b['name']:<22} {b['runs']:>3} ({b['balls']})  {b['outdec']}")
