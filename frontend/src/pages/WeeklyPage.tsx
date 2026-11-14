import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { ErrorBanner, Loading, PlayerName, probClass } from "../components/common";
import { BALANCED, StrategyPicker, toStrategyIn, type StrategyChoice } from "../components/StrategyPicker";
import { fmtDate, fmtDay, fmtNum, fmtPct, fmtStamp, fmtStat } from "../format";
import { useIsMobile } from "../hooks";
import type { GridRow, League, Meta, Outlook, WeeklyIn, WeeklyOut } from "../types";

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

/** Telefon: kategori başına bir satır (sen, rakip, kazanma olasılığın). */
function CategoryList({ meta, o }: { meta: Meta; o: Outlook }) {
  return (
    <ul className="cat-list">
      <li className="head"><span /><span className="v">Sen</span><span className="v">Rakip</span><span style={{ textAlign: "center" }}>Kazanma</span></li>
      {meta.categories.map((c, i) => (
        <li key={c.key}>
          <span className="k">{c.label}</span>
          <span className="v pname">{fmtStat(c.key, o.totals.mine[c.key])}</span>
          <span className="v muted">{fmtStat(c.key, o.totals.opp[c.key])}</span>
          <span className={"p " + (probClass(o.p[i]) || "mid")}>{fmtPct(o.p[i])}</span>
        </li>
      ))}
    </ul>
  );
}

export function WeeklyPage({ meta, league, team, injuries }: Props) {
  const mobile = useIsMobile();
  const [week, setWeek] = useState<number | null>(null);
  const [opponent, setOpponent] = useState<string | null>(null);
  const [strategy, setStrategy] = useState<StrategyChoice>(BALANCED);
  const [sitOut, setSitOut] = useState(true);
  const [qOut, setQOut] = useState(false);
  const [accMine, setAccMine] = useState<Acc>(empty);
  const [accOpp, setAccOpp] = useState<Acc>(empty);
  const [data, setData] = useState<WeeklyOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  const hasAcc = (a: Acc) => Object.values(a).some((v) => v > 0);
  const body: WeeklyIn = useMemo(() => ({
    team, week, opponent, sit_out: sitOut, questionable_out: qOut, strategy: toStrategyIn(strategy), injuries,
    acc_mine: hasAcc(accMine) ? accMine : null, acc_opp: hasAcc(accOpp) ? accOpp : null,
  }), [team, week, opponent, sitOut, qOut, strategy, injuries, accMine, accOpp]);

  useEffect(() => {
    setBusy(true);
    const t = setTimeout(() => {
      api.weekly(league.id, body)
        .then((d) => { setData(d); setError(null); })
        .catch((e: Error) => setError(e.message))
        .finally(() => setBusy(false));
    }, 250);
    return () => clearTimeout(t);
  }, [league.id, body]);

  if (!data && busy) return <Loading text="Haftalık eşleşme hesaplanıyor…" />;
  if (!data) return <ErrorBanner error={error} />;
  const o = data.outlook;
  const myName = league.teams.find((t) => t.id === team)?.name ?? team;
  const swing = meta.categories.filter((_, i) => o.p[i] >= 0.25 && o.p[i] <= 0.75).map((c) => c.label);
  const live = data.live;
  const scoreTable = (
    <div className="table-wrap">
      <table className="data">
        <thead><tr><th className="l" />{ACC.map(([, l]) => <th key={l}>{l}</th>)}</tr></thead>
        <tbody>
          {([["Sen", accMine, setAccMine, live?.mine], [data.opponent_name, accOpp, setAccOpp, live?.opp]] as const).map(([name, acc, set, yahoo]) => (
            <tr key={name}><td className="l pname">{name}</td>
              {ACC.map(([k]) => (
                <td key={k}><input className="num-input" type="number" min={0} value={acc[k] || ""}
                  placeholder={yahoo?.[k] != null ? String(yahoo[k]) : ""}
                  onChange={(e) => set({ ...acc, [k]: Number(e.target.value) || 0 })} /></td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

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
        <label className="check" title="Senaryo: Q / GTD / DTD durumundaki oyuncular bu hafta hiç oynamaz. Varsayılan model onları oynar sayar; gerçek oynama oranı ölçülmedi.">
          <input type="checkbox" checked={qOut} onChange={(e) => setQOut(e.target.checked)} /> Q/GTD de oynamasın (senaryo)
        </label>
        {busy && <span className="spinner" />}
      </div>
      <ErrorBanner error={error} />

      {data.started && (
        <div className="card">
          <div className="card-h"><h3>Bu haftanın şu ana kadarki skoru</h3>
            {live && !live.manual
              ? <span className="muted">Yahoo'dan ({fmtStamp(live.captured_at)}) · kategori skoru {live.category_wins[0] ?? "–"}–{live.category_wins[1] ?? "–"}
                  {live.partial_today ? " · maçlar sürerken çekildi, bugünün kısmi skoru dahil" : ""} · düzeltmek için üzerine yaz</span>
              : <span className="muted">Yahoo matchup sayfasından gir ya da üstten "Yahoo'dan güncelle"; boş bırakırsan yalnızca kalan {data.days.length} gün hesaplanır</span>}
          </div>
          {mobile && live && !live.manual
            ? <details className="card-b"><summary>Toplamları gör · elle düzelt</summary>{scoreTable}</details>
            : <div className="card-b">{scoreTable}</div>}
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
        {mobile ? <CategoryList meta={meta} o={o} /> : <CategoryTable meta={meta} o={o} me={myName} opp={data.opponent_name} />}
      </div>

      <div className="card">
        <div className="card-h"><h3>Gün gün kadron</h3><span className="muted">▶ oynar · B yedekte · ✕ oynamaz</span></div>
        <Grid rows={o.grid.mine} labels={data.days.map(fmtDay)} />
      </div>
      <details className="card" style={{ padding: "10px 14px" }}>
        <summary>Rakibin gün gün kadrosu</summary>
        <Grid rows={o.grid.opp} labels={data.days.map(fmtDay)} />
      </details>

      <p className="hint">Bu haftanın alım planı ve tek hamleler: Add/Drop → Bu hafta. Günlük kim oynasın: Sit/Start.</p>
      {data.notes.length > 0 && <p className="hint">{data.notes.join(" ")}</p>}
    </div>
  );
}
