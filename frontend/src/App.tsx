import { useEffect, useState } from "react";
import { api } from "./api";
import { FreeAgentsPage } from "./pages/FreeAgentsPage";
import { MultiTradePage } from "./pages/MultiTradePage";
import { RankingsPage } from "./pages/RankingsPage";
import { SeasonPage } from "./pages/SeasonPage";
import { SitStartPage } from "./pages/SitStartPage";
import { SuggestPage } from "./pages/SuggestPage";
import { TradePage, type TradeInit } from "./pages/TradePage";
import { WeeklyPage } from "./pages/WeeklyPage";
import { SyncButton } from "./components/SyncButton";
import type { Meta } from "./types";

type Theme = "auto" | "light" | "dark";
type Scale = "gr" | "br";
type Tab = "trade" | "suggest" | "multi" | "weekly" | "sitstart" | "fa" | "season" | "ranks";

const TABS: { id: Tab; label: string }[] = [
  { id: "trade", label: "Takas Analizi" },
  { id: "suggest", label: "Takas Önerileri" },
  { id: "multi", label: "Çok Takımlı Takas" },
  { id: "weekly", label: "Bu Hafta" },
  { id: "sitstart", label: "Sit/Start" },
  { id: "fa", label: "Boştaki Oyuncular" },
  { id: "season", label: "Sezon Simülasyonu" },
  { id: "ranks", label: "Lig Sıralamaları" },
];

function stored<T extends string>(key: string, fallback: T): T {
  try {
    return (localStorage.getItem(key) as T) || fallback;
  } catch {
    return fallback;
  }
}

function save(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* özel pencere vb. */
  }
}

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [injuries, setInjuries] = useState(stored("tl.injuries", "1") === "1");
  const [leagueId, setLeagueId] = useState<string>(stored("tl.league", ""));
  const [teamByLeague, setTeamByLeague] = useState<Record<string, string>>(() => {
    try {
      return JSON.parse(localStorage.getItem("tl.teams") || "{}");
    } catch {
      return {};
    }
  });
  const [theme, setTheme] = useState<Theme>(stored("tl.theme", "auto"));
  const [scale, setScale] = useState<Scale>(stored("tl.scale", "gr"));
  const [tab, setTab] = useState<Tab>(() => {
    const h = window.location.hash.replace("#", "") as Tab;
    return TABS.some((t) => t.id === h) ? h : "trade";
  });
  const [pending, setPending] = useState<{ trade: TradeInit; seq: number } | null>(null);
  const [version, setVersion] = useState(0);              // senkronizasyondan sonra sayfalar yeniden yüklenir

  const go = (t: Tab) => {
    setTab(t);
    window.history.replaceState(null, "", `#${t}`);
  };

  useEffect(() => {
    api.meta(injuries).then(setMeta).catch((e: Error) => setError(e.message));
  }, [injuries, version]);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "auto") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    root.setAttribute("data-scale", scale);
    save("tl.theme", theme);
    save("tl.scale", scale);
  }, [theme, scale]);

  if (error) return <main><div className="banner err">Veri yüklenemedi: {error}</div></main>;
  if (!meta) return <main><div className="empty"><span className="spinner" /> Ligler yükleniyor…</div></main>;

  const league = meta.leagues.find((l) => l.id === leagueId) ?? meta.leagues[0];
  const team = teamByLeague[league.id] && league.teams.some((t) => t.id === teamByLeague[league.id])
    ? teamByLeague[league.id] : league.default_team;

  const pickLeague = (id: string) => {
    setLeagueId(id);
    save("tl.league", id);
  };
  const pickTeam = (id: string) => {
    const next = { ...teamByLeague, [league.id]: id };
    setTeamByLeague(next);
    save("tl.teams", JSON.stringify(next));
  };

  return (
    <>
      <header className="topbar">
        <div className="brand"><span className="brand-dot">⇄</span> Trade Lab</div>
        <label className="field"><span>Lig</span>
          <select className="select" value={league.id} onChange={(e) => pickLeague(e.target.value)}>
            {meta.leagues.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        </label>
        <label className="field"><span>Takımın</span>
          <select className="select" value={team} onChange={(e) => pickTeam(e.target.value)}>
            {league.teams.map((t) => (
              <option key={t.id} value={t.id}>{t.name}{t.id === league.default_team ? " (sen)" : ""}</option>
            ))}
          </select>
        </label>
        <span className="spacer" />
        <SyncButton onDone={() => setVersion((v) => v + 1)} />
        <label className="check" title={meta.injury_file ? `Kaynak: ${meta.injury_file}` : "Sakatlık raporu yok (scripts/fetch_injuries.py)"}>
          <input type="checkbox" checked={injuries} disabled={!meta.injury_file}
                 onChange={(e) => { setInjuries(e.target.checked); save("tl.injuries", e.target.checked ? "1" : "0"); }} />
          Sakatlık dönüş tarihleri
        </label>
        <div className="seg" role="group" aria-label="Renk skalası" title="Değer renkleri: yeşil↔kırmızı ya da renk körlüğüne uygun mavi↔kırmızı">
          <button aria-pressed={scale === "gr"} onClick={() => setScale("gr")}>Yeşil/Kırmızı</button>
          <button aria-pressed={scale === "br"} onClick={() => setScale("br")}>Mavi/Kırmızı</button>
        </div>
        <button className="icon-btn" title="Tema: otomatik → açık → koyu"
                onClick={() => setTheme(theme === "auto" ? "light" : theme === "light" ? "dark" : "auto")}>
          {theme === "auto" ? "◐ Otomatik" : theme === "light" ? "☀ Açık" : "☾ Koyu"}
        </button>
        <span className="muted" style={{ fontSize: 12 }}>Veri: {meta.as_of}</span>
      </header>
      <nav className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.id} className="tab" role="tab" aria-selected={tab === t.id} onClick={() => go(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>
      <main key={version}>
        {tab === "trade" && (
          <TradePage key={`${league.id}-${team}-${pending?.seq ?? 0}`} meta={meta} league={league} team={team}
                     injuries={injuries} initial={pending?.trade ?? null} />
        )}
        {tab === "suggest" && (
          <SuggestPage key={league.id + team} meta={meta} league={league} team={team} injuries={injuries}
                       onOpen={(trade) => { setPending({ trade, seq: (pending?.seq ?? 0) + 1 }); go("trade"); }} />
        )}
        {tab === "multi" && <MultiTradePage key={league.id + team} meta={meta} league={league} team={team} injuries={injuries} />}
        {tab === "weekly" && <WeeklyPage key={league.id + team} meta={meta} league={league} team={team} injuries={injuries} />}
        {tab === "sitstart" && <SitStartPage key={league.id + team} meta={meta} league={league} team={team} injuries={injuries} />}
        {tab === "fa" && <FreeAgentsPage key={league.id + team} meta={meta} league={league} team={team} injuries={injuries} />}
        {tab === "season" && <SeasonPage key={league.id + team} league={league} team={team} injuries={injuries} />}
        {tab === "ranks" && <RankingsPage meta={meta} league={league} team={team} injuries={injuries} />}
      </main>
    </>
  );
}
