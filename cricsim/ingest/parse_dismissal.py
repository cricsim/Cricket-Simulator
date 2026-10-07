"""Parse scorecard dismissal text (`outdec`), e.g. "c Phil Salt b Jacob Duffy"."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Kinds credited to the bowler (a run-out, retirement or obstruction is not).
BOWLER_KINDS = {"caught", "bowled", "lbw", "stumped", "hit wicket"}

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("caught", re.compile(r"^c\s*(?:&|and)\s*b\s+(?P<bowler>.+)$")),
    ("caught", re.compile(r"^c\s+(?P<fielder>.+?)\s+b\s+(?P<bowler>.+)$")),
    ("stumped", re.compile(r"^st\s+(?P<fielder>.+?)\s+b\s+(?P<bowler>.+)$")),
    ("lbw", re.compile(r"^lbw\s+b\s+(?P<bowler>.+)$")),
    ("hit wicket", re.compile(r"^hit\s*(?:wicket|wkt)\s+b\s+(?P<bowler>.+)$")),
    ("bowled", re.compile(r"^b\s+(?P<bowler>.+)$")),
    ("run out", re.compile(r"^run\s*out\s*(?:\((?P<fielder>[^)]*)\))?")),
    ("retired hurt", re.compile(r"^ret(?:ire)?d\s*hurt")),
    ("retired out", re.compile(r"^ret(?:ire)?d\s*out")),
    ("retired hurt", re.compile(r"^ret(?:ire)?d")),
    ("obstructing", re.compile(r"^obs(?:tructing|\b)")),
    ("timed out", re.compile(r"^timed\s*out")),
]


@dataclass(frozen=True)
class Dismissal:
    kind: str  # "not out", "did not bat", "caught", "bowled", "retired hurt", ...
    bowler: str | None = None
    fielder: str | None = None

    @property
    def is_out(self) -> bool:
        return self.kind not in ("not out", "did not bat", "retired hurt")

    @property
    def is_retirement(self) -> bool:
        return self.kind.startswith("retired")

    @property
    def credited_to_bowler(self) -> bool:
        return self.kind in BOWLER_KINDS


def parse_dismissal(text: str | None) -> Dismissal:
    text = (text or "").strip()
    if not text:
        return Dismissal("did not bat")
    if text.lower().startswith("not out"):
        return Dismissal("not out")
    for kind, pattern in _PATTERNS:
        m = pattern.match(text)
        if m:
            g = m.groupdict()
            bowler = (g.get("bowler") or "").strip() or None
            fielder = (g.get("fielder") or "").strip() or None
            if kind == "caught" and fielder is None:
                fielder = bowler  # caught and bowled
            if fielder and fielder.startswith("sub"):
                fielder = None
            return Dismissal(kind, bowler, fielder)
    return Dismissal("unknown")
