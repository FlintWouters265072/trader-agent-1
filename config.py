import json
import os
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    pass


RISK_OVERRIDES_PATH = "risk_overrides.json"

# Dollar/count-denominated risk caps are not share/coin counts, since the agent can pick any US
# stock/ETF or Alpaca USD crypto pair, trading at wildly different prices (a share-count cap sane
# for a stock would be dangerous applied to Bitcoin). All four settings here are viewable/editable
# live from the dashboard's "Risk settings" panel — see effective_risk_settings() below for the
# override-file-over-.env precedence rule shared by both run.py and dashboard_server.py.
RISK_SETTINGS = {
    "max_order_value_usd": {
        "env_var": "MAX_ORDER_VALUE_USD", "default": 1500.0, "type": float,
        "min": 1.0, "max": 1_000_000.0, "label": "Max order value (USD)",
    },
    "max_symbol_exposure_usd": {
        "env_var": "MAX_SYMBOL_EXPOSURE_USD", "default": 15000.0, "type": float,
        "min": 1.0, "max": 5_000_000.0, "label": "Max symbol exposure (USD)",
    },
    "max_concurrent_positions": {
        "env_var": "MAX_CONCURRENT_POSITIONS", "default": 8, "type": int,
        "min": 1, "max": 200, "label": "Max concurrent positions",
    },
    "risk_appetite": {
        "env_var": "RISK_APPETITE", "default": "medium", "type": str,
        "choices": ["low", "medium", "high"], "label": "Risk appetite",
    },
}


def load_risk_overrides() -> dict:
    if not os.path.exists(RISK_OVERRIDES_PATH):
        return {}
    try:
        with open(RISK_OVERRIDES_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def effective_risk_settings() -> dict:
    """Effective value + source ('override'/'env') for each dashboard-editable risk setting —
    single source of truth for the override-wins-over-.env precedence, used by both Config (to
    pick what run.py actually enforces) and dashboard_server.py (to display/edit them)."""
    overrides = load_risk_overrides()
    result = {}
    for key, spec in RISK_SETTINGS.items():
        env_raw = os.environ.get(spec["env_var"], spec["default"])
        env_default = spec["type"](env_raw).strip().lower() if spec["type"] is str else spec["type"](env_raw)
        if key in overrides:
            try:
                raw = overrides[key]
                value = spec["type"](raw).strip().lower() if spec["type"] is str else spec["type"](raw)
                result[key] = {"value": value, "source": "override", "env_default": env_default}
                continue
            except (TypeError, ValueError):
                pass  # corrupt value for this key only — fall back to env default for just this key
        result[key] = {"value": env_default, "source": "env", "env_default": env_default}
    return result


def validate_risk_setting(key: str, raw_value: str):
    """Parse+validate one submitted field. Returns (value, None) or (None, error_message)."""
    spec = RISK_SETTINGS.get(key)
    if spec is None:
        return None, f"Unknown setting: {key}"
    if "choices" in spec:
        value = (raw_value or "").strip().lower()
        if value not in spec["choices"]:
            return None, f"{spec['label']} must be one of: {', '.join(spec['choices'])}."
        return value, None
    try:
        value = spec["type"](raw_value)
    except (TypeError, ValueError):
        return None, f"{spec['label']} must be a number."
    if value < spec["min"] or value > spec["max"]:
        return None, f"{spec['label']} must be between {spec['min']} and {spec['max']}."
    return value, None


def save_risk_overrides(values: dict) -> None:
    """Atomically overwrite risk_overrides.json with exactly these (always all four) values."""
    payload = {**values, "updated_at": datetime.now(timezone.utc).isoformat()}
    tmp_path = RISK_OVERRIDES_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp_path, RISK_OVERRIDES_PATH)


def reset_risk_overrides() -> None:
    if os.path.exists(RISK_OVERRIDES_PATH):
        os.remove(RISK_OVERRIDES_PATH)


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

        risk = effective_risk_settings()
        self.max_order_value_usd = risk["max_order_value_usd"]["value"]
        self.max_symbol_exposure_usd = risk["max_symbol_exposure_usd"]["value"]
        self.max_concurrent_positions = risk["max_concurrent_positions"]["value"]
        self.risk_appetite = risk["risk_appetite"]["value"]
        self.execute = os.environ.get("EXECUTE", "false").strip().lower() == "true"

        if not self.alpaca_api_key_id or not self.alpaca_api_secret_key:
            raise ConfigError(
                "ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY are not set. Copy .env.example to .env and fill them in."
            )
        if not self.anthropic_api_key:
            raise ConfigError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in.")
