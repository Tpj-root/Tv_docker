"""
================================================================================
 indicators/sma.py  -  TEMPLATE: how to add your OWN indicator
================================================================================
1. Copy this file, rename it (for example rsi.py or my_math.py).
2. Change `id`, `title`, the Params, and the maths inside compute().
3. Open indicators/__init__.py, import your module and add its INDICATOR to ALL.
4. Add the default values to config.py and use them in the Param(...) lines.

That is all: the control bar shows your parameters and the chart draws your
line.  compute() receives candles and must return one value per candle
(None = no point on that candle).
"""

from typing import Any, Dict

from .base import BaseIndicator, Param
import config


def sma_values(values, period):
    """Simple moving average. First (period-1) points are None (not enough data)."""
    out = [None] * len(values)
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= period:
            running -= values[i - period]          # drop the value that left the window
        if i >= period - 1:
            out[i] = running / period
    return out


class SMA(BaseIndicator):
    id = "sma"
    title = "SMA (example)"
    role = "overlay"
    description = "Simple moving average of the close. Template for your own indicators."
    enabled_default = config.SMA_ENABLED
    params = (
        Param("period", "Period", "int", config.SMA_PERIOD, 2, 500, 1),
    )

    def compute(self, ctx: Dict[str, Any], p: Dict[str, Any]) -> Dict[str, Any]:
        closes = [c["close"] for c in ctx["candles"]]
        return {"lines": [{
            "id": "sma", "title": f"SMA {p['period']}", "color": "#f0b429", "width": 1,
            "values": sma_values(closes, p["period"]),
        }]}


INDICATOR = SMA()
