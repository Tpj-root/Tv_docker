// ============================================================================
//  ControlPanel.jsx  -  the control bar on the right side
// ============================================================================
//  Nothing in this file knows about a specific indicator.  The backend sends a
//  "schema" (sections -> inputs) and this component draws a slider, checkbox or
//  drop-down for every input.  A new python indicator therefore shows up here
//  automatically, with no change to the frontend.
//
//  Every change is sent to the backend (POST /api/settings) after a short
//  pause; the backend validates it, recomputes the indicators and answers with
//  a fresh snapshot, so the screen always shows the real, accepted values.
// ============================================================================
import { useEffect, useRef, useState } from "react";
import { api } from "./api";

// ---- one number input: slider + typed value ------------------------------------
function NumberControl({ p, value, onCommit }) {
  const [v, setV] = useState(value);
  const timer = useRef();
  useEffect(() => setV(value), [value]);                  // accept the server's (clamped) value

  const change = (x) => {
    setV(x);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => onCommit(x), 250);   // wait until the user pauses
  };
  const showSlider = p.min != null && p.max != null && p.step && (p.max - p.min) / p.step <= 2000;

  return (
    <div className="ctl">
      <div className="ctl-head">
        <label>{p.label}</label>
        <input
          className="num" type="number" min={p.min ?? undefined} max={p.max ?? undefined}
          step={p.step ?? "any"} value={v}
          onChange={(e) => e.target.value !== "" && change(Number(e.target.value))}
        />
      </div>
      {showSlider && (
        <input type="range" min={p.min} max={p.max} step={p.step} value={v}
               onChange={(e) => change(Number(e.target.value))} />
      )}
      {p.help && <div className="hint">{p.help}</div>}
    </div>
  );
}

function ParamControl({ p, value, onCommit }) {
  if (p.kind === "int" || p.kind === "float") {
    return <NumberControl p={p} value={value} onCommit={onCommit} />;
  }
  if (p.kind === "bool") {
    return (
      <label className="ctl check">
        <input type="checkbox" checked={!!value} onChange={(e) => onCommit(e.target.checked)} />
        <span>{p.label}</span>
        {p.help && <div className="hint">{p.help}</div>}
      </label>
    );
  }
  return (                                                  // select
    <div className="ctl">
      <div className="ctl-head">
        <label>{p.label}</label>
        <select value={value} onChange={(e) => onCommit(e.target.value)}>
          {p.choices.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
    </div>
  );
}

// ---- manual order box (inside the "Manual order" section) ----------------------
function ManualButtons({ volume, notify }) {
  const send = async (side) => {
    try {
      await api("/api/orders", "POST", { side, volume });
    } catch (e) {
      notify(e.message);
    }
  };
  return (
    <div className="manual">
      <button className="btn buy" onClick={() => send("BUY")}>Buy {volume}</button>
      <button className="btn sell" onClick={() => send("SELL")}>Sell {volume}</button>
    </div>
  );
}

export default function ControlPanel({ schema, settings, notify }) {
  if (!schema || !settings) return <aside className="panel"><div className="muted pad">Loading controls…</div></aside>;

  const patch = async (groupId, values) => {
    try {
      await api("/api/settings", "POST", { patch: { [groupId]: values } });
    } catch (e) {
      notify(e.message);
    }
  };
  const reset = async () => {
    try { await api("/api/settings/reset", "POST"); } catch (e) { notify(e.message); }
  };

  return (
    <aside className="panel">
      <div className="panel-title">Control bar</div>

      {schema.groups.map((g) => {
        const cur = settings[g.id];
        if (!cur) return null;
        const off = g.has_toggle && !cur.enabled;
        return (
          <details key={g.id} className={"group" + (off ? " off" : "")} open>
            <summary>
              <span className="group-title">{g.title}</span>
              {g.has_toggle && (
                <label className="switch" onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" checked={cur.enabled}
                         onChange={(e) => patch(g.id, { enabled: e.target.checked })} />
                  <span className="slider" />
                </label>
              )}
            </summary>
            {g.description && <div className="hint group-desc">{g.description}</div>}
            <div className="group-body">
              {g.params.map((p) => (
                <ParamControl key={p.key} p={p} value={cur[p.key]}
                              onCommit={(x) => patch(g.id, { [p.key]: x })} />
              ))}
              {g.id === "manual" && <ManualButtons volume={cur.volume} notify={notify} />}
            </div>
          </details>
        );
      })}

      <div className="panel-foot">
        <button className="btn ghost" onClick={reset}>Reset to defaults</button>
        <a className="btn ghost" href="/api/trades.csv">Download trades CSV</a>
      </div>
    </aside>
  );
}
