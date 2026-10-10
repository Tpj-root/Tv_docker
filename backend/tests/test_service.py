"""
tests/test_service.py - runs the async LiveService against a FAKE Deriv hub.
Run:  cd backend && python3 -m tests.test_service
(httpx / websockets are stubbed so this also works without those packages.)
"""
import asyncio, os, sys, types, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for name in ("httpx", "websockets"):
    if name not in sys.modules:
        try:
            __import__(name)
        except ImportError:
            sys.modules[name] = types.ModuleType(name)

import config
config.CSV_DIR = tempfile.mkdtemp()
from service import LiveService
from engine import EngineError
from tests.test_engine import synthetic_ticks


class FakeHub:
    connected = True
    on_reconnect = None
    def __init__(self):
        self.queues = {}
        self.data = {"R_100": synthetic_ticks(3000, seed=1), "R_50": synthetic_ticks(3000, seed=2)}
    async def subscribe_ticks(self, s, q): self.queues.setdefault(s, set()).add(q)
    async def unsubscribe_ticks(self, s, q): self.queues.get(s, set()).discard(q)
    async def ticks_history(self, s, n):
        if s not in self.data: return []
        return self.data[s][:2400]
    def feed(self, s, ticks):
        for t in ticks:
            for q in self.queues.get(s, ()): q.put_nowait(t)


async def drain(client, timeout=0.3):
    out = []
    try:
        while True:
            out.append(await asyncio.wait_for(client.q.get(), timeout))
    except asyncio.TimeoutError:
        return out


async def main():
    hub = FakeHub()
    svc = LiveService(hub)
    svc.start()
    await asyncio.sleep(0.2)
    assert svc.ready, svc.error
    c = svc.add_client()
    first = await c.q.get()
    assert first["type"] == "snapshot" and first["symbol"] == "R_100" and first["status"]["ready"]

    hub.feed("R_100", synthetic_ticks(3000, seed=1)[2400:2800])
    msgs = await drain(c)
    ticks = [m for m in msgs if m["type"] == "tick"]
    assert len(ticks) == 400, len(ticks)
    print(f"OK  boot + live ticks -> {len(ticks)} tick messages")

    r = svc.engine.manual_order("BUY", 1); svc.push()
    m = [m for m in await drain(c) if m["type"] == "tick"][-1]
    assert any(p["id"] == r.id for p in m["positions"])
    try:
        await svc.switch_market("R_50", 60); raise SystemExit("switch should be blocked")
    except EngineError as e:
        assert e.status == 409
    svc.engine.close_all(); svc.push()
    await drain(c)
    await svc.switch_market("R_50", 300)
    snap = [m for m in await drain(c) if m["type"] == "snapshot"][-1]
    assert snap["symbol"] == "R_50" and snap["timeframe"] == 300
    await svc.switch_market("R_50", 60)       # timeframe only
    assert svc.engine.tf == 60 and len(svc.engine.ticks) > 2000
    try:
        await svc.switch_market("NOPE", 60); raise SystemExit("unknown symbol accepted")
    except EngineError:
        pass
    assert svc.engine.symbol == "R_50" and not hub.queues.get("NOPE")
    print("OK  manual order broadcast, market switch blocked/allowed, failed switch leaves market untouched")

    hub.feed("R_50", synthetic_ticks(3000, seed=2)[2400:2500])
    assert len([m for m in await drain(c) if m["type"] == "tick"]) == 100
    path = svc.csv.write_now()
    assert os.path.exists(path)
    await svc.stop()
    print("OK  service stop, CSV:", os.path.basename(path))

asyncio.run(main())
print("SERVICE TESTS PASSED")
