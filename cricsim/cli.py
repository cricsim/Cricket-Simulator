"""Command-line interface: `cricsim --help`."""

from __future__ import annotations

import random
from pathlib import Path

import typer
from rich.progress import Progress

from cricsim.api import ApiError, Cricbuzz
from cricsim.config import DEFAULT_HOST, get_settings
from cricsim.output.render import console, print_match, print_prediction

app = typer.Typer(help="Ball-by-ball T20 cricket simulator on the Cricbuzz Cricket API "
                       "(unofficial example).", no_args_is_help=True)
data_app = typer.Typer(help="Fetch and build data (advanced).", no_args_is_help=True)
sim_app = typer.Typer(help="Simulate matches from season data (advanced).", no_args_is_help=True)
app.add_typer(data_app, name="data")
app.add_typer(sim_app, name="sim")

SUBSCRIBE_URL = "https://rapidapi.com/cricketapilive/api/cricbuzz-cricket"


def _api(offline: bool = False) -> Cricbuzz:
    return Cricbuzz.from_env(offline=offline)


def _quota_line(api: Cricbuzz) -> str:
    q = api.client.quota
    left = f"{q.remaining:,} of {q.limit:,} left" if q.remaining is not None and q.limit else \
        "quota not reported"
    return f"{api.client.calls_made} API calls made ({left})"


@app.command()
def init(key: str | None = typer.Option(None, help="RapidAPI key (prompted if omitted)")):
    """Save your RapidAPI key to .env and make one test call."""
    console.print(f"Get a key by subscribing to the Cricbuzz Cricket API: {SUBSCRIBE_URL}")
    key = key or typer.prompt("RapidAPI key", hide_input=True)
    env = Path(".env")
    lines = [ln for ln in (env.read_text().splitlines() if env.exists() else [])
             if not ln.startswith(("RAPIDAPI_KEY=", "RAPIDAPI_HOST="))]
    lines += [f"RAPIDAPI_KEY={key}", f"RAPIDAPI_HOST={DEFAULT_HOST}"]
    env.write_text("\n".join(lines) + "\n")
    env.chmod(0o600)
    import os
    os.environ["RAPIDAPI_KEY"] = key
    api = _api()
    try:
        live = api.matches("live")
    except ApiError as exc:
        console.print(f"[red]Test call failed:[/red] {exc}")
        raise typer.Exit(1) from None
    n = sum(len((s.get("seriesAdWrapper") or {}).get("matches", []))
            for t in live.get("typeMatches", []) for s in t.get("seriesMatches", []))
    console.print(f"[green]Key works.[/green] {n} matches live right now. {_quota_line(api)}")
    console.print("Next: [bold]cricsim predict[/bold]")


@app.command()
def predict(
    match_id: int | None = typer.Option(None, help="Match to predict (default: next T20)"),
    lite: bool = typer.Option(False, help="Lite tier: ~10 calls, priors only"),
    runs: int = typer.Option(2000, help="Number of simulations"),
    seed: int | None = typer.Option(None, help="Random seed for reproducible output"),
    dry_run: bool = typer.Option(False, help="Only estimate the API calls needed"),
    list_matches: bool = typer.Option(False, "--list", help="List upcoming T20s and exit"),
    offline: bool = typer.Option(False, help="Use cached responses only"),
):
    """Predict an upcoming T20: win probability, projected score, a simulated scorecard."""
    from cricsim.model.profiles import Priors
    from cricsim.predict import estimate_calls, upcoming_t20s
    from cricsim.predict import predict as run_predict

    api = _api(offline)
    if match_id:
        info = api.match_info(match_id)
        info = {"matchId": match_id, "seriesId": info.get("seriesid"),
                "seriesName": info.get("seriesname", ""), "matchDesc": info.get("matchdesc", ""),
                "team1": {"teamId": info["team1"]["teamid"], "teamName": info["team1"]["teamname"],
                          "teamSName": info["team1"]["teamsname"]},
                "team2": {"teamId": info["team2"]["teamid"], "teamName": info["team2"]["teamname"],
                          "teamSName": info["team2"]["teamsname"]}}
    else:
        upcoming = upcoming_t20s(api)
        if list_matches:
            for i in upcoming:
                console.print(f"{i['matchId']}  {i['team1']['teamSName']} v "
                              f"{i['team2']['teamSName']}  {i['seriesName']}, {i['matchDesc']}")
            raise typer.Exit()
        if not upcoming:
            console.print("No upcoming T20 matches found.")
            raise typer.Exit(1)
        info = upcoming[0]
    console.print(f"Match: {info['team1']['teamSName']} v {info['team2']['teamSName']}, "
                  f"{info.get('seriesName', '')} ({info['matchId']})")
    used, more = estimate_calls(api, info, lite)
    q = api.client.quota.remaining
    console.print(f"This will use about {more} more API calls"
                  + (f" (you have {q:,} left)." if q is not None else "."))
    if dry_run:
        console.print(f"Dry run: {_quota_line(api)}")
        raise typer.Exit()
    if not lite and q is not None and q - more < 20:
        console.print("[yellow]Not enough quota for the Quick tier; switching to Lite.[/yellow]")
        lite = True
    pred = run_predict(api, info, Priors.bundled("ipl"), runs=runs, lite=lite, seed=seed)
    print_prediction(pred)
    console.print(f"[dim]{_quota_line(api)}[/dim]")


@data_app.command("find-series")
def find_series_cmd(query: str, year: int | None = None,
                    kind: str = typer.Option("league", help="international|league|domestic|women")):
    """Search the series archives, e.g. `cricsim data find-series "premier league" --year 2026`."""
    from cricsim.dataset import find_series

    api = _api()
    for sid, name, y in find_series(api, query, year, kind):
        console.print(f"{sid}  {name}  ({y})")


@data_app.command("fetch")
def fetch_cmd(series_id: list[int] = typer.Option(..., "--series-id", help="Repeatable"),
              yes: bool = typer.Option(False, "--yes", help="Skip the confirmation")):
    """Fetch completed matches (scorecard + ball-by-ball) and build player profiles."""
    from cricsim.dataset import load_seasons
    from cricsim.ingest.fetch import FetchReport, estimate_series_calls
    from cricsim.model.profiles import Priors, build_profiles, save_profiles

    api = _api()
    need = sum(estimate_series_calls(api, sid) for sid in series_id)
    console.print(f"About {need} API calls needed (cached matches are free).")
    if need and not yes:
        typer.confirm("Continue?", abort=True)
    report = FetchReport()
    with Progress(console=console) as bar:
        task = bar.add_task("Fetching matches", total=None)
        records, meta = load_seasons(
            api, series_id, report, progress=lambda n, t: bar.update(task, completed=n, total=t))
    profiles = build_profiles(records, meta, Priors.bundled("ipl"))
    path = get_settings().data_dir / "profiles.json"
    save_profiles(profiles, path)
    console.print(f"{report.matches} matches, {sum(len(r.deliveries) for r in records):,} "
                  f"deliveries, {len(profiles)} player profiles -> {path}")
    if report.run_mismatches:
        console.print(f"[yellow]{len(report.run_mismatches)} innings where ball-by-ball runs "
                      "differ from the scorecard total (kept).[/yellow]")
    if report.unknown_labels:
        console.print(f"[red]Unknown ball labels: {dict(report.unknown_labels)}[/red]")
    console.print(f"[dim]{_quota_line(api)}[/dim]")


@data_app.command("build-priors")
def build_priors_cmd(series_id: list[int] = typer.Option(..., "--series-id"),
                     name: str = "ipl",
                     out: Path = Path("cricsim/priors")):
    """(Maintainers) Rebuild the bundled league priors from cached seasons."""
    from cricsim.dataset import load_seasons
    from cricsim.model.profiles import build_priors

    api = _api()
    records, meta = load_seasons(api, series_id)
    priors = build_priors(records, meta, name)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.json").write_text(priors.to_json())
    console.print(f"Priors from {len(records)} matches ({priors.balls:,} weighted legal balls) "
                  f"-> {out / (name + '.json')}")


@sim_app.command("match")
def sim_match(team_a: str, team_b: str,
              series_id: int | None = typer.Option(None, help="Default: latest IPL"),
              runs: int = typer.Option(1, help="Simulations; >1 prints win probabilities"),
              seed: int | None = None):
    """Simulate two teams from a fetched season, e.g. `cricsim sim match RCB GT`."""
    from cricsim.dataset import latest_ipl, load_seasons
    from cricsim.engine.ball import OutcomeModel
    from cricsim.engine.match import simulate_match
    from cricsim.model.profiles import Priors, build_profiles
    from cricsim.model.teams import latest_xi

    api = _api()
    if series_id is None:
        series_id, name = latest_ipl(api)
        console.print(f"Using {name}")
    records, meta = load_seasons(api, [series_id])
    priors = Priors.bundled("ipl")
    profiles = build_profiles(records, meta, priors)
    a, b = latest_xi(team_a, records, profiles), latest_xi(team_b, records, profiles)
    model = OutcomeModel(priors)
    rng = random.Random(seed)
    if runs == 1:
        print_match(simulate_match(model, a, b, rng), profiles)
        return
    wins = {a.name: 0, b.name: 0}
    for _ in range(runs):
        m = simulate_match(model, a, b, rng)
        wins[m.winner] += 1
    for team, w in wins.items():
        console.print(f"{team}: {100 * w / runs:.1f}%")


if __name__ == "__main__":
    app()
