import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { fmtStamp } from "../format";
import type { SyncStatus } from "../types";

/** Üst çubuk: son Yahoo senkronizasyonu ve "Yahoo'dan güncelle" (bitince ``onDone`` veriyi yeniden yükletir). */
export function SyncButton({ onDone }: { onDone: () => void }) {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [players, setPlayers] = useState(true);
  const [open, setOpen] = useState(false);
  const timer = useRef<number | null>(null);

  const poll = () => {
    api.syncStatus().then((s) => {
      setStatus(s);
      if (s.running) timer.current = window.setTimeout(poll, 1500);
      else if (s.result) onDone();
    }).catch(() => undefined);
  };
  useEffect(() => {
    api.syncStatus().then((s) => { setStatus(s); if (s.running) poll(); }).catch(() => undefined);
    return () => { if (timer.current) window.clearTimeout(timer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const start = () => {
    setOpen(true);
    api.syncStart(players).then((s) => { setStatus(s); poll(); })
      .catch((e: Error) => setStatus((s) => s && { ...s, error: e.message }));
  };
  const running = status?.running ?? false;
  const last = status?.last_sync ? `Yahoo: ${fmtStamp(status.last_sync)}` : "Yahoo: hiç";

  return (
    <div className="sync">
      <button className="btn" onClick={start} disabled={running}
              title="Kadrolar, haftanın skorları, puan durumu, alım hakkı, FAB, waiver listesi ve CBS sakatlık raporu. Önce bir kez: python scripts/yahoo_login.py">
        {running ? <><span className="spinner" /> Güncelleniyor…</> : "↻ Yahoo'dan güncelle"}
      </button>
      <label className="check" title="Oyuncu projeksiyonları (~60 sayfa daha, 2–3 dk). Günde bir kez yeter.">
        <input type="checkbox" checked={players} onChange={(e) => setPlayers(e.target.checked)} disabled={running} /> projeksiyonlar
      </label>
      <button className="link-btn muted" style={{ fontSize: 12, fontWeight: 400 }} onClick={() => setOpen((x) => !x)}>{last}</button>
      {open && status && (status.running || status.error || status.result) && (
        <div className="sync-pop card">
          {status.error && <div className="banner err">{status.error}</div>}
          {status.result && !status.running && (
            <div className="banner">
              {status.result.as_of} verisi alındı ({status.result.pages} sayfa).{status.result.notes.length ? " " + status.result.notes.join(" ") : ""}
            </div>
          )}
          <ul className="sync-log">{status.log.map((l, i) => <li key={i}>{l}</li>)}</ul>
          <button className="btn" onClick={() => setOpen(false)}>Kapat</button>
        </div>
      )}
    </div>
  );
}
