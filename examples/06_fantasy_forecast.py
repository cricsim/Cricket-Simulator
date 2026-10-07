"""Cricbuzz's pre-match forecast: tabs, player badges and win prediction.

    curl -H "x-rapidapi-key: $RAPIDAPI_KEY" -H "x-rapidapi-host: cricbuzz-cricket.p.rapidapi.com" \
         https://cricbuzz-cricket.p.rapidapi.com/forecast/v1/155409/partnerPredictions

Run: python examples/06_fantasy_forecast.py 155409   (IPL 2026 final)
"""

import sys

from cricsim.api import Cricbuzz

match_id = int(sys.argv[1]) if len(sys.argv) > 1 else 155409
api = Cricbuzz.from_env()
index = api.forecast_index(match_id) or {}
tabs = [t["path"] for t in (index.get("tabs") or [])]
print(index.get("subtitle", ""), "forecast tabs:", tabs or "none for this match")
if tabs:
    pred = (api.forecast_prediction(match_id) or {}).get("cbPrediction", {})
    print("Cricbuzz forecast:", pred.get("value"))
    for group in (api.forecast_players(match_id) or {}).get("playersByRole", []):
        for p in group["players"]:
            badges = [b["label"] for b in p.get("badges", [])]
            if badges:
                print(f"  {p['teamShortName']:<5} {p['name']:<22} {', '.join(badges)}")
