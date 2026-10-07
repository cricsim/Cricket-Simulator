"""CLI smoke tests against the local cache (skipped when IPL 2026 is not cached)."""

import pytest
from typer.testing import CliRunner

from cricsim.api import Cricbuzz
from cricsim.cli import app

runner = CliRunner()
CACHED = Cricbuzz.from_env(offline=True).client.is_cached("/series/v1/9241")


def test_help_lists_newcomer_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("init", "predict", "data", "sim"):
        assert cmd in result.output


def test_predict_help():
    result = runner.invoke(app, ["predict", "--help"])
    assert result.exit_code == 0 and "--dry-run" in result.output and "--lite" in result.output


@pytest.mark.skipif(not CACHED, reason="IPL 2026 not cached")
def test_sim_match_win_probabilities_from_cache():
    result = runner.invoke(app, ["sim", "match", "RCB", "GT", "--series-id", "9241",
                                 "--runs", "200", "--seed", "1"])
    assert result.exit_code == 0, result.output
    lines = [ln for ln in result.output.splitlines() if ln.endswith("%")]
    assert len(lines) == 2
    assert abs(sum(float(ln.split(":")[1].strip(" %")) for ln in lines) - 100) < 0.2


@pytest.mark.skipif(not CACHED, reason="IPL 2026 not cached")
def test_sim_match_unknown_team_is_a_clear_error():
    result = runner.invoke(app, ["sim", "match", "XYZ", "GT", "--series-id", "9241"])
    assert result.exit_code != 0
    assert "not found" in str(result.exception)
