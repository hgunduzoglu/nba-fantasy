import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { AvailBadge, ErrorBanner, Loading, PlayerName, deltaClass, probClass } from "../components/common";
import { BALANCED, StrategyPicker, toStrategyIn, type StrategyChoice } from "../components/StrategyPicker";
import { fmtDate, fmtDelta, fmtNum, fmtPct } from "../format";
import type { AddDropWeekIn, AddDropWeekOut, CategoryKey, League, Meta } from "../types";
import { WaiverInfo } from "./FreeAgentsPage";

interface Props {
  meta: Meta;
  league: League;
  team: string;
  injuries: boolean;
}

type Mode = "win" | "critical";

/** Seçilen kategorilerdeki kazanma olasılığı değişimi toplamı (puan). */
const focusGain = (dp: Record<string, number>, keys: string[]) => keys.reduce((n, k) => n + (dp[k] ?? 0), 0) * 100;

export function WeekAddDropPage({ meta, league, team, injuries }: Props) {
  const [mode, setMode] = useState<Mode>("win");
  const [strategy, setStrategy] = useState<StrategyChoice>(BALANCED);
  const [cats, setCats] = useState<CategoryKey[] | null>(null);          // null: otomatik kritik kategoriler
  const [droppable, setDroppable] = useState<string[] | null>(null);
  const [used, setUsed] = useState<number | null>(null);
  const [data, setData] = useState<AddDropWeekOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  const body: AddDropWeekIn = useMemo(() => ({
    team, sit_out: true, injuries, strategy: toStrategyIn(strategy), mode, categories: mode === "critical" ? cats : null,
    droppable, used,
  }), [team, injuries, strategy, mode, cats, droppable, used]);

  useEffect(() => {
    setBusy(true);
    const t = setTimeout(() => {
      api.addDropWeek(league.id, body)
        .then((d) => { setData(d); setError(null); })
        .catch((e: Error) => setError(e.message))
        .finally(() => setBusy(false));
    }, 300);
    return () => clearTimeout(t);
  }, [league.id, body]);

  if (!data && busy) return <Loading text="Bu haftanın alım seçenekleri hesaplanıyor…" />;
  if (!data) return <ErrorBanner error={error} />;
  const chosen = data.chosen;
  const drops = droppable ?? data.droppable;
  const toggleCat = (k: CategoryKey) => {
    const cur = cats ?? chosen;
    const next = cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k];
    setCats(next.length ? next : null);
  };
  const maxGain = Math.max(0.02, ...data.singles.map((r) => Math.abs(r.d_expected_wins)));
  const labels = Object.fromEntries(meta.categories.map((c) => [c.key, c.label]));

  return (
    <div className="stack">
      <p className="desc">Bu haftanın eşleşmesi için alımlar: {data.opponent_name} karşısında kalan {data.days.length} gün
        ({fmtDate(data.days[0])}–{fmtDate(data.days[data.days.length - 1])}). Eklenen oyuncu bıraktığının yerini ve kalan günlerini alır;
        waiver'daki oyuncu serbest kaldığı günden önce planlanmaz.</p>
      <WaiverInfo data={{ ...data, adds_left: data.adds_left }} />
      <div className="toolbar" style={{ marginBottom: 0 }}>
        <div className="field"><span>Hedef</span>
          <div className="seg">
            <button aria-pressed={mode === "win"} onClick={() => setMode("win")}
                    title="Bu haftanın beklenen kategori galibiyeti (stratejinle)">Haftayı kazan</button>
            <button aria-pressed={mode === "critical"} onClick={() => setMode("critical")}
                    title="Yalnız seçilen kategorilere oyna (diğerleri ancak eşitlikte)">Kritik kategori</button>
          </div>
        </div>
        {mode === "win" && <StrategyPicker meta={meta} value={strategy} onChange={setStrategy} label="Senin stratejin" />}
        <label className="field"><span>Bu hafta kullandığın alım</span>
          <input className="num-input" type="number" min={0} max={data.adds_limit} value={used ?? data.adds_used}
                 onChange={(e) => setUsed(Math.max(0, Number(e.target.value) || 0))} />
        </label>
        {busy && <span className="spinner" />}
      </div>
      <ErrorBanner error={error} />

      <div className="card">
        <div className="card-h"><h3>Kategoriler: şu an ve oynanabilirlik</h3>
          <span className="muted">Kıpırdatılabilir = tek bir boştaki oyuncuyla kazanma olasılığında ulaşılabilecek artış{mode === "critical" ? " · tıkla: hedefe ekle/çıkar" : ""}</span></div>
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th className="l" />{data.categories.map((c) => (
              <th key={c.key} className={c.chosen && mode === "critical" ? "focus" : ""}
                  style={mode === "critical" ? { cursor: "pointer" } : undefined}
                  onClick={mode === "critical" ? () => toggleCat(c.key) : undefined}>
                {mode === "critical" ? (c.chosen ? "◉ " : "○ ") : ""}{c.label}</th>))}</tr></thead>
            <tbody>
              <tr><td className="l pname">Kazanma olasılığın</td>{data.categories.map((c) => <td key={c.key} className={probClass(c.p)}>{fmtPct(c.p)}</td>)}</tr>
              <tr><td className="l pname">Kıpırdatılabilir</td>{data.categories.map((c) => (
                <td key={c.key} className={c.leverage >= 0.02 ? "good" : "muted"}>{c.leverage >= 0.005 ? `+${(c.leverage * 100).toFixed(0)}` : "–"}</td>))}</tr>
            </tbody>
          </table>
        </div>
        <div className="hint" style={{ padding: "0 14px 12px" }}>
          {mode === "critical" ? <>Hedef: <b>{chosen.map((k) => labels[k]).join(" + ")}</b>{cats ? "" : " (otomatik: en çok kıpırdatılabilen)"}. </> : null}
          Beklenen kategori şu an {fmtNum(data.base.expected_wins, 2)} / 9, haftayı kazanma P(5+) {fmtPct(data.base.p5)}.
        </div>
      </div>

      <div className="card">
        <div className="card-h"><h3>Bırakılabilecek oyuncular</h3><span className="muted">varsayılan: kalan sezon değeri en düşük 3 aktif oyuncu</span></div>
        <div className="card-b">
          {data.active_roster.map((p) => {
            const on = drops.includes(p.id);
            return (
              <button key={p.id} className="chip" style={{ opacity: on ? 1 : 0.45, cursor: "pointer", border: 0, paddingRight: 10 }}
                      onClick={() => setDroppable(on ? drops.filter((y) => y !== p.id) : [...drops, p.id])}>
                {on ? "✓ " : ""}{p.name}
              </button>
            );
          })}
        </div>
      </div>

      <div className="card">
        <div className="card-h"><h3>Tek hamleler</h3><span className="muted">her boştaki oyuncu için en iyi bırakma eşi ve gün</span></div>
        <div className="table-wrap">
          <table className="data">
            <thead><tr>
              <th className="l">Al</th><th className="l">Bırak</th><th>Gün</th><th title="Bu hafta aktif slotta sayılan maç">Maç</th>
              <th title="Bu haftanın beklenen kategori galibiyeti değişimi">Δ beklenen kat.</th>
              {mode === "critical" && <th title="Hedef kategorilerde kazanma olasılığı değişimi (puan)">Δ hedef</th>}
              <th title="Haftayı kazanma P(5+) değişimi">Δ P(5+)</th>
              {meta.categories.map((c) => <th key={c.key}>{c.label}</th>)}
              <th title="Değişiklik kalıcı olsaydı kalan sezon strateji ECW'sine etkisi">Kalan sezon</th>
            </tr></thead>
            <tbody>
              {data.singles.map((r) => (
                <tr key={r.add.id}>
                  <td className="l"><PlayerName p={r.add} /><AvailBadge a={r.add.availability} /></td>
                  <td className="l"><PlayerName p={r.drop} sub={false} /></td>
                  <td>{fmtDate(r.day)}</td><td>{r.games}</td>
                  <td className={deltaClass(r.d_expected_wins, maxGain)}>{fmtDelta(r.d_expected_wins, 3)}</td>
                  {mode === "critical" && <td className={deltaClass(focusGain(r.dp, chosen), 20)}>{fmtDelta(focusGain(r.dp, chosen), 1)}</td>}
                  <td>{fmtDelta(r.d_p5 * 100, 1)}</td>
                  {meta.categories.map((c) => <td key={c.key} className={deltaClass(r.dp[c.key], 0.15)}>{Math.abs(r.dp[c.key]) >= 0.005 ? fmtDelta(r.dp[c.key] * 100, 0) : ""}</td>)}
                  <td className={r.ros_delta > 0.005 ? "good" : r.ros_delta < -0.005 ? "bad" : ""}>{fmtDelta(r.ros_delta, 3)}</td>
                </tr>
              ))}
              {!data.singles.length && <tr><td colSpan={meta.categories.length + 8} className="empty">Bu hafta maçı olan uygun oyuncu ya da bırakılacak oyuncu yok</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="card-h"><h3>Plan ({data.adds_left} alım hakkıyla)</h3><span className="muted">gün gün stream: eklenen oyuncu sonraki gün yeniden bırakılabilir</span></div>
        <div className="card-b">
          {data.adds_left === 0 && <div className="banner">Bu hafta alım hakkın kalmadı.</div>}
          {data.plan && data.plan.moves.length === 0 && <div className="banner">Bu haftayı belirgin iyileştiren bir alım bulunamadı.</div>}
          {data.plan && data.plan.moves.length > 0 && (
            <>
              <div className="banner">
                {data.plan.moves.length} alımla beklenen kategori {fmtNum(data.base.expected_wins, 2)} → <b>{fmtNum(data.plan.after.expected_wins, 2)}</b>,
                haftayı kazanma {fmtPct(data.base.p5)} → <b>{fmtPct(data.plan.after.p5)}</b>
              </div>
              <table className="data">
                <thead><tr><th className="l">Gün</th><th className="l">Bırak</th><th className="l">Al</th><th>Bu hafta maçı</th>
                  <th title="Değişiklik kalıcı olsaydı kalan sezon strateji ECW'sine etkisi">Kalıcı olsa kalan sezon</th></tr></thead>
                <tbody>
                  {data.plan.moves.map((m, i) => (
                    <tr key={i}>
                      <td className="l">{fmtDate(m.day)}</td><td className="l"><PlayerName p={m.drop} sub={false} /></td>
                      <td className="l"><PlayerName p={m.add} /><AvailBadge a={m.add.availability} /></td><td>{m.games}</td>
                      <td className={m.ros_delta > 0.005 ? "good" : m.ros_delta < -0.005 ? "bad" : ""}>{fmtDelta(m.ros_delta, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="hint">İşlemleri gün ve sırayla yap. Negatif kalan sezon etkisi: bırakılan oyuncuyu hafta sonunda geri almayı düşün
                (bırakılan oyuncu waiver'a düşer). FAB ligde waiver'daki oyuncu için teklif gerekir.</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
