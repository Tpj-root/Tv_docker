"""
================================================================================
 indicators/chandelier_exit.py  -  PIPELINE STEP 5 (+ the 6th step: buy/sell)
================================================================================
Full flow of this application (your flow):

    load_ticks_raw          core/ticks.py              ticks
    ticks_to_candles_raw    core/ticks.py              real candles
    to_heikin_ashi_raw      indicators/heikin_ashi.py  Heikin-Ashi candles
    compute_extremums_raw   indicators/extremums.py    upper / lower anchors
    chandelier_exit_raw     THIS FILE                  stops + direction + signals
    buy and sell            engine.py + broker/        orders on the paper broker

How the Chandelier Exit works
-----------------------------
    TR   = max(high-low, |high-prev_close|, |low-prev_close|)       (true range)
    ATR  = Wilder RMA of TR with alpha = 1/atr_period               (average range)
    long_stop_raw  = upper_anchor - atr_mult * ATR     (stop under the high)
    short_stop_raw = lower_anchor + atr_mult * ATR     (stop above the low)

    "Ratchet": a long stop may only move UP while price stays above it, a
    short stop may only move DOWN while price stays below it.

    direction flips to  +1 (BUY)  when close crosses above the previous short stop
                        -1 (SELL) when close crosses below the previous long stop
    buy_signal  = direction just changed -1 -> +1
    sell_signal = direction just changed +1 -> -1
    The trade is executed on the NEXT candle's real open (no look-ahead).

The maths of chandelier_exit_raw() is identical to your original function.  The
only change: it receives the already computed extremums (`ext`) instead of
recalculating them a second time, so the pipeline has one clear step per stage.
"""

from typing import Any, Dict, List

from .base import BaseIndicator, Param
from .extremums import compute_extremums_raw
import config


def chandelier_exit_raw(
    ha_candles: List[Dict[str, Any]],
    ext: Dict[str, List[float]],
    atr_period: int = 22,
    atr_mult: float = 3.0,
    mode: str = "tradingview",
) -> List[Dict[str, Any]]:
    """
    ha_candles : output of to_heikin_ashi_raw()
    ext        : output of compute_extremums_raw()   (anchors for the stops)
    returns    : one row per candle = the HA candle + indicator columns
                 (atr, long_stop, short_stop, direction, buy_signal, sell_signal ...)
    """
    n = len(ha_candles)
    if n == 0:
        return []

    # ---- 1. True Range ----------------------------------------------------
    tr = [0.0] * n
    tr[0] = ha_candles[0]["ha_high"] - ha_candles[0]["ha_low"]
    for i in range(1, n):
        h = ha_candles[i]["ha_high"]
        l = ha_candles[i]["ha_low"]
        prev_c = ha_candles[i - 1]["ha_close"]
        tr[i] = max(h - l, abs(h - prev_c), abs(l - prev_c))

    # ---- 2. ATR with Wilder's RMA (alpha = 1 / period, seeded on bar 0) ----
    atr = [0.0] * n
    atr[0] = tr[0]
    for i in range(1, n):
        atr[i] = (atr[i - 1] * (atr_period - 1) + tr[i]) / atr_period

    upper_anchor = ext["upper_anchor"]
    lower_anchor = ext["lower_anchor"]

    # ---- 3. Stops, ratchet and direction ----------------------------------
    result: List[Dict[str, Any]] = []
    direction = 1
    prev_ls = 0.0     # previous bar's (ratcheted) long stop
    prev_ss = 0.0     # previous bar's (ratcheted) short stop

    for i in range(n):
        h_max = upper_anchor[i]
        l_min = lower_anchor[i]
        cur_atr = atr[i]
        c = ha_candles[i]["ha_close"]

        ls_raw = h_max - atr_mult * cur_atr
        ss_raw = l_min + atr_mult * cur_atr
        ls = ls_raw
        ss = ss_raw

        if mode == "tradingview":
            # TradingView compares the PREVIOUS close for the ratchet ...
            if i > 0:
                prev_c = ha_candles[i - 1]["ha_close"]
                if prev_c > prev_ls:
                    ls = max(ls, prev_ls)
                if prev_c < prev_ss:
                    ss = min(ss, prev_ss)
                # ... and the CURRENT close against the previous stops for direction
                if c > prev_ss:
                    direction = 1
                elif c < prev_ls:
                    direction = -1
        else:  # "user_original": ratchet compares the CURRENT close
            if i > 0:
                if c > prev_ls:
                    ls = max(ls, prev_ls)
                if c < prev_ss:
                    ss = min(ss, prev_ss)
                if c > prev_ss:
                    direction = 1
                elif c < prev_ls:
                    direction = -1

        prev_dir = result[i - 1]["direction"] if i > 0 else 1
        buy_signal = (direction == 1 and prev_dir == -1) if i > 0 else False
        sell_signal = (direction == -1 and prev_dir == 1) if i > 0 else False

        row = dict(ha_candles[i])
        row.update({
            "tr": tr[i],
            "atr": cur_atr,
            "highest": h_max,
            "lowest": l_min,
            "long_stop_raw": ls_raw,
            "short_stop_raw": ss_raw,
            "long_stop": ls,
            "short_stop": ss,
            "direction": direction,
            "buy_signal": buy_signal,
            "sell_signal": sell_signal,
            # execution flags: act on the candle AFTER the signal candle
            "enter_long": result[i - 1]["buy_signal"] if i > 0 else False,
            "enter_short": result[i - 1]["sell_signal"] if i > 0 else False,
        })
        result.append(row)
        prev_ls = ls
        prev_ss = ss

    return result


class ChandelierExit(BaseIndicator):
    """Wraps the pipeline functions so the app can treat it like any indicator."""

    id = "chandelier_exit"
    title = "Chandelier Exit"
    role = "signal"
    description = "Gives the BUY / SELL signals. Its stop lines are also the stop loss of every trade."
    enabled_default = config.CE_ENABLED
    params = (
        Param("atr_period", "ATR period", "int", config.CE_ATR_PERIOD, 1, 200, 1,
              help="ATR length and size of the highest/lowest window"),
        Param("atr_mult", "ATR multiplier", "float", config.CE_ATR_MULT, 0.1, 15, 0.1,
              help="Bigger = stop farther from price, fewer signals"),
        Param("mode", "Ratchet mode", "select", config.CE_MODE,
              choices=("tradingview", "user_original")),
        Param("use_close", "Use close price for extremes", "bool", config.CE_USE_CLOSE,
              help="Ignore candle wicks when finding the highest/lowest"),
        Param("formula", "Extremum formula", "select", config.CE_FORMULA,
              choices=("close", "range_ma", "crest_trough", "pivot_sr")),
        Param("ma_len", "EMA length (range_ma / crest_trough)", "int", config.CE_MA_LEN, 2, 200, 1),
        Param("lookback", "Look-back (range_ma)", "int", config.CE_LOOKBACK, 2, 100, 1),
    )

    def compute(self, ctx: Dict[str, Any], p: Dict[str, Any]) -> Dict[str, Any]:
        ha = ctx["ha"]

        # PIPELINE STEP 4 - extremums
        ext = compute_extremums_raw(
            ha,
            atr_period=p["atr_period"],
            use_close=p["use_close"],
            extremum_formula=p["formula"],
            ma_len=p["ma_len"],
            lookback=p["lookback"],
        )
        # PIPELINE STEP 5 - chandelier exit
        rows = chandelier_exit_raw(
            ha, ext, atr_period=p["atr_period"], atr_mult=p["atr_mult"], mode=p["mode"]
        )

        # Standard Chandelier drawing: show the long stop while direction=+1 and
        # the short stop while direction=-1.  None = leave a gap in the line.
        long_vals = [r["long_stop"] if r["direction"] == 1 else None for r in rows]
        short_vals = [r["short_stop"] if r["direction"] == -1 else None for r in rows]

        return {
            "rows": rows,
            "buy": [r["buy_signal"] for r in rows],
            "sell": [r["sell_signal"] for r in rows],
            "lines": [
                {"id": "ce_long", "title": "CE long stop", "color": "#26a69a", "width": 2, "values": long_vals},
                {"id": "ce_short", "title": "CE short stop", "color": "#ef5350", "width": 2, "values": short_vals},
            ],
        }


INDICATOR = ChandelierExit()
