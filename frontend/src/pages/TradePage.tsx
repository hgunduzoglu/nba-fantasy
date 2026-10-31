import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../api";
import { CategoryImpact } from "../components/CategoryImpact";
import { PlayerPicker } from "../components/PlayerPicker";
import { RosterTable } from "../components/RosterTable";
import { BALANCED, StrategyPicker, strategyLabel, toStrategyIn, type StrategyChoice } from "../components/StrategyPicker";
import { deltaClass } from "../components/common";
import { fmtDelta, fmtNum, fmtPct, fmtStat } from "../format";
import { downloadJson, useScenarios, type NamedId, type Scenario } from "../scenarios";
import type { League, Meta, Player, Roster, SeasonOut, Source, TradeIn, TradeOut, TradeSide } from "../types";

export interface TradeInit {
  opp: string;
  giveA: string[];
  giveB: string[];
  dropA?: string[];
  dropB?: string[];
  addA?: string[];
  addB?: string[];
  stratA?: StrategyChoice;
  stratB?: StrategyChoice;
  auto?: boolean;
}

interface Props {
  meta: Meta;
  league: League;
  team: string;
  injuries: boolean;
  /** Takas Önerileri'nden ya da kayıtlı senaryodan: rakip, seçili oyuncular, işlemler ve stratejiler. */
  initial?: TradeInit | null;
}

const MODE_ORDER = ["remaining_games_projection", "season_total", "preseason"];

function toggle(set: Set<string>, id: string): Set<string> {
  const next = new Set(set);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

function hash(s: string): string {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
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

export function Metric({ k, before, after, delta, fmt, dfmt }: {
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

/** Bir takım için elle kadro işlemleri: kadrodan bırak, boştan al. */
export function MovesEditor({ title, roster, give, drops, adds, freeAgents, taken, onDrop, onAdd, name }: {
  title: string; roster: Player[]; give: Set<string>; drops: string[]; adds: string[]; freeAgents: Player[];
  taken: Set<string>; onDrop: (ids: string[]) => void; onAdd: (ids: string[]) => void; name: (id: string) => string;
}) {
  const droppable = roster.filter((p) => !give.has(p.id) && !drops.includes(p.id));
  return (
    <div>
      <div className="pname" style={{ marginBottom: 4 }}>{title}</div>
      <div className="move-row">
        <span className="lbl">Bırak</span>
        {drops.map((id) => (
          <span key={id} className="chip drop">{name(id)}<button aria-label="geri al" onClick={() => onDrop(drops.filter((x) => x !== id))}>×</button></span>
        ))}
        <select className="select" value="" onChange={(e) => e.target.value && onDrop([...drops, e.target.value])} style={{ minWidth: 200 }}>
          <option value="">Kadrodan seç…</option>
          {droppable.map((p) => <option key={p.id} value={p.id}>{p.name}{p.il ? " (IL)" : ""} · değer {fmtNum(p.value)}</option>)}
        </select>
      </div>
      <div className="move-row">
        <span className="lbl">Boştan al</span>
        {adds.map((id) => (
          <span key={id} className="chip add">{name(id)}<button aria-label="çıkar" onClick={() => onAdd(adds.filter((x) => x !== id))}>×</button></span>
        ))}
        <PlayerPicker players={freeAgents} exclude={taken} onPick={(p) => onAdd([...adds, p.id])} placeholder="Boştaki oyuncu ara…" />
      </div>
    </div>
  );
}

function ScenarioPanel({ list, team, onOpen, onRemove, onImport }: {
  list: Scenario[]; team: string; onOpen: (s: Scenario) => void; onRemove: (id: string) => void;
  onImport: (items: Scenario[]) => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const best = list.length ? Math.max(...list.map((s) => s.metrics.a.ecw_delta)) : 0;
  const names = (xs: NamedId[]) => xs.map((x) => x.name).join(", ");
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-h">
        <h2>Kayıtlı senaryolar</h2>
        <span className="muted">{list.length} senaryo · bu tarayıcıda saklanır</span>
        <span style={{ flex: 1 }} />
        <button className="btn" disabled={!list.length} onClick={() => downloadJson("takas_senaryolari.json", list)}>Dışa aktar</button>
        <button className="btn" onClick={() => fileRef.current?.click()}>İçe aktar</button>
        <input ref={fileRef} type="file" accept="application/json" hidden onChange={(e) => {
          const f = e.target.files?.[0];
          if (!f) return;
          f.text().then((t) => { try { const v = JSON.parse(t); if (Array.isArray(v)) onImport(v); } catch { /* geçersiz dosya */ } });
          e.target.value = "";
        }} />
      </div>
      {!list.length ? (
        <div className="empty">Bir takası analiz edip "Senaryoyu kaydet" ile buraya ekle; kayıtlar yan yana karşılaştırılır.</div>
      ) : (
        <div className="table-wrap">
          <table className="data">
            <thead><tr>
              <th className="l">Rakip</th><th className="l">Veriyorsun</th><th className="l">Alıyorsun</th><th className="l">Ek işlemler</th>
              <th className="l">Stratejiler (sen / rakip)</th>
              <th title="Rakip başına haftalık beklenen kategori (ağırlıksız)">Sen ΔECW</th>
              <th title="Senin stratejine göre (ağırlıklı) puan değişimi">Sen strateji Δ</th><th>Sen ΔP(5+)</th><th>Rakip ΔECW</th>
              <th>Değer dengesi</th><th>Rakibin gözünde</th><th>Playoff</th><th>Şampiyonluk</th><th />
            </tr></thead>
            <tbody>
              {list.map((s) => {
                const extra = [...s.dropA.map((x) => `−${x.name}`), ...s.addA.map((x) => `+${x.name}`),
                               ...s.dropB.map((x) => `rakip −${x.name}`), ...s.addB.map((x) => `rakip +${x.name}`)].join(", ");
                return (
                  <tr key={s.id}>
                    <td className="l">{s.oppName}{!s.metrics.mutual && <span className="badge out" title="İki taraf birden kazanmıyor">!</span>}</td>
                    <td className="l wrap">{names(s.giveA)}</td>
                    <td className="l wrap">{names(s.giveB)}</td>
                    <td className="l wrap muted">{extra || (s.auto ? "otomatik" : "—")}</td>
                    <td className="l wrap muted">{s.stratALabel} / {s.stratBLabel}</td>
                    <td className={deltaClass(s.metrics.a.ecw_delta, 0.3)} style={{ fontWeight: s.metrics.a.ecw_delta === best ? 700 : undefined }}>
                      {fmtDelta(s.metrics.a.ecw_delta, 3)}</td>
                    <td className={deltaClass(s.metrics.a.strategy_delta, 0.3)}>{fmtDelta(s.metrics.a.strategy_delta, 3)}</td>
                    <td>{fmtDelta(s.metrics.a.win_delta * 100, 1)}</td>
                    <td className={deltaClass(s.metrics.b.ecw_delta, 0.3)}>{fmtDelta(s.metrics.b.ecw_delta, 3)}</td>
                    <td>{fmtPct(s.metrics.fairness)}</td>
                    <td>{fmtNum(s.metrics.perceived, 2)}</td>
                    <td className={s.season ? deltaClass(s.season.me_playoff, 0.1) : "muted"}>{s.season ? fmtDelta(s.season.me_playoff * 100, 1) : "—"}</td>
                    <td className={s.season ? deltaClass(s.season.me_champion, 0.05) : "muted"}>{s.season ? fmtDelta(s.season.me_champion * 100, 1) : "—"}</td>
                    <td>
                      {s.team === team
                        ? <button className="link-btn" onClick={() => onOpen(s)}>Aç</button>
                        : <span className="muted" title="Bu senaryo başka bir takım için kaydedildi">başka takım</span>}
                      {" · "}<button className="link-btn" style={{ color: "var(--bad-ink)" }} onClick={() => onRemove(s.id)}>Sil</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="hint" style={{ padding: "0 14px 12px" }}>
        Playoff/şampiyonluk sütunları, kaydetmeden önce "Sezon etkisini hesapla" çalıştırıldıysa dolar. Değerler kaydedildiği
        andaki veriyle hesaplanmıştır; veri yenilenince senaryoyu açıp yeniden kaydet.
      </div>
    </div>
  );
}

export function TradePage({ meta, league, team, injuries, initial }: Props) {
  const others = league.teams.filter((t) => t.id !== team);
  const [opp, setOpp] = useState<string>(
    initial && others.some((t) => t.id === initial.opp) ? initial.opp : others[0]?.id ?? "");
  const [source, setSource] = useState<Source>("ros");
  const [stratA, setStratA] = useState<StrategyChoice>(initial?.stratA ?? BALANCED);
  const [stratB, setStratB] = useState<StrategyChoice>(initial?.stratB ?? BALANCED);
  const [auto, setAuto] = useState(initial?.auto ?? true);
  const [giveA, setGiveA] = useState<Set<string>>(new Set(initial?.giveA ?? []));
  const [giveB, setGiveB] = useState<Set<string>>(new Set(initial?.giveB ?? []));
  const [dropA, setDropA] = useState<string[]>(initial?.dropA ?? []);
  const [dropB, setDropB] = useState<string[]>(initial?.dropB ?? []);
  const [addA, setAddA] = useState<string[]>(initial?.addA ?? []);
  const [addB, setAddB] = useState<string[]>(initial?.addB ?? []);
  const [showMoves, setShowMoves] = useState(Boolean(initial?.dropA?.length || initial?.dropB?.length || initial?.addA?.length || initial?.addB?.length));
  const [result, setResult] = useState<TradeOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [season, setSeason] = useState<SeasonOut | null>(null);
  const [seasonBusy, setSeasonBusy] = useState(false);
  const [mode, setMode] = useState(MODE_ORDER[0]);
  const [fa, setFa] = useState<Player[]>([]);
  const [savedId, setSavedId] = useState<string | null>(null);
  const seq = useRef(0);
  const scenarios = useScenarios();

  const mine = useRoster(league.id, team, source, injuries);
  const theirs = useRoster(league.id, opp, source, injuries);

  useEffect(() => {
    api.freeAgents(league.id, source, injuries).then((r) => setFa(r.players)).catch(() => setFa([]));
  }, [league.id, source, injuries]);

  const body: TradeIn | null = useMemo(() => {
    if (!giveA.size || !giveB.size) return null;
    return { team_a: team, team_b: opp, give_a: [...giveA], give_b: [...giveB], drop_a: dropA, drop_b: dropB,
             add_a: addA, add_b: addB, auto_balance: auto, strategy_a: toStrategyIn(stratA), strategy_b: toStrategyIn(stratB),
             injuries };
  }, [team, opp, giveA, giveB, dropA, dropB, addA, addB, auto, stratA, stratB, injuries]);
  const bodyKey = body ? hash(JSON.stringify({ ...body, league: league.id })) : "";

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
      .then((s) => {
        setSeason(s);
        if (savedId === bodyKey) {               // kayıtlı senaryoyu sezon etkisiyle güncelle
          scenarios.update(bodyKey, { season: seasonPatch(s) });
        }
      })
      .catch((e: ApiError) => setError(e.message))
      .finally(() => setSeasonBusy(false));
  };

  const byId = useMemo(() => {
    const m = new Map<string, Player>();
    [...(mine.data?.players ?? []), ...(theirs.data?.players ?? []), ...fa].forEach((p) => m.set(p.id, p));
    return m;
  }, [mine.data, theirs.data, fa]);
  const name = (id: string) => byId.get(id)?.name ?? id;
  const named = (ids: Iterable<string>): NamedId[] => [...ids].map((id) => ({ id, name: name(id) }));
  const teamName = (id: string) => league.teams.find((t) => t.id === id)?.name ?? id;
  const impactScale = useMemo(() => {
    if (!result) return 5;
    const ds = [...result.teams.a.categories, ...result.teams.b.categories].map((c) => Math.abs(c.after - c.before) * 100);
    return Math.max(5, ...ds);
  }, [result]);

  const seasonPatch = (s: SeasonOut) => ({
    me_playoff: s.teams.a.playoff_after - s.teams.a.playoff_before,
    me_champion: s.teams.a.champion_after - s.teams.a.champion_before,
    opp_playoff: s.teams.b.playoff_after - s.teams.b.playoff_before,
    opp_champion: s.teams.b.champion_after - s.teams.b.champion_before,
  });

  const save = () => {
    if (!result || !body) return;
    const pick = (s: TradeSide) => ({ ecw_delta: s.ecw_delta, win_delta: s.win_delta, strategy_delta: s.strategy_delta });
    scenarios.add({
      id: bodyKey, created: new Date().toISOString(), league: league.id, team, teamName: teamName(team), opp, oppName: teamName(opp),
      giveA: named(giveA), giveB: named(giveB), dropA: named(dropA), dropB: named(dropB), addA: named(addA), addB: named(addB),
      auto, stratA, stratB, stratALabel: result.teams.a.strategy, stratBLabel: result.teams.b.strategy,
      metrics: { a: pick(result.teams.a), b: pick(result.teams.b), fairness: result.fairness,
                 perceived: result.perceived_balance, mutual: result.assessments.mutual_benefit },
      season: season ? seasonPatch(season) : undefined,
    });
    setSavedId(bodyKey);
  };

  const openScenario = (s: Scenario) => {
    setOpp(s.opp);
    setGiveA(new Set(s.giveA.map((x) => x.id)));
    setGiveB(new Set(s.giveB.map((x) => x.id)));
    setDropA(s.dropA.map((x) => x.id));
    setDropB(s.dropB.map((x) => x.id));
    setAddA(s.addA.map((x) => x.id));
    setAddB(s.addB.map((x) => x.id));
    setStratA(s.stratA ?? BALANCED);
    setStratB(s.stratB ?? BALANCED);
    setAuto(s.auto);
    setShowMoves(Boolean(s.dropA.length || s.dropB.length || s.addA.length || s.addB.length));
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const clearAll = () => {
    setGiveA(new Set()); setGiveB(new Set()); setDropA([]); setDropB([]); setAddA([]); setAddB([]);
  };
  const takenFa = new Set([...addA, ...addB]);
  const leagueScenarios = scenarios.list.filter((s) => s.league === league.id);

  return (
    <>
      <div className="toolbar">
        <label className="field"><span>Karşı takım</span>
          <select className="select" value={opp} onChange={(e) => { setOpp(e.target.value); setGiveB(new Set()); setDropB([]); setAddB([]); }}>
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
        <StrategyPicker meta={meta} value={stratA} onChange={setStratA} label="Senin stratejin" />
        <StrategyPicker meta={meta} value={stratB} onChange={setStratB} label="Rakibin stratejisi"
                        autoHint="Rakibin gerçek tercihi bilinmiyor: kategori profilinden en zayıf kategori(ler)i punt ettiği varsayılır." />
        <label className="check" title="Eşit olmayan paketlerde önce sakat oyuncu IL'e, sonra gerekirse en düşük değerli bırakılır; açılan boşluk boştaki oyuncuyla doldurulur. Elle seçtiğin işlemlerden sonra uygulanır.">
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
          Kadroyu otomatik dengele
        </label>
      </div>

      <div className="grid-2">
        <RosterTable title={teamName(team)} subtitle={giveA.size ? `${giveA.size} oyuncu veriyorsun` : "veriyorsun"}
                     players={mine.data?.players ?? null} categories={meta.categories} selected={giveA}
                     onToggle={(id) => { setGiveA((s) => toggle(s, id)); setDropA((d) => d.filter((x) => x !== id)); }}
                     loading={mine.loading} error={mine.error} />
        <RosterTable title={teamName(opp)} subtitle={giveB.size ? `${giveB.size} oyuncu alıyorsun` : "alıyorsun"}
                     players={theirs.data?.players ?? null} categories={meta.categories} selected={giveB}
                     onToggle={(id) => { setGiveB((s) => toggle(s, id)); setDropB((d) => d.filter((x) => x !== id)); }}
                     loading={theirs.loading} error={theirs.error} />
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-h">
          <h2>Takas özeti</h2>
          {busy && <span className="spinner" aria-label="hesaplanıyor" />}
          <span className="spacer" style={{ flex: 1 }} />
          {result && (
            <button className="btn" onClick={save} disabled={savedId === bodyKey}>
              {savedId === bodyKey ? "✓ Kaydedildi" : "Senaryoyu kaydet"}
            </button>
          )}
          {(giveA.size > 0 || giveB.size > 0) && <button className="btn" onClick={clearAll}>Temizle</button>}
        </div>
        <div className="card-b">
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
            <div><div className="section-title" style={{ marginTop: 0 }}>Veriyorsun</div>
              {[...giveA].map((id) => (
                <span key={id} className="chip">{name(id)}
                  <button aria-label="çıkar" onClick={() => setGiveA((s) => toggle(s, id))}>×</button></span>
              ))}
              {!giveA.size && <span className="muted">Soldaki kadrodan oyuncu seç</span>}
            </div>
            <div><div className="section-title" style={{ marginTop: 0 }}>Alıyorsun</div>
              {[...giveB].map((id) => (
                <span key={id} className="chip">{name(id)}
                  <button aria-label="çıkar" onClick={() => setGiveB((s) => toggle(s, id))}>×</button></span>
              ))}
              {!giveB.size && <span className="muted">Sağdaki kadrodan oyuncu seç</span>}
            </div>
          </div>

          <details open={showMoves} onToggle={(e) => setShowMoves((e.target as HTMLDetailsElement).open)} style={{ marginTop: 12 }}>
            <summary>Ek kadro işlemleri (isteğe bağlı): bırak / boştan al
              {(dropA.length + dropB.length + addA.length + addB.length) > 0 && <span className="pill" style={{ marginLeft: 8 }}>{dropA.length + dropB.length + addA.length + addB.length} işlem</span>}
            </summary>
            <div className="moves">
              <MovesEditor title={teamName(team)} roster={mine.data?.players ?? []} give={giveA} drops={dropA} adds={addA}
                           freeAgents={fa} taken={takenFa} onDrop={setDropA} onAdd={setAddA} name={name} />
              <MovesEditor title={teamName(opp)} roster={theirs.data?.players ?? []} give={giveB} drops={dropB} adds={addB}
                           freeAgents={fa} taken={takenFa} onDrop={setDropB} onAdd={setAddB} name={name} />
            </div>
            <p className="hint">Elle seçtiğin işlemler önce uygulanır; "Kadroyu otomatik dengele" açıksa kapasite hâlâ aşılıyorsa
              sakat oyuncu IL'e, sonra en düşük değerli bırakılır. Waiver ve Can't Cut doğrulanmaz.</p>
          </details>

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
                <span className="pill muted" title="Strateji seçimleri">{strategyLabel(stratA)} / {strategyLabel(stratB)}</span>
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

      <ScenarioPanel list={leagueScenarios} team={team} onOpen={openScenario} onRemove={scenarios.remove}
                     onImport={(items) => scenarios.replaceAll([...items, ...scenarios.list.filter((x) => !items.some((y) => y.id === x.id))])} />
    </>
  );
}
