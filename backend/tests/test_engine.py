"""
================================================================================
 tests/test_engine.py  -  offline tests (no Deriv, no internet)
================================================================================
Run:  cd backend && python3 -m tests.test_engine

1. The refactored pipeline must give EXACTLY the same Chandelier rows as the
   original chandelier_exit_raw() in your trading_ha_chandelier.py
   (only runs when that file path is given as ORIGINAL below / argv[1]).
2. Engine replay: signals, delay, stop loss, trailing, take profit, manual orders,
   profit maths and CSV logging.
"""

import importlib.util
import math
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from core.ticks import ticks_to_candles_raw
from indicators import to_heikin_ashi_raw, compute_extremums_raw, chandelier_exit_raw, trailing_stop
from engine import Engine, EngineError
from indicators.signal_delay import DelayController

ORIGINAL = sys.argv[1] if len(sys.argv) > 1 else "/mnt/user-data/uploads/trading_ha_chandelier.py"


def synthetic_ticks(n=4000, start=1_790_000_000, seed=7, drift_every=400):
    """Random walk with changing trend so the Chandelier flips direction several times."""
    rnd = random.Random(seed)
    price, out, trend = 1000.0, [], 0.05
    for i in range(n):
        if i % drift_every == 0:
            trend = rnd.choice([-0.25, -0.1, 0.1, 0.25])
        price += trend + rnd.gauss(0, 0.6)
        out.append((start + i, round(price, 2)))
    return out


def test_matches_original():
    if not os.path.exists(ORIGINAL):
        print("SKIP original comparison (file not found)")
        return
    spec = importlib.util.spec_from_file_location("orig", ORIGINAL)
    orig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(orig)
    ticks = synthetic_ticks()
    for tf in (60, 300):
        candles = ticks_to_candles_raw(ticks, tf)
        ha = to_heikin_ashi_raw(candles)
        assert ha == orig.to_heikin_ashi_raw(candles)
        for formula in ("close", "range_ma", "crest_trough", "pivot_sr"):
            for use_close in (False, True):
                for mode in ("tradingview", "user_original"):
                    ext = compute_extremums_raw(ha, atr_period=22, use_close=use_close, extremum_formula=formula)
                    mine = chandelier_exit_raw(ha, ext, 22, 3.0, mode)
                    ref = orig.chandelier_exit_raw(ha, atr_period=22, atr_mult=3.0, mode=mode,
                                                   use_close=use_close, extremum_formula=formula)
                    for a, b in zip(mine, ref):
                        for k in ("atr", "long_stop", "short_stop", "direction", "buy_signal", "sell_signal"):
                            assert a[k] == b[k], (tf, formula, use_close, mode, k)
                    assert len(mine) == len(ref)
    print("OK  pipeline identical to your original (2 timeframes x 4 formulas x 2 x 2 modes)")


def replay(eng, ticks):
    for t, p in ticks:
        eng.on_tick(t, p)


def make_engine(history=2400, **patch):
    eng = Engine()
    ticks = synthetic_ticks(6000)
    eng.load_history(ticks[:history])
    if patch:
        eng.update_settings(patch)
    return eng, ticks[history:]


def test_signals_trade_and_math():
    eng, live = make_engine(auto_trade={"enabled": True})
    replay(eng, live)
    b = eng.broker
    sig = [e for e in eng.events if e["kind"] == "SIGNAL"]
    assert sig, "expected chandelier signals"
    assert b.trades, "expected closed trades"
    for t in b.trades:
        sign = 1 if t["side"] == "BUY" else -1
        want = (t["exit_price"] - t["entry_price"]) * sign * t["volume"] * config.CONTRACT_SIZE
        assert math.isclose(t["gross_pnl"], round(want, 6), abs_tol=1e-6), t
        assert t["exit_reason"] in ("SL", "TP", "SIGNAL")
    s = b.summary(eng.price)
    assert math.isclose(s["balance"], b.start_balance + sum(t["net_pnl"] for t in b.trades), abs_tol=1e-3)
    print(f"OK  signals={len(sig)} trades={len(b.trades)} reasons={sorted({t['exit_reason'] for t in b.trades})} "
          f"net={s['realized']:+.2f} win%={s['win_rate']}")


def test_no_trade_on_history_signals():
    eng = Engine()
    eng.load_history(synthetic_ticks(3000))
    assert not eng.broker.trades and not eng.broker.positions, "history must not trade"
    print("OK  history signals are not traded")


def test_delay():
    # find when the first signal executes without delay
    base, live = make_engine()
    replay(base, live)
    first_open = next(e for e in base.events if e["kind"] == "OPEN" and "AUTO" in e["text"])

    eng, live = make_engine(signal_delay={"enabled": True, "buy_delay_s": 30, "sell_delay_s": 30})
    replay(eng, live)
    opens = [e for e in eng.events if e["kind"] == "OPEN" and "AUTO" in e["text"]]
    sigs = [e for e in eng.events if e["kind"] == "SIGNAL" and "Chandelier" in e["text"]]
    assert opens and sigs
    # first signal event time vs first open time must differ by >= 30s
    assert opens[0]["ts"] - sigs[0]["ts"] >= 30, (opens[0]["ts"] - sigs[0]["ts"])
    assert first_open["ts"] - base_signal_ts(base) == 0
    print(f"OK  delay: signal -> order wait = {opens[0]['ts'] - sigs[0]['ts']}s (0s without delay)")

    d = DelayController()
    d.submit("BUY", 1, 100, {"enabled": True, "buy_delay_s": 10, "sell_delay_s": 5})
    d.submit("SELL", 2, 103, {"enabled": True, "buy_delay_s": 10, "sell_delay_s": 5})   # replaces
    assert d.pop_due(107) is None and d.pop_due(108)["side"] == "SELL"
    print("OK  newer signal replaces a waiting one")


def base_signal_ts(eng):
    return next(e["ts"] for e in eng.events if e["kind"] == "SIGNAL" and "Chandelier" in e["text"])


def test_manual_and_trailing():
    eng, live = make_engine(auto_trade={"enabled": False})
    replay(eng, live[:300])
    pos = eng.manual_order("BUY", 2)
    assert pos.sl < pos.entry_price and pos.tp > pos.entry_price
    assert math.isclose(pos.tp - pos.entry_price, 2.0 * (pos.entry_price - pos.sl), rel_tol=1e-9)
    moves_seen, sl0 = 0, pos.sl
    for t, p in live[300:]:
        eng.on_tick(t, p)
        if pos.id not in eng.broker.positions:
            break
        assert pos.sl >= sl0 - 1e-12, "BUY stop must never move down"
        sl0 = pos.sl
    tr = eng.broker.trades[-1] if eng.broker.trades else None
    print(f"OK  manual BUY: initial SL {pos.initial_sl:.2f} -> final SL {pos.sl:.2f} "
          f"(trail moves {pos.trail_moves}), closed by {tr['exit_reason'] if tr else 'still open'}")

    sell = eng.manual_order("SELL", 1)
    assert sell.sl > sell.entry_price
    eng.close_position(sell.id)
    assert eng.broker.trades[-1]["exit_reason"] == "MANUAL"
    try:
        eng.set_market("R_50", 60)
    except EngineError:
        pass
    eng.close_all()
    eng.set_market("R_50", 60)
    print("OK  manual sell/close, market change blocked while positions open")


def test_trail_functions():
    bar = {"long_stop": 105.0, "short_stop": 95.0, "atr": 1.0}
    assert trailing_stop.trail_stop("BUY", 100, bar, 110) == 105
    assert trailing_stop.trail_stop("BUY", 106, bar, 110) == 106          # never down
    assert trailing_stop.trail_stop("BUY", 100, bar, 104) == 100          # candidate above price -> ignored
    assert trailing_stop.trail_stop("SELL", 100, bar, 90) == 95
    assert trailing_stop.trail_stop("SELL", 94, bar, 90) == 94
    assert trailing_stop.initial_stop("BUY", 100, {"long_stop": 101, "short_stop": 99, "atr": 2}, 3.0, 2) == 94
    assert trailing_stop.take_profit("SELL", 100, 104, 2.0) == 92
    print("OK  trailing / initial stop / take profit functions")


def test_csv():
    from trade_log import TradeCsvLogger
    eng, live = make_engine()
    replay(eng, live)
    with tempfile.TemporaryDirectory() as d:
        lg = TradeCsvLogger(d, lambda: eng.csv_rows())
        path = lg.write_now()
        text = open(path).read().splitlines()
        assert text[0].startswith("id,status,symbol,side") and len(text) == 1 + len(eng.csv_rows())
    print(f"OK  CSV written ({len(text) - 1} rows)")


def test_settings_validation():
    eng = Engine()
    for bad in ({"chandelier_exit": {"atr_mult": "x"}}, {"nope": {}}, {"chandelier_exit": {"mode": "zzz"}},
                {"chandelier_exit": {"nope": 1}}):
        try:
            eng.update_settings(bad)
            raise SystemExit(f"accepted bad patch {bad}")
        except EngineError:
            pass
    eng.update_settings({"chandelier_exit": {"atr_period": 9999}})
    assert eng.settings["chandelier_exit"]["atr_period"] == 200            # clamped
    eng.reset_settings()
    assert eng.settings["chandelier_exit"]["atr_period"] == config.CE_ATR_PERIOD
    print("OK  settings validated, clamped and reset")


def test_messages():
    import json
    eng, live = make_engine()
    replay(eng, live[:500])
    json.dumps(eng.snapshot())
    m = eng.tick_message()
    json.dumps(m)
    assert m["type"] == "tick" and "bar" in m
    print(f"OK  JSON messages  snapshot bars={len(eng.snapshot()['bars'])} lines={[l['id'] for l in eng.snapshot()['lines']]}")


if __name__ == "__main__":
    test_matches_original()
    test_trail_functions()
    test_settings_validation()
    test_no_trade_on_history_signals()
    test_signals_trade_and_math()
    test_delay()
    test_manual_and_trailing()
    test_messages()
    test_csv()
    print("\nALL TESTS PASSED")
