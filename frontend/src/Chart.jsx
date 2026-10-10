// ============================================================================
//  Chart.jsx  -  candles, indicator lines, signal arrows and the white
//                stop-loss / take-profit rectangles
// ============================================================================
//  * lightweight-charts (TradingView's open source library) draws candles,
//    the Chandelier lines and the BUY / SELL arrows.
//  * The rectangles are drawn on a transparent <canvas> laid over the chart.
//    It is redrawn on every animation frame, so the rectangle follows zooming,
//    scrolling and the moving (trailing) stop loss without any extra code.
// ============================================================================
import { useEffect, useRef } from "react";
import { createChart, CrosshairMode } from "lightweight-charts";
import { px } from "./api";

const UP = "#26a69a";
const DOWN = "#ef5350";
const WHITE = "#ffffff";

export default function Chart({ bus, positions, showHa }) {
  const boxRef = useRef(null);       // div that holds the chart
  const canvasRef = useRef(null);    // overlay for rectangles
  const api = useRef({});            // chart, series, line series ... (created once)
  const barsRef = useRef([]);        // all bars as sent by the backend (real + HA values)
  const positionsRef = useRef(positions);
  const showHaRef = useRef(showHa);
  const marketRef = useRef("");

  positionsRef.current = positions;  // the drawing loop always reads the latest value

  // ---- candle conversion: real or Heikin-Ashi values --------------------------
  const toCandle = (b) =>
    showHaRef.current
      ? { time: b.time, open: b.ha_open, high: b.ha_high, low: b.ha_low, close: b.ha_close }
      : { time: b.time, open: b.open, high: b.high, low: b.low, close: b.close };

  const applyBars = () => {
    const a = api.current;
    if (a.series) a.series.setData(barsRef.current.map(toCandle));
  };

  // ---- create the chart ONCE ---------------------------------------------------
  useEffect(() => {
    const chart = createChart(boxRef.current, {
      autoSize: true,
      layout: { background: { color: "#0e1117" }, textColor: "#9aa5b5", fontFamily: "IBM Plex Sans, system-ui, sans-serif" },
      grid: { vertLines: { color: "#161c26" }, horzLines: { color: "#161c26" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#232b38" },
      timeScale: { borderColor: "#232b38", timeVisible: true, secondsVisible: false, rightOffset: 6 },
    });
    const series = chart.addCandlestickSeries({
      upColor: UP, downColor: DOWN, wickUpColor: UP, wickDownColor: DOWN, borderVisible: false,
    });
    api.current = { chart, series, lines: {}, markerSig: "" };

    // -- markers: BUY / SELL arrows (oldest first, as the library requires) ------
    const setMarkers = (markers) => {
      const sig = JSON.stringify(markers);
      if (sig === api.current.markerSig) return;           // nothing changed
      api.current.markerSig = sig;
      const first = barsRef.current.length ? barsRef.current[0].time : 0;
      series.setMarkers(
        markers
          .filter((m) => m.time >= first)
          .sort((a, b) => a.time - b.time)
          .map((m) => m.side === "BUY"
            ? { time: m.time, position: "belowBar", shape: "arrowUp", color: m.confirmed ? UP : "#1d6f67", text: "BUY" }
            : { time: m.time, position: "aboveBar", shape: "arrowDown", color: m.confirmed ? DOWN : "#8d3a38", text: "SELL" })
      );
    };

    // -- indicator lines (Chandelier long / short stop, SMA ...) ------------------
    const syncLines = (lines) => {
      const store = api.current.lines;
      const ids = new Set(lines.map((l) => l.id));
      for (const id of Object.keys(store)) {               // remove lines switched off
        if (!ids.has(id)) { chart.removeSeries(store[id]); delete store[id]; }
      }
      for (const l of lines) {
        if (!store[l.id]) {
          store[l.id] = chart.addLineSeries({
            color: l.color, lineWidth: l.width, priceLineVisible: false,
            lastValueVisible: false, crosshairMarkerVisible: false, title: "",
          });
        }
        store[l.id].applyOptions({ color: l.color, lineWidth: l.width });
        store[l.id].setData(l.data);                       // {time} items without value = gaps
      }
    };

    // -- messages from the backend ------------------------------------------------
    const off = bus.on((m) => {
      if (m.type === "snapshot") {
        barsRef.current = m.bars.slice();
        applyBars();
        syncLines(m.lines);
        api.current.markerSig = "";
        setMarkers(m.markers);
        const key = `${m.symbol}/${m.timeframe}`;
        if (key !== marketRef.current) {                   // new market -> show the last ~120 bars
          marketRef.current = key;
          const n = barsRef.current.length;
          chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 120), to: n + 6 });
        }
      } else if (m.type === "tick") {
        const bars = barsRef.current;
        const last = bars[bars.length - 1];
        if (last && last.time === m.bar.time) bars[bars.length - 1] = m.bar;   // forming candle
        else bars.push(m.bar);                                                   // new candle
        try { series.update(toCandle(m.bar)); } catch {}
        for (const l of m.lines) {
          try { api.current.lines[l.id]?.update(l.point); } catch {}
        }
        setMarkers(m.markers);
      }
    });

    // -- overlay canvas: white SL / TP rectangles ---------------------------------
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    let raf = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const dpr = window.devicePixelRatio || 1;
      const w = boxRef.current.clientWidth, h = boxRef.current.clientHeight;
      if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
        canvas.width = w * dpr; canvas.height = h * dpr;
        canvas.style.width = w + "px"; canvas.style.height = h + "px";
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      const list = positionsRef.current || [];
      const bars = barsRef.current;
      if (!list.length || !bars.length) return;

      const ts = chart.timeScale();
      const plotRight = w - chart.priceScale("right").width();     // do not draw over the price scale
      const lastX = ts.timeToCoordinate(bars[bars.length - 1].time);
      const xRight = Math.min((lastX ?? plotRight) + 14, plotRight);

      ctx.save();
      ctx.beginPath(); ctx.rect(0, 0, plotRight, h); ctx.clip();
      ctx.font = "12px IBM Plex Sans, system-ui, sans-serif";
      ctx.textBaseline = "middle";

      for (const p of list) {
        const x0raw = ts.timeToCoordinate(p.entry_bar_time);
        const x0 = Math.max(0, x0raw ?? 0);
        const yE = series.priceToCoordinate(p.entry_price);
        const yS = series.priceToCoordinate(p.sl);
        const yT = p.tp != null ? series.priceToCoordinate(p.tp) : null;
        if (yE == null || yS == null) continue;

        // rectangle between the stop loss and the take profit (or entry if no TP)
        const yOther = yT ?? yE;
        const top = Math.min(yS, yOther), bottom = Math.max(yS, yOther);
        ctx.fillStyle = "rgba(255,255,255,0.06)";
        ctx.fillRect(x0, top, xRight - x0, bottom - top);
        ctx.strokeStyle = WHITE; ctx.lineWidth = 1.5; ctx.setLineDash([]);
        ctx.strokeRect(x0, top, xRight - x0, bottom - top);

        // entry line (dashed)
        ctx.setLineDash([5, 4]); ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x0, yE); ctx.lineTo(xRight, yE); ctx.stroke();
        ctx.setLineDash([]);

        // labels, written just inside the right edge
        ctx.fillStyle = WHITE; ctx.textAlign = "right";
        ctx.fillText(`SL ${px(p.sl)}`, xRight - 6, yS + (yS >= yOther ? -9 : 9));
        if (yT != null) ctx.fillText(`TP ${px(p.tp)}`, xRight - 6, yT + (yT >= yS ? -9 : 9));
        ctx.textAlign = "left";
        const pnl = `${p.unrealized >= 0 ? "+" : ""}${p.unrealized.toFixed(2)}`;
        ctx.fillText(`#${p.id} ${p.side} ${p.volume} (${pnl})`, x0 + 6, yE - 9);
      }
      ctx.restore();
    };
    raf = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(raf);
      off();
      chart.remove();
      api.current = {};
    };
  }, []);

  // ---- Heikin-Ashi switch: redraw candles from the stored bars ------------------
  useEffect(() => {
    showHaRef.current = showHa;
    applyBars();
  }, [showHa]);

  return (
    <div className="chart-wrap">
      <div ref={boxRef} className="chart-box" />
      <canvas ref={canvasRef} className="chart-overlay" />
    </div>
  );
}
