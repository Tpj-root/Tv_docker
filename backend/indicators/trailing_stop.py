"""
================================================================================
 indicators/trailing_stop.py  -  STOP LOSS / TAKE PROFIT / TRAILING
================================================================================
Every position (automatic OR manual) gets two levels:

  STOP LOSS   starts at the Chandelier Exit stop line:
                 BUY  position -> the long stop  (below price)
                 SELL position -> the short stop (above price)
              If that line is on the wrong side of the entry price (for example
              a manual BUY while the Chandelier is in a down-trend) the stop
              falls back to   entry -/+ atr_mult x ATR.

  TAKE PROFIT entry +/- tp_rr x (distance entry -> initial stop)   (risk:reward)

  TRAILING    (switch "Trailing stop" ON) after every closed candle the stop
              follows the Chandelier line, but ONLY in the profitable direction:
                 BUY : stop can only go UP,    SELL : stop can only go DOWN.
              It never jumps to a level that is already beyond the current price.

The chart draws a white rectangle from the entry candle to now, between the
current stop and the take profit.  It "moves" because the stop trails and the
right edge follows the live candle.

All functions are pure (numbers in, number out), so they can be tested alone.
"""

from typing import Any, Dict, Optional

from .base import BaseIndicator, Param
import config


def initial_stop(side: str, price: float, bar: Optional[Dict[str, Any]], atr_mult: float,
                 fallback_atr: float) -> float:
    """
    Stop loss for a NEW position.
    side          "BUY" or "SELL"
    price         entry price
    bar           last CLOSED Chandelier row (needs long_stop, short_stop, atr) or None
    atr_mult      Chandelier ATR multiplier (for the fallback distance)
    fallback_atr  ATR value used when `bar` is missing
    """
    atr = bar["atr"] if bar else fallback_atr
    if side == "BUY":
        stop = bar["long_stop"] if bar else None
        if stop is None or stop >= price:                 # wrong side -> use ATR distance
            stop = price - atr_mult * atr
        return stop
    stop = bar["short_stop"] if bar else None
    if stop is None or stop <= price:
        stop = price + atr_mult * atr
    return stop


def take_profit(side: str, entry: float, stop: float, rr: float) -> float:
    """Take profit level = entry +/- rr x risk, where risk = |entry - stop|."""
    risk = abs(entry - stop)
    return entry + rr * risk if side == "BUY" else entry - rr * risk


def trail_stop(side: str, current_stop: float, bar: Optional[Dict[str, Any]], price: float) -> float:
    """
    Return the (possibly) improved stop.
    BUY : candidate = bar.long_stop,  accepted only if  current_stop < candidate < price
    SELL: candidate = bar.short_stop, accepted only if  price < candidate < current_stop
    """
    if not bar:
        return current_stop
    if side == "BUY":
        cand = bar["long_stop"]
        if current_stop < cand < price:
            return cand
    else:
        cand = bar["short_stop"]
        if price < cand < current_stop:
            return cand
    return current_stop


class TrailingStop(BaseIndicator):
    id = "trailing_stop"
    title = "Trailing stop loss / take profit"
    role = "control"
    description = "Stop loss = Chandelier line, trails with it. Take profit by risk:reward."
    enabled_default = config.TRAIL_ENABLED
    params = (
        Param("tp_enabled", "Use take profit", "bool", config.TP_ENABLED),
        Param("tp_rr", "Take profit risk:reward", "float", config.TP_RR, 0.1, 20, 0.1,
              help="2.0 = profit target is twice the stop distance"),
    )
    # The switch of this group means "trail the stop". The initial stop is always set.


INDICATOR = TrailingStop()
