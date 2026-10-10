"""
================================================================================
 service.py  -  glue between Deriv (async), the Engine and the browsers
================================================================================
LiveService owns:
    * the Engine                 (all trading logic, synchronous)
    * the connected browsers     (each has a small queue of JSON messages)
    * the live tick pump         Deriv tick -> engine.on_tick -> broadcast
    * the CSV logger task        every minute (trade_log.py)

Message types sent to browsers over /ws/live:
    snapshot  full screen state (on connect, settings change, market change)
    tick      small update after every tick / manual action
    status    connection health every 3 seconds
"""

import asyncio
import logging
import time
from typing import Any, Dict, Optional, Set

import config
from deriv_hub import DerivHub
from engine import Engine, EngineError
from trade_log import TradeCsvLogger

log = logging.getLogger("service")


class Client:
    """One connected browser tab."""

    def __init__(self) -> None:
        self.q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self.dead = False


class LiveService:
    def __init__(self, hub: DerivHub) -> None:
        self.hub = hub
        self.engine = Engine()
        self.clients: Set[Client] = set()
        self.csv = TradeCsvLogger(config.CSV_DIR, self.engine.csv_rows)
        self.ready = False
        self.error: Optional[str] = None
        self._lock = asyncio.Lock()                      # one market switch at a time
        self._cur: Optional[tuple] = None                # (symbol, tick queue) currently streaming
        self._pump_task: Optional[asyncio.Task] = None
        self._tasks = []

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self.hub.on_reconnect = self._resync
        self._tasks = [
            asyncio.create_task(self._boot()),
            asyncio.create_task(self.csv.run()),
            asyncio.create_task(self._status_loop()),
        ]

    async def stop(self) -> None:
        for t in self._tasks + ([self._pump_task] if self._pump_task else []):
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass

    async def _boot(self) -> None:
        """Load history for the symbol / timeframe from config.py; retry until Deriv answers."""
        while True:
            try:
                async with self._lock:
                    await self._activate(self.engine.symbol, self.engine.tf)
                self.ready, self.error = True, None
                self.broadcast(self.snapshot())
                log.info("Live market ready: %s / %ss", self.engine.symbol, self.engine.tf)
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"
                log.warning("Boot failed (%s) - retry in 5 s", self.error)
                await asyncio.sleep(5)

    # ------------------------------------------------------------ market
    async def _activate(self, symbol: str, tf: int) -> None:
        """
        Start streaming `symbol`: subscribe FIRST (so no tick is missed), then
        download history, then switch the engine.  Any failure leaves the
        previous market untouched.
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        await self.hub.subscribe_ticks(symbol, q)
        try:
            ticks = await self.hub.ticks_history(symbol, config.HISTORY_TICKS)
            if not ticks:
                raise EngineError(f"No tick history for '{symbol}'")
            self.engine.set_market(symbol, tf)            # raises if positions are open
        except BaseException:
            await self.hub.unsubscribe_ticks(symbol, q)
            raise
        self.engine.load_history(ticks)
        await self._stop_stream()                          # old stream (cancel is synchronous)
        self._cur = (symbol, q)
        self._pump_task = asyncio.create_task(self._pump(q))

    async def _stop_stream(self) -> None:
        if self._pump_task:
            self._pump_task.cancel()
            self._pump_task = None
        if self._cur:
            symbol, q = self._cur
            self._cur = None
            await self.hub.unsubscribe_ticks(symbol, q)

    async def switch_market(self, symbol: str, tf: int) -> None:
        async with self._lock:
            eng = self.engine
            if self.engine.broker.positions:
                raise EngineError("Close all open positions before changing symbol or timeframe", 409)
            if symbol == eng.symbol and self.ready:
                eng.set_market(symbol, tf)                 # only the timeframe changes
            else:
                await self._activate(symbol, tf)
            self.ready, self.error = True, None
        self.broadcast(self.snapshot())

    async def _pump(self, q: asyncio.Queue) -> None:
        """Deriv tick -> engine -> every browser."""
        while True:
            t, price = await q.get()
            try:
                if self.engine.on_tick(t, price):
                    self.broadcast(self.engine.tick_message())
            except Exception:
                log.exception("tick processing failed")

    async def _resync(self) -> None:
        """After a Deriv reconnect: replay the ticks missed while offline."""
        if not self.ready or not self._cur:
            return
        try:
            ticks = await self.hub.ticks_history(self._cur[0], 1000)
            for t, p in ticks:
                if t > self.engine.last_tick_t:
                    self.engine.on_tick(t, p)
            self.broadcast(self.snapshot())
        except Exception as e:
            log.warning("resync failed: %s", e)

    # ------------------------------------------------------------ browsers
    def status(self) -> Dict[str, Any]:
        eng = self.engine
        return {
            "type": "status", "deriv_connected": self.hub.connected, "ready": self.ready,
            "error": self.error,
            "tick_age": round(time.time() - eng.last_tick_t, 1) if eng.last_tick_t else None,
            "csv_file": self.csv.path,
        }

    def snapshot(self) -> Dict[str, Any]:
        snap = self.engine.snapshot()
        snap["status"] = self.status()
        return snap

    def broadcast(self, msg: Optional[Dict[str, Any]]) -> None:
        if msg is None:
            return
        for c in list(self.clients):
            try:
                c.q.put_nowait(msg)
            except asyncio.QueueFull:
                c.dead = True                             # too slow: handler will close it

    def push(self) -> None:
        """Send the current positions / account to everybody (after a manual action)."""
        self.broadcast(self.engine.tick_message())

    def add_client(self) -> Client:
        c = Client()
        c.q.put_nowait(self.snapshot())                   # first message = full snapshot
        self.clients.add(c)                               # (no await in between -> nothing missed)
        return c

    def remove_client(self, c: Client) -> None:
        self.clients.discard(c)

    async def _status_loop(self) -> None:
        while True:
            await asyncio.sleep(3)
            self.broadcast(self.status())
