"""Save live API responses for one IPL 2026 match into tests/fixtures/ (7 calls, cached)."""

import json
from pathlib import Path

from cricsim.api import Cricbuzz

MATCH = 149618  # IPL 2026, 1st match
out = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
out.mkdir(parents=True, exist_ok=True)
api = Cricbuzz.from_env()
(out / f"scard_{MATCH}.json").write_text(json.dumps(api.scorecard(MATCH, complete=True)))
for iid in (1, 2):
    data = api.balls_graph(MATCH, iid, complete=True)
    (out / f"balls_{MATCH}_{iid}.json").write_text(json.dumps(data))
print(f"saved fixtures to {out} ({api.client.calls_made} API calls)")
