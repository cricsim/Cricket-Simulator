"""Outcome probabilities for a single delivery.

p[k] ∝ bat[k] · bowl[k] / league_bowl[k] · phase[k] · wickets[k] · chase[k] · inn2[k]

The batter's distribution is scaled by how much the bowler deviates from the league
average (a multiplicative blend), then by context factors measured from the
ingested ball-by-ball data: game phase, wickets lost, the required run rate in a chase,
and how second innings differ overall (dew, chasing with a known target).
"""

from __future__ import annotations

import random

from cricsim.model.profiles import (
    N_OUT,
    RRR_BUCKETS,
    WKT_BUCKETS,
    PlayerProfile,
    Priors,
    W,
    bucket_index,
    phase_of,
)


class OutcomeModel:
    def __init__(self, priors: Priors, adjust: dict[int, list[float]] | None = None):
        self.priors = priors
        self.adjust = adjust or {}  # optional per-player multipliers (match context)
        # Keyed by profile object identity, not player ID: the same player can have
        # different profiles (e.g. rebuilt per match in a backtest). Values keep a
        # reference to the profiles so their ids can't be reused while cached.
        self._base: dict[tuple[int, int], tuple[PlayerProfile, PlayerProfile, list[float]]] = {}
        self._cum: dict[tuple, list[float]] = {}

    def _pair(self, bat: PlayerProfile, bowl: PlayerProfile) -> list[float]:
        key = (id(bat), id(bowl))
        hit = self._base.get(key)
        if hit is not None:
            return hit[2]
        lg = self.priors.bowl
        v = [bat.bat[k] * bowl.bowl[k] / lg[k] for k in range(N_OUT)]
        for pid in (bat.player_id, bowl.player_id):
            if pid in self.adjust:
                v = [x * m for x, m in zip(v, self.adjust[pid])]
        self._base[key] = (bat, bowl, v)
        return v

    def cumulative(self, bat: PlayerProfile, bowl: PlayerProfile, over: int, wickets: int,
                   required_rate: float | None, free_hit: bool = False) -> list[float]:
        ph = phase_of(over)
        wb = bucket_index(wickets, WKT_BUCKETS)
        rb = -1 if required_rate is None else bucket_index(required_rate, RRR_BUCKETS)
        key = (id(bat), id(bowl), ph, wb, rb, free_hit)
        cum = self._cum.get(key)
        if cum is None:
            pr = self.priors
            v = self._pair(bat, bowl)
            f_ph, f_wk = pr.phase_factor[ph], pr.wkt_factor[ph][wb]
            v = [v[k] * f_ph[k] * f_wk[k] for k in range(N_OUT)]
            if rb >= 0:
                f_rr, f_i2 = pr.rrr_factor[ph][rb], pr.inn2_factor[ph]
                v = [v[k] * f_rr[k] * f_i2[k] for k in range(N_OUT)]
            if free_hit:
                v[0] += v[W]  # only a run-out is possible; treat as a dot
                v[W] = 0.0
            total = sum(v)
            cum, acc = [], 0.0
            for x in v:
                acc += x / total
                cum.append(acc)
            self._cum[key] = cum
        return cum

    @staticmethod
    def sample(cum: list[float], rng: random.Random) -> int:
        u = rng.random()
        for k, c in enumerate(cum):
            if u < c:
                return k
        return len(cum) - 1
