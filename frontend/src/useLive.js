// ============================================================================
//  useLive  -  one WebSocket to the backend (/ws/live)
// ============================================================================
//  The backend sends three kinds of messages:
//     snapshot : the whole screen (on connect, settings change, market change)
//     tick     : small update after every price tick / manual action
//     status   : Deriv connection health every 3 seconds
//
//  React state holds what the tables and panels show.  The CHART is updated
//  imperatively (series.update) through `bus`, so a tick never re-renders React.
// ============================================================================
import { useEffect, useRef, useState } from "react";

const EMPTY = {
  connected: false, settings: null, symbol: "", timeframe: 60, price: null,
  account: null, positions: [], trades: [], events: [], pending: null, status: null,
};

export function useLive() {
  const [state, setState] = useState(EMPTY);
  const listeners = useRef(new Set());
  const lastSnapshot = useRef(null);

  // `bus.on(fn)` lets the chart receive every snapshot / tick message.
  const bus = useRef({
    on: (fn) => {
      listeners.current.add(fn);
      if (lastSnapshot.current) fn(lastSnapshot.current);   // replay if it arrived first
      return () => listeners.current.delete(fn);
    },
  }).current;

  useEffect(() => {
    let ws, timer, closed = false;
    const emit = (m) => listeners.current.forEach((fn) => fn(m));

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws/live`);
      ws.onopen = () => setState((s) => ({ ...s, connected: true }));
      ws.onclose = () => {
        setState((s) => ({ ...s, connected: false }));
        if (!closed) timer = setTimeout(connect, 2000);       // auto reconnect
      };
      ws.onmessage = (ev) => {
        const m = JSON.parse(ev.data);
        if (m.type === "snapshot") {
          lastSnapshot.current = m;
          setState((s) => ({
            ...s, settings: m.settings, symbol: m.symbol, timeframe: m.timeframe, price: m.price,
            account: m.account, positions: m.positions, trades: m.trades, events: m.events,
            pending: m.pending, status: m.status,
          }));
          emit(m);
        } else if (m.type === "tick") {
          setState((s) => ({
            ...s, price: m.price, account: m.account, positions: m.positions, pending: m.pending,
            trades: m.trades ?? s.trades,                              // only sent when a trade closed
            events: m.events.length ? [...s.events, ...m.events].slice(-300) : s.events,
          }));
          emit(m);
        } else if (m.type === "status") {
          setState((s) => ({ ...s, status: m }));
        }
      };
    };
    connect();
    return () => { closed = true; clearTimeout(timer); ws && ws.close(); };
  }, []);

  return { state, bus };
}
