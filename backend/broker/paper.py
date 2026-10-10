"""
================================================================================
 broker/paper.py  -  PAPER (simulated) BROKER
================================================================================
No real money and no network.  It keeps:
    * a cash balance,
    * a dict of OPEN positions,
    * a list of CLOSED trades with every detail needed for a full report.

PROFIT CALCULATION (shown in every trade row as `formula`)
    BUY  gross = (exit_price  - entry_price) x volume x contract_size
    SELL gross = (entry_price - exit_price ) x volume x contract_size
    net        = gross - commission
    pnl_pct    = gross / (entry_price x volume x contract_size) x 100
    balance   += net            equity = balance + open (unrealised) profit

Prices are the live tick prices, there is no spread or slippage model: an order
is filled at the last tick price, a stop/take-profit at the tick that crossed it.
"""

import datetime
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


def ts_str(ts: int) -> str:
    """UNIX seconds -> 'YYYY-MM-DD HH:MM:SS' (UTC)."""
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class Position:
    """One open position."""
    id: int
    symbol: str
    side: str                    # "BUY" (long) or "SELL" (short)
    volume: float
    source: str                  # "AUTO" (chandelier signal) or "MANUAL"
    entry_ts: int                # time of the fill (tick time, epoch seconds)
    entry_bar_time: int          # start time of the candle containing the entry (chart x position)
    entry_price: float
    sl: float                    # CURRENT stop loss (moves when trailing)
    initial_sl: float            # stop loss at entry
    tp: Optional[float]          # take profit or None
    trail_moves: int = 0         # how many times the stop was trailed


class PaperBroker:
    def __init__(self, start_balance: float, contract_size: float, commission: float) -> None:
        self.start_balance = start_balance
        self.balance = start_balance
        self.contract_size = contract_size
        self.commission = commission
        self._next_id = 1
        self.positions: Dict[int, Position] = {}
        self.trades: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------ orders
    def open_position(self, symbol: str, side: str, volume: float, price: float, ts: int,
                      bar_time: int, sl: float, tp: Optional[float], source: str) -> Position:
        """Fill a market order at `price` and create the position."""
        pos = Position(
            id=self._next_id, symbol=symbol, side=side, volume=volume, source=source,
            entry_ts=ts, entry_bar_time=bar_time, entry_price=price,
            sl=sl, initial_sl=sl, tp=tp,
        )
        self._next_id += 1
        self.positions[pos.id] = pos
        return pos

    def gross_pnl(self, side: str, entry: float, exit_price: float, volume: float) -> float:
        diff = (exit_price - entry) if side == "BUY" else (entry - exit_price)
        return diff * volume * self.contract_size

    def close_position(self, pos_id: int, price: float, ts: int, reason: str) -> Dict[str, Any]:
        """
        Close a position at `price`.  reason: SL | TP | SIGNAL | MANUAL.
        Returns the finished trade record (also appended to self.trades).
        """
        pos = self.positions.pop(pos_id)
        gross = self.gross_pnl(pos.side, pos.entry_price, price, pos.volume)
        net = gross - self.commission
        notional = pos.entry_price * pos.volume * self.contract_size
        self.balance += net

        sign = "(exit - entry)" if pos.side == "BUY" else "(entry - exit)"
        a, b = (price, pos.entry_price) if pos.side == "BUY" else (pos.entry_price, price)
        formula = (f"{sign} x volume x contract = ({a:.5g} - {b:.5g}) x {pos.volume:g} x "
                   f"{self.contract_size:g} = {gross:.4f}; minus commission {self.commission:g} = {net:.4f}")

        trade = {
            "id": pos.id, "status": "CLOSED", "symbol": pos.symbol, "side": pos.side,
            "source": pos.source, "volume": pos.volume,
            "entry_time": ts_str(pos.entry_ts), "entry_ts": pos.entry_ts, "entry_price": pos.entry_price,
            "exit_time": ts_str(ts), "exit_ts": ts, "exit_price": price,
            "initial_sl": pos.initial_sl, "final_sl": pos.sl, "tp": pos.tp,
            "trail_moves": pos.trail_moves, "exit_reason": reason,
            "gross_pnl": round(gross, 6), "commission": self.commission,
            "net_pnl": round(net, 6),
            "pnl_pct": round(gross / notional * 100, 4) if notional else 0.0,
            "duration_s": ts - pos.entry_ts, "formula": formula,
            "balance_after": round(self.balance, 6),
        }
        self.trades.append(trade)
        return trade

    # ------------------------------------------------------------------ views
    def open_list(self) -> List[Position]:
        return list(self.positions.values())

    def positions_view(self, price: Optional[float]) -> List[Dict[str, Any]]:
        """Open positions with live (unrealised) profit for the UI."""
        out = []
        for p in self.positions.values():
            d = asdict(p)
            d["entry_time"] = ts_str(p.entry_ts)
            unreal = self.gross_pnl(p.side, p.entry_price, price, p.volume) if price is not None else 0.0
            notional = p.entry_price * p.volume * self.contract_size
            d["price"] = price
            d["unrealized"] = round(unreal, 4)
            d["unrealized_pct"] = round(unreal / notional * 100, 4) if notional else 0.0
            d["risk_amount"] = round(abs(p.entry_price - p.initial_sl) * p.volume * self.contract_size, 4)
            out.append(d)
        return out

    def summary(self, price: Optional[float]) -> Dict[str, Any]:
        """Account totals shown above the tables."""
        unreal = sum(self.gross_pnl(p.side, p.entry_price, price, p.volume)
                     for p in self.positions.values()) if price is not None else 0.0
        wins = [t for t in self.trades if t["net_pnl"] > 0]
        losses = [t for t in self.trades if t["net_pnl"] <= 0]
        gp = sum(t["net_pnl"] for t in wins)
        gl = -sum(t["net_pnl"] for t in losses)
        realized = sum(t["net_pnl"] for t in self.trades)
        return {
            "start_balance": self.start_balance,
            "balance": round(self.balance, 4),
            "unrealized": round(unreal, 4),
            "equity": round(self.balance + unreal, 4),
            "realized": round(realized, 4),
            "trades": len(self.trades),
            "open": len(self.positions),
            "wins": len(wins), "losses": len(losses),
            "win_rate": round(len(wins) / len(self.trades) * 100, 1) if self.trades else 0.0,
            "gross_profit": round(gp, 4), "gross_loss": round(gl, 4),
            "profit_factor": round(gp / gl, 2) if gl > 0 else None,
        }

    def csv_rows(self, price: Optional[float]) -> List[Dict[str, Any]]:
        """Closed trades + currently open positions, one dict per row (for the CSV log)."""
        rows = list(self.trades)
        for p in self.positions.values():
            unreal = self.gross_pnl(p.side, p.entry_price, price, p.volume) if price is not None else 0.0
            rows.append({
                "id": p.id, "status": "OPEN", "symbol": p.symbol, "side": p.side,
                "source": p.source, "volume": p.volume,
                "entry_time": ts_str(p.entry_ts), "entry_ts": p.entry_ts, "entry_price": p.entry_price,
                "exit_time": "", "exit_ts": "", "exit_price": price if price is not None else "",
                "initial_sl": p.initial_sl, "final_sl": p.sl, "tp": p.tp,
                "trail_moves": p.trail_moves, "exit_reason": "",
                "gross_pnl": round(unreal, 6), "commission": "", "net_pnl": round(unreal, 6),
                "pnl_pct": "", "duration_s": "", "formula": "open position (unrealised)",
                "balance_after": "",
            })
        rows.sort(key=lambda r: r["id"])
        return rows
