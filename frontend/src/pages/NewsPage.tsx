import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { ErrorBanner, Loading } from "../components/common";
import { fmtDate, fmtDelta, fmtStamp } from "../format";
import { useIsMobile } from "../hooks";
import type { League, NewsEvent, NewsOut, NewsPerson, NewsStatus } from "../types";

interface Props {
  league: League;
  team: string;
  injuries: boolean;
}

type Filter = "mine" | "opp" | "fa" | "all";

const TYPE_LABEL: Record<string, string> = {
  injury: "Sakatlık", return: "Dönüş", role_up: "Rol ↑", role_down: "Rol ↓", lineup: "Rotasyon", trade: "Takas",
  trade_rumor: "Takas söylentisi", signing: "İmza", waived: "Serbest bırakıldı", suspension: "Ceza", rest: "Dinlenme",
  performance: "Performans", other: "Diğer",
};
const STATUS_LABEL: Record<string, string> = {
  out: "oynamaz", doubtful: "zayıf ihtimal", questionable: "şüpheli", probable: "muhtemelen oynar", available: "oynar",
};

function ago(iso: string): string {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (!Number.isFinite(mins)) return "";
  if (mins < 60) return `${Math.max(1, mins)} dk önce`;
  if (mins < 48 * 60) return `${Math.round(mins / 60)} sa önce`;
  return fmtStamp(iso);
}

function Owner({ p }: { p: NewsPerson }) {
  if (p.owner === "me") return <span className="badge mine" title="Senin kadronda">Senin</span>;
  if (p.owner === "opp") return <span className="badge opp" title="Bu haftaki rakibinin kadrosunda">Rakip</span>;
  if (p.owner === "FA") return <span className="badge fa" title="Serbest oyuncu: hemen alınabilir">FA</span>;
  if (p.owner === "W") return <span className="badge w" title="Waiver'da">W{p.waiver_until ? ` → ${fmtDate(p.waiver_until)}` : ""}</span>;
  if (p.owner === "team") return <span className="psub" title={p.owner_name ?? ""}> · {p.owner_name}</span>;
  return null;
}

function Person({ p, dir }: { p: NewsPerson; dir?: "up" | "down" }) {
  return (
    <span className={"person " + (dir ?? "")}>
      {dir === "up" ? "▲ " : dir === "down" ? "▼ " : ""}<span className="pname">{p.name}</span><Owner p={p} />
    </span>
  );
}

function EventCard({ e }: { e: NewsEvent }) {
  const tone = e.impact == null ? "" : e.impact > 0 ? "good" : e.impact < 0 ? "bad" : "";
  return (
    <li className="news-item">
      <div className="news-meta">
        <span className="muted">{ago(e.published)}</span>
        {e.type && <span className={"badge type-" + e.type}>{TYPE_LABEL[e.type] ?? e.type}</span>}
        {e.status && STATUS_LABEL[e.status] && <span className="muted">{STATUS_LABEL[e.status]}</span>}
        {e.return_estimate && <span className="muted">· dönüş ~{fmtDate(e.return_estimate)}</span>}
        {e.games_out != null && e.games_out > 0 && <span className="muted">· ~{e.games_out} maç</span>}
        <span className="spacer" />
        <a className="muted" href={e.url} target="_blank" rel="noreferrer">{e.source === "cbs" ? "RotoWire/CBS" : "ESPN"} ↗</a>
      </div>
      <div className="news-head">
        {e.player && <><Person p={e.player} />{e.impact != null && e.impact !== 0 && <span className={tone}> {e.impact > 0 ? "▲" : "▼"}</span>} — </>}
        <span className={e.analyzed ? "" : "muted"}>{e.summary ?? e.headline}</span>
      </div>
      {(e.beneficiaries.length > 0 || e.hurt.length > 0) && (
        <div className="news-people">
          {e.beneficiaries.map((p) => <Person key={"b" + p.name} p={p} dir="up" />)}
          {e.hurt.map((p) => <Person key={"h" + p.name} p={p} dir="down" />)}
        </div>
      )}
      {e.analyzed && (
        <details className="news-src"><summary className="muted">Kaynak metin</summary>
          <p><b>{e.headline}</b> {e.body}</p></details>
      )}
    </li>
  );
}

export function NewsPage({ league, team, injuries }: Props) {
  const mobile = useIsMobile();
  const [filter, setFilter] = useState<Filter>("mine");
  const [data, setData] = useState<NewsOut | null>(null);
  const [status, setStatus] = useState<NewsStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    api.news(league.id, team, injuries).then((d) => { setData(d); setError(null); })
      .catch((e: Error) => setError(e.message));
  }, [league.id, team, injuries, version]);

  const poll = () => {
    api.newsStatus().then((s) => {
      setStatus(s);
      if (s.running) timer.current = window.setTimeout(poll, 2000);
      else if (s.result) setVersion((v) => v + 1);
    }).catch(() => undefined);
  };
  useEffect(() => {
    api.newsStatus().then((s) => { setStatus(s); if (s.running) poll(); }).catch(() => undefined);
    return () => { if (timer.current) window.clearTimeout(timer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const refresh = () => api.newsRefresh().then((s) => { setStatus(s); poll(); }).catch((e: Error) => setError(e.message));

  if (!data && !error) return <Loading text="Haberler yükleniyor…" />;
  if (!data) return <ErrorBanner error={error} />;
  const pick = (tags: string[]) => filter === "all" || tags.includes(filter);
  const events = data.events.filter((e) => pick(e.tags));
  const roleOwners: Record<Filter, string[]> = { mine: ["me"], opp: ["opp"], fa: ["FA", "W"], all: ["me", "opp", "FA", "W"] };
  const roles = data.roles.filter((r) => roleOwners[filter].includes(r.player.owner ?? ""));
  const counts = (f: Filter) => data.events.filter((e) => f === "all" || e.tags.includes(f)).length;

  return (
    <div className="stack">
      <p className="desc">RotoWire (CBS) oyuncu notları ve ESPN haberleri, Claude ile özetlenip lige göre etiketlenir: kimin oynamadığı,
        ne zaman döneceği, yerine kimin süre alacağı. Altta, bu sezonun maç kayıtlarından ölçülen rol değişimleri.</p>
      <div className="toolbar" style={{ marginBottom: 0 }}>
        <div className="seg" role="group" aria-label="Haber filtresi">
          <button aria-pressed={filter === "mine"} onClick={() => setFilter("mine")}>{mobile ? "Senin" : "Senin için"} ({counts("mine")})</button>
          <button aria-pressed={filter === "opp"} onClick={() => setFilter("opp")}>Rakibin{!mobile && data.opponent_name ? `: ${data.opponent_name}` : ""} ({counts("opp")})</button>
          <button aria-pressed={filter === "fa"} onClick={() => setFilter("fa")}>{mobile ? "Fırsatlar" : "Boştaki fırsatlar"} ({counts("fa")})</button>
          <button aria-pressed={filter === "all"} onClick={() => setFilter("all")}>Tümü ({counts("all")})</button>
        </div>
        <span className="spacer" />
        {status && (
          <span className="muted" style={{ fontSize: 12 }}>
            Son yenileme {status.fetched_at ? fmtStamp(status.fetched_at) : "yok"} · {status.analyzed}/{status.items} analiz
            {mobile ? "" : ` · ${status.model}`} · son 7 gün ~${status.cost_7d.toFixed(2)}
          </span>
        )}
        <button className="btn" onClick={refresh} disabled={status?.running || !status?.has_key}
                title={status?.has_key ? "CBS ve ESPN'den yeni haberleri çek ve analiz et" : "ANTHROPIC_API_KEY yok (.env)"}>
          {status?.running ? <><span className="spinner" /> Yenileniyor…</> : "↻ Haberleri yenile"}
        </button>
      </div>
      {status?.error && <div className="banner err">{status.error}</div>}
      <ErrorBanner error={error} />

      <div className="card">
        <div className="card-h"><h3>Haberler</h3><span className="muted">son 7 gün · ▲ süre/rol kazanır · ▼ kaybeder</span></div>
        <ul className="news-list">
          {events.map((e) => <EventCard key={e.id} e={e} />)}
          {!events.length && <li className="empty">Bu filtrede haber yok.</li>}
        </ul>
      </div>

      <div className="card">
        <div className="card-h"><h3>Rol değişimleri</h3>
          <span className="muted">şu an oynamayan önemli takım arkadaşı yokken bu sezon maç başı fark (az maça göre küçültülmüş); Sit/Start ve Add/Drop bunu kullanır</span></div>
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th className="l">Oyuncu</th><th className="l">Yokken</th><th title="Bu güne kadar geçerli">Geçerli</th>
              <th title="Yokken / varken oynadığı maç">Maç</th><th>Dakika</th><th>Sayı</th><th>Ribaund</th><th>Asist</th>
              <th>Top çalma</th><th>Blok</th><th>3PM</th></tr></thead>
            <tbody>
              {roles.map((r) => (
                <tr key={r.player.id ?? r.player.name}>
                  <td className="l"><Person p={r.player} /> <span className="psub">{r.team}</span></td>
                  <td className="l">{r.absent.join(", ")}</td>
                  <td>{r.until ? fmtDate(r.until) : "sezon"}</td>
                  <td>{r.n_without}/{r.n_with}</td>
                  {(["minutes", "pts", "reb", "ast", "stl", "blk", "fg3m"] as const).map((k) => (
                    <td key={k} className={r.delta[k] > 0.05 ? "good" : r.delta[k] < -0.05 ? "bad" : "muted"}>{fmtDelta(r.delta[k], 1)}</td>
                  ))}
                </tr>
              ))}
              {!roles.length && <tr><td colSpan={11} className="empty">Bu filtrede rol değişimi yok.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
