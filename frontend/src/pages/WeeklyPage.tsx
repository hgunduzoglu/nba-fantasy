import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { ErrorBanner, Loading, PlayerName, probClass } from "../components/common";
import { BALANCED, StrategyPicker, toStrategyIn, type StrategyChoice } from "../components/StrategyPicker";
import { fmtDate, fmtDay, fmtDelta, fmtNum, fmtPct, fmtStat } from "../format";
import type { GridRow, League, Meta, Outlook, StreamOut, WeeklyIn, WeeklyOut } from "../types";

interface Props {
  meta: Meta;
  league: League;
  team: string;
  injuries: boolean;
}

const ACC = [["fgm", "FGM"], ["fga", "FGA"], ["ftm", "FTM"], ["fta", "FTA"], ["fg3m", "3PTM"], ["pts", "PTS"],
  ["reb", "REB"], ["ast", "AST"], ["stl", "ST"], ["blk", "BLK"], ["tov", "TO"]] as const;
type Acc = Record<string, number>;
const empty = (): Acc => Object.fromEntries(ACC.map(([k]) => [k, 0]));

function Grid({ rows, labels }: { rows: GridRow[]; labels: string[] }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead><tr><th className="l">Oyuncu</th>{labels.map((d) => <th key={d}>{d}</th>)}<th>Sayılan</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td className="l"><PlayerName p={r} /></td>
              {r.marks.map((m, i) => (
                <td key={i}>
                  {m === "▶" && <span className="mark play" title="Aktif kadroda oynar">▶</span>}
                  {m === "B" && <span className="mark bench" title="Maçı var ama aktif slot yok (yedek)">B</span>}
                  {m === "✕" && <span className="mark out" title="Oynamaz (sakat / dönüş tarihi öncesi)">✕</span>}
                </td>
              ))}
              <td className="pname">{r.counted}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CategoryTable({ meta, o, me, opp }: { meta: Meta; o: Outlook; me: string; opp: string }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead><tr><th className="l" />{meta.categories.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
        <tbody>
          <tr><td className="l pname">{me}</td>{meta.categories.map((c) => <td key={c.key}>{fmtStat(c.key, o.totals.mine[c.key])}</td>)}</tr>
          <tr><td className="l pname">{opp}</td>{meta.categories.map((c) => <td key={c.key}>{fmtStat(c.key, o.totals.opp[c.key])}</td>)}</tr>
          <tr><td className="l pname">Kazanma olasılığın</td>
            {o.p.map((p, i) => <td key={i} className={probClass(p)}>{fmtPct(p)}</td>)}</tr>
        </tbody>
      </table>
    </div>
  );
}

export function WeeklyPage({ meta, league, team, injuries }: Props) {
  const [week, setWeek] = useState<number | null>(null);
  const [opponent, setOpponent] = useState<string | null>(null);
  const [strategy, setStrategy] = useState<StrategyChoice>(BALANCED);
  const [sitOut, setSitOut] = useState(true);
  const [accMine, setAccMine] = useState<Acc>(empty);
  const [accOpp, setAccOpp] = useState<Acc>(empty);
  const [data, setData] = useState<WeeklyOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [used, setUsed] = useState(0);
  const [droppable, setDroppable] = useState<string[] | null>(null);
  const [plan, setPlan] = useState<StreamOut | null>(null);
  const [planBusy, setPlanBusy] = useState(false);

  const hasAcc = (a: Acc) => Object.values(a).some((v) => v > 0);
  const body: WeeklyIn = useMemo(() => ({
    team, week, opponent, sit_out: sitOut, strategy: toStrategyIn(strategy), injuries,
    acc_mine: hasAcc(accMine) ? accMine : null, acc_opp: hasAcc(accOpp) ? accOpp : null,
  }), [team, week, opponent, sitOut, strategy, injuries, accMine, accOpp]);

  useEffect(() => {
    setBusy(true);
    setPlan(null);
    const t = setTimeout(() => {
      api.weekly(league.id, body)
        .then((d) => { setData(d); setError(null); setDroppable((x) => x ?? d.default_droppable); })
        .catch((e: Error) => setError(e.message))
        .finally(() => setBusy(false));
    }, 250);
    return () => clearTimeout(t);
  }, [league.id, body]);

  const runPlan = () => {
    if (!data) return;
    setPlanBusy(true);
    api.stream(league.id, { ...body, used, droppable: droppable ?? [] })
      .then(setPlan).catch((e: Error) => setError(e.message)).finally(() => setPlanBusy(false));
  };

  if (!data && busy) return <Loading text="Haftalık eşleşme hesaplanıyor…" />;
  if (!data) return <ErrorBanner error={error} />;
  const o = data.outlook;
  const myName = league.teams.find((t) => t.id === team)?.name ?? team;
  const swing = meta.categories.filter((_, i) => o.p[i] >= 0.25 && o.p[i] <= 0.75).map((c) => c.label);
  const left = Math.max(0, data.acquisitions_limit - used);

  return (
    <div className="stack">
      <div className="toolbar" style={{ marginBottom: 0 }}>
        <label className="field"><span>Hafta</span>
          <select className="select" value={data.week} onChange={(e) => { setWeek(Number(e.target.value)); setOpponent(null); setAccMine(empty()); setAccOpp(empty()); }}>
            {data.weeks.map((w) => (
              <option key={w.week} value={w.week}>
                {w.week}. hafta · {fmtDate(w.start)}–{fmtDate(w.end)}{w.playoff ? " · playoff" : ""}{w.current ? " (bu hafta)" : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="field"><span>Rakip</span>
          <select className="select" value={data.opponent} onChange={(e) => setOpponent(e.target.value)}>
            {league.teams.filter((t) => t.id !== team).map((t) => (
              <option key={t.id} value={t.id}>{t.name}{t.id === data.fixture_opponent ? " (fikstür)" : ""}</option>
            ))}
          </select>
        </label>
        <StrategyPicker meta={meta} value={strategy} onChange={setStrategy} label="Senin stratejin" />
        <label className="check" title="NA (takımda değil) her zaman oynamaz; Q oynar; dönüş tarihi bilinen sakatlar o güne kadar oynamaz.">
          <input type="checkbox" checked={sitOut} onChange={(e) => setSitOut(e.target.checked)} /> O durumundakileri oynatma
        </label>
        {busy && <span className="spinner" />}
      </div>
      <ErrorBanner error={error} />

      {data.started && (
        <div className="card">
          <div className="card-h"><h3>Bu haftanın şu ana kadarki skoru</h3>
            <span className="muted">Yahoo matchup sayfasından gir; boş bırakırsan yalnızca kalan {data.days.length} gün hesaplanır</span></div>
          <div className="card-b table-wrap">
            <table className="data">
              <thead><tr><th className="l" />{ACC.map(([, l]) => <th key={l}>{l}</th>)}</tr></thead>
              <tbody>
                {([["Sen", accMine, setAccMine], [data.opponent_name, accOpp, setAccOpp]] as const).map(([name, acc, set]) => (
                  <tr key={name}><td className="l pname">{name}</td>
                    {ACC.map(([k]) => (
                      <td key={k}><input className="num-input" type="number" min={0} value={acc[k] || ""}
                        onChange={(e) => set({ ...acc, [k]: Number(e.target.value) || 0 })} /></td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="kpis">
        <div className="metric"><div className="k">Beklenen kategori</div><div className="v num">{fmtNum(o.expected_wins, 2)} / 9</div></div>
        <div className="metric"><div className="k">Haftayı kazanma P(5+)</div><div className="v num">{fmtPct(o.p5)}</div></div>
        <div className="metric"><div className="k">Sayılan maç (sen / rakip)</div><div className="v num">{o.counted.mine} / {o.counted.opp}</div></div>
        <div className="metric"><div className="k">Yedekte kalan maçın</div><div className="v num">{o.benched.mine}</div></div>
        <div className="metric"><div className="k">Kalan gün</div><div className="v num">{data.days.length}</div>
          <div className="d muted">{fmtDate(data.days[0])}–{fmtDate(data.days[data.days.length - 1])}</div></div>
      </div>

      <div className="card">
        <div className="card-h"><h3>Kategoriler — {myName} vs {data.opponent_name}</h3>
          <span className="muted">Çevrilebilir: {swing.length ? swing.join(", ") : "yok"}</span></div>
        <CategoryTable meta={meta} o={o} me={myName} opp={data.opponent_name} />
      </div>

      <div className="card">
        <div className="card-h"><h3>Gün gün kadron</h3><span className="muted">▶ oynar · B yedekte · ✕ oynamaz</span></div>
        <Grid rows={o.grid.mine} labels={data.days.map(fmtDay)} />
      </div>
      <details className="card" style={{ padding: "10px 14px" }}>
        <summary>Rakibin gün gün kadrosu</summary>
        <Grid rows={o.grid.opp} labels={data.days.map(fmtDay)} />
      </details>

      <div className="card">
        <div className="card-h"><h3>Streaming planı</h3><span className="muted">haftalık alım sınırı {data.acquisitions_limit}</span></div>
        <div className="card-b">
          <div className="toolbar">
            <label className="field"><span>Bu hafta kullandığın alım</span>
              <input className="num-input" type="number" min={0} max={data.acquisitions_limit} value={used}
                     onChange={(e) => setUsed(Math.max(0, Number(e.target.value) || 0))} />
            </label>
            <div className="field"><span>Bırakılabilecek oyuncular</span>
              <div>
                {data.active_roster.map((p) => {
                  const on = droppable?.includes(p.id) ?? false;
                  return (
                    <button key={p.id} className={"chip"} style={{ opacity: on ? 1 : 0.45, cursor: "pointer", border: 0, paddingRight: 10 }}
                            onClick={() => setDroppable((x) => on ? (x ?? []).filter((y) => y !== p.id) : [...(x ?? []), p.id])}>
                      {on ? "✓ " : ""}{p.name}
                    </button>
                  );
                })}
              </div>
            </div>
            <button className="btn primary" onClick={runPlan} disabled={planBusy || left === 0 || !droppable?.length}>
              {planBusy ? <><span className="spinner" /> Deneniyor…</> : `Planı hesapla (${left} alım)`}
            </button>
          </div>
          {plan && plan.moves.length === 0 && <div className="banner">Bu haftayı belirgin iyileştiren bir alım bulunamadı.</div>}
          {plan && plan.moves.length > 0 && (
            <>
              <div className="banner">
                {plan.moves.length} alımla beklenen kategori {fmtNum(plan.before.expected_wins, 2)} → <b>{fmtNum(plan.after.expected_wins, 2)}</b>,
                haftayı kazanma {fmtPct(plan.before.p5)} → <b>{fmtPct(plan.after.p5)}</b>
              </div>
              <table className="data">
                <thead><tr><th className="l">Gün</th><th className="l">Bırak</th><th className="l">Al</th><th>Bu hafta maçı</th>
                  <th title="Değişiklik kalıcı olsaydı kalan sezon strateji ECW'sine etkisi">Kalıcı olsa ROS etkisi</th></tr></thead>
                <tbody>
                  {plan.moves.map((m, i) => (
                    <tr key={i}>
                      <td className="l">{fmtDate(m.day)}</td><td className="l"><PlayerName p={m.drop} sub={false} /></td>
                      <td className="l"><PlayerName p={m.add} /></td><td>{m.games}</td>
                      <td className={m.ros_delta > 0.005 ? "good" : m.ros_delta < -0.005 ? "bad" : ""}>{fmtDelta(m.ros_delta, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="section-title">Plan sonrası kategoriler</div>
              <CategoryTable meta={meta} o={plan.after} me={myName} opp={data.opponent_name} />
              <p className="hint">İşlemleri gün ve sırayla yap; her satırda bırakılanın yerine yenisi gelir. Waiver'daki oyuncular,
                Can't Cut listesi ve maç saatleri doğrulanmadı. Negatif ROS etkisi: o oyuncuyu hafta sonunda geri almayı düşün.</p>
            </>
          )}
        </div>
      </div>
      {data.notes.length > 0 && <p className="hint">{data.notes.join(" ")}</p>}
    </div>
  );
}
