"""
================================================================================
 indicators/__init__.py  -  the indicator registry
================================================================================
ALL lists every indicator the app knows.  Order = order in the control bar.
To add your own: import it below and append its INDICATOR to ALL.

Pipeline functions (steps 3-5) are re-exported so you can also use them in
stand-alone scripts:   from indicators import to_heikin_ashi_raw
"""

from .heikin_ashi import to_heikin_ashi_raw
from .extremums import compute_extremums_raw
from .chandelier_exit import chandelier_exit_raw
from . import chandelier_exit, signal_delay, trailing_stop, sma

ALL = [
    chandelier_exit.INDICATOR,   # signal source  (also provides the stop lines)
    signal_delay.INDICATOR,      # timing control
    trailing_stop.INDICATOR,     # stop loss / take profit / trailing
    sma.INDICATOR,               # example overlay - add yours here
]

BY_ID = {ind.id: ind for ind in ALL}
