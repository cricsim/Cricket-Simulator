"""Choose the bowler for each over.

Rules: at most `max_per_bowler` overs each, no bowler twice in a row, and the remaining
overs must stay coverable. Preference comes from each bowler's real usage: the share of
their overs bowled at this over index times how many overs a match they usually bowl.
"""

from __future__ import annotations

import random

from cricsim.model.profiles import PlayerProfile


class BowlingPlan:
    def __init__(self, xi: list[PlayerProfile], max_overs: int = 20,
                 max_per_bowler: int | None = None):
        self.max_overs = max_overs
        self.cap = max_per_bowler or max(1, -(-max_overs // 5))  # 4 in a T20
        regulars = [p for p in xi if p.bowls]
        regulars.sort(key=lambda p: -(p.overs_per_match or 0.5))
        # Part-timers (non-keepers who don't usually bowl), most experienced first.
        self.part_timers = sorted((p for p in xi if p not in regulars and not p.is_keeper),
                                  key=lambda p: -p.bowl_balls)
        self.pool = regulars
        self.used: dict[int, int] = {}
        self.last: int | None = None

    def _capacity(self, exclude: int | None) -> int:
        return sum(self.cap - self.used.get(p.player_id, 0)
                   for p in self.pool if p.player_id != exclude)

    def next_bowler(self, over: int, rng: random.Random) -> PlayerProfile:
        remaining_after = self.max_overs - over - 1
        while True:
            candidates = []
            for p in self.pool:
                used = self.used.get(p.player_id, 0)
                if used >= self.cap or p.player_id == self.last:
                    continue
                # Others plus this bowler's own leftover overs must cover the rest.
                if self._capacity(p.player_id) + (self.cap - used - 1) < remaining_after:
                    continue
                pref = p.over_pref[over] if p.over_pref else 1 / 20
                weight = pref * max(p.overs_per_match, 1.0) + 1e-6
                candidates.append((p, weight))
            if candidates:
                break
            if not self.part_timers:
                # Nobody eligible: relax the consecutive-overs rule as a last resort.
                eligible = [p for p in self.pool if self.used.get(p.player_id, 0) < self.cap]
                choice = eligible[0] if eligible else self.pool[0]
                self._record(choice)
                return choice
            self.pool.append(self.part_timers.pop(0))
        # Sharpen preferences so main bowlers mostly bowl their usual overs.
        weights = [w * w for _, w in candidates]
        choice = rng.choices([p for p, _ in candidates], weights=weights)[0]
        self._record(choice)
        return choice

    def _record(self, p: PlayerProfile) -> None:
        self.used[p.player_id] = self.used.get(p.player_id, 0) + 1
        self.last = p.player_id
