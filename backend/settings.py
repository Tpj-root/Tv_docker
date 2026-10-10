"""
================================================================================
 settings.py  -  every adjustable setting in one place
================================================================================
settings (a dict) looks like this and is the single source of truth while the
backend runs:

    {
      "chandelier_exit": {"enabled": True, "atr_period": 22, "atr_mult": 3.0, ...},
      "signal_delay":    {"enabled": False, "buy_delay_s": 5, "sell_delay_s": 5},
      "trailing_stop":   {"enabled": True, "tp_enabled": True, "tp_rr": 2.0},
      "auto_trade":      {"enabled": True, "volume": 1.0, "reverse": True},
      "manual":          {"volume": 1.0},
      "view":            {"show_ha": False},
    }

The start-up values come from config.py.  The browser edits them at run time
with POST /api/settings (partial updates, fully validated here).
"""

import copy
from typing import Any, Dict, List

import config
from indicators import ALL as INDICATORS
from indicators.base import Param, SettingsGroup


class AutoTrade(SettingsGroup):
    """Chandelier signals -> paper broker."""
    id = "auto_trade"
    title = "Auto trading"
    role = "control"
    description = "Open / close trades automatically from the signals."
    enabled_default = config.AUTO_TRADE
    params = (
        Param("volume", "Volume per trade", "float", config.AUTO_VOLUME, 0.01, 100000, 0.01),
        Param("reverse", "Reverse on opposite signal", "bool", config.REVERSE_ON_SIGNAL,
              help="A BUY signal closes automatic SELL trades and vice versa"),
    )


class Manual(SettingsGroup):
    """Default volume of the manual Buy / Sell buttons."""
    id = "manual"
    title = "Manual order"
    role = "control"
    has_toggle = False
    params = (
        Param("volume", "Volume", "float", config.MANUAL_VOLUME, 0.01, 100000, 0.01),
    )


class View(SettingsGroup):
    """Chart display options."""
    id = "view"
    title = "Chart"
    role = "control"
    has_toggle = False
    params = (
        Param("show_ha", "Show Heikin-Ashi candles", "bool", config.SHOW_HEIKIN_ASHI),
    )


# Order = order of the sections in the control bar.
GROUPS: List[SettingsGroup] = [*INDICATORS, AutoTrade(), Manual(), View()]
BY_ID: Dict[str, SettingsGroup] = {g.id: g for g in GROUPS}


def default_settings() -> Dict[str, Dict[str, Any]]:
    """A fresh settings dict with the values from config.py."""
    return {g.id: g.defaults() for g in GROUPS}


def schema() -> List[Dict[str, Any]]:
    """Description of all sections / controls for the browser."""
    return [g.schema() for g in GROUPS]


def apply_patch(current: Dict[str, Dict[str, Any]], patch: Dict[str, Dict[str, Any]]):
    """
    Validate `patch` ({"group_id": {"key": value}}) and return a NEW settings dict.
    Raises ValueError (-> HTTP 400) when a group / key / value is invalid.
    `current` is not modified, so a bad patch changes nothing.
    """
    new = copy.deepcopy(current)
    for gid, values in patch.items():
        group = BY_ID.get(gid)
        if group is None:
            raise ValueError(f"unknown settings group '{gid}'")
        if not isinstance(values, dict):
            raise ValueError(f"{gid}: expected an object")
        new[gid].update(group.coerce_patch(values))
    return new
