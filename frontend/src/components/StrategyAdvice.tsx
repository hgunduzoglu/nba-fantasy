import { useState } from "react";
import { api } from "../api";
import { fmtPct } from "../format";
import type { StrategyAdviceOut } from "../types";

function delta(d?: { delta: number; se: number; clear: boolean }) {
  if (!d) return "—";
  const v = `${d.delta >= 0 ? "+" : "−"}${(Math.abs(d.delta) * 100).toFixed(1)}`;
  return <span className={d.clear ? (d.delta > 0 ? "good" : "bad") : "muted"} title={`±${(d.se * 100).toFixed(1)} puan (simülasyon gürültüsü)`}>{v}</span>;
}

/** Kendi stratejinin sezona etkisi: her hazır stratejiyle kalan sezon aynı tohumla simüle edilir; dengeliye göre
 * eşleşmeli fark. Hesap ~1 dakika sürer, sonuç veri değişene kadar önbellekte. */
export function StrategyAdvice({ league, team, injuries }: { league: string; team: string; injuries: boolean }) {
  const [data, setData] = useState<StrategyAdviceOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [basis, setBasis] = useState<"ros" | "season" | "blend">("ros");
  const run = () => {
    setBusy(true);
    api.strategyAdvice(league, team, injuries, basis).then((d) => { setData(d); setError(null); })
      .catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };
  const key = data?.rank_by ?? "playoff";
  return (
    <div className="card">
      <div className="card-h"><h3>Strateji önerisi</h3>
        <span className="muted">Kadro, waiver ve günlük kadro kararlarını hangi stratejiyle verirsen sezonun nasıl değişir</span>
        <span className="spacer" />
        <div className="seg" title="Kalan sezon oranlarının temeli">
          {([["ros", "Yahoo"], ["season", "Bu sezon"], ["blend", "Karma"]] as const).map(([k, l]) => (
            <button key={k} aria-pressed={basis === k} onClick={() => { setBasis(k); setData(null); }}>{l}</button>
          ))}
        </div>
        <button className="btn" onClick={run} disabled={busy}>{busy ? <><span className="spinner" /> Simüle ediliyor…</> : data ? "↻ Yeniden" : "Hesapla"}</button>
      </div>
      {error && <div className="banner err" style={{ margin: 12 }}>{error}</div>}
      {data && (
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th className="l">Strateji</th>
              <th>{key === "playoff" ? "Playoff" : "Şampiyonluk"}</th><th title="Dengeliye göre, puan">Fark</th>
              <th title="Dengeliye göre, puan">Şampiyonluk farkı</th></tr></thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.strategy}>
                  <td className="l pname">{r.strategy}</td>
                  <td>{fmtPct(r[key]?.after ?? null)}</td>
                  <td>{delta(r[key])}</td>
                  <td>{key === "playoff" ? delta(r.champion) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="hint" style={{ padding: "0 14px 12px" }}>
        {data ? `${data.n_sims} simülasyon, aynı çekilişler. Renkli farklar gürültüden ayrılıyor; gri olanlar ayrılmıyor. ` : ""}
        Rakiplerin stratejisi sabit. Strateji fiziksel kategori olasılıklarını değiştirmez; hangi oyuncuyu oynatacağını, alacağını ve bırakacağını değiştirir.
        Punt kazancı projeksiyon temeline göre değişebilir: bir stratejiye ancak üç temelde de pozitifse güven.
      </div>
    </div>
  );
}
