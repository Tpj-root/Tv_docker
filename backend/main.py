"""
================================================================================
 main.py  -  HTTP + WebSocket API (FastAPI)
================================================================================
  GET  /api/health              liveness + Deriv connection state
  GET  /api/symbols             symbols for the drop-down
  GET  /api/schema              all control-bar sections + default values
  POST /api/settings            {"patch": {"chandelier_exit": {"atr_mult": 2.5}}}
  POST /api/settings/reset      back to config.py values
  POST /api/market              {"symbol": "R_50", "timeframe": 300}
  POST /api/orders              manual order {"side": "BUY"|"SELL", "volume": 1}
  POST /api/positions/{id}/close
  POST /api/positions/close_all
  GET  /api/trades.csv          download all trades now
  WS   /ws/live                 snapshot / tick / status messages
"""

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import Response
from pydantic import BaseModel

import config
import settings as settings_mod
from deriv_hub import DerivHub
from engine import EngineError
from service import LiveService
from trade_log import rows_to_csv_text

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")

FALLBACK_SYMBOLS = [
    {"symbol": "R_10", "name": "Volatility 10 Index"},
    {"symbol": "R_25", "name": "Volatility 25 Index"},
    {"symbol": "R_50", "name": "Volatility 50 Index"},
    {"symbol": "R_75", "name": "Volatility 75 Index"},
    {"symbol": "R_100", "name": "Volatility 100 Index"},
    {"symbol": "1HZ100V", "name": "Volatility 100 (1s) Index"},
    {"symbol": "stpRNG", "name": "Step Index"},
]
SYMBOL_RE = re.compile(r"^[A-Za-z0-9_]{2,30}$")

hub = DerivHub()
service = LiveService(hub)


@asynccontextmanager
async def lifespan(app):
    hub.start()            # fails fast when .env is missing
    service.start()
    yield
    await service.stop()
    await hub.stop()


app = FastAPI(lifespan=lifespan)


def fail(e: EngineError):
    raise HTTPException(e.status, str(e))


# ----------------------------------------------------------------- read-only
@app.get("/api/health")
def health():
    return {"status": "ok", "deriv_connected": hub.connected, "ready": service.ready, "error": service.error}


@app.get("/api/schema")
def get_schema():
    return {"groups": settings_mod.schema(), "defaults": settings_mod.default_settings()}


@app.get("/api/symbols")
async def symbols():
    try:
        msg = await hub.request({"active_symbols": "brief"}, timeout=5)
        out = []
        for s in msg.get("active_symbols", []):
            sym = s.get("underlying_symbol") or s.get("symbol")
            if sym:
                out.append({"symbol": sym, "name": s.get("display_name") or s.get("underlying_symbol_name") or sym})
        if out:
            return sorted(out, key=lambda x: x["name"])
    except Exception as e:
        log.warning("active_symbols failed, using fallback list: %s", e)
    return FALLBACK_SYMBOLS


@app.get("/api/trades.csv")
def trades_csv():
    return Response(rows_to_csv_text(service.engine.csv_rows()), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=trades.csv"})


# ------------------------------------------------------------------- settings
class SettingsPatch(BaseModel):
    patch: Dict[str, Dict[str, Any]]


@app.post("/api/settings")
def post_settings(body: SettingsPatch):
    try:
        service.engine.update_settings(body.patch)
    except EngineError as e:
        fail(e)
    service.broadcast(service.snapshot())
    return service.engine.settings


@app.post("/api/settings/reset")
def reset_settings():
    service.engine.reset_settings()
    service.broadcast(service.snapshot())
    return service.engine.settings


class MarketReq(BaseModel):
    symbol: str
    timeframe: int


@app.post("/api/market")
async def post_market(body: MarketReq):
    if not SYMBOL_RE.match(body.symbol):
        raise HTTPException(400, "invalid symbol")
    try:
        await service.switch_market(body.symbol, body.timeframe)
    except EngineError as e:
        fail(e)
    except asyncio.TimeoutError:
        raise HTTPException(504, "Deriv did not answer in time")
    except Exception as e:
        raise HTTPException(502, str(e))
    return {"symbol": service.engine.symbol, "timeframe": service.engine.tf}


# --------------------------------------------------------------------- orders
class OrderReq(BaseModel):
    side: str
    volume: Optional[float] = None


@app.post("/api/orders")
def post_order(body: OrderReq):
    volume = body.volume if body.volume is not None else service.engine.settings["manual"]["volume"]
    try:
        pos = service.engine.manual_order(body.side.upper(), volume)
    except EngineError as e:
        fail(e)
    service.push()
    return {"id": pos.id}


@app.post("/api/positions/close_all")
def close_all():
    n = service.engine.close_all()
    service.push()
    return {"closed": n}


@app.post("/api/positions/{pos_id}/close")
def close_one(pos_id: int):
    try:
        service.engine.close_position(pos_id)
    except EngineError as e:
        fail(e)
    service.push()
    return {"closed": pos_id}


# ------------------------------------------------------------------ websocket
@app.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    await ws.accept()
    client = service.add_client()
    try:
        while not client.dead:
            msg = await client.q.get()
            await ws.send_json(msg)
    except Exception:
        pass                      # browser closed the tab
    finally:
        service.remove_client(client)
        try:
            await ws.close()
        except Exception:
            pass
