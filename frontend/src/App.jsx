import { useEffect, useState, useRef } from "react";
import { createChart } from "lightweight-charts";

const TIMEFRAMES = [
  ["1m", 60], ["5m", 300], ["15m", 900], ["30m",1800],
  ["1h", 3600], ["4h", 14400], ["1d", 86400],
];

export default function App() {
  const ref = useRef(null);
  const [symbols, setSymbols] = useState([]);
  const [symbol, setSymbol] = useState("R_100");
  const [gran, setGran] = useState(60);
  const [status, setStatus] = useState("loading...");

  useEffect(() => {
    fetch("/api/symbols").then((r) => r.json()).then(setSymbols).catch(() => {});
  }, []);

  useEffect(() => {
    let alive = true;
    let ws;
    setStatus("loading...");

    const chart = createChart(ref.current, {
      height: window.innerHeight - 60,
      layout: { background: { color: "#131722" }, textColor: "#d1d4dc" },
      grid: { vertLines: { color: "#1e222d" }, horzLines: { color: "#1e222d" } },
      timeScale: { timeVisible: true, secondsVisible: false },
    });
    const series = chart.addCandlestickSeries();

    fetch(`/api/candles?symbol=${encodeURIComponent(symbol)}&granularity=${gran}&count=500`)
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
        return r.json();
      })
      .then((data) => {
        if (!alive) return;
        series.setData(data);
        chart.timeScale().fitContent();

        const proto = location.protocol === "https:" ? "wss" : "ws";
        ws = new WebSocket(
          `${proto}://${location.host}/ws/candles?symbol=${encodeURIComponent(symbol)}&granularity=${gran}`
        );
        ws.onmessage = (e) => {
          const m = JSON.parse(e.data);
          if (m.error) return setStatus("error: " + m.error);
          try { series.update(m); setStatus("live"); } catch {}
        };
        ws.onclose = () => alive && setStatus("disconnected");
      })
      .catch((err) => alive && setStatus("error: " + err.message));

    const onResize = () =>
      chart.applyOptions({ width: ref.current.clientWidth, height: window.innerHeight - 60 });
    window.addEventListener("resize", onResize);

    return () => {
      alive = false;
      window.removeEventListener("resize", onResize);
      ws && ws.close();
      chart.remove();
    };
  }, [symbol, gran]);

  const list = symbols.length ? symbols : [{ symbol, name: symbol }];

  return (
    <>
      <header style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <span>TV Clone</span>
        <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
          {list.map((s) => (
            <option key={s.symbol} value={s.symbol}>{s.name} ({s.symbol})</option>
          ))}
        </select>
        <select value={gran} onChange={(e) => setGran(Number(e.target.value))}>
          {TIMEFRAMES.map(([label, g]) => <option key={g} value={g}>{label}</option>)}
        </select>
        <span style={{ marginLeft: "auto", fontWeight: 400, opacity: 0.7 }}>{status}</span>
      </header>
      <div ref={ref} />
    </>
  );
}