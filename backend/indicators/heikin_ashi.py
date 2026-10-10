"""
================================================================================
 indicators/heikin_ashi.py  -  PIPELINE STEP 3
================================================================================
Transforms real candles into Heikin-Ashi (HA) candles.  HA smooths noise:

    ha_close = (open + high + low + close) / 4
    ha_open  = (previous ha_open + previous ha_close) / 2
               first candle: (open + close) / 2      <- TradingView seed rule
    ha_high  = max(real high, ha_open, ha_close)
    ha_low   = min(real low,  ha_open, ha_close)

Each output row keeps the real OHLC too (real_open ... real_close) because the
broker must trade at REAL prices, never at synthetic HA prices.
"""


def to_heikin_ashi_raw(candles):
    """Computes Heikin-Ashi candles with TradingView seed logic."""
    ha_list = []
    n = len(candles)
    if n == 0:
        return []

    prev_ha_open = 0.0
    prev_ha_close = 0.0

    for i, c in enumerate(candles):
        ha_close = (c["open"] + c["high"] + c["low"] + c["close"]) / 4.0
        if i == 0:
            ha_open = (c["open"] + c["close"]) / 2.0
        else:
            ha_open = (prev_ha_open + prev_ha_close) / 2.0

        ha_high = max(c["high"], ha_open, ha_close)
        ha_low = min(c["low"], ha_open, ha_close)

        ha_list.append({
            "time": c["time"],
            "time_str": c["time_str"],
            "ha_open": ha_open,
            "ha_high": ha_high,
            "ha_low": ha_low,
            "ha_close": ha_close,
            "real_open": c["open"],
            "real_high": c["high"],
            "real_low": c["low"],
            "real_close": c["close"],
            "ticks": c["ticks"],
        })

        prev_ha_open = ha_open
        prev_ha_close = ha_close

    return ha_list
