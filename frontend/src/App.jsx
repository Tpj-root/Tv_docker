// ============================================================================
//  App.jsx  -  page layout and the top bar
// ============================================================================
//   +--------------------------------------------+----------------+
//   | top bar: symbol, timeframe, price, status  |  control bar   |
//   +--------------------------------------------+  (right side)  |
//   | chart                                      |                |
//   +--------------------------------------------+                |
//   | tabs: positions / history / summary / log  |                |
//   +--------------------------------------------+----------------+
// ============================================================================
import { useEffect, useRef, useState } from "react";
import { api, px, money, clsPnl } from "./api";
import { useLive } from "./useLive";
import Chart from "./Chart";
import ControlPanel from "./ControlPanel";
import { Positions, History, Summary, Log } from "./Tables";

const TIMEFRAMES = [["1m", 60], ["2m", 120], ["3m", 180], ["5m", 300], ["10m", 600], ["15m", 900], ["30m", 1800], ["1h", 3600]];

export default function App() {
  const { state, bus } = useLive();
  const [schema, setSchema] = useState(null);
  const [symbols, setSymbols] = useState([]);
  const [tab, setTab] = useState("positions");
  const [notice, setNotice] = useState(null);
  const noticeTimer = useRef();

  // Short message at the bottom of the screen (errors from the backend).
  const notify = (msg) => {
    setNotice(msg);
    clearTimeout(noticeTimer.current);
    noticeTimer.current = setTimeout(() => setNotice(null), 6000);
  };

  useEffect(() => {
    api("/api/schema").then(setSchema).catch((e) => notify(e.message));
  }, []);

  // Symbols come from Deriv, so load them again once the backend is connected.
  const ready = state.status?.ready;
  useEffect(() => {
    api("/api/symbols").then(setSymbols).catch(() => {});
  }, [ready]);

  const changeMarket = async (symbol, timeframe) => {
    try {
      await api("/api/market", "POST", { symbol, timeframe });
    } catch (e) {
      notify(e.message);
    }
  };

  const list = symbols.some((s) => s.symbol === state.symbol) || !state.symbol
    ? symbols : [{ symbol: state.symbol, name: state.symbol }, ...symbols];

  // ---- connection status chip ----
  const st = state.status;
  let chip = { cls: "bad", text: "Backend offline" };
  if (state.connected && st) {
    if (!st.deriv_connected) chip = { cls: "bad", text: "Deriv offline" };
    else if (!st.ready) chip = { cls: "warn", text: st.error ? "Retrying…" : "Loading history…" };
    else chip = { cls: "ok", text: st.tick_age != null && st.tick_age > 15 ? `No tick for ${Math.round(st.tick_age)} s` : "Live" };
  }

  const acc = state.account;
  const showHa = !!state.settings?.view?.show_ha;

  return (
    <div className="app">
      <header className="top">
        <div className="brand">TV Clone</div>

        <select className="sym" value={state.symbol} onChange={(e) => changeMarket(e.target.value, state.timeframe)}>
          {list.map((s) => <option key={s.symbol} value={s.symbol}>{s.name} ({s.symbol})</option>)}
        </select>

        <div className="seg">
          {TIMEFRAMES.map(([label, sec]) => (
            <button key={sec} className={state.timeframe === sec ? "on" : ""}
                    onClick={() => changeMarket(state.symbol, sec)}>{label}</button>
          ))}
        </div>

        <div className="price">{state.price != null ? px(state.price) : "-"}</div>

        {state.pending && (
          <div className={"pending " + state.pending.side.toLowerCase()}>
            {state.pending.side} waiting {Math.ceil(state.pending.remaining)} s
          </div>
        )}

        <div className="spacer" />
        {acc && (
          <div className="acct">
            <span>Equity <b>{acc.equity}</b></span>
            <span>Open profit <b className={clsPnl(acc.unrealized)}>{money(acc.unrealized)}</b></span>
            <span>Closed profit <b className={clsPnl(acc.realized)}>{money(acc.realized)}</b></span>
          </div>
        )}
        <div className={"chip " + chip.cls}>{chip.text}</div>
      </header>

      <main className="main">
        <section className="chart-area">
          <Chart bus={bus} positions={state.positions} showHa={showHa} />
        </section>

        <section className="bottom">
          <nav className="tabs">
            <button className={tab === "positions" ? "on" : ""} onClick={() => setTab("positions")}>
              Open positions ({state.positions.length})
            </button>
            <button className={tab === "history" ? "on" : ""} onClick={() => setTab("history")}>
              Trade history ({state.trades.length})
            </button>
            <button className={tab === "summary" ? "on" : ""} onClick={() => setTab("summary")}>Account</button>
            <button className={tab === "log" ? "on" : ""} onClick={() => setTab("log")}>Activity</button>
          </nav>
          <div className="tab-body">
            {tab === "positions" && <Positions positions={state.positions} notify={notify} />}
            {tab === "history" && <History trades={state.trades} />}
            {tab === "summary" && <Summary account={acc} />}
            {tab === "log" && <Log events={state.events} />}
          </div>
        </section>
      </main>

      <ControlPanel schema={schema} settings={state.settings} notify={notify} />

      {notice && <div className="notice" onClick={() => setNotice(null)}>{notice}</div>}
    </div>
  );
}
