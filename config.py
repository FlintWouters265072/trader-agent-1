import os

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    pass


class Config:
    def __init__(self):
        self.alpaca_api_key_id = os.environ.get("ALPACA_API_KEY_ID", "").strip()
        self.alpaca_api_secret_key = os.environ.get("ALPACA_API_SECRET_KEY", "").strip()
        self.alpaca_base_url = os.environ.get(
            "ALPACA_BASE_URL", "https://paper-api.alpaca.markets"
        ).rstrip("/")
        self.alpaca_data_url = os.environ.get(
            "ALPACA_DATA_URL", "https://data.alpaca.markets"
        ).rstrip("/")
        self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

        # Dollar-denominated risk caps — not a share/coin count, since the agent can now pick
        # any US stock/ETF or Alpaca USD crypto pair, and those trade at wildly different prices
        # (a share-count cap that's sane for a stock would be dangerous applied to Bitcoin).
        self.max_order_value_usd = float(os.environ.get("MAX_ORDER_VALUE_USD", "1500"))
        self.max_symbol_exposure_usd = float(os.environ.get("MAX_SYMBOL_EXPOSURE_USD", "15000"))
        self.execute = os.environ.get("EXECUTE", "false").strip().lower() == "true"

        if not self.alpaca_api_key_id or not self.alpaca_api_secret_key:
            raise ConfigError(
                "ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY are not set. Copy .env.example to .env and fill them in."
            )
        if not self.anthropic_api_key:
            raise ConfigError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in.")
