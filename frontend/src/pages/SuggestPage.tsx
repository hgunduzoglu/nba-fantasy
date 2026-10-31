import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBanner, Loading, PlayerName, deltaClass } from "../components/common";
import { BALANCED, StrategyPicker, toStrategyIn, type StrategyChoice } from "../components/StrategyPicker";
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

type Effect = { me_playoff: number; me_champion: number; opp_playoff: number } | "err";

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
  const [strategy, setStrategy] = useState<StrategyChoice>(BALANCED);
  const [assume, setAssume] = useState<"balanced" | "punt1" | "punt2">("balanced");
  const [perceived, setPerceived] = useState<Perceived>("blend");
  const [minBalance, setMinBalance] = useState(0.9);
  const [minEdge, setMinEdge] = useState(1.0);
  const [packages, setPackages] = useState<string[]>(["1x1", "2x1", "1x2", "2x2"]);
  const [budget, setBudget] = useState(4000);
  const [minFair, setMinFair] = useState(0.55);
  const [result, setResult] = useState<SuggestOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mis, setMis] = useState<{ sell_high: MispricedRow[]; buy_low: MispricedRow[] } | null>(null);
  const [effects, setEffects] = useState<Record<number, Effect>>({});
  const [effBusy, setEffBusy] = useState(false);
  const [sortBy, setSortBy] = useState<"score" | "playoff">("score");

  useEffect(() => {
    if (mode === "mutual") return;
    api.mispricing(league.id, team, perceived, injuries).then(setMis).catch(() => setMis(null));
  }, [mode, league.id, team, perceived, injuries]);

  useEffect(() => {
    setResult(null);
    setEffects({});
  }, [mode, league.id, team]);

  const search = () => {
    setBusy(true);
    setError(null);
    setEffects({});
    api.suggest(league.id, {
      team, mode, opponent_assumption: assume, perceived, min_balance: minBalance, min_edge: minEdge, packages,
      max_evaluations: budget, min_fairness: minFair, min_gain: 0.005, auto_balance: true,
      strategy: toStrategyIn(strategy), injuries,
    }).then(setResult).catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };

  const runEffects = async () => {
    if (!result) return;
    setEffBusy(true);
    for (let i = 0; i < result.suggestions.length; i++) {
      const s = result.suggestions[i];
      try {
        const r = await api.season(league.id, {
          team_a: team, team_b: s.team_b, give_a: s.give_a.map((p) => p.id), give_b: s.give_b.map((p) => p.id),
          auto_balance: true, strategy_a: toStrategyIn(strategy),
          strategy_b: { name: s.other_strategy, weights: s.other_weights }, injuries, n_sims: 1000,
        });
        const e: Effect = { me_playoff: r.teams.a.playoff_after - r.teams.a.playoff_before,
                            me_champion: r.teams.a.champion_after - r.teams.a.champion_before,
                            opp_playoff: r.teams.b.playoff_after - r.teams.b.playoff_before };
        setEffects((x) => ({ ...x, [i]: e }));
      } catch {
        setEffects((x) => ({ ...x, [i]: "err" }));
      }
    }
    setEffBusy(false);
  };

  const rows = result ? result.suggestions.map((s, i) => ({ s, i })) : [];
  if (sortBy === "playoff") {
    const v = (i: number) => { const e = effects[i]; return e && e !== "err" ? e.me_champion + e.me_playoff : -9; };
    rows.sort((a, b) => v(b.i) - v(a.i));
  }
  const modeInfo = MODES.find((m) => m.id === mode)!;

  const open = (s: Suggestion) => onOpen({
    opp: s.team_b, giveA: s.give_a.map((p) => p.id), giveB: s.give_b.map((p) => p.id), stratA: strategy,
    stratB: s.other_weights.every((w) => w === 1) ? BALANCED : { kind: "custom", weights: s.other_weights },
  });

  return (
    <div className="stack">
      <div>
        <div className="seg" role="group" aria-label="Öneri türü">
          {MODES.map((m) => <button key={m.id} aria-pressed={mode === m.id} onClick={() => setMode(m.id)}>{m.label}</button>)}
        </div>
        <p className="desc" style={{ marginTop: 10 }}>{modeInfo.desc}</p>
      </div>

      <div className="card"><div className="card-b">
        <div className="toolbar" style={{ marginBottom: 0 }}>
          <StrategyPicker meta={meta} value={strategy} onChange={setStrategy} label="Senin stratejin" />
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
          <div className="field"><span>Paketler (ver × al)</span>
            <div className="seg">
              {PACKAGES.map((p) => (
                <button key={p} aria-pressed={packages.includes(p)}
                        onClick={() => setPackages((x) => x.includes(p) ? x.filter((y) => y !== p) : [...x, p])}>{p}</button>
              ))}
            </div>
          </div>
          <label className="field"><span>Taranacak paket</span>
            <input className="num-input" type="number" step={500} min={200} max={50000} value={budget}
                   onChange={(e) => setBudget(Number(e.target.value))} />
          </label>
          <button className="btn primary" onClick={search} disabled={busy || !packages.length}>
            {busy ? <><span className="spinner" /> Aranıyor…</> : "Önerileri bul"}
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
      {busy && <Loading text="Paketler taranıyor (birkaç saniye ile yarım dakika)…" />}
      {result && !busy && (
        <div className="card">
          <div className="card-h">
            <h2>{result.suggestions.length} öneri</h2>
            <span className="muted">{result.examined} paket tarandı · {result.eligible} eşikleri geçti{result.limit_reached ? " · bütçe doldu" : ""}</span>
            <span style={{ flex: 1 }} />
            {result.suggestions.length > 0 && (
              <>
                <div className="seg">
                  <button aria-pressed={sortBy === "score"} onClick={() => setSortBy("score")}>Öneri puanı</button>
                  <button aria-pressed={sortBy === "playoff"} onClick={() => setSortBy("playoff")}
                          disabled={!Object.keys(effects).length}>Playoff + şampiyonluk</button>
                </div>
                <button className="btn" onClick={runEffects} disabled={effBusy}>
                  {effBusy ? <><span className="spinner" /> {Object.keys(effects).length}/{result.suggestions.length}</> : "Playoff etkisini hesapla"}
                </button>
              </>
            )}
          </div>
          {result.message && <div className="banner" style={{ margin: 12 }}>{result.message}</div>}
          {result.suggestions.length > 0 && (
            <div className="table-wrap">
              <table className="data">
                <thead><tr>
                  <th className="l">Rakip</th><th className="l">Veriyorsun</th><th className="l">Alıyorsun</th>
                  <th title="Senin kalan sezon strateji kazancı (rakip başına haftalık kategori)">Sen Δ</th>
                  <th title="Rakibin (varsayılan stratejisiyle) kazancı">Rakip Δ</th>
                  <th>Sen P(5+)</th>
                  <th title="Kalan sezon değeri: küçük paket / büyük paket">Değer dengesi</th>
                  {mode !== "mutual" && <th title="Rakibin aldığı / verdiği algılanan değer">Rakibin gözünde</th>}
                  <th title="Playoff olasılığı değişimi (puan)">Playoff</th><th title="Şampiyonluk olasılığı değişimi (puan)">Şampiyonluk</th>
                  <th title="Rakibin playoff olasılığı değişimi">Rakip playoff</th><th />
                </tr></thead>
                <tbody>
                  {rows.map(({ s, i }) => {
                    const e = effects[i];
                    const key = new Set(s.key_players);
                    return (
                      <tr key={i}>
                        <td className="l">{s.team_b_name}</td>
                        <td className="l wrap">{s.give_a.map((p) => <div key={p.id}><PlayerName p={p} sub={false} />{key.has(p.id) && <span className="badge q" title="Yanlış fiyatlanan oyuncu">★</span>}</div>)}</td>
                        <td className="l wrap">{s.give_b.map((p) => <div key={p.id}><PlayerName p={p} sub={false} />{key.has(p.id) && <span className="badge q" title="Yanlış fiyatlanan oyuncu">★</span>}</div>)}</td>
                        <td className={deltaClass(s.own_delta, 0.3)}>{fmtDelta(s.own_delta, 3)}</td>
                        <td className={deltaClass(s.other_delta, 0.3)}>{fmtDelta(s.other_delta, 3)}</td>
                        <td>{fmtDelta(s.own_win * 100, 1)}</td>
                        <td>{fmtPct(s.fairness)}</td>
                        {mode !== "mutual" && <td>{fmtNum(s.perceived_balance, 2)}</td>}
                        <td className={e && e !== "err" ? deltaClass(e.me_playoff, 0.1) : ""}>{e === "err" ? "—" : e ? fmtDelta(e.me_playoff * 100, 1) : ""}</td>
                        <td className={e && e !== "err" ? deltaClass(e.me_champion, 0.05) : ""}>{e === "err" ? "—" : e ? fmtDelta(e.me_champion * 100, 1) : ""}</td>
                        <td>{e === "err" ? "—" : e ? fmtDelta(e.opp_playoff * 100, 1) : ""}</td>
                        <td><button className="link-btn" onClick={() => open(s)}>Takas ekranında aç →</button></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <div className="hint" style={{ padding: "0 14px 12px" }}>
            Δ: rakip başına haftalık beklenen kategori değişimi (kalan sezon). Playoff etkisi aynı çekilişlerle takassız/takaslı
            sezon simülasyonudur (1000 simülasyon). Kabul olasılığı ölçülmez; olasılıklar kalibre edilmedi.
          </div>
        </div>
      )}
    </div>
  );
}
