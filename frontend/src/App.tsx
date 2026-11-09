import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "./api";
import { AddDropPage } from "./pages/AddDropPage";
import { HistoryPage } from "./pages/HistoryPage";
import { NewsPage } from "./pages/NewsPage";
import { MultiTradePage } from "./pages/MultiTradePage";
import { RankingsPage } from "./pages/RankingsPage";
import { SeasonPage } from "./pages/SeasonPage";
import { SitStartPage } from "./pages/SitStartPage";
import { SuggestPage } from "./pages/SuggestPage";
import { TradePage, type TradeInit } from "./pages/TradePage";
import { WeeklyPage } from "./pages/WeeklyPage";
import { Icon, Sheet } from "./components/Mobile";
import { DataStatus } from "./components/DataStatus";
import { SyncButton } from "./components/SyncButton";
import { useIsMobile } from "./hooks";
import type { League, Meta } from "./types";

type Theme = "auto" | "light" | "dark";
type Scale = "gr" | "br";
type Tab = "trade" | "suggest" | "multi" | "weekly" | "sitstart" | "fa" | "news" | "history" | "season" | "ranks";

const TABS: { id: Tab; label: string; short: string; hint: string }[] = [
  { id: "trade", label: "Takas Analizi", short: "Takas", hint: "iki takım arası takası değerlendir" },
  { id: "suggest", label: "Takas Önerileri", short: "Öneriler", hint: "sana uygun takaslar" },
  { id: "multi", label: "Çok Takımlı Takas", short: "Çok takımlı", hint: "üç ve daha çok takımlı takas" },
  { id: "weekly", label: "Bu Hafta", short: "Bu Hafta", hint: "eşleşme ve kategori olasılıkları" },
  { id: "sitstart", label: "Sit/Start", short: "Sit/Start", hint: "her gün kim oynasın" },
  { id: "fa", label: "Add/Drop", short: "Add/Drop", hint: "kalan sezon ve bu hafta alımları" },
  { id: "news", label: "Haberler", short: "Haberler", hint: "sakatlık, rol ve takas haberleri" },
  { id: "history", label: "Performans", short: "Performans", hint: "haftalık kategori sıran" },
  { id: "season", label: "Sezon Simülasyonu", short: "Sezon", hint: "playoff ve şampiyonluk ihtimali" },
  { id: "ranks", label: "Lig Sıralamaları", short: "Sıralamalar", hint: "takımların güç sıralaması" },
];
/** Telefonda alt çubukta duranlar; diğerleri "Daha" panelinde. */
const PRIMARY: Tab[] = ["weekly", "sitstart", "fa", "news"];

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

const THEME_LABEL: Record<Theme, string> = { auto: "◐ Otomatik", light: "☀ Açık", dark: "☾ Koyu" };

export default function App() {
  const mobile = useIsMobile();
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
    if (TABS.some((t) => t.id === h)) return h;
    const last = stored<Tab | "">("tl.tab", "");
    if (last && TABS.some((t) => t.id === last)) return last;
    return window.matchMedia("(max-width: 760px)").matches ? "weekly" : "trade";
  });
  const [pending, setPending] = useState<{ trade: TradeInit; seq: number } | null>(null);
  const [version, setVersion] = useState(0);              // senkronizasyondan sonra sayfalar yeniden yüklenir
  const [sheet, setSheet] = useState<"settings" | "more" | null>(null);
  const lastSync = useRef<string | null | undefined>(undefined);

  const go = (t: Tab) => {
    setTab(t);
    setSheet(null);
    save("tl.tab", t);
    window.history.replaceState(null, "", `#${t}`);
    if (mobile) window.scrollTo({ top: 0 });
  };

  useEffect(() => {
    setError(null);
    api.meta(injuries).then(setMeta).catch((e: Error) => setError(e.message));
    api.syncStatus().then((s) => { lastSync.current = s.last_sync; }).catch(() => undefined);
  }, [injuries, version]);

  // Uygulamaya geri dönünce (telefonda arka plandan), arada zamanlanmış bir senkronizasyon olduysa yeniden yükle.
  useEffect(() => {
    const check = () => {
      if (document.hidden || lastSync.current === undefined) return;
      api.syncStatus().then((s) => {
        if (!s.running && s.last_sync !== lastSync.current) setVersion((v) => v + 1);
      }).catch(() => undefined);
    };
    document.addEventListener("visibilitychange", check);
    return () => document.removeEventListener("visibilitychange", check);
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "auto") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    root.setAttribute("data-scale", scale);
    save("tl.theme", theme);
    save("tl.scale", scale);
    // Telefonun durum çubuğu rengi üst çubukla aynı olsun.
    const metas = document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]');
    metas.forEach((m) => {
      const dark = m.media.includes("dark");
      m.content = theme === "auto" ? (dark ? "#161a20" : "#ffffff") : theme === "dark" ? "#161a20" : "#ffffff";
    });
  }, [theme, scale]);

  if (error && !meta) {
    const offline = /fetch|network|load failed/i.test(error);
    return (
      <main>
        <div className="banner err">
          {offline ? "Sunucuya ulaşılamadı: bilgisayar açık mı, uygulama çalışıyor mu, Tailscale bağlı mı?" : `Veri yüklenemedi: ${error}`}
        </div>
        <button className="btn primary" onClick={() => setVersion((v) => v + 1)}>Yeniden dene</button>
      </main>
    );
  }
  if (!meta) return <main><div className="empty"><span className="spinner" /> Ligler yükleniyor…</div></main>;

  const league = meta.leagues.find((l) => l.id === leagueId) ?? meta.leagues[0];
  const team = teamByLeague[league.id] && league.teams.some((t) => t.id === teamByLeague[league.id])
    ? teamByLeague[league.id] : league.default_team;
  const teamName = league.teams.find((t) => t.id === team)?.name ?? team;
  const current = TABS.find((t) => t.id === tab)!;

  const pickLeague = (id: string) => {
    setLeagueId(id);
    save("tl.league", id);
  };
  const pickTeam = (id: string) => {
    const next = { ...teamByLeague, [league.id]: id };
    setTeamByLeague(next);
    save("tl.teams", JSON.stringify(next));
  };
  const toggleInjuries = (on: boolean) => {
    setInjuries(on);
    save("tl.injuries", on ? "1" : "0");
  };
  const leagueSelect = (
    <select className="select" value={league.id} onChange={(e) => pickLeague(e.target.value)}>
      {meta.leagues.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
    </select>
  );
  const teamSelect = (
    <select className="select" value={team} onChange={(e) => pickTeam(e.target.value)}>
      {league.teams.map((t) => (
        <option key={t.id} value={t.id}>{t.name}{t.id === league.default_team ? " (sen)" : ""}</option>
      ))}
    </select>
  );
  const injuryToggle = (
    <label className="check" title={meta.injury_file ? `Kaynak: ${meta.injury_file}` : "Sakatlık raporu yok (scripts/fetch_injuries.py)"}>
      <input type="checkbox" checked={injuries} disabled={!meta.injury_file} onChange={(e) => toggleInjuries(e.target.checked)} />
      Sakatlık dönüş tarihleri
    </label>
  );
  const scaleSeg = (
    <div className="seg" role="group" aria-label="Renk skalası" title="Değer renkleri: yeşil↔kırmızı ya da renk körlüğüne uygun mavi↔kırmızı">
      <button aria-pressed={scale === "gr"} onClick={() => setScale("gr")}>Yeşil/Kırmızı</button>
      <button aria-pressed={scale === "br"} onClick={() => setScale("br")}>Mavi/Kırmızı</button>
    </div>
  );

  return (
    <>
      {mobile ? (
        <header className="m-top">
          <button className="m-ctx" onClick={() => setSheet("settings")} aria-label="Lig, takım ve ayarlar">
            <span className="brand-dot">⇄</span>
            <span className="m-ctx-text">
              <b>{current.label}</b>
              <small>{league.name} · {teamName} <Icon name="chevron" size={13} /></small>
            </span>
          </button>
          <SyncButton compact onDone={() => setVersion((v) => v + 1)} />
        </header>
      ) : (
        <>
          <header className="topbar">
            <div className="brand"><span className="brand-dot">⇄</span> Trade Lab</div>
            <label className="field"><span>Lig</span>{leagueSelect}</label>
            <label className="field"><span>Takımın</span>{teamSelect}</label>
            <span className="spacer" />
            <SyncButton onDone={() => setVersion((v) => v + 1)} />
            {injuryToggle}
            {scaleSeg}
            <button className="icon-btn" title="Tema: otomatik → açık → koyu"
                    onClick={() => setTheme(theme === "auto" ? "light" : theme === "light" ? "dark" : "auto")}>
              {THEME_LABEL[theme]}
            </button>
            <DataStatus key={version} asOf={meta.as_of} />
          </header>
          <nav className="tabs" role="tablist">
            {TABS.map((t) => (
              <button key={t.id} className="tab" role="tab" aria-selected={tab === t.id} onClick={() => go(t.id)}>
                {t.label}
              </button>
            ))}
          </nav>
        </>
      )}
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
        {tab === "fa" && <AddDropPage key={league.id + team} meta={meta} league={league} team={team} injuries={injuries} />}
        {tab === "news" && <NewsPage key={league.id + team} league={league} team={team} injuries={injuries} />}
        {tab === "history" && <HistoryPage key={league.id + team} meta={meta} league={league} team={team} injuries={injuries} />}
        {tab === "season" && <SeasonPage key={league.id + team} league={league} team={team} injuries={injuries} />}
        {tab === "ranks" && <RankingsPage meta={meta} league={league} team={team} injuries={injuries} />}
      </main>

      {mobile && (
        <nav className="m-nav" aria-label="Sayfalar">
          {PRIMARY.map((id) => {
            const t = TABS.find((x) => x.id === id)!;
            return (
              <button key={id} aria-current={tab === id ? "page" : undefined} onClick={() => go(id)}>
                <span className="m-ico"><Icon name={id} /></span>{t.short}
              </button>
            );
          })}
          <button aria-current={!PRIMARY.includes(tab) ? "page" : undefined} onClick={() => setSheet("more")}>
            <span className="m-ico"><Icon name="more" /></span>Daha
          </button>
        </nav>
      )}

      {sheet === "more" && (
        <Sheet title="Diğer sayfalar" onClose={() => setSheet(null)}>
          <div className="tiles">
            {TABS.filter((t) => !PRIMARY.includes(t.id)).map((t) => (
              <button key={t.id} className="tile" aria-current={tab === t.id ? "page" : undefined} onClick={() => go(t.id)}>
                <Icon name={t.id} />
                <span>{t.label}<small>{t.hint}</small></span>
              </button>
            ))}
          </div>
        </Sheet>
      )}
      {sheet === "settings" && (
        <SettingsSheet meta={meta} league={league} leagueSelect={leagueSelect} teamSelect={teamSelect}
                       injuryToggle={injuryToggle} scaleSeg={scaleSeg} theme={theme} setTheme={setTheme}
                       onClose={() => setSheet(null)} />
      )}
    </>
  );
}

function SettingsSheet({ meta, league, leagueSelect, teamSelect, injuryToggle, scaleSeg, theme, setTheme, onClose }: {
  meta: Meta; league: League; leagueSelect: ReactNode; teamSelect: ReactNode; injuryToggle: ReactNode;
  scaleSeg: ReactNode; theme: Theme; setTheme: (t: Theme) => void; onClose: () => void;
}) {
  return (
    <Sheet title="Lig ve ayarlar" onClose={onClose}>
      <label className="field"><span>Lig</span>{leagueSelect}</label>
      <label className="field"><span>Takımın</span>{teamSelect}</label>
      <div className="sheet-row">{injuryToggle}</div>
      <div className="field"><span>Değer renkleri</span>{scaleSeg}</div>
      <div className="field"><span>Tema</span>
        <div className="seg" role="group" aria-label="Tema">
          {(["auto", "light", "dark"] as Theme[]).map((t) => (
            <button key={t} aria-pressed={theme === t} onClick={() => setTheme(t)}>{THEME_LABEL[t]}</button>
          ))}
        </div>
      </div>
      <p className="sheet-note">Veri tarihi {meta.as_of} · {league.teams.length} takım
        {league.trade_deadline ? ` · takas son gün ${league.trade_deadline}` : ""}</p>
      <DataStatus asOf={meta.as_of} inline />
      <button className="btn block" onClick={onClose}>Tamam</button>
    </Sheet>
  );
}
