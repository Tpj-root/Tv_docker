import asyncio, random, time
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

TF = 60  # 1-minute candles


def make_candles(n=300):
    now = int(time.time()) // TF * TF
    price, out = 100.0, []
    for i in range(n, 0, -1):
        o = price
        c = o + random.gauss(0, 0.4)
        h = max(o, c) + abs(random.gauss(0, 0.2))
        l = min(o, c) - abs(random.gauss(0, 0.2))
        out.append({"time": now - i * TF, "open": round(o, 2), "high": round(h, 2),
                    "low": round(l, 2), "close": round(c, 2)})
        price = c
    return out


candles = make_candles()


async def ticker():
    """Simulates live price ticks every second."""
    while True:
        await asyncio.sleep(1)
        last = candles[-1]
        t = int(time.time()) // TF * TF
        price = last["close"] + random.gauss(0, 0.15)
        if t > last["time"]:  # new minute -> new candle
            candles.append({"time": t, "open": last["close"], "high": price,
                            "low": price, "close": round(price, 2)})
        else:
            last["close"] = round(price, 2)
            last["high"] = max(last["high"], price)
            last["low"] = min(last["low"], price)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(ticker())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/candles")
def get_candles():
    return candles


@app.websocket("/ws/ticks")
async def ws_ticks(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            await ws.send_json(candles[-1])
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass