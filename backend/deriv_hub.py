import asyncio
import itertools
import json
import logging
import os
from typing import Any, Dict, Optional, Set, Tuple

import httpx
import websockets

log = logging.getLogger("deriv")
Key = Tuple[str, int]  # (symbol, granularity_seconds)


class DerivError(Exception):
    pass


def _candle(c: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "time": int(c.get("epoch") or c.get("open_time")),
        "open": float(c["open"]),
        "high": float(c["high"]),
        "low": float(c["low"]),
        "close": float(c["close"]),
    }


class DerivHub:
    """One shared Deriv WebSocket: history requests + live candle fan-out."""

    def __init__(self):
        self.app_id = os.environ.get("DERIV_APP_ID")
        self.token = os.environ.get("DERIV_API_TOKEN")
        self.account_id = os.environ.get("DERIV_ACCOUNT_ID")
        self.base_url = os.environ.get("DERIV_BASE_URL", "https://api.derivws.com")

        self.ws = None
        self._task: Optional[asyncio.Task] = None
        self._connected = asyncio.Event()
        self._ids = itertools.count(100)
        self._pending: Dict[int, asyncio.Future] = {}
        self._subs: Dict[Key, Set[asyncio.Queue]] = {}
        self._sub_ids: Dict[Key, str] = {}
        self._sub_reqs: Dict[int, Key] = {}

    # ---------- lifecycle ----------
    def start(self):
        missing = [n for n, v in [("DERIV_APP_ID", self.app_id),
                                  ("DERIV_API_TOKEN", self.token),
                                  ("DERIV_ACCOUNT_ID", self.account_id)] if not v]
        if missing:
            raise RuntimeError(f"Missing env vars: {', '.join(missing)} (see .env.example)")
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ---------- connection ----------
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

    async def _run(self):
        backoff = 1
        while True:
            pinger = None
            try:
                ws_url = await self._get_ws_url()  # OTP is one-time -> fetch per connect
                async with websockets.connect(
                    ws_url, additional_headers={"Deriv-App-ID": self.app_id}
                ) as ws:
                    self.ws = ws
                    self._connected.set()
                    backoff = 1
                    log.info("Deriv WebSocket connected")
                    pinger = asyncio.create_task(self._ping_loop(ws))
                    asyncio.create_task(self._resubscribe())
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

    async def _ping_loop(self, ws):
        while True:
            await asyncio.sleep(30)
            await ws.send(json.dumps({"ping": 1}))

    async def _resubscribe(self):
        for key in list(self._subs):
            try:
                await self._start_stream(key)
            except Exception as e:
                log.warning("Resubscribe %s failed: %s", key, e)

    # ---------- message routing ----------
    def _dispatch(self, msg: Dict[str, Any]):
        rid = msg.get("req_id")

        if "error" in msg:
            err = msg["error"]
            fut = self._pending.pop(rid, None)
            if fut and not fut.done():
                fut.set_exception(DerivError(f"{err.get('code')}: {err.get('message')}"))
            else:
                log.warning("Deriv error: %s", err)
            return

        if msg.get("msg_type") == "ohlc" or "ohlc" in msg:
            o = msg["ohlc"]
            key = self._sub_reqs.get(rid) or (
                o.get("symbol") or o.get("underlying_symbol"),
                int(o.get("granularity", 0)),
            )
            candle = {
                "time": int(o["open_time"]),
                "open": float(o["open"]),
                "high": float(o["high"]),
                "low": float(o["low"]),
                "close": float(o["close"]),
            }
            for q in self._subs.get(key, ()):
                try:
                    q.put_nowait(candle)
                except asyncio.QueueFull:
                    pass  # slow client, drop tick
            return

        fut = self._pending.pop(rid, None)
        if fut and not fut.done():
            fut.set_result(msg)
        elif msg.get("msg_type") not in ("ping", "pong"):
            log.debug("Unhandled message: %s", msg)

    # ---------- requests ----------
    async def request(self, payload: Dict[str, Any], timeout: float = 15, key: Optional[Key] = None):
        await asyncio.wait_for(self._connected.wait(), timeout)
        rid = next(self._ids)
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        if key:
            self._sub_reqs[rid] = key
        try:
            await self.ws.send(json.dumps({**payload, "req_id": rid}))
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(rid, None)

    async def history(self, symbol: str, granularity: int, count: int = 500):
        msg = await self.request({
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count": count,
            "end": "latest",
            "start": 1,
            "style": "candles",
            "granularity": granularity,
        })
        return [_candle(c) for c in msg.get("candles", [])]

    # ---------- live candle streams ----------
    async def _start_stream(self, key: Key):
        symbol, gran = key
        msg = await self.request({
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count": 1,
            "end": "latest",
            "start": 1,
            "style": "candles",
            "granularity": gran,
            "subscribe": 1,
        }, key=key)
        sid = (msg.get("subscription") or {}).get("id")
        if sid:
            self._sub_ids[key] = sid

    async def subscribe(self, key: Key, q: asyncio.Queue):
        subs = self._subs.setdefault(key, set())
        first = not subs
        subs.add(q)
        if first:
            try:
                await self._start_stream(key)
            except Exception:
                subs.discard(q)
                if not subs:
                    self._subs.pop(key, None)
                raise

    async def unsubscribe(self, key: Key, q: asyncio.Queue):
        subs = self._subs.get(key)
        if not subs:
            return
        subs.discard(q)
        if not subs:
            self._subs.pop(key, None)
            sid = self._sub_ids.pop(key, None)
            if sid and self.ws:
                try:
                    await self.ws.send(json.dumps({"forget": sid}))
                except Exception:
                    pass