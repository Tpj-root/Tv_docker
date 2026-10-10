"""
================================================================================
 core/ticks.py  -  PIPELINE STEP 1 and 2
================================================================================
   load_ticks_raw      : tick CSV file  -> sorted list of (epoch_seconds, price)
   ticks_to_candles_raw: ticks          -> list of real OHLC candles

Both functions are kept exactly as in your trading_ha_chandelier.py so the
live app and your back-tests produce identical candles.

A "tick" is a tuple  (time, price)  where time is a UNIX timestamp in SECONDS.
Only the first tick of each second is kept (same rule as your CSV loader).

A "candle" is a dict:
    time      start of the bucket (epoch seconds)   e.g. 1790274600
    time_str  the same time as HH:MM:SS (UTC)
    open/high/low/close   first / max / min / last tick price in the bucket
    ticks     how many ticks fell into the bucket
"""

import csv
import datetime
import os


def load_ticks_raw(csv_path: str):
    """Reads tick CSV (times, prices) into sorted list of (time, price)."""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    ticks = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = [h.strip().lower() for h in next(reader, [])]
        time_idx = 0
        price_idx = 1
        for i, h in enumerate(header):
            if "time" in h or h in ("t", "ts"):
                time_idx = i
            elif "price" in h or h in ("p", "close", "last"):
                price_idx = i

        seen_times = set()
        for row in reader:
            if not row or len(row) <= max(time_idx, price_idx):
                continue
            try:
                t = float(row[time_idx])
                p = float(row[price_idx])
                # Convert milliseconds if needed
                t_sec = int(t // 1000 if t > 1e11 else t)
                if t_sec not in seen_times:
                    seen_times.add(t_sec)
                    ticks.append((t_sec, p))
            except ValueError:
                continue

    ticks.sort(key=lambda x: x[0])
    return ticks


def ticks_to_candles_raw(ticks, seconds: int):
    """Buckets (time, price) tuples into list of OHLC dicts."""
    if not ticks or seconds <= 0:
        return []

    buckets = {}
    for t, p in ticks:
        b = (t // seconds) * seconds
        if b not in buckets:
            buckets[b] = []
        buckets[b].append(p)

    sorted_buckets = sorted(buckets.keys())
    candles = []
    for b in sorted_buckets:
        prices = buckets[b]
        o = prices[0]
        h = max(prices)
        l = min(prices)
        c = prices[-1]
        candles.append({
            "time": b,
            "time_str": datetime.datetime.fromtimestamp(b, tz=datetime.timezone.utc).strftime("%H:%M:%S"),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "ticks": len(prices),
        })
    return candles
