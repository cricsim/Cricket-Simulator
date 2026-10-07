"""Backtest helpers: forecast parsing and scoring rules."""

import importlib.util
import math
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "backtest", Path(__file__).resolve().parent.parent / "scripts" / "backtest.py")
backtest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backtest)


class FakeApi:
    def __init__(self, value):
        self.value = value

    def forecast_prediction(self, match_id):
        return None if self.value is None else {"cbPrediction": {"value": self.value}}


def test_cricbuzz_probability_is_oriented_to_team1():
    assert backtest.cricbuzz_prob(FakeApi("GT Wins (55% Probability)"), 1, "GT") == 0.55
    assert abs(backtest.cricbuzz_prob(FakeApi("GT Wins (55% Probability)"), 1, "RCB") - 0.45) < 1e-9
    assert backtest.cricbuzz_prob(FakeApi(None), 1, "GT") is None
    assert backtest.cricbuzz_prob(FakeApi("Too close to call"), 1, "GT") is None


def test_scores():
    coin = backtest.scores([0.5, 0.5], [1, 0])
    assert abs(coin["log_loss"] - math.log(2)) < 1e-9 and coin["brier"] == 0.25
    assert math.isnan(coin["accuracy"])
    perfect = backtest.scores([1.0, 0.0], [1, 0])
    assert perfect["brier"] == 0 and perfect["accuracy"] == 1
