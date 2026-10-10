"""
================================================================================
 indicators/base.py  -  building blocks shared by every indicator
================================================================================
The control bar on the right side of the chart is NOT hand-written per
indicator.  The browser asks the backend for a "schema" and draws one slider /
checkbox / dropdown for every Param it finds.  That means:

    To add your own indicator you only write ONE python file that declares its
    Params and a compute() function.  The control bar appears automatically.

Classes
-------
Param          one adjustable input (an int slider, a float slider, a checkbox
               or a dropdown) with its default, limits and validation.
SettingsGroup  a titled group of Params with an optional on/off switch.
BaseIndicator  a SettingsGroup that can also compute() lines / signals.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class Param:
    """One user-adjustable input value."""

    key: str                             # name used in python code and in JSON
    label: str                           # text shown next to the control
    kind: str                            # "int" | "float" | "bool" | "select"
    default: Any                         # value used at start-up (comes from config.py)
    min: Optional[float] = None          # lowest allowed value  (int / float)
    max: Optional[float] = None          # highest allowed value (int / float)
    step: Optional[float] = None         # slider step           (int / float)
    choices: Optional[Tuple[str, ...]] = None   # allowed values (select)
    help: str = ""                       # small hint under the control

    def coerce(self, value: Any) -> Any:
        """
        Validate a value that came from the browser and convert it to the
        right python type.  Numbers are clamped into [min, max].
        Raises ValueError on garbage so the API can answer HTTP 400.
        """
        if self.kind == "bool":
            if not isinstance(value, bool):
                raise ValueError(f"{self.key}: expected true/false")
            return value

        if self.kind == "select":
            if value not in (self.choices or ()):
                raise ValueError(f"{self.key}: must be one of {self.choices}")
            return value

        if self.kind in ("int", "float"):
            if isinstance(value, bool):          # bool is a subclass of int - reject it
                raise ValueError(f"{self.key}: expected a number")
            try:
                num = int(value) if self.kind == "int" else float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{self.key}: expected a number")
            if self.min is not None:
                num = max(self.min, num)
            if self.max is not None:
                num = min(self.max, num)
            return num

        raise ValueError(f"{self.key}: unknown kind {self.kind}")

    def to_dict(self) -> Dict[str, Any]:
        """JSON description sent to the browser so it can draw the control."""
        return {
            "key": self.key, "label": self.label, "kind": self.kind,
            "default": self.default, "min": self.min, "max": self.max,
            "step": self.step, "choices": list(self.choices) if self.choices else None,
            "help": self.help,
        }


class SettingsGroup:
    """
    A titled block of Params shown as one section of the control bar.

    id               short unique name, also the key in the settings dict
    title            heading shown in the browser
    has_toggle       True -> the section has an On/Off switch (key "enabled")
    enabled_default  start-up state of that switch
    params           tuple of Param
    """

    id: str = ""
    title: str = ""
    description: str = ""
    role: str = "control"                 # "signal" | "overlay" | "control" (only used for labelling)
    has_toggle: bool = True
    enabled_default: bool = True
    params: Tuple[Param, ...] = ()

    def defaults(self) -> Dict[str, Any]:
        """Start-up values: {"enabled": ..., "<param key>": default, ...}."""
        out: Dict[str, Any] = {}
        if self.has_toggle:
            out["enabled"] = self.enabled_default
        for p in self.params:
            out[p.key] = p.default
        return out

    def coerce_patch(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a partial update such as {"atr_mult": 2.5}."""
        by_key = {p.key: p for p in self.params}
        clean: Dict[str, Any] = {}
        for key, value in patch.items():
            if key == "enabled" and self.has_toggle:
                if not isinstance(value, bool):
                    raise ValueError("enabled: expected true/false")
                clean[key] = value
            elif key in by_key:
                clean[key] = by_key[key].coerce(value)
            else:
                raise ValueError(f"{self.id}: unknown setting '{key}'")
        return clean

    def schema(self) -> Dict[str, Any]:
        """Everything the browser needs to draw this section."""
        return {
            "id": self.id, "title": self.title, "description": self.description,
            "role": self.role, "has_toggle": self.has_toggle,
            "params": [p.to_dict() for p in self.params],
        }


class BaseIndicator(SettingsGroup):
    """
    A SettingsGroup that can calculate something from candles.

    compute(ctx, p) receives
        ctx = {"candles": [...real OHLC candles...],
               "ha":      [...Heikin-Ashi candles (also hold real_* prices)...]}
        p   = this indicator's current settings dict (see defaults())
    and returns a dict that may contain
        "lines":  [{"id", "title", "color", "width", "values": [float|None per candle]}]
        "buy":    [bool per candle]     (signal indicators)
        "sell":   [bool per candle]     (signal indicators)
        "rows":   anything the broker needs per candle (e.g. stop levels)
    A None value in a line means "draw nothing on this candle".
    """

    def compute(self, ctx: Dict[str, Any], p: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError
