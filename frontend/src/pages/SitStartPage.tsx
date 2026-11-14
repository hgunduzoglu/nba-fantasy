import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { ErrorBanner, Loading, PlayerName, deltaClass } from "../components/common";
import { BALANCED, StrategyPicker, toStrategyIn, type StrategyChoice } from "../components/StrategyPicker";
import { fmtDate, fmtDay, fmtDelta, fmtNum, fmtPct, fmtStamp } from "../format";
import { useIsMobile } from "../hooks";
import type { League, Meta, SitStartOut, SitStartPlayer, SitStartToday } from "../types";

interface Props {
  meta: Meta;
  league: League;
  team: string;
  injuries: boolean;
}

/** Bir maçın kategori olasılığı etkisi (puan, bir ondalık): en büyük üçü. */
function Effects({ p, labels }: { p: SitStartPlayer; labels: Record<string, string> }) {
  const items = Object.entries(p.dp).map(([c, d]) => ({ c, d: d * 100 }))
    .filter((x) => Math.abs(x.d) >= 0.2).sort((a, b) => Math.abs(b.d) - Math.abs(a.d)).slice(0, 3);
  if (!items.length) return <span className="muted">etkisiz</span>;
  return (
    <span className="catchips">
      {items.map((x) => (
        <span key={x.c} className={x.d > 0 ? "good" : "bad"}>{labels[x.c]} {x.d > 0 ? "+" : "−"}{Math.abs(x.d).toFixed(1)}</span>
      ))}
    </span>
  );
}

function Cell({ c }: { c: SitStartPlayer["cells"][number] }) {
  if (c.state === "start") return <span className="mark play" title="Aktif slotta oynar">{c.slot}</span>;
  if (c.state === "sit") return <span className="mark sit" title="Maçı var ama bu eşleşmede kategorilerine zarar veriyor: boş slot olsa da oturt">Otur</span>;
  if (c.state === "bench") return <span className="mark bench" title="Maçı var, aktif slot yok (daha değerliler oynuyor)">B</span>;
  if (c.state === "out") return <span className="mark out" title="Oynamaz (sakat / dönüş tarihi öncesi)">✕</span>;
  return null;
}

function TodayCard({ today }: { today: SitStartToday }) {
  const none = !today.start.length && !today.sit.length;
  return (
    <div className="card">
      <div className="card-h"><h3>Bugün ({fmtDay(today.day)}) Yahoo'da yapılacaklar</h3>
        <span className="muted">Yahoo'daki düzenin önerilenle karşılaştırıldı; maçı başlamış oyuncu değiştirilemez</span></div>
      <div className="card-b">
        {none && <div className="banner">Yahoo'daki düzenin önerilenle aynı; değişiklik gerekmiyor.</div>}
        {today.start.length > 0 && (
          <div className="stack-sm">
            <div className="section-title">Başlat</div>
            {today.start.map((r) => (
              <div key={r.id} className="todo-row"><span className="chip add">▲ {r.slot}</span> <PlayerName p={r} />
                <span className="muted"> · şu an {r.yahoo_slot || "kadroda yok"} · maç değeri {fmtDelta(r.value, 3)}</span></div>
            ))}
          </div>
        )}
        {today.sit.length > 0 && (
          <div className="stack-sm">
            <div className="section-title">Oturt (yedeğe al)</div>
            {today.sit.map((r) => (
              <div key={r.id} className="todo-row"><span className="chip drop">▼ BN</span> <PlayerName p={r} />
                <span className="muted"> · şu an {r.yahoo_slot} · {r.negative ? "bu eşleşmede kategorilerine zarar veriyor" : "daha değerlisi oynuyor"} ({fmtDelta(r.value, 3)})</span></div>
            ))}
          </div>
        )}
        <p className="hint">Maç değeri: oyuncunun bir maçının bu haftaki beklenen kategori galibiyetine katkısı.</p>
      </div>
    </div>
  );
}

export function SitStartPage({ meta, league, team, injuries }: Props) {
  const mobile = useIsMobile();
  const [week, setWeek] = useState<number | null>(null);
  const [strategy, setStrategy] = useState<StrategyChoice>(BALANCED);
  const [sitOut, setSitOut] = useState(true);
  const [qOut, setQOut] = useState(false);
  const [data, setData] = useState<SitStartOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const labels = useMemo(() => Object.fromEntries(meta.categories.map((c) => [c.key, c.label])), [meta]);

  useEffect(() => {
    setBusy(true);
    api.sitstart(league.id, { team, week, sit_out: sitOut, questionable_out: qOut, strategy: toStrategyIn(strategy), injuries })
      .then((d) => { setData(d); setError(null); })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  }, [league.id, team, week, sitOut, qOut, strategy, injuries]);

  if (!data && busy) return <Loading text="Kadro düzeni hesaplanıyor…" />;
  if (!data) return <ErrorBanner error={error} />;
  const gain = data.after.expected_wins - data.before.expected_wins;
  const sits = data.players.filter((p) => p.cells.some((c) => c.state === "sit"));
  const rows = [...data.players].sort((a, b) => b.games - a.games || b.value - a.value);
  const maxV = Math.max(0.02, ...data.players.map((p) => Math.abs(p.value)));

  return (
    <div className="stack">
      {mobile && data.today && <TodayCard today={data.today} />}
      <p className="desc">Her gün kim oynasın: oyuncunun bir maçının bu eşleşmede beklenen kategori galibiyetine katkısına göre.
        Maçı olan oyuncu slottan fazlaysa en değerliler oynar; oranlarda (FG%, FT%) ya da TO'da zarar veren oyuncu boş slot olsa da oturur.</p>
      <div className="toolbar" style={{ marginBottom: 0 }}>
        <label className="field"><span>Hafta</span>
          <select className="select" value={data.week} onChange={(e) => setWeek(Number(e.target.value))}>
            {data.weeks.map((w) => (
              <option key={w.week} value={w.week}>{w.week}. hafta · {fmtDate(w.start)}–{fmtDate(w.end)}{w.current ? " (bu hafta)" : ""}</option>
            ))}
          </select>
        </label>
        <StrategyPicker meta={meta} value={strategy} onChange={setStrategy} label="Senin stratejin" />
        <label className="check" title="O durumundakiler oynamaz; Q oynar; dönüş tarihi bilinen sakatlar o güne kadar oynamaz.">
          <input type="checkbox" checked={sitOut} onChange={(e) => setSitOut(e.target.checked)} /> O durumundakileri oynatma
        </label>
        <label className="check" title="Senaryo: Q / GTD / DTD durumundaki oyuncular bu hafta hiç oynamaz. Varsayılan model onları oynar sayar; gerçek oynama oranı ölçülmedi.">
          <input type="checkbox" checked={qOut} onChange={(e) => setQOut(e.target.checked)} /> Q/GTD de oynamasın (senaryo)
        </label>
        {busy && <span className="spinner" />}
      </div>
      <ErrorBanner error={error} />

      <div className="kpis">
        <div className="metric"><div className="k">Rakip</div><div className="v" style={{ fontSize: 16 }}>{data.opponent_name}</div>
          {data.live && <div className="d muted">Skor Yahoo'dan · {fmtStamp(data.live.captured_at)}</div>}</div>
        <div className="metric"><div className="k">Beklenen kategori (basit → önerilen)</div>
          <div className="v num">{fmtNum(data.before.expected_wins, 2)} → {fmtNum(data.after.expected_wins, 2)}</div>
          <div className={"d " + (gain > 0.005 ? "good" : "muted")}>{fmtDelta(gain, 2)}</div></div>
        <div className="metric"><div className="k">Haftayı kazanma P(5+)</div>
          <div className="v num">{fmtPct(data.before.p5)} → {fmtPct(data.after.p5)}</div></div>
        <div className="metric"><div className="k">Oturtulan maç (oran koruma)</div>
          <div className="v num">{sits.reduce((n, p) => n + p.cells.filter((c) => c.state === "sit").length, 0)}</div>
          <div className="d muted">{sits.map((p) => p.name).join(", ") || "yok"}</div></div>
      </div>

      {!mobile && data.today && <TodayCard today={data.today} />}

      <div className="card">
        <div className="card-h"><h3>Gün gün önerilen düzen</h3>
          <span className="muted">slot = oynar · Otur = zarar veriyor · B = slot yok · ✕ oynamaz</span></div>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr><th className="l">Oyuncu</th><th title="Yahoo'daki bugünkü slotu">Yahoo</th>
                {data.days.map((d) => <th key={d}>{fmtDay(d)}</th>)}
                <th title="Bir maçın bu haftaki beklenen kategori galibiyetine katkısı">Maç değeri</th>
                <th className="l" title="Bir maçın kategori kazanma olasılığına etkisi (puan)">Etkisi</th></tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id}>
                  <td className="l"><PlayerName p={p} /></td>
                  <td className="muted">{p.yahoo_slot ?? ""}</td>
                  {p.cells.map((c, i) => <td key={i}><Cell c={c} /></td>)}
                  <td className={p.games ? deltaClass(p.value, maxV) : ""}>{p.games ? fmtDelta(p.value, 3) : ""}</td>
                  <td className="l">{p.games ? <Effects p={p} labels={labels} /> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <p className="hint">Rakibin düzeni sabit varsayılır. Q/GTD oyuncular oynar sayılır: maç saatinden önce durumunu kontrol et.
        Değerler önerilen düzene göredir; bir oyuncuyu oturtmak diğerlerinin değerini de değiştirebilir.</p>
    </div>
  );
}
