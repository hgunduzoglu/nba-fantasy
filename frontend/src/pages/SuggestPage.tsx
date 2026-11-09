import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { AcceptBadge, CategoryChips, ErrorBanner, Loading, PlayerName, deltaClass } from "../components/common";
import { BALANCED, StrategyPicker, strategyLabel, toStrategyIn, type StrategyChoice } from "../components/StrategyPicker";
import { fmtDelta, fmtNum, fmtPct } from "../format";
import type { League, Meta, MispricedRow, Perceived, SuggestMode, SuggestOut, Suggestion } from "../types";

import type { TradeInit } from "./TradePage";

interface Props {
  meta: Meta;
  league: League;
  team: string;
  injuries: boolean;
  onOpen: (t: TradeInit) => void;
}

const MODES: { id: SuggestMode; label: string; desc: string }[] = [
  { id: "mutual", label: "Karşılıklı fayda",
    desc: "İki takımın da kalan sezon kategori beklentisi artar; paketlerin kalan sezon değeri dengelidir." },
  { id: "sell_high", label: "Sat yüksek",
    desc: "Verdiğin pakette olduğundan iyi görünen bir oyuncu var. Rakip, baktığı değere göre takası adil ya da kârlı görür; sen kalan sezonda kazanırsın. Rakibin kalan sezonda kazanması şart değil." },
  { id: "buy_low", label: "Al düşük",
    desc: "Aldığın pakette olduğundan kötü görünen bir oyuncu var. Rakip, baktığı değere göre takası adil ya da kârlı görür; sen kalan sezonda kazanırsın." },
];
const PERCEIVED: { id: Perceived; label: string }[] = [
  { id: "blend", label: "Bu sezon + isim değeri" },
  { id: "season_total", label: "Bu sezonun rakamları" },
  { id: "preseason", label: "Sezon öncesi isim değeri" },
];
const PACKAGES = ["1x1", "2x1", "1x2", "2x2", "3x2", "2x3"];

/** Arama yönü: senin takımın hangi hedefle değerlendirileceği. Her yön ayrı bir arama yapar. */
type DirId = "balanced" | "punt1" | "punt2" | "revive1" | "revive2" | "win" | "custom";
interface Direction { id: DirId; tag: string; label: string; desc: string; strategy: StrategyChoice; ecw?: number }
const DIRECTIONS: Direction[] = [
  { id: "balanced", tag: "D", label: "Dengeli", strategy: BALANCED,
    desc: "9 kategori eşit önemde; genel güç artışı." },
  { id: "punt1", tag: "P", label: "Otomatik punt", strategy: { kind: "auto", n: 1 },
    desc: "En zayıf kategorinden vazgeç, o kategoriyi verip kalan 8'i güçlendiren takaslar." },
  { id: "punt2", tag: "P2", label: "Otomatik punt ×2", strategy: { kind: "auto", n: 2 },
    desc: "En zayıf iki kategoriden vazgeç; 7 kategoriye yüklen." },
  { id: "revive1", tag: "C", label: "Zayıfı canlandır", strategy: { kind: "revive", n: 1 },
    desc: "Punt'lanmış gibi duran en zayıf kategorin ×3 önemli: o kategoriyi geri kazandıran takaslar." },
  { id: "revive2", tag: "C2", label: "İki zayıfı canlandır", strategy: { kind: "revive", n: 2 },
    desc: "En zayıf iki kategorin ×3 önemli." },
  { id: "win", tag: "G", label: "Haftalık galibiyet", strategy: BALANCED, ecw: 0,
    desc: "Kategori beklentisi yerine doğrudan haftayı kazanma olasılığını P(5+) büyüten takaslar; kıl payı kategorilere ağırlık verir." },
  { id: "custom", tag: "Ö", label: "Seçtiğin strateji", strategy: BALANCED,
    desc: "Aşağıdaki seçicideki hazır punt ya da özel ağırlıklar." },
];
const DEFAULT_DIRS: DirId[] = ["balanced", "punt1", "revive1", "win"];

type Effect = { me_playoff: number; me_champion: number; opp_playoff: number } | "err";
type Row = { key: string; s: Suggestion; dirs: DirId[]; best: DirId };

const tradeKey = (s: Suggestion) =>
  `${s.team_b}|${s.give_a.map((p) => p.id).sort().join(",")}|${s.give_b.map((p) => p.id).sort().join(",")}`;

/** Senin kategori değişimin, bir yönün ağırlıklarıyla (0–9 ölçeğinde) puanlanır. */
function weighted(s: Suggestion, weights: number[], keys: string[]): number {
  const sum = weights.reduce((a, b) => a + b, 0) || 1;
  return keys.reduce((acc, c, i) => acc + (s.my_categories[c as keyof typeof s.my_categories] ?? 0) * weights[i], 0) / sum * 9;
}

function MispricedTable({ rows, title, showTeam }: { rows: MispricedRow[]; title: string; showTeam: boolean }) {
  return (
    <div className="card">
      <div className="card-h"><h3>{title}</h3></div>
      <div className="table-wrap">
        <table className="data">
          <thead><tr><th className="l">Oyuncu</th>{showTeam && <th className="l">Takım</th>}<th>Bu sezon maç</th>
            <th title="Rakibin baktığı değere göre sıra">Algılanan sıra</th><th>Kalan sezon sırası</th><th>Fark</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.player_id}>
                <td className="l pname">{r.name}</td>{showTeam && <td className="l muted">{r.team}</td>}
                <td>{fmtNum(r.gp_now, 0)}</td><td>{fmtNum(r.perceived_rank, 0)}</td><td>{fmtNum(r.ros_rank, 0)}</td>
                <td className={r.edge > 0 ? "good" : "bad"}>{fmtDelta(r.edge, 2)}</td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={showTeam ? 6 : 5} className="empty">Eşik üstünde oyuncu yok</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function SuggestPage({ meta, league, team, injuries, onOpen }: Props) {
  const [mode, setMode] = useState<SuggestMode>("mutual");
  const [dirs, setDirs] = useState<DirId[]>(DEFAULT_DIRS);
  const [custom, setCustom] = useState<StrategyChoice>({ kind: "custom", weights: Array(9).fill(1) });
  const [assume, setAssume] = useState<"balanced" | "punt1" | "punt2">("balanced");
  const [perceived, setPerceived] = useState<Perceived>("blend");
  const [minBalance, setMinBalance] = useState(0.9);
  const [minEdge, setMinEdge] = useState(1.0);
  const [packages, setPackages] = useState<string[]>(["1x1", "2x1", "1x2", "2x2"]);
  const [budget, setBudget] = useState(4000);
  const [minFair, setMinFair] = useState(0.55);
  const [minView, setMinView] = useState(0.8);
  const [results, setResults] = useState<Partial<Record<DirId, SuggestOut>>>({});
  const [progress, setProgress] = useState<{ done: number; total: number; label: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"all" | DirId>("all");
  const [mis, setMis] = useState<{ sell_high: MispricedRow[]; buy_low: MispricedRow[] } | null>(null);
  const [effects, setEffects] = useState<Record<string, Effect>>({});
  const [effBusy, setEffBusy] = useState<{ done: number; total: number } | null>(null);
  const [sortBy, setSortBy] = useState<"score" | "robust" | "ecw" | "playoff">("score");
  const busy = progress !== null;
  const catKeys = meta.categories.map((c) => c.key);
  const labels = Object.fromEntries(meta.categories.map((c) => [c.key, c.label]));

  useEffect(() => {
    if (mode === "mutual") return;
    api.mispricing(league.id, team, perceived, injuries).then(setMis).catch(() => setMis(null));
  }, [mode, league.id, team, perceived, injuries]);

  useEffect(() => {
    setResults({});
    setEffects({});
  }, [mode, league.id, team]);

  const dirInfo = (id: DirId): Direction => {
    const d = DIRECTIONS.find((x) => x.id === id)!;
    return id === "custom" ? { ...d, strategy: custom, label: `Seçtiğin: ${strategyLabel(custom)}` } : d;
  };

  const search = async () => {
    const chosen = DIRECTIONS.filter((d) => dirs.includes(d.id)).map((d) => dirInfo(d.id));
    setError(null);
    setEffects({});
    const out: Partial<Record<DirId, SuggestOut>> = {};
    setResults({});
    for (let k = 0; k < chosen.length; k++) {
      const d = chosen[k];
      setProgress({ done: k, total: chosen.length, label: d.label });
      try {
        out[d.id] = await api.suggest(league.id, {
          team, mode, opponent_assumption: assume, perceived, min_balance: minBalance, min_edge: minEdge, packages,
          max_evaluations: budget, min_fairness: minFair, min_gain: 0.005, min_view: minView, auto_balance: true,
          strategy: toStrategyIn(d.strategy), ecw_weight: d.ecw ?? 0.65, injuries,
        });
        setResults({ ...out });
      } catch (e) {
        setError(`${d.label}: ${(e as Error).message}`);
      }
    }
    setProgress(null);
    setView(chosen.length > 1 ? "all" : chosen[0]?.id ?? "all");
  };

  const found = (Object.keys(results) as DirId[]).filter((d) => results[d]);
  // Aynı takas birden çok yönde bulunabilir: birleşik görünümde tek satır, bulunduğu yönler etiketlenir.
  const combined = useMemo(() => {
    const m = new Map<string, Row>();
    for (const d of found) {
      for (const s of results[d]!.suggestions) {
        const key = tradeKey(s);
        const r = m.get(key);
        if (!r) m.set(key, { key, s, dirs: [d], best: d });
        else {
          r.dirs.push(d);
          if (s.score > r.s.score) { r.s = s; r.best = d; }
        }
      }
    }
    return [...m.values()];
  }, [results]);

  /** Seçili yönlerin kaçında senin kazancın pozitif (galibiyet yönü: P(5+) artışı). */
  const robustness = (s: Suggestion) => {
    const parts = found.map((d) => {
      const g = d === "win" ? s.own_win * 100 : weighted(s, results[d]!.strategy.weights, catKeys);
      return { d, g, label: d === "win" ? `${dirInfo(d).label} ${fmtDelta(g, 1)} puan` : `${results[d]!.strategy.name} ${fmtDelta(g, 3)}` };
    });
    return { n: parts.filter((p) => p.g > 1e-6).length, total: parts.length, tip: parts.map((p) => p.label).join("\n") };
  };

  const rows: Row[] = view === "all" ? [...combined]
    : (results[view]?.suggestions ?? []).map((s) => ({ key: tradeKey(s), s, dirs: [view], best: view }));
  const ecwOf = (s: Suggestion) => Object.values(s.my_categories).reduce((a, b) => a + b, 0);
  const effVal = (k: string) => { const e = effects[k]; return e && e !== "err" ? e.me_champion + e.me_playoff : -9; };
  if (sortBy === "playoff") rows.sort((a, b) => effVal(b.key) - effVal(a.key));
  else if (sortBy === "ecw") rows.sort((a, b) => ecwOf(b.s) - ecwOf(a.s));
  else if (sortBy === "robust") rows.sort((a, b) => robustness(b.s).n - robustness(a.s).n || b.s.score - a.s.score);
  else if (view === "all") rows.sort((a, b) => b.dirs.length - a.dirs.length || b.s.score - a.s.score);

  const runEffects = async () => {
    const list = rows.slice(0, 25).filter((r) => !effects[r.key]);
    setEffBusy({ done: 0, total: list.length });
    for (let i = 0; i < list.length; i++) {
      const { key, s, best } = list[i];
      try {
        const r = await api.season(league.id, {
          team_a: team, team_b: s.team_b, give_a: s.give_a.map((p) => p.id), give_b: s.give_b.map((p) => p.id),
          auto_balance: true, strategy_a: toStrategyIn(dirInfo(best).strategy),
          strategy_b: { name: s.other_strategy, weights: s.other_weights }, injuries, n_sims: 1000,
        });
        const e: Effect = { me_playoff: r.teams.a.playoff_after - r.teams.a.playoff_before,
                            me_champion: r.teams.a.champion_after - r.teams.a.champion_before,
                            opp_playoff: r.teams.b.playoff_after - r.teams.b.playoff_before };
        setEffects((x) => ({ ...x, [key]: e }));
      } catch {
        setEffects((x) => ({ ...x, [key]: "err" }));
      }
      setEffBusy({ done: i + 1, total: list.length });
    }
    setEffBusy(null);
  };

  const modeInfo = MODES.find((m) => m.id === mode)!;
  const open = (r: Row) => onOpen({
    opp: r.s.team_b, giveA: r.s.give_a.map((p) => p.id), giveB: r.s.give_b.map((p) => p.id),
    stratA: dirInfo(r.best).strategy,
    stratB: r.s.other_weights.every((w) => w === 1) ? BALANCED
      : r.s.other_strategy.startsWith("Otomatik") ? { kind: "auto", n: r.s.other_weights.filter((w) => w === 0).length === 2 ? 2 : 1 }
      : { kind: "custom", weights: r.s.other_weights },
  });
  const anyResult = found.length > 0;
  const total = (d: DirId) => results[d]?.suggestions.length ?? 0;
  const examined = found.reduce((a, d) => a + results[d]!.examined, 0);
  const rejectedView = found.reduce((a, d) => a + (results[d]!.rejected_view ?? 0), 0);
  const rejectedReason = found.reduce((a, d) => a + (results[d]!.rejected_reason ?? 0), 0);
  const rejectedOverpay = found.reduce((a, d) => a + (results[d]!.rejected_overpay ?? 0), 0);

  return (
    <div className="stack">
      <div>
        <div className="seg" role="group" aria-label="Öneri türü">
          {MODES.map((m) => <button key={m.id} aria-pressed={mode === m.id} onClick={() => setMode(m.id)}>{m.label}</button>)}
        </div>
        <p className="desc" style={{ marginTop: 10 }}>{modeInfo.desc}</p>
      </div>

      <div className="card"><div className="card-b">
        <div className="section-title" style={{ marginTop: 0 }}>Yönler: takımın hangi hedefle aransın? (her yön ayrı arama)</div>
        <div className="dirs" role="group" aria-label="Arama yönleri">
          {DIRECTIONS.map((d) => (
            <button key={d.id} className="dir" aria-pressed={dirs.includes(d.id)}
                    onClick={() => setDirs((x) => x.includes(d.id) ? x.filter((y) => y !== d.id) : [...x, d.id])}>
              <b><span className="tag">{d.tag}</span>{d.label}</b><small>{d.desc}</small>
            </button>
          ))}
        </div>
        {dirs.includes("custom") && (
          <div style={{ marginTop: 10 }}>
            <StrategyPicker meta={meta} value={custom} onChange={setCustom} label="Seçtiğin strateji (Ö)" />
          </div>
        )}
        <div className="toolbar" style={{ marginTop: 14, marginBottom: 0 }}>
          <label className="field"><span>Rakip stratejisi varsayımı</span>
            <select className="select" value={assume} onChange={(e) => setAssume(e.target.value as typeof assume)}>
              <option value="balanced">Dengeli</option>
              <option value="punt1">En zayıf kategorisini punt</option>
              <option value="punt2">En zayıf iki kategorisini punt</option>
            </select>
          </label>
          {mode !== "mutual" && (
            <>
              <label className="field"><span>Rakibin baktığı değer</span>
                <select className="select" value={perceived} onChange={(e) => setPerceived(e.target.value as Perceived)}>
                  {PERCEIVED.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
                </select>
              </label>
              <label className="field" title="Rakibin aldığı / verdiği algılanan değer. 1 = eşit görür.">
                <span>Rakibin gözünde en az denge</span>
                <input className="num-input" type="number" step={0.05} min={0.5} max={1.5} value={minBalance}
                       onChange={(e) => setMinBalance(Number(e.target.value))} />
              </label>
              <label className="field" title="Algılanan fiyat ile kalan sezon değeri arasındaki en az fark">
                <span>En az yanlış fiyatlama</span>
                <input className="num-input" type="number" step={0.25} min={0} max={5} value={minEdge}
                       onChange={(e) => setMinEdge(Number(e.target.value))} />
              </label>
            </>
          )}
          {mode === "mutual" && (
            <label className="field" title="Kalan sezon değerine göre küçük paket / büyük paket">
              <span>En az değer dengesi</span>
              <input className="num-input" type="number" step={0.05} min={0} max={1} value={minFair}
                     onChange={(e) => setMinFair(Number(e.target.value))} />
            </label>
          )}
          {mode === "mutual" && (
            <label className="field" title="Rakip oyunculara bu sezonun rakamları ve isim değeriyle bakar: aldığı / verdiği algılanan değer bu oranın altındaysa öneri elenir (model rakibin kazandığını hesaplasa bile kabul etmez). 0 = kapalı.">
              <span>Rakibin gözünde en az</span>
              <input className="num-input" type="number" step={0.05} min={0} max={1.5} value={minView}
                     onChange={(e) => setMinView(Number(e.target.value))} />
            </label>
          )}
          <div className="field"><span>Paketler (ver × al)</span>
            <div className="seg">
              {PACKAGES.map((p) => (
                <button key={p} aria-pressed={packages.includes(p)}
                        onClick={() => setPackages((x) => x.includes(p) ? x.filter((y) => y !== p) : [...x, p])}>{p}</button>
              ))}
            </div>
          </div>
          <label className="field" title="Her yön için taranacak en fazla paket"><span>Taranacak paket / yön</span>
            <input className="num-input" type="number" step={500} min={200} max={50000} value={budget}
                   onChange={(e) => setBudget(Number(e.target.value))} />
          </label>
          <button className="btn primary" onClick={search} disabled={busy || !packages.length || !dirs.length}>
            {busy ? <><span className="spinner" /> {progress!.done + 1}/{progress!.total} · {progress!.label}</> : `Önerileri bul (${dirs.length} yön)`}
          </button>
        </div>
      </div></div>

      {mode !== "mutual" && mis && (
        <div className="row">
          {mode === "sell_high"
            ? <MispricedTable rows={mis.sell_high.filter((r) => r.edge >= minEdge)} title="Kadrondaki sat-yüksek adayları" showTeam={false} />
            : <MispricedTable rows={mis.buy_low.filter((r) => -r.edge >= minEdge)} title="Rakiplerdeki al-düşük hedefleri" showTeam />}
        </div>
      )}

      <ErrorBanner error={error} />
      {busy && !anyResult && <Loading text={`Paketler taranıyor: ${progress!.label} (yön başına birkaç saniye)…`} />}
      {anyResult && (
        <div className="card">
          <div className="card-h" style={{ flexWrap: "wrap" }}>
            <div className="seg" role="tablist" aria-label="Yön sonuçları">
              {found.length > 1 && <button aria-pressed={view === "all"} onClick={() => setView("all")}>Tümü ({combined.length})</button>}
              {found.map((d) => (
                <button key={d} aria-pressed={view === d} onClick={() => setView(d)} title={results[d]!.strategy.name}>
                  <span className="tag">{dirInfo(d).tag}</span>{dirInfo(d).label} ({total(d)})
                </button>
              ))}
            </div>
            <span className="muted">{examined} paket tarandı{rejectedView ? ` · ${rejectedView} rakibin gözünde dengesiz diye elendi` : ""}</span>
            <span style={{ flex: 1 }} />
            {rows.length > 0 && (
              <>
                <div className="seg">
                  <button aria-pressed={sortBy === "score"} onClick={() => setSortBy("score")}>Öneri puanı</button>
                  <button aria-pressed={sortBy === "robust"} onClick={() => setSortBy("robust")}
                          title="Kaç yönde senin kazancın pozitif">Sağlamlık</button>
                  <button aria-pressed={sortBy === "ecw"} onClick={() => setSortBy("ecw")}>Senin ΔECW</button>
                  <button aria-pressed={sortBy === "playoff"} onClick={() => setSortBy("playoff")}
                          disabled={!Object.keys(effects).length}>Playoff + şampiyonluk</button>
                </div>
                <button className="btn" onClick={runEffects} disabled={effBusy !== null}>
                  {effBusy ? <><span className="spinner" /> {effBusy.done}/{effBusy.total}</> : "Playoff etkisini hesapla (ilk 25)"}
                </button>
              </>
            )}
          </div>
          {view !== "all" && results[view]?.message && <div className="banner" style={{ margin: 12 }}>{results[view]!.message}</div>}
          {view !== "all" && results[view] && (
            <div className="hint" style={{ padding: "8px 14px 0" }}>Senin stratejin bu yönde: <b>{results[view]!.strategy.name}</b>
              {results[view]!.limit_reached ? " · tarama bütçesi doldu" : ""}</div>
          )}
          {rows.length > 0 && (
            <div className="table-wrap">
              <table className="data">
                <thead><tr>
                  {view === "all" && <th className="l" title="Takasın bulunduğu yönler">Yön</th>}
                  <th className="l">Rakip</th><th className="l">Veriyorsun</th><th className="l">Alıyorsun</th>
                  {view !== "all" && <th title="Bu yönün stratejisine göre kazancın (rakip başına haftalık kategori)">Sen Δ</th>}
                  <th title="Seçili yönlerin kaçında senin kazancın pozitif (üstüne gel: yön yön)">Sağlamlık</th>
                  <th title="Ağırlıksız beklenen kategori değişimi (rakip başına haftalık)">Sen ΔECW</th>
                  <th title="Haftayı kazanma olasılığı değişimi (puan)">Sen P(5+)</th>
                  <th title="Rakibin (varsayılan stratejisiyle) kazancı">Rakip Δ</th>
                  <th className="l" title="En çok değişen 3 kategori (kazanma olasılığı, puan)">Kategori etkisi</th>
                  <th title="Fantezi playoff haftalarında kadronun toplam NBA maçı farkı (otomatik bırak/ekle dahil)">PO maç</th>
                  <th title="Kalan sezon değeri: küçük paket / büyük paket">Değer dengesi</th>
                  <th title="Rakibin gözünden (bu sezon + isim değeri): aldığı / verdiği. 1 = eşit görür.">Rakibin gözünde</th>
                  <th title="Rakip için kabul gerekçesi: modelde kazanıyor mu, kendi gözünde eşit ya da fazla alıyor mu. İkisi yüksek, biri orta. Olasılık değil.">Kabul gerekçesi</th>
                  <th title="Playoff olasılığı değişimi (puan)">Playoff</th><th title="Şampiyonluk olasılığı değişimi (puan)">Şamp.</th>
                  <th title="Rakibin playoff olasılığı değişimi">Rakip PO</th><th />
                </tr></thead>
                <tbody>
                  {rows.map((r) => {
                    const { s } = r;
                    const e = effects[r.key];
                    const key = new Set(s.key_players);
                    const rob = robustness(s);
                    const ecw = ecwOf(s);
                    const star = (id: string) => key.has(id) && <span className="badge q" title="Yanlış fiyatlanan oyuncu">★</span>;
                    return (
                      <tr key={r.key}>
                        {view === "all" && <td className="l">{r.dirs.map((d) => <span key={d} className="tag" title={dirInfo(d).label}>{dirInfo(d).tag}</span>)}</td>}
                        <td className="l">{s.team_b_name}</td>
                        <td className="l wrap">{s.give_a.map((p) => <div key={p.id}><PlayerName p={p} sub={false} />{star(p.id)}</div>)}</td>
                        <td className="l wrap">
                          {s.give_b.map((p) => <div key={p.id}><PlayerName p={p} sub={false} />{star(p.id)}</div>)}
                          {s.position_gap > 0 && <span className="badge out" title={`Takastan sonra ${s.position_gap} aktif pozisyon doldurulamıyor`}>⚠ pozisyon</span>}
                        </td>
                        {view !== "all" && <td className={deltaClass(s.own_delta, 0.3)}>{fmtDelta(s.own_delta, 3)}</td>}
                        <td title={rob.tip} className={rob.n === rob.total ? "good" : rob.n === 0 ? "bad" : ""}>{rob.n}/{rob.total}</td>
                        <td className={deltaClass(ecw, 0.3)}>{fmtDelta(ecw, 3)}</td>
                        <td>{fmtDelta(s.own_win * 100, 1)}</td>
                        <td className={deltaClass(s.other_delta, 0.3)}>{fmtDelta(s.other_delta, 3)}</td>
                        <td className="l"><CategoryChips deltas={s.my_categories} labels={labels} /></td>
                        <td className={s.playoff_games === null ? "muted" : s.playoff_games > 0 ? "good" : s.playoff_games < 0 ? "bad" : ""}>
                          {s.playoff_games === null ? "—" : fmtDelta(s.playoff_games, 0)}</td>
                        <td>{fmtPct(s.fairness)}</td>
                        <td>{fmtNum(s.perceived_view, 2)}</td>
                        <td><AcceptBadge level={s.acceptability} reasons={s.counterpart_reasons} /></td>
                        <td className={e && e !== "err" ? deltaClass(e.me_playoff, 0.1) : ""}>{e === "err" ? "—" : e ? fmtDelta(e.me_playoff * 100, 1) : ""}</td>
                        <td className={e && e !== "err" ? deltaClass(e.me_champion, 0.05) : ""}>{e === "err" ? "—" : e ? fmtDelta(e.me_champion * 100, 1) : ""}</td>
                        <td>{e === "err" ? "—" : e ? fmtDelta(e.opp_playoff * 100, 1) : ""}</td>
                        <td><button className="link-btn" onClick={() => open(r)}>Takas ekranında aç →</button></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {!rows.length && <div className="empty">Bu görünümde öneri yok.</div>}
          <div className="hint" style={{ padding: "0 14px 12px" }}>
            Δ: rakip başına haftalık beklenen kategori değişimi (kalan sezon). Sağlamlık: takas senin için kaç yönde kazançlı; yüksekse
            takas stratejin değişse de iyi kalır. Etiketler: {DIRECTIONS.map((d) => `${d.tag} = ${d.label}`).join(" · ")}. PO maç:
            playoff haftalarında kadronun toplam maç farkı (otomatik bırak/ekle ve sakatlık dönüşü dahil). Playoff etkisi aynı çekilişlerle takassız/takaslı sezon
            simülasyonudur (1000 simülasyon). Kabul gerekçesi: rakip modelde kazanıyor mu, kendi gözünde eşit ya da fazla alıyor mu;
            ikisi de yoksa paket listelenmez{rejectedReason ? ` (${rejectedReason} paket elendi)` : ""}. Karşılıklı faydada rakibin gözünde
            1,25'ten fazla alıyorsa (piyasa gözünde senin fazla ödemen) de listelenmez{rejectedOverpay ? ` (${rejectedOverpay} paket)` : ""}.
            Kabul olasılığı ölçülmez; olasılıklar kalibre edilmedi.
          </div>
        </div>
      )}
    </div>
  );
}
