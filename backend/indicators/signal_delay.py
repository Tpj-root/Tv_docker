"""
================================================================================
 indicators/signal_delay.py  -  TIMING CONTROL INDICATOR
================================================================================
Sits between the Chandelier Exit signal and the broker:

    Chandelier signal  ->  [ signal delay ]  ->  broker buy / sell

    * Delay OFF : the order is sent the moment the signal is confirmed.
    * Delay ON  : the order waits `buy_delay_s` (BUY) or `sell_delay_s` (SELL)
                  seconds.  Only after the wait is over the order is executed,
                  at the price of that moment.

Rule for overlapping signals: there is ONE waiting slot.  If a new signal
arrives while another one is still waiting, the newer signal replaces it
(a buy that is still waiting is cancelled by a later sell, and vice versa).

DelayController has no network or broker code, so it is easy to unit-test.
"""

from typing import Any, Dict, Optional

from .base import BaseIndicator, Param
import config


class DelayController:
    """Holds at most one waiting (pending) signal."""

    def __init__(self) -> None:
        self.pending: Optional[Dict[str, Any]] = None

    def submit(self, side: str, signal_time: int, now: float, p: Dict[str, Any]) -> None:
        """
        Register a new signal.
        side         "BUY" or "SELL"
        signal_time  candle time that produced the signal (shown in the log)
        now          current time in seconds (time.time())
        p            this indicator's settings (enabled, buy_delay_s, sell_delay_s)
        """
        delay = 0
        if p.get("enabled"):
            delay = p["buy_delay_s"] if side == "BUY" else p["sell_delay_s"]
        self.pending = {
            "side": side,
            "signal_time": signal_time,
            "created_at": now,
            "due_at": now + delay,
            "delay": delay,
        }

    def pop_due(self, now: float) -> Optional[Dict[str, Any]]:
        """Return the pending signal once its waiting time is over (and forget it)."""
        if self.pending and now >= self.pending["due_at"]:
            done, self.pending = self.pending, None
            return done
        return None

    def clear(self) -> None:
        self.pending = None

    def status(self, now: float) -> Optional[Dict[str, Any]]:
        """Small JSON for the UI: what is waiting and for how many more seconds."""
        if not self.pending:
            return None
        return {
            "side": self.pending["side"],
            "remaining": max(0.0, round(self.pending["due_at"] - now, 1)),
            "delay": self.pending["delay"],
        }


class SignalDelay(BaseIndicator):
    id = "signal_delay"
    title = "Signal delay (timing)"
    role = "control"
    description = "Wait N seconds after a Chandelier signal before the buy / sell is executed."
    enabled_default = config.DELAY_ENABLED
    params = (
        Param("buy_delay_s", "Buy delay (seconds)", "int", config.BUY_DELAY_SECONDS, 0, 3600, 1),
        Param("sell_delay_s", "Sell delay (seconds)", "int", config.SELL_DELAY_SECONDS, 0, 3600, 1),
    )
    # No compute(): this indicator draws nothing, the engine uses DelayController.


INDICATOR = SignalDelay()
