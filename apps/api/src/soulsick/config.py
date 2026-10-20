"""Configuration d'environnement (chemins, port). Le reste vit en base (voir settings_store)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Env(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOULSICK_", env_file=".env", extra="ignore")

    config_dir: Path = Path("./data/config")
    music_dir: Path = Path("./data/music")
    downloads_dir: Path = Path("./data/downloads")
    web_dist: Path | None = None
    host: str = "0.0.0.0"
    port: int = 5030
    # Désactive le moteur Soulseek (tests, dev du front sans réseau)
    disable_engine: bool = False
    # Behind a VPN with port forwarding (gluetun): file holding the forwarded port. When set,
    # Soulseek listens on that port (it changes over time) instead of the one in the settings.
    forwarded_port_file: Path | None = None
    # The library folder must be mounted from the host (never the container's own disk).
    # Unset: required when running in a container.
    require_library_mount: bool | None = None

    @property
    def db_path(self) -> Path:
        return self.config_dir / "soulsick.db"

    @property
    def covers_dir(self) -> Path:
        return self.config_dir / "covers"

    def ensure_dirs(self) -> None:
        for d in (self.config_dir, self.music_dir, self.downloads_dir, self.covers_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_env() -> Env:
    return Env()
