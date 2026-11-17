import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { fmtPct } from "../format";
import type { IndexPlayer, League, Meta, ScenarioCheckOut, ScenarioEffectOut } from "../types";
import { addTrade, hasItems, isActive, setWhatIf, summary, useWhatIf, type WhatIf } from "../whatif";

const signed = (v: number) => `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}`;

/** Senaryo çubuğu (README §13.53): açıkken bütün sayfalar bekleyen takasları ve rol çarpanlarını varsayarak hesaplar.
 *  Panelden başka takımlar arası takas, rol çarpanı eklenir; senaryonun sezon etkisi gerçek durumla karşılaştırılır. */
export function ScenarioBar({ meta, league, team, injuries }: { meta: Meta; league: League; team: string; injuries: boolean }) {
  const w = useWhatIf();
  const [open, setOpen] = useState(false);
  const [check, setCheck] = useState<ScenarioCheckOut | null>(null);
  useEffect(() => {
    if (!hasItems(w)) { setCheck(null); return; }
    let live = true;
    api.scenarioCheck(w, injuries).then((c) => { if (live) setCheck(c); }).catch(() => { if (live) setCheck(null); });
    return () => { live = false; };
  }, [w, injuries]);
  const problems = (check?.trades ?? []).filter((s) => s.status !== "applied").length
    + (check?.roles ?? []).filter((r) => r.status !== "applied").length;
  const leagueName = (id: string) => meta.leagues.find((l) => l.id === id)?.name ?? id;

  if (!hasItems(w) && !open) {
    return (
      <div className="toolbar" style={{ justifyContent: "flex-end", marginBottom: 4 }}>
        <button className="link-btn muted" onClick={() => setOpen(true)}
                title="Bekleyen takasları geçmiş say, oyuncu rolünü değiştir; bütün sayfalar buna göre hesaplanır">
          ＋ Senaryo (bekleyen takas, rol çarpanı)
        </button>
      </div>
    );
  }
  return (
    <div className={"banner " + (isActive(w) ? (problems ? "err" : "warn") : "")}>
      <div className="toolbar" style={{ marginBottom: 0, alignItems: "center" }}>
        <b>🧪 Senaryo {isActive(w) ? "açık" : "kapalı"}</b>
        {hasItems(w) && <span>{summary(w)}{isActive(w) ? " — bütün sayfalar buna göre hesaplanıyor" : ""}</span>}
        {problems > 0 && <span className="badge out">{problems} adım uygulanamadı</span>}
        <span className="spacer" style={{ flex: 1 }} />
        {hasItems(w) && (
          <button className="btn" onClick={() => setWhatIf({ ...w, enabled: !w.enabled })}>{w.enabled ? "Kapat" : "Aç"}</button>
        )}
        <button className="btn" onClick={() => setOpen((x) => !x)}>{open ? "Gizle" : "Düzenle"}</button>
        {hasItems(w) && <button className="btn" onClick={() => setWhatIf({ enabled: true, trades: [], roles: {} })}>Temizle</button>}
      </div>
      {open && (
        <div className="stack" style={{ gap: 12, marginTop: 10 }}>
          <div>
            <div className="section-title" style={{ marginTop: 0 }}>Takaslar (sırayla uygulanır; her biri bir öncekinin sonucuna)</div>
            {!w.trades.length && <div className="muted">Takas yok. Takas Analizi'nde "Geçti say" ya da aşağıdaki form.</div>}
            <ol style={{ margin: "4px 0 0 18px" }}>
              {w.trades.map((t, k) => {
                const st = check?.trades.find((s) => s.index === k);
                return (
                  <li key={k}>
                    <span className="muted">{leagueName(t.league)}:</span> {t.label}{" "}
                    {st && <span className={"badge " + (st.status === "applied" ? "fa" : "out")}>
                      {st.status === "applied" ? "uygulandı" : st.status === "skipped" ? "atlandı" : "hata"}</span>}
                    {st?.reason && <span className="muted"> {st.reason}</span>}
                    {st?.moves && Object.keys(st.moves).length > 0 && (
                      <span className="muted"> · {Object.entries(st.moves).map(([tm, m]) =>
                        `${tm}: ${Object.entries(m).map(([kind, ns]) => `${{ drop: "bırak", add: "al", move_to_il: "IL'e", activate: "aktife" }[kind] ?? kind} ${ns?.join(", ")}`).join("; ")}`).join(" · ")}</span>
                    )}
                    <button className="link-btn" aria-label="kaldır" onClick={() => setWhatIf({ ...w, trades: w.trades.filter((_, i) => i !== k) })}> ✕</button>
                  </li>
                );
              })}
            </ol>
          </div>
          <TradeForm league={league} injuries={injuries} w={w} />
          <RoleForm league={league} injuries={injuries} w={w} check={check} />
          {isActive(w) && <Effect league={league} team={team} injuries={injuries} />}
        </div>
      )}
    </div>
  );
}

function useIndex(league: string, injuries: boolean, w: WhatIf) {
  const [rows, setRows] = useState<IndexPlayer[]>([]);
  useEffect(() => {
    let live = true;
    api.playersIndex(league, injuries).then((r) => { if (live) setRows(r); }).catch(() => { if (live) setRows([]); });
    return () => { live = false; };
  }, [league, injuries, w]);
  return rows;
}

/** Başka iki takım arasındaki (ya da kendi) bekleyen takas: iki kadrodan oyuncu seç; kadro otomatik dengelenir. */
function TradeForm({ league, injuries, w }: { league: League; injuries: boolean; w: WhatIf }) {
  const index = useIndex(league.id, injuries, w);
  const [a, setA] = useState(league.teams[0]?.id ?? "");
  const [b, setB] = useState(league.teams[1]?.id ?? "");
  const [ga, setGa] = useState<string[]>([]);
  const [gb, setGb] = useState<string[]>([]);
  const [auto, setAuto] = useState(true);
  const roster = (t: string) => index.filter((p) => p.team_id === t);
  const name = (id: string) => index.find((p) => p.id === id)?.name ?? id;
  const tname = (id: string) => league.teams.find((t) => t.id === id)?.name ?? id;
  const pick = (list: string[], set: (x: string[]) => void, id: string) =>
    set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  const add = () => {
    addTrade({ league: league.id, team_a: a, team_b: b, give_a: ga, give_b: gb, drop_a: [], drop_b: [], add_a: [], add_b: [], auto,
               label: `${tname(a)}: ${ga.map(name).join(", ")} ⇄ ${tname(b)}: ${gb.map(name).join(", ")}` });
    setGa([]); setGb([]);
  };
  const side = (t: string, set: (x: string) => void, list: string[], setList: (x: string[]) => void) => (
    <div style={{ minWidth: 220, flex: 1 }}>
      <select className="select" value={t} onChange={(e) => { set(e.target.value); setList([]); }}>
        {league.teams.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
      </select>
      <div style={{ maxHeight: 180, overflow: "auto", marginTop: 4 }}>
        {roster(t).map((p) => (
          <label key={p.id} className="check" style={{ display: "flex" }}>
            <input type="checkbox" checked={list.includes(p.id)} onChange={() => pick(list, setList, p.id)} />
            {p.name} <span className="muted">{p.nba_team}{p.status ? ` · ${p.status}` : ""}{p.il ? " · IL" : ""}</span>
          </label>
        ))}
      </div>
    </div>
  );
  return (
    <div>
      <div className="section-title" style={{ marginTop: 0 }}>Bekleyen takas ekle ({league.name})</div>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        {side(a, setA, ga, setGa)}
        {side(b, setB, gb, setGb)}
      </div>
      <div className="toolbar" style={{ marginTop: 6, marginBottom: 0 }}>
        <label className="check" title="Eşit olmayan pakette sakat IL'e, sonra en düşük değerli bırakılır; boşluk boştakiyle dolar">
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> Kadroyu otomatik dengele
        </label>
        <button className="btn primary" disabled={!ga.length || !gb.length || a === b} onClick={add}>Takası ekle</button>
      </div>
    </div>
  );
}

/** Rol çarpanı: oyuncunun kalan sezon üretimi × çarpan (ör. ilk beşe girerse 1.5–2). Rakibin algısı değişmez. */
function RoleForm({ league, injuries, w, check }: { league: League; injuries: boolean; w: WhatIf; check: ScenarioCheckOut | null }) {
  const index = useIndex(league.id, injuries, w);
  const [text, setText] = useState("");
  const [factor, setFactor] = useState("1.5");
  const byName = useMemo(() => new Map(index.map((p) => [p.name, p])), [index]);
  const chosen = byName.get(text);
  const f = Number(factor);
  const add = () => {
    if (!chosen || !(f >= 0.25 && f <= 3)) return;
    setWhatIf({ ...w, enabled: true, roles: { ...w.roles, [chosen.id]: { factor: f, name: chosen.name } } });
    setText("");
  };
  return (
    <div>
      <div className="section-title" style={{ marginTop: 0 }}>Rol çarpanı (kalan sezon üretimi × çarpan; maç sayısı ve yüzdeler aynı)</div>
      {Object.entries(w.roles).map(([id, r]) => {
        const st = check?.roles.find((x) => x.player_id === id);
        return (
          <span key={id} className="chip">{r.name} ×{r.factor}
            {st?.status === "error" && <span className="badge out" title={st.reason}>etkisiz</span>}
            <button aria-label="kaldır" onClick={() => { const { [id]: _drop, ...rest } = w.roles; setWhatIf({ ...w, roles: rest }); }}>×</button>
          </span>
        );
      })}
      <div className="toolbar" style={{ marginTop: 6, marginBottom: 0 }}>
        <input className="select" list="whatif-players" placeholder="Oyuncu adı" value={text} onChange={(e) => setText(e.target.value)} />
        <datalist id="whatif-players">{index.map((p) => <option key={p.id} value={p.name} />)}</datalist>
        <input className="select" type="number" min={0.25} max={3} step={0.05} value={factor} style={{ width: 80 }}
               onChange={(e) => setFactor(e.target.value)} />
        <button className="btn" disabled={!chosen || !(f >= 0.25 && f <= 3)} onClick={add}>Ekle</button>
        <span className="hint" style={{ marginTop: 0 }}>0.25–3; ör. 2 = üretim iki katı</span>
      </div>
    </div>
  );
}

/** Senaryonun sezon etkisi: gerçek durum ile senaryo aynı tohumla; bütün takımlar, en çok etkilenen önce. */
function Effect({ league, team, injuries }: { league: League; team: string; injuries: boolean }) {
  const [out, setOut] = useState<ScenarioEffectOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = () => {
    setBusy(true); setError(null);
    const other = league.teams.find((t) => t.id !== team)?.id ?? team;
    api.scenarioEffect(league.id, { team_a: team, team_b: other, injuries, n_sims: 2000 })
      .then(setOut).catch((e) => setError(String(e.message ?? e))).finally(() => setBusy(false));
  };
  const rows = (out?.teams ?? []).slice().sort((x, y) =>
    Number(y.team_id === team) - Number(x.team_id === team) || Math.abs(y.playoff?.delta ?? 0) - Math.abs(x.playoff?.delta ?? 0));
  return (
    <div>
      <div className="toolbar" style={{ marginBottom: 4 }}>
        <button className="btn" onClick={run} disabled={busy}>{busy ? <><span className="spinner" /> Simülasyon…</> : `Sezon etkisi (${league.name})`}</button>
        <span className="hint" style={{ marginTop: 0 }}>Gerçek durum ile senaryo, 2000 simülasyon; ±1–1,5 puan gürültü.</span>
      </div>
      {error && <div className="banner err">{error}</div>}
      {out && (
        <table className="data">
          <thead><tr><th className="l">Takım</th><th>Playoff</th><th>Δ</th><th>Şampiyonluk</th><th>Δ</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.team_id} style={r.team_id === team ? { fontWeight: 600 } : undefined}>
                <td className="l">{r.team}</td>
                <td>{r.playoff ? `${fmtPct(r.playoff.before)} → ${fmtPct(r.playoff.after)}` : "–"}</td>
                <td className={r.playoff && r.playoff.delta > 0 ? "good" : ""}>{r.playoff ? signed(r.playoff.delta) : "–"}</td>
                <td>{r.champion ? `${fmtPct(r.champion.before, 1)} → ${fmtPct(r.champion.after, 1)}` : "–"}</td>
                <td>{r.champion ? signed(r.champion.delta) : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
