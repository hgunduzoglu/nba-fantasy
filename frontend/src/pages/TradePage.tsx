import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../api";
import { CategoryImpact } from "../components/CategoryImpact";
import { RosterTable } from "../components/RosterTable";
import { fmtDelta, fmtNum, fmtPct, fmtStat } from "../format";
import type { League, Meta, Player, Roster, SeasonOut, Source, StrategyIn, TradeIn, TradeOut, TradeSide } from "../types";

interface Props {
  meta: Meta;
  league: League;
  team: string;
  injuries: boolean;
}

const MODE_ORDER = ["remaining_games_projection", "season_total", "preseason"];

function toggle(set: Set<string>, id: string): Set<string> {
  const next = new Set(set);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

function strategyIn(name: string): StrategyIn | null {
  return name ? { preset: name } : null;
}

function useRoster(league: string, team: string, source: Source, injuries: boolean) {
  const [state, setState] = useState<{ data: Roster | null; loading: boolean; error: string | null }>({
    data: null, loading: true, error: null,
  });
  useEffect(() => {
    let live = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    api.roster(league, team, source, injuries)
      .then((data) => live && setState({ data, loading: false, error: null }))
      .catch((e: Error) => live && setState({ data: null, loading: false, error: e.message }));
    return () => {
      live = false;
    };
  }, [league, team, source, injuries]);
  return state;
}

function Metric({ k, before, after, delta, fmt, dfmt }: {
  k: string; before: number; after: number; delta: number;
  fmt: (v: number) => string; dfmt: (v: number) => string;
}) {
  return (
    <div className="metric" title={`Önce ${fmt(before)} → sonra ${fmt(after)}`}>
      <div className="k">{k}</div>
      <div className="v num">{fmt(after)}</div>
      <div className={"d num " + (delta > 1e-9 ? "good" : delta < -1e-9 ? "bad" : "muted")}>
        {dfmt(delta)} <span className="muted" style={{ fontWeight: 400 }}>· önce {fmt(before)}</span>
      </div>
    </div>
  );
}

function SideCard({ side, title, scale }: { side: TradeSide; title: string; scale: number }) {
  const adj = side.adjustments;
  const moves = [
    ...adj.move_to_il.map((x) => `${x.name} → IL`),
    ...adj.drop.map((x) => `${x.name} bırakılır`),
    ...adj.add.map((x) => `${x.name} boştan alınır`),
  ];
  return (
    <div className="card">
      <div className="card-h">
        <h3>{side.team}</h3>
        <span className="muted">{title} · strateji: {side.strategy}</span>
      </div>
      <div className="card-b">
        <div className="metrics">
          <Metric k="Beklenen kategori / hafta" before={side.ecw_before} after={side.ecw_after} delta={side.ecw_delta}
                  fmt={(v) => fmtNum(v, 2)} dfmt={(v) => fmtDelta(v, 3)} />
          <Metric k="Haftayı kazanma P(5+)" before={side.win_before} after={side.win_after} delta={side.win_delta}
                  fmt={(v) => fmtPct(v, 1)} dfmt={(v) => fmtDelta(v * 100, 1, " puan")} />
          <Metric k="Stratejiye göre puan" before={side.strategy_before} after={side.strategy_after}
                  delta={side.strategy_delta} fmt={(v) => fmtNum(v, 2)} dfmt={(v) => fmtDelta(v, 3)} />
        </div>
        <div className="section-title">Kategori kazanma olasılığı değişimi (puan)</div>
        <CategoryImpact rows={side.categories} scale={scale} />
        {moves.length > 0 && (
          <>
            <div className="section-title">Kadro işlemleri</div>
            <div>{moves.map((m) => <span key={m} className="pill" style={{ marginRight: 6 }}>{m}</span>)}</div>
          </>
        )}
      </div>
    </div>
  );
}

export function TradePage({ meta, league, team, injuries }: Props) {
  const others = league.teams.filter((t) => t.id !== team);
  const [opp, setOpp] = useState<string>(others[0]?.id ?? "");
  const [source, setSource] = useState<Source>("ros");
  const [stratA, setStratA] = useState("");
  const [stratB, setStratB] = useState("");
  const [auto, setAuto] = useState(true);
  const [giveA, setGiveA] = useState<Set<string>>(new Set());
  const [giveB, setGiveB] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<TradeOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [season, setSeason] = useState<SeasonOut | null>(null);
  const [seasonBusy, setSeasonBusy] = useState(false);
  const [mode, setMode] = useState(MODE_ORDER[0]);
  const seq = useRef(0);

  useEffect(() => {
    if (!others.some((t) => t.id === opp)) setOpp(others[0]?.id ?? "");
    setGiveA(new Set());
  }, [league.id, team]);
  useEffect(() => setGiveB(new Set()), [opp, league.id]);

  const mine = useRoster(league.id, team, source, injuries);
  const theirs = useRoster(league.id, opp, source, injuries);

  const body: TradeIn | null = useMemo(() => {
    if (!giveA.size || !giveB.size) return null;
    return { team_a: team, team_b: opp, give_a: [...giveA], give_b: [...giveB], auto_balance: auto,
             strategy_a: strategyIn(stratA), strategy_b: strategyIn(stratB), injuries };
  }, [team, opp, giveA, giveB, auto, stratA, stratB, injuries]);

  useEffect(() => {
    setSeason(null);
    if (!body) {
      setResult(null);
      setError(null);
      return;
    }
    const id = ++seq.current;
    setBusy(true);
    const t = setTimeout(() => {
      api.analyze(league.id, body)
        .then((r) => { if (id === seq.current) { setResult(r); setError(null); } })
        .catch((e: Error) => { if (id === seq.current) { setResult(null); setError(e.message); } })
        .finally(() => { if (id === seq.current) setBusy(false); });
    }, 200);
    return () => clearTimeout(t);
  }, [body, league.id]);

  const runSeason = () => {
    if (!body) return;
    setSeasonBusy(true);
    api.season(league.id, { ...body, n_sims: 2000 })
      .then(setSeason)
      .catch((e: ApiError) => setError(e.message))
      .finally(() => setSeasonBusy(false));
  };

  const byId = useMemo(() => {
    const m = new Map<string, Player>();
    [...(mine.data?.players ?? []), ...(theirs.data?.players ?? [])].forEach((p) => m.set(p.id, p));
    return m;
  }, [mine.data, theirs.data]);
  const teamName = (id: string) => league.teams.find((t) => t.id === id)?.name ?? id;
  // iki takımın kategori grafikleri aynı ölçekte (yan yana karşılaştırma yanıltmasın)
  const impactScale = useMemo(() => {
    if (!result) return 5;
    const ds = [...result.teams.a.categories, ...result.teams.b.categories].map((c) => Math.abs(c.after - c.before) * 100);
    return Math.max(5, ...ds);
  }, [result]);

  return (
    <>
      <div className="toolbar">
        <label className="field"><span>Karşı takım</span>
          <select className="select" value={opp} onChange={(e) => setOpp(e.target.value)}>
            {others.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </label>
        <div className="field"><span>İstatistik</span>
          <div className="seg" role="group" aria-label="İstatistik kaynağı">
            {(Object.keys(meta.sources) as Source[]).map((s) => (
              <button key={s} aria-pressed={source === s} onClick={() => setSource(s)}>
                {s === "ros" ? "Kalan sezon" : s === "season" ? "Bu sezon" : "Sezon öncesi"}
              </button>
            ))}
          </div>
        </div>
        <label className="field"><span>Senin stratejin</span>
          <select className="select" value={stratA} onChange={(e) => setStratA(e.target.value)}>
            <option value="">Dengeli</option>
            {meta.presets.filter((p) => p.name !== "Dengeli").map((p) => <option key={p.name}>{p.name}</option>)}
          </select>
        </label>
        <label className="field"><span>Rakibin stratejisi</span>
          <select className="select" value={stratB} onChange={(e) => setStratB(e.target.value)}>
            <option value="">Dengeli</option>
            {meta.presets.filter((p) => p.name !== "Dengeli").map((p) => <option key={p.name}>{p.name}</option>)}
          </select>
        </label>
        <label className="check" title="Eşit olmayan paketlerde önce sakat oyuncu IL'e, sonra gerekirse en düşük değerli bırakılır; açılan boşluk boştaki oyuncuyla doldurulur.">
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
          Kadroyu otomatik dengele
        </label>
      </div>

      <div className="grid-2">
        <RosterTable title={teamName(team)} subtitle={giveA.size ? `${giveA.size} oyuncu veriyorsun` : "veriyorsun"}
                     players={mine.data?.players ?? null} categories={meta.categories} selected={giveA}
                     onToggle={(id) => setGiveA((s) => toggle(s, id))} loading={mine.loading} error={mine.error} />
        <RosterTable title={teamName(opp)} subtitle={giveB.size ? `${giveB.size} oyuncu alıyorsun` : "alıyorsun"}
                     players={theirs.data?.players ?? null} categories={meta.categories} selected={giveB}
                     onToggle={(id) => setGiveB((s) => toggle(s, id))} loading={theirs.loading} error={theirs.error} />
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-h">
          <h2>Takas özeti</h2>
          {busy && <span className="spinner" aria-label="hesaplanıyor" />}
          <span className="spacer" style={{ flex: 1 }} />
          {(giveA.size > 0 || giveB.size > 0) && (
            <button className="btn" onClick={() => { setGiveA(new Set()); setGiveB(new Set()); }}>Temizle</button>
          )}
        </div>
        <div className="card-b">
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
            <div><div className="section-title" style={{ marginTop: 0 }}>Veriyorsun</div>
              {[...giveA].map((id) => (
                <span key={id} className="chip">{byId.get(id)?.name ?? id}
                  <button aria-label="çıkar" onClick={() => setGiveA((s) => toggle(s, id))}>×</button></span>
              ))}
              {!giveA.size && <span className="muted">Soldaki kadrodan oyuncu seç</span>}
            </div>
            <div><div className="section-title" style={{ marginTop: 0 }}>Alıyorsun</div>
              {[...giveB].map((id) => (
                <span key={id} className="chip">{byId.get(id)?.name ?? id}
                  <button aria-label="çıkar" onClick={() => setGiveB((s) => toggle(s, id))}>×</button></span>
              ))}
              {!giveB.size && <span className="muted">Sağdaki kadrodan oyuncu seç</span>}
            </div>
          </div>

          {error && <div className="banner err" style={{ marginTop: 14 }}>{error}</div>}

          {result && (
            <>
              <div className="verdict">
                <span className={"pill " + (result.assessments.mutual_benefit ? "okay" : "warn")}>
                  {result.assessments.mutual_benefit ? "✓ İki taraf da kazanıyor (seçilen stratejilerle)" : "✕ İki taraf birden kazanmıyor"}
                </span>
                <span className="pill" title="Kalan sezon piyasa değerine göre küçük paket / büyük paket">
                  Değer dengesi {fmtPct(result.fairness)}
                </span>
                {result.perceived_balance !== null && (
                  <span className="pill" title="Rakibin gözünden (bu sezon + isim değeri): aldığı / verdiği. 1 = eşit görür.">
                    Rakibin gözünde {fmtNum(result.perceived_balance, 2)}
                  </span>
                )}
                <span className="pill" title={`İnceleme: ${result.assessments.review_type} · ${result.assessments.review_time}`}>
                  Komisyon riski: {result.assessments.commissioner_risk}
                </span>
                {result.assessments.deadline && <span className="pill">Son takas tarihi {result.assessments.deadline}</span>}
              </div>

              <div className="summary-grid">
                <SideCard side={result.teams.a} title="sen" scale={impactScale} />
                <SideCard side={result.teams.b} title="karşı taraf" scale={impactScale} />
              </div>

              <div className="section-title">Playoff ve şampiyonluk etkisi</div>
              {!season && (
                <button className="btn primary" onClick={runSeason} disabled={seasonBusy}>
                  {seasonBusy ? <><span className="spinner" /> Simüle ediliyor…</> : "Sezon etkisini hesapla"}
                </button>
              )}
              {season && (
                <table className="mini" style={{ maxWidth: 720 }}>
                  <thead><tr><th className="l">Takım</th><th>Playoff</th><th>Fark</th><th>Şampiyonluk</th><th>Fark</th><th>Ort. sıra</th></tr></thead>
                  <tbody>
                    {(["a", "b"] as const).map((k) => {
                      const s = season.teams[k];
                      const dp = s.playoff_after - s.playoff_before;
                      const dc = s.champion_after - s.champion_before;
                      return (
                        <tr key={k}>
                          <td className="l">{teamName(s.team_id)}</td>
                          <td>{fmtPct(s.playoff_before)} → {fmtPct(s.playoff_after)}</td>
                          <td className={dp > 0.005 ? "good" : dp < -0.005 ? "bad" : ""}>{fmtDelta(dp * 100, 1)}</td>
                          <td>{fmtPct(s.champion_before, 1)} → {fmtPct(s.champion_after, 1)}</td>
                          <td className={dc > 0.005 ? "good" : dc < -0.005 ? "bad" : ""}>{fmtDelta(dc * 100, 1)}</td>
                          <td>{fmtNum(s.seed_before)} → {fmtNum(s.seed_after)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
              {season && <p className="muted" style={{ fontSize: 12 }}>{season.n_sims} simülasyon · takım gücü belirsizliği ±%{(season.strength_sd * 100).toFixed(0)} · aynı çekilişlerle takassız/takaslı karşılaştırma. Olasılıklar kalibre edilmedi.</p>}

              <div className="section-title">Lig sıralamasında kategori değişimi</div>
              <div className="seg" role="group" style={{ marginBottom: 10 }}>
                {MODE_ORDER.map((m) => (
                  <button key={m} aria-pressed={mode === m} onClick={() => setMode(m)}>{result.modes[m]}</button>
                ))}
              </div>
              <div className="summary-grid">
                {(["a", "b"] as const).map((k) => (
                  <table key={k} className="mini">
                    <thead><tr><th className="l">{result.teams[k].team}</th><th>Önce</th><th>Sonra</th><th>Sıra</th></tr></thead>
                    <tbody>
                      {result.teams[k].ranks[mode].map((r) => {
                        const gain = (r.rank_before ?? 0) - (r.rank_after ?? 0);
                        const pct = r.key === "FG_PCT" || r.key === "FT_PCT";
                        return (
                          <tr key={r.key}>
                            <td className="l">{r.label}</td>
                            <td>{pct ? fmtStat(r.key, r.value_before) : fmtNum(r.value_before, 0)}</td>
                            <td>{pct ? fmtStat(r.key, r.value_after) : fmtNum(r.value_after, 0)}</td>
                            <td className={gain > 0 ? "good" : gain < 0 ? "bad" : ""}>
                              {fmtNum(r.rank_before, 0)} → {fmtNum(r.rank_after, 0)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                ))}
              </div>

              <details style={{ marginTop: 14 }}>
                <summary>Varsayımlar ve notlar</summary>
                <ul className="muted">{result.notes.map((n) => <li key={n}>{n}</li>)}</ul>
              </details>
            </>
          )}
          {!result && !error && giveA.size > 0 && giveB.size > 0 && busy && <div className="empty">Hesaplanıyor…</div>}
        </div>
      </div>
    </>
  );
}
