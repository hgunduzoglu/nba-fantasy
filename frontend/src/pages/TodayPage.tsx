import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { DataChecks } from "../components/DataChecks";
import { ErrorBanner, Loading } from "../components/common";
import { fmtDate, fmtNum, fmtPct, fmtStamp } from "../format";
import type { TodayLeague, TodayOut } from "../types";

type Go = (league: string, tab: "weekly" | "fa" | "news" | "season") => void;

function LeagueCard({ l, go }: { l: TodayLeague; go: Go }) {
  if (l.error) return <div className="card"><div className="card-h"><h3>{l.league}</h3></div><div className="banner err" style={{ margin: 12 }}>{l.error}</div></div>;
  const w = l.week;
  const gain = w && w.plan_expected_wins != null ? w.plan_expected_wins - w.expected_wins : null;
  return (
    <div className="card">
      <div className="card-h">
        <h3>{l.team}</h3><span className="muted">{l.league}</span>
        <span className="spacer" />
        {l.season && <span className="muted">{l.season.record} · playoff {fmtPct(l.season.p_playoff)} · şampiyonluk {fmtPct(l.season.p_champion, 1)}</span>}
      </div>
      <div className="card-b stack" style={{ gap: 8 }}>
        {l.alerts.map((a, k) => <div key={k} className="banner err">⚠ {a.text}</div>)}
        <DataChecks league={l.league_id} teams={[l.team_id]} injuries={true} />
        {w && (
          <div>
            <b>{w.week}. hafta</b> · rakip {w.opponent}: beklenen kategori {fmtNum(w.expected_wins, 2)}, haftayı kazanma {fmtPct(w.p_win)}
            {w.adds_limit != null && <span className="muted"> · alım {w.adds_left}/{w.adds_limit}</span>}
          </div>
        )}
        {w && w.moves.length > 0 && (
          <div>
            <span>Streaming planı ({w.moves.length} alım): {fmtNum(w.expected_wins, 2)} → <b>{fmtNum(w.plan_expected_wins ?? 0, 2)}</b>
              {gain != null && <span className={gain > 0 ? "good" : ""}> (+{fmtNum(gain, 2)})</span>}, kazanma {fmtPct(w.p_win)} → <b>{fmtPct(w.plan_p_win ?? 0)}</b></span>
            <ul style={{ margin: "4px 0 0 18px" }}>
              {w.moves.map((m, k) => <li key={k}>{fmtDate(m.day)}: <b>{m.add}</b> al, {m.drop} bırak</li>)}
            </ul>
          </div>
        )}
        {w && w.moves.length === 0 && w.adds_left !== 0 && <div className="muted">Bu haftayı belirgin iyileştiren alım yok.</div>}
        {l.waiver && <div>Kalan sezon için en iyi alım: <b>{l.waiver.add}</b> ← {l.waiver.drop} <span className="muted">(+{fmtNum(l.waiver.delta_ecw ?? 0, 3)})</span></div>}
        {l.injuries && l.injuries.players > 0 && (
          <div className="muted">{l.injuries.players} sakat/belirsiz oyuncu{l.injuries.stale ? `, ${l.injuries.stale} için güncel analiz yok` : ""}</div>
        )}
        <div className="toolbar" style={{ marginBottom: 0 }}>
          <button className="btn" onClick={() => go(l.league_id, "weekly")}>Bu Hafta</button>
          <button className="btn" onClick={() => go(l.league_id, "fa")}>Add/Drop</button>
          <button className="btn" onClick={() => go(l.league_id, "news")}>Haberler</button>
          <button className="btn" onClick={() => go(l.league_id, "season")}>Sezon</button>
        </div>
      </div>
    </div>
  );
}

/** Dört ligde kullanıcının takımı için bugünün özeti: sunucuda veri her geldiğinde bir kez hesaplanır. */
export function TodayPage({ go }: { go: Go }) {
  const [data, setData] = useState<TodayOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  const load = () => {
    api.today().then((d) => {
      setData(d); setError(null);
      if (!d.fresh || d.job.running) timer.current = window.setTimeout(load, 5000);
    }).catch((e: Error) => setError(e.message));
  };
  useEffect(() => { load(); return () => { if (timer.current) window.clearTimeout(timer.current); }; },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []);

  if (!data) return error ? <ErrorBanner error={error} /> : <Loading text="Bugünün özeti yükleniyor…" />;
  return (
    <div className="stack">
      <p className="desc">Her ligde senin takımın: bu haftanın eşleşmesi ve alım planı, kalan sezon için en iyi alım, sezon olasılıkları ve
        kadro uyarıları. Veri her geldiğinde bir kez hesaplanır{data.computed_at ? ` (son: ${fmtStamp(data.computed_at)})` : ""}.</p>
      {(!data.fresh || data.job.running) && (
        <div className="banner"><span className="spinner" /> {data.leagues.length ? "Yeni veriyle yeniden hesaplanıyor; aşağıdakiler önceki veriden." : "Hesaplanıyor (birkaç dakika)…"}
          {data.job.log.length > 0 && <span className="muted"> {data.job.log[data.job.log.length - 1]}</span>}</div>
      )}
      {data.job.error && <div className="banner err">{data.job.error}</div>}
      {data.leagues.map((l) => <LeagueCard key={l.league_id} l={l} go={go} />)}
    </div>
  );
}
