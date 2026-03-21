"""Configuration loader for the trading system."""

from __future__ import annotations

import yaml
from pathlib import Path


def load_config(path: str | Path = "config.yaml") -> dict:
    """Load and return configuration from YAML file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def get_tick_value(config: dict) -> float:
    """Return tick value in dollars based on configured asset."""
    asset = config.get("system", {}).get("asset", "MES")
    tick_cfg = config.get("tick", {})
    if asset == "ES":
        return tick_cfg.get("es_tick_value", 12.50)
    return tick_cfg.get("mes_tick_value", 1.25)


def get_tick_size(config: dict) -> float:
    """Return tick size (minimum price increment)."""
    asset = config.get("system", {}).get("asset", "MES")
    tick_cfg = config.get("tick", {})
    if asset == "ES":
        return tick_cfg.get("es_tick_size", 0.25)
    return tick_cfg.get("mes_tick_size", 0.25)


def get_point_value(config: dict) -> float:
    """Return dollar value per full point (4 ticks)."""
    return get_tick_value(config) * 4
