"""Validated runtime configuration."""

from enum import StrEnum
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[1]


class ModelProvider(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    BEDROCK = "bedrock"


class LLMMode(StrEnum):
    RECORD = "record"
    REPLAY = "replay"


class Settings(BaseSettings):
    """Environment-backed settings with no embedded credentials."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    model_provider: ModelProvider = ModelProvider.ANTHROPIC
    llm_mode: LLMMode = LLMMode.REPLAY
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    anthropic_model_id: str = "claude-sonnet-4-20250514"
    openai_model_id: str = "gpt-4o"
    bedrock_model_id: str = "anthropic.claude-sonnet-4-20250514-v1:0"
    database_path: Path = Field(default=ROOT_DIR / ".local" / "agentdesk.db")
    replay_dir: Path = Field(default=ROOT_DIR / "fixtures" / "replay")
    policies_dir: Path = Field(default=ROOT_DIR / "policies")

    @property
    def model_id(self) -> str:
        return {
            ModelProvider.ANTHROPIC: self.anthropic_model_id,
            ModelProvider.OPENAI: self.openai_model_id,
            ModelProvider.BEDROCK: self.bedrock_model_id,
        }[self.model_provider]
