"""Settings: API credentials from the environment or a local .env file, plus data paths."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HOST = "cricbuzz-cricket.p.rapidapi.com"


def load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env loader (KEY=VALUE lines). Existing environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    api_host: str
    data_dir: Path

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"


def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        api_key=os.environ.get("RAPIDAPI_KEY") or None,
        api_host=os.environ.get("RAPIDAPI_HOST", DEFAULT_HOST),
        data_dir=Path(os.environ.get("CRICSIM_DATA", "data")),
    )
