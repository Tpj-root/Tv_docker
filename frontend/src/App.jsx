import { useEffect, useRef } from "react";
import { createChart } from "lightweight-charts";

export default function App() {
  const ref = useRef(null);

  useEffect(() => {
    const chart = createChart(ref.current, {
      height: window.innerHeight - 50,
      layout: { background: { color: "#131722" }, textColor: "#d1d4dc" },
      grid: { vertLines: { color: "#1e222d" }, horzLines: { color: "#1e222d" } },
      timeScale: { timeVisible: true, secondsVisible: false },
    });
    const series = chart.addCandlestickSeries();

    fetch("/api/candles")
      .then((r) => r.json())
      .then((data) => series.setData(data));

    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/ticks`);
    ws.onmessage = (e) => series.update(JSON.parse(e.data));

    const onResize = () =>
      chart.applyOptions({ width: ref.current.clientWidth, height: window.innerHeight - 50 });
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      ws.close();
      chart.remove();
    };
  }, []);

  return (
    <>
      <header>TV Clone · DEMO/USD · 1m</header>
      <div ref={ref} />
    </>
  );
}