# cricsim: ball-by-ball T20 simulator on the Cricbuzz Cricket API

Predict any upcoming T20 match ball by ball, using real ball-by-ball data from the
[Cricbuzz Cricket API on RapidAPI](https://rapidapi.com/cricketapilive/api/cricbuzz-cricket).

> **Unofficial example.** Not affiliated with or endorsed by Cricbuzz. You need your own
> RapidAPI key; this repo contains no Cricbuzz data.

```
$ cricsim predict
Match: ZIMW v WIW, West Indies Women tour of Zimbabwe, 2026 (173123)
┏━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Team ┃ Win % ┃  Score when batting first ┃
┡━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ WIW  │ 92.8% │ 174 (middle 50%: 158–191) │
│ ZIMW │  7.1% │ 127 (middle 50%: 115–139) │
└──────┴───────┴───────────────────────────┘
...followed by one fully simulated scorecard
```

## Quickstart

1. **Get a key:** subscribe to the
   [Cricbuzz Cricket API](https://rapidapi.com/cricketapilive/api/cricbuzz-cricket) on RapidAPI.
2. **Install and save your key** (Python 3.10+):
   ```bash
   pip install -e .
   cricsim init          # paste your key; makes one test call
   ```
3. **Predict the next T20:**
   ```bash
   cricsim predict --dry-run   # shows how many API calls it will use
   cricsim predict
   ```

## What it does

| Command | What you get | API calls |
|---|---|---|
| `cricsim predict` | Next T20 anywhere (IPL, internationals, women's, domestic): win %, projected score, a simulated scorecard. Uses each team's last 5 completed T20s | ~25–45 first run, then mostly cached |
| `cricsim predict --lite` | Same, from squad roles and bundled priors only | ~3–10 |
| `cricsim predict --list` | Upcoming T20s with match IDs | 1 |
| `cricsim data fetch --series-id 9241` | A full season (here IPL 2026) as player profiles | ~225 per season, once |
| `cricsim sim match RCB GT --runs 2000` | Two teams from a fetched season, latest XIs | 0 once fetched |

Every command prints the API calls it made and your remaining quota. Finished-match data
is cached permanently under `data/`, so re-running costs nothing.

## Endpoints used

Standalone scripts for each are in [`examples/`](examples/) (Python, with a `curl`
one-liner in each docstring) and [`examples/js/`](examples/js/) (Node 18+, no
dependencies). The client in [`cricsim/api/`](cricsim/api/) works without the simulator:

```python
from cricsim.api import Cricbuzz

api = Cricbuzz.from_env()
balls = api.balls_graph(149618, innings=1, complete=True)["balls"]
```

## How the model works

- **Data:** `ballsGraph` returns every delivery with striker, bowler, over and outcome.
  It reconciles with the scorecard: balls faced per batter match exactly, and wickets
  join to the fall-of-wicket list by ball number.
- **Players:** each batter and bowler gets a distribution over 0/1/2/3/4/6/W per ball,
  shrunk toward a prior for their batting position or bowling type, so a player with
  few balls stays close to the prior. Bowlers also get their real over-by-over usage
  (pace in the powerplay and at the death, spin in the middle) and wide rate.
- **Each ball:** the batter's distribution is scaled by how far the bowler is from
  league average, then by context factors measured from the data: phase, wickets lost,
  required run rate when chasing, and how second innings differ overall.
- **Laws:** 4-over limit, no consecutive overs, wides, no-balls with free hits, byes,
  leg byes, strike rotation and a super over on a tie.
- **Other competitions:** the bundled priors ([`cricsim/priors/ipl.json`](cricsim/priors/ipl.json),
  aggregate parameters from IPL 2025–26) are re-scaled using the teams' recent matches.
  Output is labelled "approximate" outside the IPL.

**Calibration** (IPL 2026, real XIs, 1,380 simulated matches):

| | Real | Simulated |
|---|---|---|
| 1st-innings score | 194.4 (sd 35.9) | 192.4 (sd 34.4) |
| 1st-innings wickets | 6.3 | 6.0 |
| Fours / sixes | 16.1 / 10.2 | 16.6 / 9.9 |
| Team batting first wins | 36% | 49% |

**Out-of-sample backtest** (`python scripts/backtest.py`): every IPL 2026 match predicted using
only IPL 2025 and the 2026 matches already played.

| | Matches | Log-loss | Brier | Accuracy |
|---|---|---|---|---|
| Coin flip | 70 | 0.693 | 0.250 | – |
| cricsim | 70 | 0.694 | 0.250 | 57% |
| cricsim | 36 with a Cricbuzz forecast | 0.622 | 0.215 | 75% |
| Cricbuzz forecast | same 36 | 0.664 | 0.236 | 58% |

Totals are well calibrated, but match winners are not yet predicted better than a coin flip
over the whole season. The model under-rates chasing sides, which is the next target.

## Development

```bash
pip install -e ".[dev]"
pytest              # 129 tests; no API key needed (cache, fixture and live tests skip)
CRICSIM_LIVE=1 pytest tests/test_live_api.py   # live schema checks + examples (~15 calls)
python scripts/save_fixtures.py   # save 3 live responses to tests/fixtures/ (gitignored)
python scripts/backtest.py        # out-of-sample win-probability backtest (~70 calls)
ruff check cricsim tests examples scripts
```
