// Small fetch helper used by every button / control.
// Throws Error(message) with the backend's explanation, so the UI can show it.
export async function api(path, method = "GET", body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {}
    throw new Error(msg);
  }
  return res.json();
}

// Price formatting: 2 decimals for big prices (1054.90), 4 for small ones.
export const px = (n) =>
  n === null || n === undefined || n === "" ? "-" : Number(n).toFixed(Math.abs(n) >= 100 ? 2 : 4);

// Signed money / profit formatting: +12.34 / -3.20
export const money = (n) =>
  n === null || n === undefined || n === "" ? "-" : (n > 0 ? "+" : "") + Number(n).toFixed(2);

export const clsPnl = (n) => (n > 0 ? "up" : n < 0 ? "down" : "");
