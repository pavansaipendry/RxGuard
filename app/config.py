from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = ""

    upstream_mode: str = "anthropic"  # "anthropic" | "openai"
    upstream_model: str = "claude-sonnet-5"
    upstream_base_url: str = ""
    upstream_api_key: str = ""
    upstream_max_tokens: int = 1024

    judge_model: str = "claude-haiku-4-5-20251001"
    judges_enabled: bool = True
    judge_timeout_s: float = 15.0

    rxguard_db: str = "data/rxguard.db"

    dosage_kb_path: str = str(PROJECT_ROOT / "data" / "dosage_kb.csv")
    ddinter_path: str = str(PROJECT_ROOT / "data" / "ddinter_curated.csv")
    lexicon_path: str = str(PROJECT_ROOT / "data" / "drug_lexicon.csv")

    @property
    def judges_available(self) -> bool:
        return self.judges_enabled and bool(self.anthropic_api_key)


settings = Settings()
