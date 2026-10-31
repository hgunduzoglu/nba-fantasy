import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBanner, InlineBar, Loading, probClass } from "../components/common";
import { fmtDate, fmtDelta, fmtNum, fmtPct } from "../format";
import type { League, SeasonPageOut } from "../types";

export function SeasonPage({ league, team, injuries }: { league: League; team: string; injuries: boolean }) {
  const [n, setN] = useState(2000);
  const [sd, setSd] = useState(0.06);
  const [data, setData] = useState<SeasonPageOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    setBusy(true);
    api.seasonPage(league.id, team, n, sd, injuries)
      .then((d) => { setData(d); setError(null); })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  }, [league.id, team, n, sd, injuries]);

  const me = data?.table.find((r) => r.team_id === team);
  const maxChamp = Math.max(0.05, ...(data?.table.map((r) => r.p_champion) ?? [0]));

  return (
    <div className="stack">
      <div className="toolbar" style={{ marginBottom: 0 }}>
        <div className="field"><span>Simülasyon</span>
          <div className="seg">{[500, 1000, 2000, 5000].map((x) => <button key={x} aria-pressed={n === x} onClick={() => setN(x)}>{x}</button>)}</div>
        </div>
        <div className="field" title="Kalan sezon projeksiyonunun hatası: her simülasyonda takım gücü sezon boyu bu kadar sapabilir. 0 = güçler kesin bilinir (aşırı kesin olasılıklar). Kalibre edilmedi.">
          <span>Takım gücü belirsizliği</span>
          <div className="seg">{[0, 0.03, 0.06, 0.1, 0.15].map((x) => <button key={x} aria-pressed={sd === x} onClick={() => setSd(x)}>±%{Math.round(x * 100)}</button>)}</div>
        </div>
        {busy && <span className="spinner" />}
      </div>
      <ErrorBanner error={error} />
      {!data && busy && <Loading text="Kalan sezon ve playoff simüle ediliyor…" />}
      {data && me && (
        <>
          {!data.standings_known && <div className="banner err">Sıralama verisi yok: tamamlanmış haftalar da simüle edildi.</div>}
          <div className="kpis">
            <div className="metric"><div className="k">Playoff ({data.playoff_size} takım)</div><div className="v num">{fmtPct(me.p_playoff)}</div></div>
            <div className="metric"><div className="k">{data.byes ? "Bay (ilk tur yok)" : "Normal sezon 1.si"}</div>
              <div className="v num">{fmtPct(data.byes ? me.p_bye : me.p_first)}</div></div>
            <div className="metric"><div className="k">Şampiyonluk</div><div className="v num">{fmtPct(me.p_champion, 1)}</div></div>
            <div className="metric"><div className="k">Ortalama sıra</div><div className="v num">{fmtNum(me.mean_seed)}</div></div>
            <div className="metric"><div className="k">Beklenen kayıt</div><div className="v num">{me.exp_w.toFixed(0)}-{me.exp_l.toFixed(0)}-{me.exp_t.toFixed(0)}</div>
              <div className="d muted">şu an {me.record_now || "—"}</div></div>
          </div>

          <div className="card">
            <div className="card-h"><h3>Lig</h3>
              <span className="muted">{data.start_week}. haftadan · {data.n_sims} simülasyon · playoff haftaları {data.playoff_weeks.join(", ")} · reseeding {data.reseed ? "açık" : "kapalı"}</span></div>
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th className="l">Takım</th><th>Şu an</th><th>Beklenen W-L-T</th><th>Ort. sıra</th>
                  <th className="l">Playoff</th><th>{data.byes ? "Bay" : "1."}</th><th className="l">Şampiyonluk</th></tr></thead>
                <tbody>
                  {data.table.map((r) => (
                    <tr key={r.team_id} className={r.team_id === team ? "me" : ""}>
                      <td className="l pname">{r.team}</td><td>{r.record_now}</td>
                      <td>{r.exp_w.toFixed(0)}-{r.exp_l.toFixed(0)}-{r.exp_t.toFixed(0)}</td><td>{fmtNum(r.mean_seed)}</td>
                      <td className="l"><span className="num" style={{ display: "inline-block", width: 40, textAlign: "right" }}>{fmtPct(r.p_playoff)}</span><InlineBar value={r.p_playoff} /></td>
                      <td>{fmtPct(data.byes ? r.p_bye : r.p_first)}</td>
                      <td className="l"><span className="num" style={{ display: "inline-block", width: 44, textAlign: "right" }}>{fmtPct(r.p_champion, 1)}</span><InlineBar value={r.p_champion} max={maxChamp} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="row">
            <div className="card">
              <div className="card-h"><h3>Kalan fikstürün</h3></div>
              <div className="table-wrap">
                <table className="data">
                  <thead><tr><th>Hafta</th><th className="l">Başlangıç</th><th className="l">Rakip</th><th>Beklenen kategori</th><th>Kazanma</th></tr></thead>
                  <tbody>{data.schedule.map((s) => (
                    <tr key={s.week}><td>{s.week}</td><td className="l">{fmtDate(s.start)}</td><td className="l">{s.opponent_name}</td>
                      <td>{fmtNum(s.exp_cats, 2)}</td><td className={probClass(s.p_win)}>{fmtPct(s.p_win)}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            </div>
            <div className="card">
              <div className="card-h"><h3>Playoff haftalarında sayılan maç</h3></div>
              <table className="data">
                <thead><tr><th>Hafta</th><th className="l">Tarih</th><th>Senin</th><th>Lig ort.</th><th>Fark</th></tr></thead>
                <tbody>{data.playoff_games.map((g) => (
                  <tr key={g.week}><td>{g.week}</td><td className="l">{fmtDate(g.start)}–{fmtDate(g.end)}</td><td>{g.mine}</td>
                    <td>{fmtNum(g.avg)}</td><td className={g.mine - g.avg > 0.5 ? "good" : g.mine - g.avg < -0.5 ? "bad" : ""}>{fmtDelta(g.mine - g.avg, 1)}</td></tr>
                ))}</tbody>
              </table>
              <p className="hint" style={{ padding: "0 14px" }}>Günlük lineup'ta aktif slota yerleşen maçlar (bütün kadro). Playoff'ta fazla maç oynayan oyuncular değerlidir.</p>
            </div>
          </div>
          <p className="hint">{data.notes.join(" ")} Kadrolar sezon boyu sabit; olasılıklar kalibre edilmedi.</p>
        </>
      )}
    </div>
  );
}
