import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { fmtStamp } from "../format";
import type { ReportRecord, TradeIn } from "../types";

const CODE_KEY = "tl.reportCode";
const readCode = () => { try { return localStorage.getItem(CODE_KEY) ?? ""; } catch { return ""; } };
const saveCode = (c: string) => { try { localStorage.setItem(CODE_KEY, c); } catch { /* özel pencere */ } };

const DECISION: Record<string, string> = {
  "kabul et": "okay", "karşı teklif ver": "", "reddet": "warn", "bekle": "",
};

/** Takas için Claude'dan yazılı detaylı analiz (README §13.29): arka planda üretilir, durum sorulur. */
export function TradeReport({ league, body, needsCode, onApply }: {
  league: string; body: TradeIn; needsCode: boolean; onApply: (give: string[], get: string[]) => void;
}) {
  const [rec, setRec] = useState<ReportRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState(readCode);
  const timer = useRef<number | null>(null);
  const bodyKey = JSON.stringify(body);

  useEffect(() => {                       // takas değişince önceki rapor gösterilmez
    setRec(null); setError(null); setBusy(false);
    if (timer.current) window.clearTimeout(timer.current);
  }, [bodyKey, league]);
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);

  const handle = (r: ReportRecord) => {
    if (r.status === "running") {
      setBusy(true);
      timer.current = window.setTimeout(() => {
        api.tradeReportStatus(r.key, code).then(handle).catch((e: Error) => { setBusy(false); setError(e.message); });
      }, 3000);
      return;
    }
    setBusy(false);
    if (r.status === "error") setError(r.error ?? "Analiz alınamadı.");
    else setRec(r);
  };
  const start = (refresh: boolean) => {
    setError(null);
    setBusy(true);
    if (needsCode) saveCode(code);
    api.tradeReport(league, { ...body, refresh }, code).then(handle)
      .catch((e: Error) => { setBusy(false); setError(e.message); });
  };

  const rep = rec?.report;
  return (
    <div className="report">
      {!rep && (
        <div className="complete-bar" style={{ marginTop: 0 }}>
          {needsCode && (
            <input className="num-input" type="password" placeholder="Erişim kodu" value={code} style={{ width: 140 }}
                   onChange={(e) => setCode(e.target.value)} aria-label="Detaylı analiz erişim kodu" />
          )}
          <button className="btn primary" onClick={() => start(false)} disabled={busy || (needsCode && !code)}>
            {busy ? <><span className="spinner" /> Analiz yazılıyor… (~1 dk)</> : "Detaylı analiz yaz"}
          </button>
          <span className="hint" style={{ marginTop: 0 }}>Claude; oyuncuların bu sezonu, projeksiyonu, son maçları, takımdaki rolü,
            dönen sakatlar, haberler, dört senaryo ve IL takvimiyle yorumlar. Rapor başı ~0,15 $; aynı takas tekrar açılınca ücretsiz.</span>
        </div>
      )}
      {error && <div className="banner err" style={{ marginTop: 10 }}>{error}</div>}
      {rep && rec && (
        <>
          <div className="verdict" style={{ marginTop: 0 }}>
            <span className={"pill " + (DECISION[rep.decision] ?? "")} style={{ fontWeight: 700 }}>{rep.decision.toLocaleUpperCase("tr-TR")}</span>
            <span className="pill muted">güven: {rep.confidence}</span>
          </div>
          <p className="report-headline">{rep.headline}</p>
          {rep.sections.map((s) => (
            <div key={s.title} className="report-sec">
              <div className="section-title">{s.title}</div>
              <ul>{s.points.map((p, i) => <li key={i}>{p}</li>)}</ul>
            </div>
          ))}
          {rep.counter_offers.length > 0 && (
            <div className="report-sec">
              <div className="section-title">Karşı teklif önerileri</div>
              <ul className="m-list">
                {rep.counter_offers.map((c, i) => (
                  <li key={i} className="m-item">
                    <div className="m-line"><span className="m-lbl drop">Ver</span>
                      <span className="pkg">{c.give.map((p) => <span key={p.id} className="chip">{p.name}</span>)}</span></div>
                    <div className="m-line"><span className="m-lbl add">Al</span>
                      <span className="pkg">{c.get.map((p) => <span key={p.id} className="chip">{p.name}</span>)}</span>
                      <span className="spacer" />
                      {c.valid && <button className="btn" onClick={() => onApply(c.give.map((p) => p.id), c.get.map((p) => p.id))}>Takas ekranında aç</button>}
                    </div>
                    <div className="m-line hint" style={{ marginTop: 2 }}>{c.why}</div>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {rep.watch.length > 0 && (
            <div className="report-sec">
              <div className="section-title">İzle</div>
              <ul>{rep.watch.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </div>
          )}
          <p className="hint">
            {rec.model} · {rec.created_at ? fmtStamp(rec.created_at) : ""} · maliyet ~{(rec.cost ?? 0).toFixed(2)} $ · aynı veriyle aynı takas
            kayıttan açılır.{" "}
            <button className="link-btn" onClick={() => start(true)} disabled={busy}>{busy ? "Yazılıyor…" : "Yeniden yaz"}</button>
          </p>
        </>
      )}
    </div>
  );
}
