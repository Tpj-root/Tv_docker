"""
================================================================================
 broker/__init__.py  -  broker factory
================================================================================
make_broker() builds the broker chosen by config.BROKER.  Only the paper broker
exists today.  To add a real one later, create broker/deriv_real.py with the
same methods as PaperBroker (open_position, close_position, positions_view,
summary, csv_rows ...) and return it here.
"""

import config
from .paper import PaperBroker, ts_str, Position  # noqa: F401  (re-exported)


def make_broker() -> PaperBroker:
    if config.BROKER == "paper":
        return PaperBroker(config.PAPER_START_BALANCE, config.CONTRACT_SIZE, config.COMMISSION_PER_TRADE)
    raise ValueError(f"BROKER '{config.BROKER}' is not implemented - use 'paper'")
