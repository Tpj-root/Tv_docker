"""
================================================================================
 engine.py  -  THE TRADING ENGINE (no web / network code inside)
================================================================================
The engine is a plain python object.  You feed it ticks, it answers with JSON
messages.  Because it knows nothing about FastAPI or Deriv it can be unit-tested
by replaying ticks (see backend/tests/test_engine.py).

What happens for EVERY new tick  (on_tick):

  1. add the tick                      ticks -> real candles -> Heikin-Ashi ->
  2. rebuild the indicator pipeline    extremums -> Chandelier Exit rows
  3. check open positions              stop loss / take profit hit?  -> close
                                       then trail the stop (trailing_stop.py)
  4. look for NEW signals              only on CLOSED candles (never repaints)
                                       -> handed to the delay controller
  5. execute signals whose waiting     -> paper broker opens / closes trades
     time (signal delay) is over

Why only closed candles?  The newest candle is still forming, so its HA values
and Chandelier direction can still change.  A signal on candle N is confirmed
when candle N+1 opens, and the order is filled at that moment - the same
"next candle open, zero look-ahead" rule as your back-test.

Time:  the engine's clock is the TICK time (Deriv epoch seconds).  This keeps
live trading and replay tests identical.
"""

from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

import config
import settings as settings_mod
from broker import make_broker, ts_str
from core.ticks import ticks_to_candles_raw                    # pipeline step 2
from indicators import chandelier_exit, trailing_stop, to_heikin_ashi_raw   # steps 3-5 + stops
from indicators import ALL as INDICATORS
from indicators.signal_delay import DelayController

ALLOWED_TIMEFRAMES = (60, 120, 180, 300, 600, 900, 1800, 3600, 7200, 14400, 28800, 86400)
MAX_BARS_SENT = 1500          # newest candles sent to the browser


class EngineError(Exception):
    """A request that cannot be done right now.  `status` is the HTTP code the API answers with."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class Engine:
    def __init__(self) -> None:
        self.symbol: str = config.SYMBOL
        self.tf: int = config.TIMEFRAME_SECONDS
        self.settings: Dict[str, Dict[str, Any]] = settings_mod.default_settings()
        self.broker = make_broker()
        self.delay = DelayController()
        self.events: Deque[Dict[str, Any]] = deque(maxlen=300)   # activity log
        self._new_events: List[Dict[str, Any]] = []              # events since last tick message
        self._trades_dirty = False                               # a trade closed since last message
        self._reset_market_state()

    # ===================================================================== state
    def _reset_market_state(self) -> None:
        """Forget everything that belongs to one symbol / timeframe."""
        self.ticks: List[Tuple[int, float]] = []
        self.last_tick_t: int = 0
        self.price: Optional[float] = None
        self.candles: List[Dict[str, Any]] = []
        self.ha: List[Dict[str, Any]] = []
        self.ce_rows: List[Dict[str, Any]] = []
        self.lines: List[Dict[str, Any]] = []
        self.markers: List[Dict[str, Any]] = []
        self.last_signal_bar: int = 0      # newest closed candle already checked for signals
        self.delay.clear()

    def _event(self, ts: int, kind: str, text: str) -> None:
        ev = {"ts": ts, "time": ts_str(ts) if ts else "", "kind": kind, "text": text}
        self.events.append(ev)
        self._new_events.append(ev)

    # ============================================================ market / history
    def load_history(self, ticks: List[Tuple[int, float]]) -> None:
        """
        Start (or restart) a market with historical ticks [(epoch, price), ...].
        Signals that already happened in the history are NOT traded; only
        candles that close after this moment can trigger orders.
        """
        self._reset_market_state()
        last = 0
        for t, p in sorted(ticks, key=lambda x: x[0]):
            if t > last:                          # keep first tick of every second
                self.ticks.append((t, p))
                last = t
        if self.ticks:
            self.last_tick_t, self.price = self.ticks[-1]
        self._recompute()
        if len(self.ce_rows) >= 2:
            self.last_signal_bar = self.ce_rows[-2]["time"]

    def set_market(self, symbol: str, timeframe: int) -> None:
        """Change symbol / timeframe.  Refused while positions are open."""
        if timeframe not in ALLOWED_TIMEFRAMES:
            raise EngineError(f"timeframe must be one of {ALLOWED_TIMEFRAMES}")
        if self.broker.positions:
            raise EngineError("Close all open positions before changing symbol or timeframe", 409)
        keep = self.ticks if symbol == self.symbol else []     # same symbol: re-bucket the same ticks
        self.symbol, self.tf = symbol, timeframe
        self._reset_market_state()
        if keep:
            self.load_history(keep)
        self._event(self.last_tick_t, "INFO", f"Market: {symbol}  timeframe {timeframe}s")

    # ================================================================== settings
    def update_settings(self, patch: Dict[str, Dict[str, Any]]) -> None:
        """Apply a validated partial update and recompute the indicators."""
        try:
            self.settings = settings_mod.apply_patch(self.settings, patch)
        except ValueError as e:
            raise EngineError(str(e))
        self._recompute()

    def reset_settings(self) -> None:
        """Back to the values written in config.py."""
        self.settings = settings_mod.default_settings()
        self._recompute()
        self._event(self.last_tick_t, "INFO", "Settings reset to config.py defaults")

    # ============================================================== the pipeline
    def _recompute(self) -> None:
        """
        Run the whole indicator pipeline on all ticks:
            ticks_to_candles_raw -> to_heikin_ashi_raw -> compute_extremums_raw ->
            chandelier_exit_raw  (the last two live inside ChandelierExit.compute)
        then collect lines (for the chart) and signal markers.
        """
        self.candles = ticks_to_candles_raw(self.ticks, self.tf)
        self.ha = to_heikin_ashi_raw(self.candles)
        ctx = {"candles": self.candles, "ha": self.ha}

        ce_set = self.settings["chandelier_exit"]
        # The Chandelier is ALWAYS calculated because its stop lines are the stop
        # loss of every trade.  "enabled" decides whether it draws and signals.
        ce = chandelier_exit.INDICATOR.compute(ctx, ce_set) if self.ha else \
            {"rows": [], "buy": [], "sell": [], "lines": []}
        self.ce_rows = ce["rows"]

        lines: List[Dict[str, Any]] = list(ce["lines"]) if ce_set["enabled"] else []
        for ind in INDICATORS:
            if ind.role == "overlay" and self.settings[ind.id]["enabled"] and self.candles:
                lines.extend(ind.compute(ctx, self.settings[ind.id]).get("lines", []))
        self.lines = lines

        n = len(self.ce_rows)
        self.markers = []
        if ce_set["enabled"]:
            for i, r in enumerate(self.ce_rows):
                side = "BUY" if r["buy_signal"] else "SELL" if r["sell_signal"] else None
                if side:
                    self.markers.append({"time": r["time"], "side": side, "confirmed": i < n - 1})
            self.markers = self.markers[-500:]

    def _closed_bar(self) -> Optional[Dict[str, Any]]:
        """Newest CLOSED Chandelier row (the forming candle is excluded)."""
        if not self.ce_rows:
            return None
        return self.ce_rows[-2] if len(self.ce_rows) >= 2 else self.ce_rows[-1]

    # ===================================================================== ticks
    def on_tick(self, t: int, price: float) -> bool:
        """Process one live tick.  Returns False if the tick was ignored."""
        if t <= self.last_tick_t:                 # duplicate second / out of order
            return False
        self.ticks.append((t, price))
        if len(self.ticks) > config.MAX_TICKS_IN_MEMORY:
            del self.ticks[: len(self.ticks) - config.MAX_TICKS_IN_MEMORY]
        self.last_tick_t, self.price = t, price

        self._recompute()                         # steps 1-2 of "for every tick"
        self._check_positions(t, price)           # 3
        self._scan_signals(t)                     # 4
        due = self.delay.pop_due(t)               # 5
        if due:
            self._execute_signal(due, t, price)
        return True

    # ================================================================== positions
    def _check_positions(self, t: int, price: float) -> None:
        """For every open position: stop / target hit -> close, otherwise trail the stop."""
        bar = self._closed_bar()
        trail_on = self.settings["trailing_stop"]["enabled"]
        for pos in list(self.broker.open_list()):
            hit = None
            if pos.side == "BUY":
                if price <= pos.sl:
                    hit = "SL"
                elif pos.tp is not None and price >= pos.tp:
                    hit = "TP"
            else:
                if price >= pos.sl:
                    hit = "SL"
                elif pos.tp is not None and price <= pos.tp:
                    hit = "TP"
            if hit:
                self._close(pos, price, t, hit)
                continue
            if trail_on:
                new_sl = trailing_stop.trail_stop(pos.side, pos.sl, bar, price)
                if new_sl != pos.sl:
                    pos.sl = new_sl
                    pos.trail_moves += 1

    def _open(self, side: str, volume: float, source: str):
        """Open a position at the last tick price with chandelier stop + take profit."""
        price, t = self.price, self.last_tick_t
        bar = self._closed_bar()
        atr_mult = self.settings["chandelier_exit"]["atr_mult"]
        fallback_atr = bar["atr"] if bar else price * 0.001
        sl = trailing_stop.initial_stop(side, price, bar, atr_mult, fallback_atr)
        tr = self.settings["trailing_stop"]
        tp = trailing_stop.take_profit(side, price, sl, tr["tp_rr"]) if tr["tp_enabled"] else None
        bar_time = (t // self.tf) * self.tf
        pos = self.broker.open_position(self.symbol, side, volume, price, t, bar_time, sl, tp, source)
        tp_txt = f"{tp:.4f}" if tp is not None else "-"
        self._event(t, "OPEN", f"#{pos.id} {source} {side} {volume:g} @ {price:.4f}  SL {sl:.4f}  TP {tp_txt}")
        return pos

    def _close(self, pos, price: float, t: int, reason: str) -> Dict[str, Any]:
        trade = self.broker.close_position(pos.id, price, t, reason)
        self._trades_dirty = True
        self._event(t, "CLOSE", f"#{pos.id} {pos.side} closed by {reason} @ {price:.4f}  "
                                f"net {trade['net_pnl']:+.4f}")
        return trade

    # ================================================================== signals
    def _scan_signals(self, t: int) -> None:
        """
        Find Chandelier signals on candles that CLOSED since the last tick and
        hand them to the delay controller (delay 0 = executed right away).
        """
        rows = self.ce_rows
        new_rows = []
        i = len(rows) - 2                          # rows[-1] is the forming candle
        while i >= 0 and rows[i]["time"] > self.last_signal_bar:
            new_rows.append(rows[i])
            i -= 1
        for r in reversed(new_rows):               # oldest first
            self.last_signal_bar = r["time"]
            if not self.settings["chandelier_exit"]["enabled"]:
                continue
            side = "BUY" if r["buy_signal"] else "SELL" if r["sell_signal"] else None
            if side:
                self.delay.submit(side, r["time"], t, self.settings["signal_delay"])
                d = self.delay.pending["delay"]
                wait = f", executes in {d}s" if d else ""
                self._event(t, "SIGNAL", f"Chandelier {side} signal (candle {ts_str(r['time'])}){wait}")

    def _execute_signal(self, sig: Dict[str, Any], t: int, price: float) -> None:
        """Turn a (possibly delayed) signal into broker orders."""
        side = sig["side"]
        auto = self.settings["auto_trade"]
        if not auto["enabled"]:
            self._event(t, "SIGNAL", f"{side} signal not traded (auto trading is off)")
            return
        if auto["reverse"]:
            for pos in list(self.broker.open_list()):
                if pos.source == "AUTO" and pos.side != side:
                    self._close(pos, price, t, "SIGNAL")
        if any(p.source == "AUTO" and p.side == side for p in self.broker.open_list()):
            self._event(t, "SIGNAL", f"{side} signal skipped (automatic {side} position already open)")
            return
        self._open(side, auto["volume"], "AUTO")

    # ============================================================ manual orders
    def manual_order(self, side: str, volume: float):
        """Manual BUY / SELL at the last tick price.  Gets the same SL / TP / trailing as auto trades."""
        if side not in ("BUY", "SELL"):
            raise EngineError("side must be BUY or SELL")
        if volume <= 0:
            raise EngineError("volume must be positive")
        if self.price is None or not self.ce_rows:
            raise EngineError("No price data yet")
        return self._open(side, volume, "MANUAL")

    def close_position(self, pos_id: int) -> Dict[str, Any]:
        pos = self.broker.positions.get(pos_id)
        if pos is None:
            raise EngineError(f"position {pos_id} is not open")
        return self._close(pos, self.price, self.last_tick_t, "MANUAL")

    def close_all(self) -> int:
        positions = self.broker.open_list()
        for pos in positions:
            self._close(pos, self.price, self.last_tick_t, "MANUAL")
        return len(positions)

    # =================================================================== output
    def _bar_json(self, i: int) -> Dict[str, Any]:
        c, h = self.candles[i], self.ha[i]
        return {
            "time": c["time"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"],
            "ha_open": h["ha_open"], "ha_high": h["ha_high"], "ha_low": h["ha_low"], "ha_close": h["ha_close"],
        }

    @staticmethod
    def _point(line: Dict[str, Any], i: int, time: int) -> Dict[str, Any]:
        v = line["values"][i]
        return {"time": time} if v is None else {"time": time, "value": v}

    def snapshot(self) -> Dict[str, Any]:
        """Everything a browser needs to draw the whole screen."""
        n = len(self.candles)
        start = max(0, n - MAX_BARS_SENT)
        lines = []
        for ln in self.lines:
            data = [self._point(ln, i, self.candles[i]["time"]) for i in range(start, n)]
            lines.append({"id": ln["id"], "title": ln["title"], "color": ln["color"],
                          "width": ln.get("width", 1), "data": data})
        return {
            "type": "snapshot", "symbol": self.symbol, "timeframe": self.tf,
            "settings": self.settings,
            "bars": [self._bar_json(i) for i in range(start, n)],
            "lines": lines, "markers": self.markers,
            "price": self.price, "time": self.last_tick_t,
            "account": self.broker.summary(self.price),
            "positions": self.broker.positions_view(self.price),
            "trades": self.broker.trades,
            "events": list(self.events),
            "pending": self.delay.status(self.last_tick_t),
        }

    def tick_message(self) -> Optional[Dict[str, Any]]:
        """Small update sent after every tick (and after every manual action)."""
        n = len(self.candles)
        if n == 0:
            return None
        msg: Dict[str, Any] = {
            "type": "tick", "price": self.price, "time": self.last_tick_t,
            "bar": self._bar_json(n - 1),
            "lines": [{"id": ln["id"], "point": self._point(ln, n - 1, self.candles[n - 1]["time"])}
                      for ln in self.lines],
            "markers": self.markers,
            "account": self.broker.summary(self.price),
            "positions": self.broker.positions_view(self.price),
            "pending": self.delay.status(self.last_tick_t),
            "events": self._new_events,
        }
        if self._trades_dirty:
            msg["trades"] = self.broker.trades
            self._trades_dirty = False
        self._new_events = []
        return msg

    def csv_rows(self) -> List[Dict[str, Any]]:
        return self.broker.csv_rows(self.price)
