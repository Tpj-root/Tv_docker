"""
================================================================================
 deriv_hub.py  -  ONE shared connection to the Deriv WebSocket API
================================================================================
Uses the same login flow as your deriv_ws_client.py:

   1. POST {base_url}/trading/v1/options/accounts/{account_id}/otp
        headers: Deriv-App-ID, Authorization: Bearer <token>
      -> answer contains a ONE-TIME wss:// url
   2. connect to that url (header Deriv-App-ID)
   3. send JSON requests, receive JSON answers

The hub is async (asyncio) so it fits FastAPI.  What it offers:

   ticks_history(symbol, count)      past ticks as [(epoch, price), ...]
   subscribe_ticks(symbol, queue)    live ticks are put into `queue` as (epoch, price)
   unsubscribe_ticks(symbol, queue)
   request({...})                    any raw request, returns the answer
   active_symbols()                  via request()

Robustness: automatic reconnect with back-off (a new OTP every time because an
OTP can be used only once), keep-alive {"ping":1} every 30 s, and live
subscriptions are re-created after a reconnect.
"""

import asyncio
import itertools
import json
import logging
import os
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
import websockets

log = logging.getLogger("deriv")


class DerivError(Exception):
    pass


class DerivHub:
    def __init__(self) -> None:
        self.app_id = os.environ.get("DERIV_APP_ID")
        self.token = os.environ.get("DERIV_API_TOKEN")
        self.account_id = os.environ.get("DERIV_ACCOUNT_ID")
        self.base_url = os.environ.get("DERIV_BASE_URL", "https://api.derivws.com")

        self.ws = None
        self._task: Optional[asyncio.Task] = None
        self._connected = asyncio.Event()
        self._ids = itertools.count(100)                      # req_id counter
        self._pending: Dict[int, asyncio.Future] = {}         # req_id -> waiting answer
        self._subs: Dict[str, Set[asyncio.Queue]] = {}        # symbol -> tick queues
        self._sub_ids: Dict[str, str] = {}                    # symbol -> Deriv subscription id
        self._sub_reqs: Dict[int, str] = {}                   # req_id of a subscribe -> symbol
        self.on_reconnect = None                              # optional async callback

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        missing = [n for n, v in [("DERIV_APP_ID", self.app_id), ("DERIV_API_TOKEN", self.token),
                                  ("DERIV_ACCOUNT_ID", self.account_id)] if not v]
        if missing:
            raise RuntimeError(f"Missing env vars: {', '.join(missing)} (see .env.example)")
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------ connection
    async def _get_ws_url(self) -> str:
        url = f"{self.base_url}/trading/v1/options/accounts/{self.account_id}/otp"
        headers = {"Deriv-App-ID": self.app_id, "Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, headers=headers)
        try:
            data = r.json()
        except ValueError:
            raise DerivError(f"OTP: invalid JSON (HTTP {r.status_code})")
        if r.status_code != 200:
            raise DerivError(f"OTP failed (HTTP {r.status_code}): {data}")
        ws_url = (data.get("data") or {}).get("url")
        if not ws_url:
            raise DerivError(f"OTP: no url in response: {data}")
        return ws_url

    async def _run(self) -> None:
        backoff = 1
        while True:
            pinger = None
            try:
                ws_url = await self._get_ws_url()
                async with websockets.connect(ws_url, additional_headers={"Deriv-App-ID": self.app_id}) as ws:
                    self.ws = ws
                    self._connected.set()
                    backoff = 1
                    log.info("Deriv WebSocket connected")
                    pinger = asyncio.create_task(self._ping_loop(ws))
                    asyncio.create_task(self._after_connect())
                    async for raw in ws:
                        self._dispatch(json.loads(raw))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("Deriv connection problem: %s", e)
            finally:
                if pinger:
                    pinger.cancel()
                self._connected.clear()
                self.ws = None
                self._sub_ids.clear()
                self._sub_reqs.clear()
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(DerivError("Deriv connection lost"))
                self._pending.clear()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    async def _ping_loop(self, ws) -> None:
        while True:
            await asyncio.sleep(30)
            await ws.send(json.dumps({"ping": 1}))

    async def _after_connect(self) -> None:
        """Re-create live subscriptions after a reconnect, then tell the service."""
        for symbol in list(self._subs):
            try:
                await self._start_stream(symbol)
            except Exception as e:
                log.warning("Resubscribe %s failed: %s", symbol, e)
        if self.on_reconnect:
            try:
                await self.on_reconnect()
            except Exception as e:
                log.warning("on_reconnect failed: %s", e)

    # ------------------------------------------------------- message routing
    def _dispatch(self, msg: Dict[str, Any]) -> None:
        rid = msg.get("req_id")

        if "error" in msg:
            err = msg["error"]
            fut = self._pending.pop(rid, None)
            if fut and not fut.done():
                fut.set_exception(DerivError(f"{err.get('code')}: {err.get('message')}"))
            else:
                log.warning("Deriv error: %s", err)
            return

        # live tick: {"msg_type":"tick","tick":{"epoch":..,"quote":..,"symbol":..}}
        if "tick" in msg and isinstance(msg["tick"], dict):
            tk = msg["tick"]
            symbol = self._sub_reqs.get(rid) or tk.get("symbol") or tk.get("underlying_symbol")
            try:
                item = (int(tk["epoch"]), float(tk["quote"]))
            except (KeyError, TypeError, ValueError):
                item = None
            if item:
                for q in self._subs.get(symbol, ()):
                    try:
                        q.put_nowait(item)
                    except asyncio.QueueFull:
                        pass
            # fall through: the FIRST tick also answers the subscribe request

        fut = self._pending.pop(rid, None)
        if fut and not fut.done():
            fut.set_result(msg)
        elif msg.get("msg_type") not in ("tick", "ping", "pong"):
            log.debug("Unhandled message: %s", msg)

    # --------------------------------------------------------------- requests
    async def request(self, payload: Dict[str, Any], timeout: float = 15, symbol: Optional[str] = None):
        """Send one request and wait for its answer (matched by req_id)."""
        await asyncio.wait_for(self._connected.wait(), timeout)
        rid = next(self._ids)
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        if symbol:
            self._sub_reqs[rid] = symbol
        try:
            await self.ws.send(json.dumps({**payload, "req_id": rid}))
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(rid, None)

    async def ticks_history(self, symbol: str, count: int) -> List[Tuple[int, float]]:
        """
        Last `count` ticks, oldest first.  Deriv returns at most 5000 per request,
        so bigger numbers are fetched in several requests walking backwards in time.
        """
        out: List[Tuple[int, float]] = []
        end: Any = "latest"
        remaining = count
        while remaining > 0:
            chunk = min(5000, remaining)
            msg = await self.request({
                "ticks_history": symbol, "adjust_start_time": 1, "count": chunk,
                "end": end, "start": 1, "style": "ticks",
            })
            hist = msg.get("history") or {}
            times, prices = hist.get("times") or [], hist.get("prices") or []
            rows = [(int(t), float(p)) for t, p in zip(times, prices)]
            if not rows:
                break
            out = rows + out
            remaining -= len(rows)
            if len(rows) < chunk:
                break
            end = rows[0][0] - 1
        return out

    # ------------------------------------------------------------ live ticks
    async def _start_stream(self, symbol: str) -> None:
        msg = await self.request({"ticks": symbol, "subscribe": 1}, symbol=symbol)
        sid = (msg.get("subscription") or {}).get("id")
        if sid:
            self._sub_ids[symbol] = sid

    async def subscribe_ticks(self, symbol: str, q: asyncio.Queue) -> None:
        subs = self._subs.setdefault(symbol, set())
        first = not subs
        subs.add(q)
        if first:
            try:
                await self._start_stream(symbol)
            except Exception:
                subs.discard(q)
                if not subs:
                    self._subs.pop(symbol, None)
                raise

    async def unsubscribe_ticks(self, symbol: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(symbol)
        if not subs:
            return
        subs.discard(q)
        if not subs:
            self._subs.pop(symbol, None)
            sid = self._sub_ids.pop(symbol, None)
            if sid and self.ws:
                try:
                    await self.ws.send(json.dumps({"forget": sid}))
                except Exception:
                    pass
