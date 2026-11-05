from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    initial_capital_inr: float = Field(default=1_000_000, gt=0)
    journal_dir: Path = Path("data/journal")
    strategy_mode: Literal["technical", "news", "corporate_actions", "combined"] = "technical"
    trading_horizon: Literal["intraday", "swing", "positional"] = "intraday"
    enable_parallel_execution: bool = True
    max_parallel_agents: int = Field(default=6, ge=1, le=32)
    max_concurrent_tool_calls: int = Field(default=10, ge=1, le=100)
    max_llm_concurrency: int = Field(default=4, ge=1, le=32)
    agent_timeout_seconds: int = Field(default=120, gt=0, le=900)
    agent_max_retries: int = Field(default=2, ge=0, le=5)
    max_risk_per_trade_pct: float = Field(default=.01, gt=0, le=.05)
    max_daily_loss_pct: float = Field(default=.03, gt=0, le=.20)
    max_drawdown_pct: float = Field(default=.10, gt=0, le=.50)
    max_open_positions: int = Field(default=5, ge=1, le=100)
    max_gross_exposure_pct: float = Field(default=0.80, gt=0, le=1)
    max_single_position_exposure_pct: float = Field(default=0.25, gt=0, le=1)
    cycle_interval_seconds: int = Field(default=60, ge=5, le=3600)
    max_market_data_freshness_seconds: int = Field(default=86400, ge=1, le=604800)
    watchlist: list[str] = Field(default_factory=lambda: ["RELIANCE"])
    default_exchange: Literal["NSE", "BSE"] = "NSE"
    llm_provider: Literal["disabled", "ollama", "openrouter"] = "disabled"
    llm_base_url: str = "http://localhost:11434"
    llm_model: str = "qwen3:4b"
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: int = Field(default=30, ge=1, le=300)

    @model_validator(mode="after")
    def validate_limits(self) -> "Settings":
        if self.max_risk_per_trade_pct >= self.max_daily_loss_pct:
            raise ValueError("per-trade risk must be below daily loss limit")
        normalized = [symbol.strip().upper() for symbol in self.watchlist]
        if not normalized or any(not symbol for symbol in normalized):
            raise ValueError("watchlist must contain non-empty symbols")
        if len(normalized) != len(set(normalized)):
            raise ValueError("watchlist symbols must be unique")
        self.watchlist = normalized
        if self.llm_provider == "openrouter":
            if self.llm_api_key is None or not self.llm_api_key.get_secret_value().strip():
                raise ValueError("LLM_API_KEY is required when LLM_PROVIDER=openrouter")
            if self.llm_base_url.rstrip("/") == "http://localhost:11434":
                self.llm_base_url = "https://openrouter.ai/api/v1"
        return self
