import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, WebSocket

from deriv_hub import DerivError, DerivHub

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")

GRANULARITIES = {60, 120, 180, 300, 600, 900, 1800, 3600, 7200, 14400, 28800, 86400}

FALLBACK_SYMBOLS = [
    {"symbol": "R_10", "name": "Volatility 10 Index"},
    {"symbol": "R_25", "name": "Volatility 25 Index"},
    {"symbol": "R_50", "name": "Volatility 50 Index"},
    {"symbol": "R_75", "name": "Volatility 75 Index"},
    {"symbol": "R_100", "name": "Volatility 100 Index"},
    {"symbol": "1HZ100V", "name": "Volatility 100 (1s) Index"},
    {"symbol": "stpRNG", "name": "Step Index"},
]

hub = DerivHub()


@asynccontextmanager
async def lifespan(app):
    hub.start()  # fails fast if .env is missing
    yield
    await hub.stop()


app = FastAPI(lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"status": "ok", "deriv_connected": hub._connected.is_set()}


@app.get("/api/symbols")
async def symbols():
    try:
        msg = await hub.request({"active_symbols": "brief"})
        out = []
        for s in msg.get("active_symbols", []):
            sym = s.get("underlying_symbol") or s.get("symbol")
            if sym:
                out.append({
                    "symbol": sym,
                    "name": s.get("display_name") or s.get("underlying_symbol_name") or sym,
                })
        if out:
            return sorted(out, key=lambda x: x["name"])
    except Exception as e:
        log.warning("active_symbols failed, using fallback: %s", e)
    return FALLBACK_SYMBOLS


@app.get("/api/candles")
async def candles(symbol: str = "R_100", granularity: int = 60,
                  count: int = Query(500, ge=1, le=5000)):
    if granularity not in GRANULARITIES:
        raise HTTPException(400, f"granularity must be one of {sorted(GRANULARITIES)}")
    try:
        return await hub.history(symbol, granularity, count)
    except DerivError as e:
        raise HTTPException(502, str(e))
    except asyncio.TimeoutError:
        raise HTTPException(504, "Deriv did not respond in time")


@app.websocket("/ws/candles")
async def ws_candles(ws: WebSocket, symbol: str = "R_100", granularity: int = 60):
    await ws.accept()
    if granularity not in GRANULARITIES:
        await ws.close(code=1008)
        return
    key = (symbol, granularity)
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    try:
        await hub.subscribe(key, q)
    except Exception as e:
        await ws.send_json({"error": str(e)})
        await ws.close(code=1011)
        return
    try:
        while True:
            await ws.send_json(await q.get())
    except Exception:
        pass  # client went away
    finally:
        await hub.unsubscribe(key, q)