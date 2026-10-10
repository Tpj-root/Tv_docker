// ============================================================================
//  Tables.jsx  -  open positions, trade history, account summary, activity log
// ============================================================================
import { Fragment, useState } from "react";
import { api, px, money, clsPnl } from "./api";

const dur = (s) => (s >= 3600 ? `${(s / 3600).toFixed(1)} h` : s >= 60 ? `${Math.floor(s / 60)} m ${s % 60} s` : `${s} s`);
const Side = ({ s }) => <span className={"tag " + (s === "BUY" ? "buy" : "sell")}>{s}</span>;

// ---- open positions --------------------------------------------------------------
export function Positions({ positions, notify }) {
  const close = async (id) => { try { await api(`/api/positions/${id}/close`, "POST"); } catch (e) { notify(e.message); } };
  const closeAll = async () => { try { await api("/api/positions/close_all", "POST"); } catch (e) { notify(e.message); } };

  if (!positions.length) return <div className="empty">No open positions. Orders appear here with their live profit.</div>;
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>#</th><th>Side</th><th>Source</th><th>Volume</th><th>Entry time</th><th>Entry</th>
            <th>Stop loss</th><th>Take profit</th><th>Trails</th><th>Now</th>
            <th>Profit</th><th>%</th>
            <th><button className="btn small ghost" onClick={closeAll}>Close all</button></th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => (
            <tr key={p.id}>
              <td>{p.id}</td><td><Side s={p.side} /></td><td>{p.source}</td><td>{p.volume}</td>
              <td>{p.entry_time}</td><td>{px(p.entry_price)}</td>
              <td title={`initial ${px(p.initial_sl)}`}>{px(p.sl)}</td>
              <td>{p.tp != null ? px(p.tp) : "-"}</td>
              <td>{p.trail_moves}</td><td>{px(p.price)}</td>
              <td className={clsPnl(p.unrealized)}>{money(p.unrealized)}</td>
              <td className={clsPnl(p.unrealized)}>{money(p.unrealized_pct)}%</td>
              <td><button className="btn small" onClick={() => close(p.id)}>Close</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---- closed trades (click a row to see the profit calculation) ---------------------
export function History({ trades }) {
  const [open, setOpen] = useState(null);
  if (!trades.length) return <div className="empty">No closed trades yet.</div>;
  const rows = [...trades].reverse();
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>#</th><th>Side</th><th>Source</th><th>Volume</th><th>Buy / sell time</th><th>Entry</th>
            <th>Exit time</th><th>Exit</th><th>Closed by</th><th>Duration</th>
            <th>Gross</th><th>Fee</th><th>Net profit</th><th>%</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <Fragment key={t.id}>
              <tr className="click" onClick={() => setOpen(open === t.id ? null : t.id)}>
                <td>{t.id}</td><td><Side s={t.side} /></td><td>{t.source}</td><td>{t.volume}</td>
                <td>{t.entry_time}</td><td>{px(t.entry_price)}</td>
                <td>{t.exit_time}</td><td>{px(t.exit_price)}</td><td>{t.exit_reason}</td>
                <td>{dur(t.duration_s)}</td>
                <td className={clsPnl(t.gross_pnl)}>{money(t.gross_pnl)}</td>
                <td>{t.commission}</td>
                <td className={clsPnl(t.net_pnl)}><b>{money(t.net_pnl)}</b></td>
                <td className={clsPnl(t.net_pnl)}>{money(t.pnl_pct)}%</td>
              </tr>
              {open === t.id && (
                <tr className="detail">
                  <td colSpan={14}>
                    <div><b>Profit calculation:</b> {t.formula}</div>
                    <div>
                      Stop loss {px(t.initial_sl)} → {px(t.final_sl)} ({t.trail_moves} trail moves) ·
                      Take profit {t.tp != null ? px(t.tp) : "none"} · Balance after trade {t.balance_after}
                    </div>
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---- account totals ----------------------------------------------------------------
export function Summary({ account }) {
  if (!account) return null;
  const items = [
    ["Start balance", account.start_balance], ["Balance", account.balance],
    ["Open profit", money(account.unrealized), clsPnl(account.unrealized)],
    ["Equity", account.equity],
    ["Closed profit", money(account.realized), clsPnl(account.realized)],
    ["Closed trades", account.trades], ["Open trades", account.open],
    ["Wins / losses", `${account.wins} / ${account.losses}`],
    ["Win rate", `${account.win_rate}%`],
    ["Gross profit", account.gross_profit], ["Gross loss", account.gross_loss],
    ["Profit factor", account.profit_factor ?? "-"],
  ];
  return (
    <div className="summary">
      {items.map(([k, v, c]) => (
        <div key={k} className="stat"><div className="stat-k">{k}</div><div className={"stat-v " + (c || "")}>{v}</div></div>
      ))}
    </div>
  );
}

// ---- activity log (newest first) -----------------------------------------------------
export function Log({ events }) {
  if (!events.length) return <div className="empty">Signals, orders and closes are listed here.</div>;
  return (
    <div className="log">
      {[...events].reverse().map((e, i) => (
        <div key={i} className={"log-row " + e.kind.toLowerCase()}>
          <span className="log-time">{e.time}</span><span className="log-kind">{e.kind.toLowerCase()}</span>
          <span>{e.text}</span>
        </div>
      ))}
    </div>
  );
}
