from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ai_provider: str = Field(default="hackclub", description="hackclub or mock")
    news_provider: str = Field(default="hackclub", description="hackclub or mock")
    market_provider: str = Field(default="yfinance", description="yfinance")

    ai_hackclub_base_url: str = "https://ai.hackclub.com"
    ai_hackclub_endpoint: str = "/proxy/v1/chat/completions"
    ai_hackclub_model: str = "gpt-5-mini"
    ai_hackclub_api_key: str | None = None
    ai_hackclub_timeout_seconds: int = 20
    ai_hackclub_max_retries: int = 2

    search_hackclub_base_url: str = "https://search.hackclub.com"
    search_hackclub_endpoint: str = "/res/v1/news/search"
    search_hackclub_api_key: str | None = None
    search_hackclub_timeout_seconds: int = 15
    search_hackclub_max_retries: int = 2

    universe: str = "AAPL,MSFT,GOOGL,AMZN,NVDA"
    universe_mode: str = Field(default="auto", description="fixed or auto")
    auto_universe_max_symbols: int = 2000
    auto_universe_batch_size: int = 60
    auto_universe_min_price: float = 3.0
    auto_universe_max_price: float = 500.0

    data_dir: str = "data"
    dashboard_history_limit: int = 200
    cycle_interval_mins: int = 5

    # Display / timezone settings
    display_timezone: str = "America/New_York"
    buy_only_during_market_hours: bool = False
    market_open_hhmm: str = "09:30"
    market_close_hhmm: str = "16:00"

    starting_cash: float = 100_000.0
    max_allocation_per_trade: float = 0.03
    stop_loss_pct: float = 0.08

    ai_weight: float = 0.60
    conventional_weight: float = 0.40

    def universe_symbols(self) -> list[str]:
        return [s.strip().upper() for s in self.universe.split(",") if s.strip()]


settings = Settings()
