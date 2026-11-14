from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    data_dir: Path = ROOT / "data"
    workspace_database_url: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    search_api_key: str = ""
    public_base_url: str = "http://127.0.0.1:8000"

    @property
    def database_url(self):
        return (
            self.workspace_database_url
            or f"sqlite:///{self.data_dir.resolve() / 'workspace.db'}"
        )


@lru_cache
def settings():
    result = Settings()
    if not result.data_dir.is_absolute():
        result.data_dir = (ROOT / result.data_dir).resolve()
    for directory in ["uploads", "generated", "backups"]:
        (result.data_dir / directory).mkdir(parents=True, exist_ok=True)
    return result
