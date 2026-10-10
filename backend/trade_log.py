"""
================================================================================
 trade_log.py  -  AUTOMATIC CSV TRADE LOG (every 1 minute)
================================================================================
Every `config.CSV_INTERVAL_SECONDS` (default 60) ALL trades - closed ones and
currently open positions - are written to:

        data/trades_<start of this run>.csv

* The file is written to a temporary name and then renamed, so you never see a
  half-written file, even if you open it in Excel at that moment.
* Each run of the backend creates its own file, so old sessions are never
  overwritten.
* Open positions have status OPEN (their pnl is the unrealised profit).
* In Docker ./data is mounted, so the files appear in tv-app/data on your PC.
"""

import asyncio
import csv
import datetime
import logging
import os
from typing import Any, Callable, Dict, List

import config

log = logging.getLogger("tradelog")

COLUMNS = [
    "id", "status", "symbol", "side", "source", "volume",
    "entry_time", "entry_price", "exit_time", "exit_price",
    "initial_sl", "final_sl", "tp", "trail_moves", "exit_reason",
    "gross_pnl", "commission", "net_pnl", "pnl_pct", "duration_s",
    "balance_after", "formula", "entry_ts", "exit_ts",
]


def rows_to_csv_text(rows: List[Dict[str, Any]]) -> str:
    """Used by the download endpoint (/api/trades.csv)."""
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


class TradeCsvLogger:
    def __init__(self, directory: str, get_rows: Callable[[], List[Dict[str, Any]]]) -> None:
        self.directory = directory
        self.get_rows = get_rows
        os.makedirs(directory, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = os.path.join(directory, f"trades_{stamp}.csv")

    def write_now(self) -> str:
        """Write every trade to the CSV file (atomic replace) and return the path."""
        tmp = self.path + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
            w.writeheader()
            w.writerows(self.get_rows())
        os.replace(tmp, self.path)
        return self.path

    async def run(self) -> None:
        """Background loop: write, sleep, write ... until cancelled (a final write is done on exit)."""
        try:
            while True:
                try:
                    self.write_now()
                except Exception as e:                     # never let logging kill the app
                    log.warning("CSV write failed: %s", e)
                await asyncio.sleep(config.CSV_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            try:
                self.write_now()
            except Exception:
                pass
            raise
