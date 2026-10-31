import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { CategoryImpact } from "../components/CategoryImpact";
import { CategoryChips, ErrorBanner, Loading, PlayerName, deltaClass } from "../components/common";
import { RosterTable } from "../components/RosterTable";
import { BALANCED, StrategyPicker, toStrategyIn, type StrategyChoice } from "../components/StrategyPicker";
import { fmtDelta, fmtNum, fmtPct, fmtStat } from "../format";
import type {
  League, Meta, MultiSeasonOut, MultiSuggestOut, MultiSuggestion, MultiTeamOut, MultiTradeIn, MultiTradeOut, Player,
  Roster, Source,
} from "../types";

import { Metric, MovesEditor } from "./TradePage";

interface Props {
  meta: Meta;
  league: League;
  team: string;
  injuries: boolean;
}

/** Analiz ekranına aktarılan takas: takımlar (sıra = döngü), hareketler ve stratejiler. */
interface MultiInit {
  teams: string[];
  moves: { player: string; from: string; to: string }[];
  strategies: Record<string, StrategyChoice>;
}

const MAX_TEAMS = 4;
const MODE_ORDER = ["remaining_games_projection", "season_total", "preseason"];
const SHAPES: { id: string; label: string; desc: string }[] = [
  { id: "1-1-1", label: "3 takım · 1-1-1", desc: "Sen → A → B → sen; herkes bir oyuncu verir." },
  { id: "2-1-1", label: "3 takım · sen 2 verirsin", desc: "İki oyuncunu verip bir üst seviye oyuncu alırsın (kadroda yer açılır)." },
  { id: "1-2-1", label: "3 takım · ortadaki 2 verir", desc: "A, B'ye iki oyuncu verir; döngü yine sende kapanır." },
  { id: "1-1-2", label: "3 takım · sen 2 alırsın", desc: "Bir oyuncunu verip iki oyuncu alırsın (kadrodan biri bırakılır)." },
  { id: "1-1-1-1", label: "4 takım · 1-1-1-1", desc: "Sen → A → B → C → sen. Arama hacmi büyük: takım başına daha kısa liste." },
];

function choiceFrom(name: string, weights: number[]): StrategyChoice {
  if (weights.every((w) => w === 1)) return BALANCED;
  if (name.startsWith("Otomatik")) return { kind: "auto", n: weights.filter((w) => w === 0).length === 2 ? 2 : 1 };
  return { kind: "custom", weights };
}

function useRosters(league: string, teams: string[], source: Source, injuries: boolean) {
  const [map, setMap] = useState<Record<string, Roster>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const key = teams.filter(Boolean).join(",");
  useEffect(() => {
    let live = true;
    setMap({});
    setErrors({});
    for (const t of key ? key.split(",") : []) {
      api.roster(league, t, source, injuries)
        .then((r) => live && setMap((m) => ({ ...m, [t]: r })))
        .catch((e: Error) => live && setErrors((x) => ({ ...x, [t]: e.message })));
    }
    return () => {
      live = false;
    };
  }, [league, key, source, injuries]);
  return { map, errors };
}

// ------------------------------------------------------------------ analiz
function TeamCard({ t, scale }: { t: MultiTeamOut; scale: number }) {
  const adj = t.adjustments;
  const moves = [
    ...adj.move_to_il.map((x) => `${x.name} → IL`),
    ...adj.drop.map((x) => `${x.name} bırakılır`),
    ...adj.add.map((x) => `${x.name} boştan alınır`),
  ];
  return (
    <div className="card">
      <div className="card-h">
        <h3>{t.team}</h3>
        <span className="muted">strateji: {t.strategy}</span>
        <span style={{ flex: 1 }} />
        <span className={"pill " + (t.strategy_delta > 1e-8 ? "okay" : "warn")}>{t.strategy_delta > 1e-8 ? "kazanır" : "kaybeder"}</span>
      </div>
      <div className="card-b">
        <div className="flow" style={{ marginBottom: 10 }}>
          {t.sent.map((p) => <div key={p.id} className="flow-row"><span className="bad">verir</span><PlayerName p={p} sub={false} /><span className="arrow">→ {p.to_name}</span></div>)}
          {t.received.map((p) => <div key={p.id} className="flow-row"><span className="good">alır</span><PlayerName p={p} sub={false} /><span className="arrow">← {p.from_name}</span></div>)}
        </div>
        <div className="metrics">
          <Metric k="Beklenen kategori / hafta" before={t.ecw_before} after={t.ecw_after} delta={t.ecw_delta}
                  fmt={(v) => fmtNum(v, 2)} dfmt={(v) => fmtDelta(v, 3)} />
          <Metric k="Haftayı kazanma P(5+)" before={t.win_before} after={t.win_after} delta={t.win_delta}
                  fmt={(v) => fmtPct(v, 1)} dfmt={(v) => fmtDelta(v * 100, 1, " puan")} />
          <Metric k="Stratejiye göre puan" before={t.strategy_before} after={t.strategy_after} delta={t.strategy_delta}
                  fmt={(v) => fmtNum(v, 2)} dfmt={(v) => fmtDelta(v, 3)} />
        </div>
        <div className="section-title">Kategori kazanma olasılığı değişimi (puan)</div>
        <CategoryImpact rows={t.categories} scale={scale} />
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

function MultiAnalyze({ meta, league, team, injuries, initial }: Props & { initial: MultiInit | null }) {
  const [slots, setSlots] = useState<string[]>(initial?.teams ?? [team, "", ""]);
  const [moves, setMoves] = useState<Map<string, { from: string; to: string }>>(
    () => new Map((initial?.moves ?? []).map((m) => [m.player, { from: m.from, to: m.to }])));
  const [strategies, setStrategies] = useState<Record<string, StrategyChoice>>(initial?.strategies ?? {});
  const [drops, setDrops] = useState<Record<string, string[]>>({});
  const [adds, setAdds] = useState<Record<string, string[]>>({});
  const [auto, setAuto] = useState(true);
  const [source, setSource] = useState<Source>("ros");
  const [fa, setFa] = useState<Player[]>([]);
  const [result, setResult] = useState<MultiTradeOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [season, setSeason] = useState<MultiSeasonOut | null>(null);
  const [seasonBusy, setSeasonBusy] = useState(false);
  const [rankMode, setRankMode] = useState(MODE_ORDER[0]);
  const seq = useRef(0);

  const filled = slots.filter(Boolean);
  const { map: rosters, errors } = useRosters(league.id, filled, source, injuries);
  const teamName = (id: string) => league.teams.find((t) => t.id === id)?.name ?? id;

  useEffect(() => {
    api.freeAgents(league.id, source, injuries).then((r) => setFa(r.players)).catch(() => setFa([]));
  }, [league.id, source, injuries]);

  const byId = useMemo(() => {
    const m = new Map<string, Player>();
    Object.values(rosters).forEach((r) => r.players.forEach((p) => m.set(p.id, p)));
    fa.forEach((p) => m.set(p.id, p));
    return m;
  }, [rosters, fa]);
  const name = (id: string) => byId.get(id)?.name ?? id;

  const setSlot = (i: number, id: string) => {
    const old = slots[i];
    const next = [...slots];
    next[i] = id;
    setSlots(next);
    if (old && old !== id) {
      // Eski takımın hareketleri ve o takıma giden oyuncular kaldırılır / yeniden yönlenir.
      setMoves((m) => {
        const out = new Map<string, { from: string; to: string }>();
        const live = next.filter(Boolean);
        m.forEach((v, k) => {
          if (v.from === old) return;
          const to = v.to === old ? live.find((t) => t !== v.from) ?? "" : v.to;
          if (to) out.set(k, { ...v, to });
        });
        return out;
      });
      setDrops((d) => { const x = { ...d }; delete x[old]; return x; });
      setAdds((d) => { const x = { ...d }; delete x[old]; return x; });
    }
  };

  const toggle = (from: string, pid: string) => {
    setMoves((m) => {
      const next = new Map(m);
      if (next.has(pid)) next.delete(pid);
      else {
        const i = filled.indexOf(from);
        const to = filled[(i + 1) % filled.length];
        if (to && to !== from) next.set(pid, { from, to });
      }
      return next;
    });
    setDrops((d) => ({ ...d, [from]: (d[from] ?? []).filter((x) => x !== pid) }));
  };

  const involved = useMemo(() => {
    const s = new Set<string>();
    moves.forEach((v) => { s.add(v.from); s.add(v.to); });
    return filled.filter((t) => s.has(t));
  }, [moves, filled]);
  const problems = involved.flatMap((t) => {
    const sends = [...moves.values()].some((v) => v.from === t);
    const gets = [...moves.values()].some((v) => v.to === t);
    return !sends ? [`${teamName(t)} hiç oyuncu vermiyor`] : !gets ? [`${teamName(t)} hiç oyuncu almıyor`] : [];
  });

  const body: MultiTradeIn | null = useMemo(() => {
    if (involved.length < 2 || problems.length) return null;
    const pick = (rec: Record<string, string[]>) => Object.fromEntries(involved.map((t) => [t, rec[t] ?? []]).filter(([, v]) => v.length));
    return {
      moves: [...moves.entries()].map(([player, v]) => ({ player, from_team: v.from, to_team: v.to })),
      drops: pick(drops), adds: pick(adds),
      strategies: Object.fromEntries(involved.map((t) => [t, toStrategyIn(strategies[t] ?? BALANCED)])),
      auto_balance: auto, injuries,
    };
  }, [moves, involved, problems.length, drops, adds, strategies, auto, injuries]);   // problems türetilir

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
      api.multiAnalyze(league.id, body)
        .then((r) => { if (id === seq.current) { setResult(r); setError(null); } })
        .catch((e: Error) => { if (id === seq.current) { setResult(null); setError(e.message); } })
        .finally(() => { if (id === seq.current) setBusy(false); });
    }, 250);
    return () => clearTimeout(t);
  }, [JSON.stringify(body), league.id]);   // gövde içerik olarak karşılaştırılır

  const runSeason = () => {
    if (!body) return;
    setSeasonBusy(true);
    api.multiSeason(league.id, { ...body, n_sims: 2000 }).then(setSeason).catch((e: Error) => setError(e.message))
      .finally(() => setSeasonBusy(false));
  };

  const scale = useMemo(() => {
    if (!result) return 5;
    return Math.max(5, ...result.teams.flatMap((t) => t.categories.map((c) => Math.abs(c.after - c.before) * 100)));
  }, [result]);
  const takenFa = new Set(Object.values(adds).flat());
  const used = new Set(filled);

  return (
    <>
      <div className="toolbar">
        <div className="slot-bar">
          {slots.map((s, i) => (
            <label key={i} className="field"><span>{i === 0 ? "1. takım" : `${i + 1}. takım`}</span>
              <select className="select" value={s} onChange={(e) => setSlot(i, e.target.value)}>
                <option value="">Takım seç…</option>
                {league.teams.map((t) => (
                  <option key={t.id} value={t.id} disabled={used.has(t.id) && t.id !== s}>{t.name}{t.id === team ? " (sen)" : ""}</option>
                ))}
              </select>
            </label>
          ))}
          {slots.length < MAX_TEAMS && <button className="btn" onClick={() => setSlots([...slots, ""])}>+ 4. takım</button>}
          {slots.length > 3 && <button className="btn" onClick={() => { setSlot(slots.length - 1, ""); setSlots((x) => x.slice(0, -1)); }}>4. takımı çıkar</button>}
        </div>
        <div className="field"><span>İstatistik</span>
          <div className="seg" role="group" aria-label="İstatistik kaynağı">
            {(Object.keys(meta.sources) as Source[]).map((s) => (
              <button key={s} aria-pressed={source === s} onClick={() => setSource(s)}>
                {s === "ros" ? "Kalan sezon" : s === "season" ? "Bu sezon" : "Sezon öncesi"}
              </button>
            ))}
          </div>
        </div>
        <label className="check" title="Kadrosu kapasiteyi aşan takımda önce sakat oyuncu IL'e, sonra en düşük değerli bırakılır; boşalan yer boştaki oyuncuyla doldurulur.">
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
          Kadroları otomatik dengele
        </label>
      </div>

      {filled.length < 2 && <div className="banner">Takasa girecek en az iki takım seç (çok takımlı takas için üç ya da dört). Sonra kadrolardan oyuncuya tıkla ve nereye gideceğini seç.</div>}

      <div className="grid-teams">
        {filled.map((t) => {
          const mine = [...moves.entries()].filter(([, v]) => v.from === t).map(([k]) => k);
          return (
            <div key={t}>
              <div style={{ marginBottom: 8 }}>
                <StrategyPicker meta={meta} value={strategies[t] ?? BALANCED} label={`${teamName(t)} stratejisi`}
                                onChange={(c) => setStrategies((s) => ({ ...s, [t]: c }))}
                                autoHint="Takımın gerçek tercihi bilinmiyor: kategori profilinden en zayıf kategori(ler)i punt ettiği varsayılır." />
              </div>
              <RosterTable title={teamName(t)} subtitle={mine.length ? `${mine.length} oyuncu veriyor` : "oyuncuya tıkla = takasa koy"}
                           players={rosters[t]?.players ?? null} categories={meta.categories} selected={new Set(mine)}
                           onToggle={(pid) => toggle(t, pid)} loading={!rosters[t] && !errors[t]} error={errors[t] ?? null} />
            </div>
          );
        })}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-h">
          <h2>Takas hareketleri</h2>
          {busy && <span className="spinner" aria-label="hesaplanıyor" />}
          <span style={{ flex: 1 }} />
          {moves.size > 0 && <button className="btn" onClick={() => { setMoves(new Map()); setDrops({}); setAdds({}); }}>Temizle</button>}
        </div>
        <div className="card-b">
          {!moves.size && <span className="muted">Kadrolardan oyuncu seç; her oyuncunun hangi takıma gideceğini burada değiştirebilirsin.</span>}
          <div className="flow">
            {[...moves.entries()].map(([pid, v]) => {
              const p = byId.get(pid);
              return (
                <div key={pid} className="flow-row">
                  {p ? <PlayerName p={p} sub={false} /> : <span className="pname">{name(pid)}</span>}
                  <span className="muted">{teamName(v.from)}</span>
                  <span className="arrow">→</span>
                  <select className="select" value={v.to} aria-label={`${name(pid)} nereye gidiyor`}
                          onChange={(e) => setMoves((m) => new Map(m).set(pid, { ...v, to: e.target.value }))}>
                    {filled.filter((t) => t !== v.from).map((t) => <option key={t} value={t}>{teamName(t)}</option>)}
                  </select>
                  <button className="link-btn" style={{ color: "var(--bad-ink)" }} onClick={() => toggle(v.from, pid)}>çıkar</button>
                </div>
              );
            })}
          </div>
          {problems.length > 0 && <div className="banner" style={{ marginTop: 10 }}>{problems.join(" · ")}: takastaki her takım en az bir oyuncu vermeli ve almalı.</div>}
          {filled.filter((t) => !involved.includes(t)).length > 0 && moves.size > 0 && (
            <p className="hint">Takasta yer almayan: {filled.filter((t) => !involved.includes(t)).map(teamName).join(", ")}</p>
          )}

          {involved.length > 0 && (
            <details style={{ marginTop: 12 }}>
              <summary>Ek kadro işlemleri (isteğe bağlı): bırak / boştan al</summary>
              <div className="moves">
                {involved.map((t) => (
                  <MovesEditor key={t} title={teamName(t)} roster={rosters[t]?.players ?? []}
                               give={new Set([...moves.entries()].filter(([, v]) => v.from === t).map(([k]) => k))}
                               drops={drops[t] ?? []} adds={adds[t] ?? []} freeAgents={fa} taken={takenFa} name={name}
                               onDrop={(ids) => setDrops((d) => ({ ...d, [t]: ids }))} onAdd={(ids) => setAdds((d) => ({ ...d, [t]: ids }))} />
                ))}
              </div>
            </details>
          )}

          <ErrorBanner error={error} />

          {result && (
            <>
              <div className="verdict">
                <span className={"pill " + (result.mutual ? "okay" : "warn")}>
                  {result.mutual ? `✓ ${result.n_teams} takımın hepsi kazanıyor (seçilen stratejilerle)` : "✕ Her takım kazanmıyor"}
                </span>
                <span className="pill" title="Takastaki en dengesiz takımın aldığı / verdiği kalan sezon değeri">Değer dengesi {fmtPct(result.fairness)}</span>
                <span className="pill" title={`İnceleme: ${result.assessments.review_type}`}>Komisyon riski: {result.assessments.commissioner_risk}</span>
                {result.assessments.deadline && <span className="pill">Son takas tarihi {result.assessments.deadline}</span>}
              </div>

              <div className="table-wrap">
                <table className="data">
                  <thead><tr>
                    <th className="l">Takım</th><th className="l">Strateji</th><th className="l">Verir</th><th className="l">Alır</th>
                    <th title="Rakip başına haftalık beklenen kategori (ağırlıksız)">ΔECW</th><th>ΔP(5+)</th>
                    <th title="Takımın stratejisine göre puan değişimi">Strateji Δ</th>
                    <th title="Kalan sezon değeri: alınan / verilen">Değer al / ver</th>
                    <th title="Bu sezon + isim değeri: alınan / verilen (takımın gözünden)">Algılanan al / ver</th>
                    <th title="Playoff haftalarında kadronun toplam NBA maçı farkı (otomatik bırak/ekle dahil)">PO maç</th>
                    <th className="l">Otomatik işlemler</th>
                  </tr></thead>
                  <tbody>
                    {result.teams.map((t) => {
                      const a = t.adjustments;
                      const extra = [...a.move_to_il.map((x) => `${x.name} → IL`), ...a.drop.map((x) => `−${x.name}`), ...a.add.map((x) => `+${x.name}`)];
                      return (
                        <tr key={t.team_id} className={t.team_id === team ? "me" : ""}>
                          <td className="l">{t.team}</td>
                          <td className="l muted">{t.strategy}</td>
                          <td className="l wrap">{t.sent.map((p) => p.name).join(", ")}</td>
                          <td className="l wrap">{t.received.map((p) => p.name).join(", ")}</td>
                          <td className={deltaClass(t.ecw_delta, 0.3)}>{fmtDelta(t.ecw_delta, 3)}</td>
                          <td>{fmtDelta(t.win_delta * 100, 1)}</td>
                          <td className={deltaClass(t.strategy_delta, 0.3)}>{fmtDelta(t.strategy_delta, 3)}</td>
                          <td>{fmtNum(t.value_in, 2)} / {fmtNum(t.value_out, 2)}</td>
                          <td>{fmtNum(t.perceived_in, 2)} / {fmtNum(t.perceived_out, 2)}</td>
                          <td className={t.playoff_games === null ? "muted" : t.playoff_games > 0 ? "good" : t.playoff_games < 0 ? "bad" : ""}>
                            {t.playoff_games === null ? "—" : fmtDelta(t.playoff_games, 0)}</td>
                          <td className="l wrap muted">{extra.join(", ") || "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="grid-teams" style={{ marginTop: 16 }}>
                {result.teams.map((t) => <TeamCard key={t.team_id} t={t} scale={scale} />)}
              </div>

              <div className="section-title">Playoff ve şampiyonluk etkisi</div>
              {!season && (
                <button className="btn primary" onClick={runSeason} disabled={seasonBusy}>
                  {seasonBusy ? <><span className="spinner" /> Simüle ediliyor…</> : "Sezon etkisini hesapla"}
                </button>
              )}
              {season && (
                <>
                  <table className="mini" style={{ maxWidth: 820 }}>
                    <thead><tr><th className="l">Takım</th><th>Playoff</th><th>Fark</th><th>Şampiyonluk</th><th>Fark</th><th>Ort. sıra</th></tr></thead>
                    <tbody>
                      {season.teams.map((s) => {
                        const dp = s.playoff_after - s.playoff_before;
                        const dc = s.champion_after - s.champion_before;
                        return (
                          <tr key={s.team_id}>
                            <td className="l">{s.team}</td>
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
                  <p className="muted" style={{ fontSize: 12 }}>{season.n_sims} simülasyon · takım gücü belirsizliği ±%{(season.strength_sd * 100).toFixed(0)} · aynı çekilişlerle takassız/takaslı karşılaştırma. Olasılıklar kalibre edilmedi.</p>
                </>
              )}

              <div className="section-title">Lig sıralamasında kategori değişimi</div>
              <div className="seg" role="group" style={{ marginBottom: 10 }}>
                {MODE_ORDER.map((m) => <button key={m} aria-pressed={rankMode === m} onClick={() => setRankMode(m)}>{result.modes[m]}</button>)}
              </div>
              <div className="grid-teams">
                {result.teams.map((t) => (
                  <table key={t.team_id} className="mini">
                    <thead><tr><th className="l">{t.team}</th><th>Önce</th><th>Sonra</th><th>Sıra</th></tr></thead>
                    <tbody>
                      {t.ranks[rankMode].map((r) => {
                        const gain = (r.rank_before ?? 0) - (r.rank_after ?? 0);
                        const pct = r.key === "FG_PCT" || r.key === "FT_PCT";
                        return (
                          <tr key={r.key}>
                            <td className="l">{r.label}</td>
                            <td>{pct ? fmtStat(r.key, r.value_before) : fmtNum(r.value_before, 0)}</td>
                            <td>{pct ? fmtStat(r.key, r.value_after) : fmtNum(r.value_after, 0)}</td>
                            <td className={gain > 0 ? "good" : gain < 0 ? "bad" : ""}>{fmtNum(r.rank_before, 0)} → {fmtNum(r.rank_after, 0)}</td>
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
        </div>
      </div>
    </>
  );
}

// ------------------------------------------------------------------ öneriler
type Effect = { playoff: number; champion: number } | "err";

function MultiSuggest({ meta, league, team, injuries, onOpen }: Props & { onOpen: (init: MultiInit) => void }) {
  const [shapes, setShapes] = useState<string[]>(["1-1-1", "2-1-1", "1-1-2", "1-1-1-1"]);
  const [strategy, setStrategy] = useState<StrategyChoice>(BALANCED);
  const [assume, setAssume] = useState<"balanced" | "punt1" | "punt2">("balanced");
  const [minFair, setMinFair] = useState(0.5);
  const [minGain, setMinGain] = useState(0.005);
  const [shortlist, setShortlist] = useState(6);
  const [shortlist4, setShortlist4] = useState(4);
  const [result, setResult] = useState<MultiSuggestOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [effects, setEffects] = useState<Record<number, Effect>>({});
  const [effBusy, setEffBusy] = useState<{ done: number; total: number } | null>(null);
  const [sortBy, setSortBy] = useState<"score" | "mine" | "playoff">("score");
  const labels = Object.fromEntries(meta.categories.map((c) => [c.key, c.label]));

  const search = () => {
    setBusy(true);
    setError(null);
    setEffects({});
    api.multiSuggest(league.id, {
      team, shapes, opponent_assumption: assume, shortlist, shortlist4: Math.min(shortlist4, shortlist),
      min_fairness: minFair, min_gain: minGain, strategy: toStrategyIn(strategy), injuries,
    }).then(setResult).catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };

  const bodyOf = (s: MultiSuggestion): MultiTradeIn => ({
    moves: s.moves.map((m) => ({ player: m.player.id, from_team: m.from, to_team: m.to })),
    strategies: Object.fromEntries(s.teams.map((t) => [t.team_id, t.team_id === team ? toStrategyIn(strategy)
      : { name: t.strategy, weights: t.weights }])),
    auto_balance: true, injuries,
  });

  const runEffects = async () => {
    if (!result) return;
    const list = result.suggestions.map((s, i) => ({ s, i })).filter(({ i }) => !effects[i]);
    setEffBusy({ done: 0, total: list.length });
    for (let k = 0; k < list.length; k++) {
      const { s, i } = list[k];
      try {
        const r = await api.multiSeason(league.id, { ...bodyOf(s), n_sims: 1000 });
        const me = r.teams.find((t) => t.team_id === team)!;
        setEffects((x) => ({ ...x, [i]: { playoff: me.playoff_after - me.playoff_before, champion: me.champion_after - me.champion_before } }));
      } catch {
        setEffects((x) => ({ ...x, [i]: "err" }));
      }
      setEffBusy({ done: k + 1, total: list.length });
    }
    setEffBusy(null);
  };

  const rows = result ? result.suggestions.map((s, i) => ({ s, i, me: s.teams.find((t) => t.team_id === team)! })) : [];
  const effVal = (i: number) => { const e = effects[i]; return e && e !== "err" ? e.playoff + e.champion : -9; };
  if (sortBy === "mine") rows.sort((a, b) => b.me.strategy_delta - a.me.strategy_delta);
  else if (sortBy === "playoff") rows.sort((a, b) => effVal(b.i) - effVal(a.i));

  const open = (s: MultiSuggestion) => {
    const teams = s.teams.map((t) => t.team_id);
    onOpen({
      teams: [team, ...teams.filter((t) => t !== team)],
      moves: s.moves.map((m) => ({ player: m.player.id, from: m.from, to: m.to })),
      strategies: Object.fromEntries(s.teams.map((t) => [t.team_id, t.team_id === team ? strategy : choiceFrom(t.strategy, t.weights)])),
    });
  };

  return (
    <div className="stack">
      <div className="card"><div className="card-b">
        <div className="section-title" style={{ marginTop: 0 }}>Takas şekilleri (döngü her zaman sende başlar ve biter)</div>
        <div className="dirs" role="group" aria-label="Takas şekilleri">
          {SHAPES.map((d) => (
            <button key={d.id} className="dir" aria-pressed={shapes.includes(d.id)}
                    onClick={() => setShapes((x) => x.includes(d.id) ? x.filter((y) => y !== d.id) : [...x, d.id])}>
              <b>{d.label}</b><small>{d.desc}</small>
            </button>
          ))}
        </div>
        <div className="toolbar" style={{ marginTop: 14, marginBottom: 0 }}>
          <StrategyPicker meta={meta} value={strategy} onChange={setStrategy} label="Senin stratejin (yön)" />
          <label className="field"><span>Diğer takımların stratejisi</span>
            <select className="select" value={assume} onChange={(e) => setAssume(e.target.value as typeof assume)}>
              <option value="balanced">Dengeli</option>
              <option value="punt1">En zayıf kategorisini punt</option>
              <option value="punt2">En zayıf iki kategorisini punt</option>
            </select>
          </label>
          <label className="field" title="Takastaki en dengesiz takımın aldığı / verdiği kalan sezon değeri"><span>En az değer dengesi</span>
            <input className="num-input" type="number" step={0.05} min={0} max={1} value={minFair} onChange={(e) => setMinFair(Number(e.target.value))} />
          </label>
          <label className="field" title="Her takımın en az strateji kazancı (rakip başına haftalık kategori)"><span>En az kazanç (her takım)</span>
            <input className="num-input" type="number" step={0.005} min={0} max={0.5} value={minGain} onChange={(e) => setMinGain(Number(e.target.value))} />
          </label>
          <label className="field" title="Takım başına aday oyuncu (3 takımlı döngüler)"><span>Aday / takım</span>
            <input className="num-input" type="number" step={1} min={3} max={10} value={shortlist} onChange={(e) => setShortlist(Number(e.target.value))} />
          </label>
          <label className="field" title="4 takımlı döngüde takım başına aday (arama hacmi aday⁴)"><span>Aday / takım (4'lü)</span>
            <input className="num-input" type="number" step={1} min={2} max={6} value={shortlist4} onChange={(e) => setShortlist4(Number(e.target.value))} />
          </label>
          <button className="btn primary" onClick={search} disabled={busy || !shapes.length}>
            {busy ? <><span className="spinner" /> Döngüler taranıyor…</> : "Önerileri bul"}
          </button>
        </div>
      </div></div>

      <ErrorBanner error={error} />
      {busy && <Loading text="Üç ve dört takımlı döngüler taranıyor (birkaç saniye)…" />}
      {result && !busy && (
        <div className="card">
          <div className="card-h">
            <h2>{result.suggestions.length} öneri</h2>
            <span className="muted">{result.scanned.toLocaleString("tr-TR")} döngü tarandı · {result.evaluated} tam modelle değerlendirildi · {result.eligible} eşikleri geçti · senin stratejin: {result.strategy.name}</span>
            <span style={{ flex: 1 }} />
            {result.suggestions.length > 0 && (
              <>
                <div className="seg">
                  <button aria-pressed={sortBy === "score"} onClick={() => setSortBy("score")}>Öneri puanı</button>
                  <button aria-pressed={sortBy === "mine"} onClick={() => setSortBy("mine")}>Senin kazancın</button>
                  <button aria-pressed={sortBy === "playoff"} onClick={() => setSortBy("playoff")} disabled={!Object.keys(effects).length}>Playoff + şampiyonluk</button>
                </div>
                <button className="btn" onClick={runEffects} disabled={effBusy !== null}>
                  {effBusy ? <><span className="spinner" /> {effBusy.done}/{effBusy.total}</> : "Playoff etkisini hesapla"}
                </button>
              </>
            )}
          </div>
          {result.message && <div className="banner" style={{ margin: 12 }}>{result.message}</div>}
          {rows.length > 0 && (
            <div className="table-wrap">
              <table className="data">
                <thead><tr>
                  <th className="l">Şekil</th><th className="l">Hareketler</th>
                  <th title="Senin stratejine göre kazancın (rakip başına haftalık kategori)">Sen Δ</th>
                  <th title="Haftayı kazanma olasılığı değişimi (puan)">Sen P(5+)</th>
                  <th title="Ağırlıksız beklenen kategori değişimi">Sen ΔECW</th>
                  <th className="l" title="Diğer takımların (varsayılan stratejileriyle) kazancı">Diğer takımlar Δ</th>
                  <th className="l">Kategori etkisi (sen)</th>
                  <th title="Playoff haftalarında kadronun toplam NBA maçı farkı (sen; otomatik bırak/ekle dahil)">PO maç</th>
                  <th title="Takastaki en dengesiz takımın değer oranı">Değer dengesi</th>
                  <th>Playoff</th><th>Şamp.</th><th />
                </tr></thead>
                <tbody>
                  {rows.map(({ s, i, me }) => {
                    const e = effects[i];
                    const others = s.teams.filter((t) => t.team_id !== team);
                    return (
                      <tr key={i}>
                        <td className="l muted">{s.shape_label}</td>
                        <td className="l wrap">
                          <div className="flow">
                            {s.moves.map((m) => (
                              <div key={m.player.id} className="flow-row">
                                <PlayerName p={m.player} sub={false} />
                                <span className="muted">{m.from === team ? "sen" : m.from_name} → {m.to === team ? "sen" : m.to_name}</span>
                              </div>
                            ))}
                          </div>
                        </td>
                        <td className={deltaClass(me.strategy_delta, 0.3)}>{fmtDelta(me.strategy_delta, 3)}</td>
                        <td>{fmtDelta(me.win_delta * 100, 1)}</td>
                        <td className={deltaClass(me.ecw_delta, 0.3)}>{fmtDelta(me.ecw_delta, 3)}</td>
                        <td className="l wrap">
                          {others.map((t) => (
                            <div key={t.team_id} title={`${t.team} · strateji: ${t.strategy} · P(5+) ${fmtDelta(t.win_delta * 100, 1)} puan`}>
                              <span className="muted">{t.team}</span> <span className={t.strategy_delta > 0 ? "good" : "bad"}>{fmtDelta(t.strategy_delta, 3)}</span>
                            </div>
                          ))}
                        </td>
                        <td className="l"><CategoryChips deltas={me.categories} labels={labels} /></td>
                        <td className={me.playoff_games === null ? "muted" : me.playoff_games > 0 ? "good" : me.playoff_games < 0 ? "bad" : ""}>
                          {me.playoff_games === null ? "—" : fmtDelta(me.playoff_games, 0)}</td>
                        <td>{fmtPct(s.fairness)}</td>
                        <td className={e && e !== "err" ? deltaClass(e.playoff, 0.1) : ""}>{e === "err" ? "—" : e ? fmtDelta(e.playoff * 100, 1) : ""}</td>
                        <td className={e && e !== "err" ? deltaClass(e.champion, 0.05) : ""}>{e === "err" ? "—" : e ? fmtDelta(e.champion * 100, 1) : ""}</td>
                        <td><button className="link-btn" onClick={() => open(s)}>Analizde aç →</button></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <div className="hint" style={{ padding: "0 14px 12px" }}>
            Döngüdeki her takımın kendi stratejisine göre kazandığı takaslar listelenir. Yahoo çok takımlı takası tek işlemde yapmaz:
            bunlar aynı anda kabul edilmesi gereken ikili takaslardır. Kabul olasılığı ölçülmez; olasılıklar kalibre edilmedi.
          </div>
        </div>
      )}
    </div>
  );
}

export function MultiTradePage({ meta, league, team, injuries }: Props) {
  const [sub, setSub] = useState<"analyze" | "suggest">("analyze");
  const [init, setInit] = useState<{ data: MultiInit; seq: number } | null>(null);
  return (
    <div className="stack">
      <div>
        <div className="seg" role="group" aria-label="Çok takımlı takas">
          <button aria-pressed={sub === "analyze"} onClick={() => setSub("analyze")}>Analiz</button>
          <button aria-pressed={sub === "suggest"} onClick={() => setSub("suggest")}>Öneriler</button>
        </div>
        <p className="desc" style={{ marginTop: 10 }}>
          {sub === "analyze"
            ? "3–4 takım seç, kadrolardan oyuncuları işaretle ve her oyuncunun gideceği takımı belirle. Takastaki tüm takımların kadroları aynı anda değişir; her takım kendi stratejisine göre değerlendirilir."
            : "Sen → A → B (→ C) → sen döngüleri: iki takımlı takasta karşılığı olmayan, ama üç-dört takım arasında herkesin kazandığı takaslar."}
        </p>
      </div>
      <div hidden={sub !== "analyze"}>
        <MultiAnalyze key={init?.seq ?? 0} meta={meta} league={league} team={team} injuries={injuries} initial={init?.data ?? null} />
      </div>
      <div hidden={sub !== "suggest"}>
        <MultiSuggest meta={meta} league={league} team={team} injuries={injuries}
                      onOpen={(data) => { setInit({ data, seq: (init?.seq ?? 0) + 1 }); setSub("analyze"); window.scrollTo({ top: 0 }); }} />
      </div>
    </div>
  );
}
