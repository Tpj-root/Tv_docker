# Tv_docker


# TV Clone - Day 3: Chandelier Exit + paper broker

## Run
```bash
cp .env.example .env        # fill DERIV_APP_ID, DERIV_API_TOKEN, DERIV_ACCOUNT_ID
docker compose up --build
```
* Chart + control bar: http://localhost:5173
* API docs:            http://localhost:8000/docs
* Trade CSV files:     `tv-app/data/trades_<start time>.csv` (rewritten every 60 s)

Without Docker: `cd backend && pip install -r requirements.txt && uvicorn main:app --reload`
and `cd frontend && BACKEND=localhost:8000 npm install && BACKEND=localhost:8000 npm run dev`.

## Folder map
```
backend/
  config.py               ALL default values (edit + save = backend restarts with them)
  settings.py             builds the control-bar schema from the indicators + app groups
  engine.py               ticks -> pipeline -> signals -> delay -> broker (no network code)
  service.py              async glue: Deriv ticks -> engine -> browsers
  deriv_hub.py            Deriv OTP login, ticks history, live ticks, reconnect
  trade_log.py            CSV file every minute
  main.py                 REST + WebSocket API
  core/ticks.py           1 load_ticks_raw   2 ticks_to_candles_raw
  indicators/
    heikin_ashi.py        3 to_heikin_ashi_raw
    extremums.py          4 compute_extremums_raw
    chandelier_exit.py    5 chandelier_exit_raw  (+ the indicator class)
    signal_delay.py       timing indicator (wait N s before buy / sell)
    trailing_stop.py      stop loss = chandelier line, trailing, take profit
    sma.py                template for YOUR indicators
    base.py, __init__.py  Param / indicator base classes and the registry
  broker/paper.py         paper broker, profit maths, per-trade details
  tests/                  offline tests (python3 -m tests.test_engine / test_service)
frontend/src/             Chart.jsx  ControlPanel.jsx  Tables.jsx  App.jsx ...
```

## Add your own indicator
1. Copy `backend/indicators/sma.py`, rename, change the `Param(...)` list and `compute()`.
2. Add its default values to `config.py`.
3. In `backend/indicators/__init__.py` import it and add `yourfile.INDICATOR` to `ALL`.
The control bar shows its inputs automatically and the chart draws the lines it returns.

## Tests (no internet needed)
```bash
cd backend
python3 -m tests.test_engine    # also compares against your trading_ha_chandelier.py
python3 -m tests.test_service
```



### Running without Docker (development)

```bash
cd backend && uvicorn main:app --port 8010
cd frontend && npm install && npm run dev                       # terminal 2
```

