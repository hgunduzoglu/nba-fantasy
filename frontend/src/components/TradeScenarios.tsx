import { deltaClass } from "./common";
import { fmtDate, fmtDelta, fmtNum, fmtStat } from "../format";
import type { Basis, CategoryKey, ReturnEvent, ScenariosOut } from "../types";

export const BASIS_LABELS: Record<Basis, string> = {
  ros: "Yahoo projeksiyonu", season: "Bu sezonki oranlar", recent: "Son 10 maç", blend: "Karma", late: "Geç dönüş",
};
export const BASIS_SHORT: Record<Basis, string> = {
  ros: "Yahoo", season: "Bu sezon", recent: "Son 10 maç", blend: "Karma", late: "Geç dönüş",
};
export const BASIS_HINT: Record<Basis, string> = {
  ros: "Yahoo'nun kalan sezon projeksiyonu (varsayılan)",
  season: "Bu sezonun gerçekleşen maç başı ortalamaları, kalan maçlara uygulanır (en az 3 maç; yoksa Yahoo)",
  recent: "Son 10 maçın ortalaması: rol değişimini en hızlı yansıtır (en az 3 maç)",
  blend: "Yahoo ile bu sezon arasında, oynanan maça göre ağırlık (10 maçta yarı yarıya)",
  late: "Yahoo oranları; sakat oyuncular CBS'in \"en erken\" dönüş tarihinden bir süre sonra döner (senaryo, kalibre değil). " +
    "Gerçekte oyuncuların çoğu en erken tarihte dönmüyor.",
};

const RATE_COLS: { key: CategoryKey; label: string }[] = [
  { key: "PTS", label: "Sayı" }, { key: "REB", label: "Rib" }, { key: "AST", label: "Ast" }, { key: "FG3M", label: "3P" },
  { key: "STL", label: "TÇ" }, { key: "BLK", label: "Blok" }, { key: "TOV", label: "TO" }, { key: "FG_PCT", label: "FG%" },
  { key: "FT_PCT", label: "FT%" },
];

/** IL dönüş takvimi: kim döner, kim bırakılır; takasla gelen bırakılıyorsa işaretli. */
export function ReturnList({ events }: { events: ReturnEvent[] }) {
  if (!events.length) return null;
  return (
    <ul className="returns">
      {events.map((e) => (
        <li key={e.returning.id}>
          <span className="muted">{e.date ? fmtDate(e.date) : "tarih yok"}</span> · <b>{e.returning.name}</b> döner
          {e.self_cut ? <span className="muted"> ama kadroya girmez (kendisi bırakılır, kimseyi etkilemez)</span>
            : e.dropped ? <> → <span className={e.incoming ? "bad" : ""}>{e.dropped.name}</span> bırakılır
              {e.incoming && <span className="badge out" title="Takasla gelen oyuncu bu dönüşte bırakılıyor: katkısı yalnız bu tarihe kadar">takasla gelen</span>}</>
            : <span className="muted"> → boş yere girer</span>}
        </li>
      ))}
    </ul>
  );
}

/** Aynı takas dört istatistik temelinde; "Aç" tam analizi o temelle yeniler. */
export function TradeScenarios({ data, busy, current, onPick }: {
  data: ScenariosOut | null; busy: boolean; current: Basis; onPick: (b: Basis) => void;
}) {
  if (!data) return busy ? <span className="muted"><span className="spinner" /> Hesaplanıyor…</span> : null;
  const sign = (d: number) => (d > 0.005 ? "good" : d < -0.005 ? "bad" : "");
  return (
    <>
      <div className="table-wrap">
        <table className="data">
          <thead><tr>
            <th className="l">Temel</th>
            <th title="Rakip başına haftalık beklenen kategori değişimi">Sen ΔECW</th>
            <th title="Haftayı kazanma P(5+) değişimi">Sen P(5+)</th>
            <th>Rakip ΔECW</th>
            <th className="l" title="IL dönüşlerinde takasla gelen oyuncu bırakılıyor mu">Takasla gelen</th>
            <th />
          </tr></thead>
          <tbody>
            {data.bases.map((b) => {
              const cut = b.a.returns.filter((e) => e.incoming);
              return (
                <tr key={b.basis} className={b.basis === current ? "rec" : ""} title={BASIS_HINT[b.basis]}>
                  <td className="l pname">{b.label}{b.mutual && <span className="badge fa" title="İki taraf da kazanıyor">ikisi de</span>}</td>
                  <td className={deltaClass(b.a.ecw_delta, 0.3)}>{fmtDelta(b.a.ecw_delta, 3)}</td>
                  <td className={sign(b.a.win_delta)}>{fmtDelta(b.a.win_delta * 100, 1)}</td>
                  <td className={deltaClass(b.b.ecw_delta, 0.3)}>{fmtDelta(b.b.ecw_delta, 3)}</td>
                  <td className="l wrap">{cut.length
                    ? cut.map((e) => <span key={e.returning.id} className="bad">{e.dropped?.name} bırakılır{e.date ? ` (${fmtDate(e.date)})` : ""} </span>)
                    : <span className="muted">kadroda kalır</span>}</td>
                  <td>{b.basis === current ? <span className="muted">açık</span>
                    : <button className="link-btn" onClick={() => onPick(b.basis)}>Bu temelle aç</button>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <details style={{ marginTop: 10 }}>
        <summary>Oyuncuların her temeldeki maç başı oranları</summary>
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th className="l">Oyuncu</th><th className="l">Temel</th>{RATE_COLS.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
            <tbody>
              {data.players.flatMap((p) => (Object.keys(BASIS_SHORT) as Basis[]).filter((b) => p.rates[b]).map((b, i) => (
                <tr key={p.id + b}>
                  <td className="l pname">{i === 0 ? <>{p.name}<div className="psub">{p.side === "a" ? "veriyorsun" : "alıyorsun"} · bu sezon {fmtNum(p.season_gp, 0)} maç</div></> : ""}</td>
                  <td className="l muted">{BASIS_SHORT[b]}</td>
                  {RATE_COLS.map((c) => {
                    const v = p.rates[b]?.[c.key];
                    return <td key={c.key}>{v == null ? "–" : c.key === "FG_PCT" || c.key === "FT_PCT" ? fmtStat(c.key, v) : fmtNum(v, 1)}</td>;
                  })}
                </tr>
              )))}
            </tbody>
          </table>
        </div>
      </details>
      <p className="hint">Her temelde bütün lig (rakipler, boştakiler, IL dönüşünde kimin bırakılacağı) aynı oranlarla değerlenir; kalan maç
        sayısı hep Yahoo'nunkidir. Yahoo projeksiyonu yavaş güncellenir; bu sezon ve son maçlar rol değişimini hızlı yansıtır ama az maçta
        gürültülüdür. Karma, oynanan maç arttıkça gerçekleşene yaslanır. Geç dönüş oranları değiştirmez; sakat oyuncuların CBS'in "en erken"
        tarihinden sonra döndüğü etiketli bir senaryodur (gün sayısı varsayım). Temeller aynı yönü gösteriyorsa karar sağlamdır; ayrışıyorsa
        sonuç hangi orana inandığına bağlıdır.</p>
    </>
  );
}
