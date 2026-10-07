"""Terminal output with rich: scorecards and prediction summaries."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from cricsim.engine.match import InningsResult, MatchResult
from cricsim.model.profiles import PlayerProfile

console = Console()


def _name(pid: int, profiles: dict[int, PlayerProfile]) -> str:
    p = profiles.get(pid)
    return p.name if p else str(pid)


def innings_table(inn: InningsResult, profiles: dict[int, PlayerProfile], title: str) -> Table:
    t = Table(title=f"{title}: {inn.team} {inn.runs}/{inn.wickets} ({inn.overs} ov)",
              title_justify="left", expand=False)
    for col, just in (("Batter", "left"), ("", "left"), ("R", "right"), ("B", "right"),
                      ("4s", "right"), ("6s", "right"), ("SR", "right")):
        t.add_column(col, justify=just)
    for pid, c in inn.batting.items():
        sr = f"{100 * c.runs / c.balls:.1f}" if c.balls else "-"
        t.add_row(_name(pid, profiles), c.how_out, str(c.runs), str(c.balls), str(c.fours),
                  str(c.sixes), sr)
    t.add_row("Extras", "", str(inn.extras), "", "", "", "", style="dim")
    return t


def bowling_table(inn: InningsResult, profiles: dict[int, PlayerProfile]) -> Table:
    t = Table(expand=False)
    for col, just in (("Bowler", "left"), ("O", "right"), ("R", "right"), ("W", "right"),
                      ("Econ", "right"), ("Wd", "right"), ("Nb", "right")):
        t.add_column(col, justify=just)
    for pid, c in inn.bowling.items():
        overs = f"{c.balls // 6}.{c.balls % 6}" if c.balls % 6 else str(c.balls // 6)
        econ = f"{6 * c.runs / c.balls:.2f}" if c.balls else "-"
        t.add_row(_name(pid, profiles), overs, str(c.runs), str(c.wickets), econ, str(c.wides),
                  str(c.noballs))
    return t


def print_match(m: MatchResult, profiles: dict[int, PlayerProfile]) -> None:
    console.print(f"[dim]{m.toss}[/dim]")
    for i, inn in enumerate(m.innings, start=1):
        console.print(innings_table(inn, profiles, f"Innings {i}"))
        console.print(bowling_table(inn, profiles))
    if m.super_over:
        so = m.super_over
        console.print(f"Super over: {so[0].team} {so[0].runs}/{so[0].wickets}, "
                      f"{so[1].team} {so[1].runs}/{so[1].wickets}")
    result = f"{m.winner} won by {m.margin}" if m.winner else "No result"
    console.print(f"[bold]{result}[/bold]\n")


def print_prediction(pred, show_sample: bool = True) -> None:
    from cricsim.predict import summarise_totals

    console.rule(f"[bold]{pred.title}[/bold]")
    console.print(f"Model: {pred.tier} tier, {pred.runs:,} simulations, {pred.confidence}")
    t = Table(expand=False)
    t.add_column("Team")
    t.add_column("Win %", justify="right")
    t.add_column("Score when batting first", justify="right")
    for team, p in sorted(pred.win_prob.items(), key=lambda kv: -kv[1]):
        t.add_row(team, f"{100 * p:.1f}%", summarise_totals(pred.first_innings.get(team, [])))
    console.print(t)
    if pred.cricbuzz_forecast:
        console.print(f"Cricbuzz pre-match forecast: [bold]{pred.cricbuzz_forecast}[/bold]")
    for team, names in pred.xi.items():
        console.print(f"[dim]{team} XI: {', '.join(names)}[/dim]")
    for note in pred.notes:
        console.print(f"[yellow]Note:[/yellow] {note}")
    if show_sample and pred.sample:
        console.rule("One simulated match")
        print_match(pred.sample, pred.profiles)
