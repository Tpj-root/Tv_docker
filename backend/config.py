"""
================================================================================
 config.py  -  ALL DEFAULT VALUES LIVE HERE
================================================================================
Every time the backend (re)starts it reads this file, so the app always starts
from these values.  Edit a value, save, and uvicorn --reload (used in Docker)
restarts the backend automatically.

Values changed from the control bar in the browser are RUNTIME ONLY: they are
not written back to this file.  Press "Reset to defaults" in the panel (or
restart the backend) to return to the values below.

Deriv credentials are NOT here - they stay in .env (DERIV_APP_ID,
DERIV_API_TOKEN, DERIV_ACCOUNT_ID) so secrets never end up in source code.
"""

# --------------------------------------------------------------------------
# MARKET
# --------------------------------------------------------------------------
SYMBOL = "R_100"               # Deriv symbol shown at start-up
TIMEFRAME_SECONDS = 60         # candle size: 60 = 1 minute, 300 = 5 minutes ...
HISTORY_TICKS = 5000           # ticks loaded at start (Deriv returns max 5000 per request;
                               # larger values are fetched in several requests)
MAX_TICKS_IN_MEMORY = 60000    # oldest ticks are dropped above this limit

# --------------------------------------------------------------------------
# INDICATOR 1 - CHANDELIER EXIT (gives the BUY / SELL signals)
# --------------------------------------------------------------------------
CE_ENABLED = True
CE_ATR_PERIOD = 22             # ATR length and highest/lowest look-back window
CE_ATR_MULT = 3.0              # distance of the stop from the extreme, in ATRs
CE_MODE = "tradingview"        # "tradingview" or "user_original" (ratchet compare rule)
CE_USE_CLOSE = False           # True = extremes from CLOSE prices, wicks ignored
CE_FORMULA = "close"           # "close" | "range_ma" | "crest_trough" | "pivot_sr"
CE_MA_LEN = 20                 # EMA length used by range_ma / crest_trough
CE_LOOKBACK = 5                # window used by range_ma

# --------------------------------------------------------------------------
# INDICATOR 2 - SIGNAL DELAY (timing control)
# When ON, a Chandelier signal is not executed immediately: the engine waits
# the configured number of seconds first, then executes the buy / sell.
# --------------------------------------------------------------------------
DELAY_ENABLED = False
BUY_DELAY_SECONDS = 5
SELL_DELAY_SECONDS = 5

# --------------------------------------------------------------------------
# INDICATOR 3 - TRAILING STOP LOSS + TAKE PROFIT (applies to EVERY position)
# --------------------------------------------------------------------------
TRAIL_ENABLED = True           # stop follows the Chandelier stop line (never moves backwards)
TP_ENABLED = True
TP_RR = 2.0                    # take profit = entry +/- TP_RR x (entry - initial stop)

# --------------------------------------------------------------------------
# AUTO TRADING (Chandelier signals -> paper broker)
# --------------------------------------------------------------------------
AUTO_TRADE = True              # False = only draw signals, never open trades by itself
AUTO_VOLUME = 1.0              # volume of automatic trades
REVERSE_ON_SIGNAL = True       # a buy signal closes AUTO shorts (and vice versa)

# --------------------------------------------------------------------------
# PAPER BROKER
# --------------------------------------------------------------------------
BROKER = "paper"               # only "paper" is implemented (see broker/__init__.py)
PAPER_START_BALANCE = 10000.0
CONTRACT_SIZE = 1.0            # profit = price difference x volume x CONTRACT_SIZE
COMMISSION_PER_TRADE = 0.0     # charged once per closed trade
MANUAL_VOLUME = 1.0            # default volume in the manual Buy / Sell box

# --------------------------------------------------------------------------
# CSV TRADE LOG
# --------------------------------------------------------------------------
CSV_DIR = "data"
CSV_INTERVAL_SECONDS = 60      # every N seconds ALL trades are written to a new CSV file per run

# --------------------------------------------------------------------------
# EXAMPLE EXTRA INDICATOR - SMA (template for the indicators you add yourself)
# --------------------------------------------------------------------------
SMA_ENABLED = False
SMA_PERIOD = 20

# --------------------------------------------------------------------------
# CHART
# --------------------------------------------------------------------------
SHOW_HEIKIN_ASHI = False       # draw Heikin-Ashi candles instead of real candles
