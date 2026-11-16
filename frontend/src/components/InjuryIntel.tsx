import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { fmtDate, fmtStamp } from "../format";
import type { InjuryIntelOut, InjuryIntelRow } from "../types";

const CODE_KEY = "tl.reportCode";
const readCode = () => { try { return localStorage.getItem(CODE_KEY) ?? ""; } catch { return ""; } };
const saveCode = (c: string) => { try { localStorage.setItem(CODE_KEY, c); } catch { /* özel pencere */ } };

const STATUS: Record<string, string> = {
  out: "oynamaz", doubtful: "zayıf ihtimal", questionable: "şüpheli", probable: "muhtemelen oynar", available: "oynar",
  unknown: "bilinmiyor",
};
const FLAG: Record<string, string> = { none: "yok", likely: "muhtemel", confirmed: "kesin", unknown: "?" };
const LEVEL: Record<string, string> = { low: "düşük", medium: "orta", high: "yüksek" };

function window_(a: InjuryIntelRow["analysis"]): string {
  if (!a) return "";
  const e = a.return_earliest ? fmtDate(a.return_earliest) : "?";
  const l = a.return_latest ? fmtDate(a.return_latest) : "?";
  return e === l ? e : `${e} – ${l}`;
}

/** Takımın sakat / belirsiz oyuncuları: CBS tarihi ve Claude'un web aramasıyla güncel durum özeti. Ücretli yenileme
 * erişim koduyla (sunucu) ve günlük bütçeyle sınırlı; sonuçlar modele girmez, yalnız gösterilir. */
export function InjuryIntel({ league, team, injuries }: { league: string; team: string; injuries: boolean }) {
  const [data, setData] = useState<InjuryIntelOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState(readCode);
  const [version, setVersion] = useState(0);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    api.injuryIntel(league, team, injuries).then((d) => { setData(d); setError(null); })
      .catch((e: Error) => setError(e.message));
  }, [league, team, injuries, version]);
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);

  const poll = () => {
    api.injuryIntelStatus().then((s) => {
      if (s.running) timer.current = window.setTimeout(poll, 3000);
      else { if (s.error) setError(s.error); setVersion((v) => v + 1); }
    }).catch(() => undefined);
  };
  const refresh = () => {
    if (data?.needs_code) saveCode(code);
    api.injuryIntelRefresh(league, { team, injuries }, code).then(() => { setError(null); setVersion((v) => v + 1); poll(); })
      .catch((e: Error) => setError(e.message));
  };

  if (!data) return error ? <div className="banner err">{error}</div> : null;
  if (!data.players.length) return null;
  const running = data.job.running;
  const stale = data.players.filter((p) => p.stale).length;
  return (
    <div className="card">
      <div className="toolbar" style={{ padding: "10px 14px 0", marginBottom: 0 }}>
        <b>Sakatlık analizi</b>
        <span className="muted" style={{ fontSize: 12 }}>{data.model} · web araması · bugün ${data.spent_today.toFixed(2)} / ${data.daily_cap.toFixed(2)}</span>
        <span className="spacer" />
        {data.needs_code && (
          <input className="num-input" type="password" placeholder="Erişim kodu" value={code} style={{ width: 130 }}
                 onChange={(e) => setCode(e.target.value)} />
        )}
        {data.available && (
          <button className="btn" onClick={refresh} disabled={running || (data.needs_code && !code) || stale === 0}
                  title={stale ? `${stale} oyuncunun analizi eski ya da yok` : "Hepsi güncel (20 saat)"}>
            {running ? <><span className="spinner" /> Araştırılıyor…</> : `↻ Yenile (${stale})`}
          </button>
        )}
      </div>
      {error && <div className="banner err" style={{ margin: "8px 14px" }}>{error}</div>}
      {running && data.job.log.length > 0 && <div className="hint" style={{ padding: "4px 14px" }}>{data.job.log[data.job.log.length - 1]}</div>}
      <div className="table-wrap">
        <table className="data">
          <thead><tr>
            <th className="l">Oyuncu</th><th>Yahoo</th><th title="CBS sakatlık raporundaki en erken dönüş">CBS</th>
            <th title="Web araştırmasına göre ilk maç penceresi">Tahmini dönüş</th><th>Güven</th>
            <th title="Dönüşten sonraki maçlarda dakika kısıtlaması">Dakika</th>
            <th title="B2B'nin ikinci maçında dinlendirilme beklentisi (hafta)">B2B</th><th>Tekrar riski</th>
            <th className="l">Özet</th>
          </tr></thead>
          <tbody>
            {data.players.map((p) => {
              const a = p.analysis;
              return (
                <tr key={p.id}>
                  <td className="l pname">{p.name}<span className="psub"> {p.team}</span></td>
                  <td>{p.yahoo_status || "—"}</td>
                  <td>{p.cbs?.return_date ? fmtDate(p.cbs.return_date) : "—"}</td>
                  <td>{a ? window_(a) : "—"}</td>
                  <td>{a ? LEVEL[a.return_confidence] ?? a.return_confidence : ""}</td>
                  <td>{a ? FLAG[a.minutes_restriction] ?? "" : ""}</td>
                  <td>{a ? `${FLAG[a.b2b_rest] ?? ""}${a.b2b_rest_weeks > 0 ? ` (${a.b2b_rest_weeks} hf)` : ""}` : ""}</td>
                  <td>{a ? LEVEL[a.reinjury_risk] ?? "" : ""}</td>
                  <td className="l" style={{ minWidth: 240 }}>
                    {a ? <>
                      <span>{STATUS[a.status] ?? a.status}{a.injury ? ` · ${a.injury}` : ""}. {a.summary_tr}</span>
                      {a.sources.length > 0 && (
                        <span className="muted"> {a.sources.map((s, k) => (
                          <a key={k} href={s.url} target="_blank" rel="noreferrer" title={s.title}> [{s.date ? fmtDate(s.date) : k + 1}]</a>
                        ))}</span>
                      )}
                      {p.analyzed_at && <span className="muted" style={{ fontSize: 11 }}> · {fmtStamp(p.analyzed_at)}</span>}
                    </> : <span className="muted">{p.cbs?.status_text || "Analiz yok"}</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="hint" style={{ padding: "0 14px 12px" }}>
        Claude güncel haberleri web'de arar; tarihler tahmindir ve modele girmez. Model CBS tarihini ve maç kayıtlarından
        ölçülen dönüş/B2B oranlarını kullanır.
      </div>
    </div>
  );
}
