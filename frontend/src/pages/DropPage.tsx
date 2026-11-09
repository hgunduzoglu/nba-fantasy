import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { CategoryChips, ErrorBanner, Loading, PlayerName, deltaClass } from "../components/common";
import { BALANCED, StrategyPicker, toStrategyIn, type StrategyChoice } from "../components/StrategyPicker";
import { fmtDate, fmtDelta, fmtNum, fmtPct } from "../format";
import { useIsMobile } from "../hooks";
import type { DropIL, DropIn, DropOut, DropRow, League, Meta } from "../types";

interface Props {
  meta: Meta;
  league: League;
  team: string;
  injuries: boolean;
}

type Sort = "ros" | "week";

/** Kalan sezonda öneriye göre ek kayıp bu kadardan azsa iki seçenek "neredeyse eşit" sayılır. */
const CLOSE = 0.02;

const signClass = (d: number, eps = 0.005) => (d > eps ? "good" : d < -eps ? "bad" : "");

function ilNote(p: DropIL): string {
  if (p.season) return "sezon dışı";
  if (p.return_date) return `dönüş ${fmtDate(p.return_date)}`;
  return p.status === "O" || p.status === "INJ" ? "tarih yok" : "sağlıklı";
}

function Tags({ r, rec }: { r: DropRow; rec: boolean }) {
  return (
    <>
      {rec && <span className="badge fa" title="Pozisyonu bozmayan, kalan sezon kaybı en düşük seçenek">öneri</span>}
      {r.returning && <span className="badge mine" title="IL'den dönen oyuncu: kendisini bırakmak da bir seçenek">dönen</span>}
      {r.open_slots > 0 && <span className="badge out" title="Bırakınca bir aktif pozisyon doldurulamaz">pozisyon açığı</span>}
    </>
  );
}

export function DropPage({ meta, league, team, injuries }: Props) {
  const mobile = useIsMobile();
  const labels = Object.fromEntries(meta.categories.map((c) => [c.key, c.label]));
  const [strategy, setStrategy] = useState<StrategyChoice>(BALANCED);
  const [activate, setActivate] = useState<string[] | null>(null);       // null: dönen/dönmek üzere olanlar
  const [sort, setSort] = useState<Sort>("ros");
  const [data, setData] = useState<DropOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  useEffect(() => setActivate(null), [league.id, team]);

  const body: DropIn = useMemo(() => ({ team, sit_out: true, injuries, strategy: toStrategyIn(strategy), activate }),
    [team, injuries, strategy, activate]);

  useEffect(() => {
    setBusy(true);
    const t = setTimeout(() => {
      api.drops(league.id, body)
        .then((d) => { setData(d); setError(null); })
        .catch((e: Error) => setError(e.message))
        .finally(() => setBusy(false));
    }, 250);
    return () => clearTimeout(t);
  }, [league.id, body]);

  if (!data && busy) return <Loading text="Bırakma seçenekleri hesaplanıyor…" />;
  if (!data) return <ErrorBanner error={error} />;

  const acts = data.activate;
  const toggle = (id: string) => setActivate(acts.includes(id) ? acts.filter((x) => x !== id) : [...acts, id]);
  const rec = new Set(data.recommended);
  const best = Math.min(...data.rows.map((r) => r.ros_loss));
  const extra = (r: DropRow) => r.ros_loss - best;                         // öneriye göre kalan sezon ek kaybı
  const rows = sort === "ros" ? data.rows
    : [...data.rows].sort((a, b) => a.week_loss - b.week_loss || a.ros_loss - b.ros_loss);
  const recRows = data.rows.filter((r) => rec.has(r.player.id));
  const alt = data.rows.find((r) => !rec.has(r.player.id) && r.open_slots === 0);
  const weekBest = data.rows.reduce<DropRow | null>((m, r) => (!m || r.week_loss < m.week_loss ? r : m), null);
  const total = data.active_count + acts.length;
  const lastDay = data.days[data.days.length - 1];

  const advice = recRows.length > 0 && (
    <div className="card">
      <div className="card-h"><h3>{data.need > 1 ? `Önerilen: ${data.need} oyuncu bırak` : "Önerilen bırakma"}</h3>
        <span className="muted">pozisyonu bozmayan, kalan sezonda en az kayıp ({data.objective})</span></div>
      <div className="card-b">
        <ul className="m-list">
          {recRows.map((r) => (
            <li key={r.player.id} className="m-item">
              <div className="m-line"><span className="m-lbl drop">Bırak</span><PlayerName p={r.player} /><Tags r={r} rec={false} /></div>
              <div className="m-line">
                <span className="m-kv">bu haftaya etkisi <b className={signClass(r.week_d_expected)}>{fmtDelta(r.week_d_expected, 2)}</b> beklenen kategori</span>
                <span className="m-kv">maç: bu hafta <b>{r.games_left}</b> · gelecek <b>{r.games_next}</b></span>
                {r.player.rank != null && <span className="m-kv">değer sırası <b>#{Math.round(r.player.rank)}</b></span>}
              </div>
              {r.replacement && (
                <div className="m-line hint">Boşta ondan iyisi var: <b>{r.replacement.add.name}</b> (kalan sezon {fmtDelta(r.replacement.score, 3)}).
                  Alım hakkın varsa sonra onu da alabilirsin.</div>
              )}
            </li>
          ))}
        </ul>
        <p className="hint">
          {data.need === 0 && "Şu an yer var, bırakman gerekmiyor; liste yalnızca kimin en az değerli olduğunu gösteriyor. "}
          {data.need <= 1 && alt && extra(alt) < CLOSE && <>Neredeyse eşit seçenek: <b>{alt.player.name}</b> (kalan sezonda haftada {fmtNum(extra(alt), 3)} kategori fark). </>}
          {weekBest && !rec.has(weekBest.player.id) && recRows.every((r) => r.week_loss - weekBest.week_loss > 0.03) && (
            <>Yalnızca bu haftayı düşünürsen <b>{weekBest.player.name}</b> daha az kaybettirir
              ({fmtDelta(weekBest.week_d_expected, 2)} beklenen kategori). </>
          )}
        </p>
      </div>
    </div>
  );

  return (
    <div className="stack">
      <p className="desc">IL'den dönen oyuncuya yer açarken kimi bırakmalısın. Kadrondaki her oyuncu (dönenin kendisi dahil) için kalan sezona
        ve bu haftaki eşleşmeye ({data.opponent_name}, {fmtDate(data.days[0])}–{fmtDate(lastDay)}) etkisi.</p>
      <div className="toolbar" style={{ marginBottom: 0 }}>
        <StrategyPicker meta={meta} value={strategy} onChange={setStrategy} label="Senin stratejin" />
        <div className="field"><span>Sırala</span>
          <div className="seg">
            <button aria-pressed={sort === "ros"} onClick={() => setSort("ros")} title="Bırakma kalıcı: varsayılan">Kalan sezon</button>
            <button aria-pressed={sort === "week"} onClick={() => setSort("week")} title="Yalnızca bu haftaki eşleşme">Bu hafta</button>
          </div>
        </div>
        {busy && <span className="spinner" />}
      </div>
      <ErrorBanner error={error} />

      <div className="card">
        <div className="card-h"><h3>Dönen oyuncular</h3><span className="muted">işaretli olan aktif kadroya alınır</span></div>
        <div className="card-b">
          {data.il.length === 0 && <div className="muted">IL'de oyuncun yok.</div>}
          {data.il.map((p) => {
            const on = acts.includes(p.id);
            return (
              <button key={p.id} className="chip" aria-pressed={on} onClick={() => toggle(p.id)}
                      style={{ opacity: on ? 1 : 0.5, cursor: "pointer", border: 0, paddingRight: 10 }}
                      title={p.injury?.text || undefined}>
                {on ? "✓ " : ""}{p.name}<span className="psub">{ilNote(p)}</span>
              </button>
            );
          })}
          <div className={"banner" + (data.need > 0 ? " warn" : "")} style={{ marginTop: 10 }}>
            Aktif kadro {data.active_count}{acts.length ? ` + ${acts.length} dönen` : ""} = {total} / {data.capacity}
            {data.need > 0 ? <> · <b>{data.need} oyuncu bırakmalısın</b></> : " · yer var"}
          </div>
          <p className="hint">Varsayılan işaret: dönüşü 2 gün içinde olan ya da artık sakat görünmeyen IL oyuncuları.
            Bu hafta şu an beklenen kategori {fmtNum(data.base.expected_wins, 2)} / 9, P(5+) {fmtPct(data.base.p5)} (dönenler dahil).</p>
        </div>
      </div>

      {advice}

      <div className="card">
        <div className="card-h"><h3>Bütün seçenekler</h3>
          <span className="muted">{sort === "ros" ? "kalan sezon kaybına göre (az → çok)" : "bu haftaki kayba göre (az → çok)"}</span></div>
        {mobile && (
          <ul className="m-list">
            {rows.map((r) => (
              <li key={r.player.id} className="m-item">
                <div className="m-line"><PlayerName p={r.player} /><Tags r={r} rec={rec.has(r.player.id)} />
                  <span className="spacer" />{r.player.rank != null && <span className="m-kv">#{Math.round(r.player.rank)}</span>}</div>
                <div className="m-line">
                  <span className={"m-big " + (extra(r) < 0.005 ? "good" : extra(r) > 0.1 ? "bad" : "")}>{extra(r) < 0.0005 ? "en az" : fmtDelta(-extra(r), 3)}</span>
                  <span className="m-kv">kalan sezon</span>
                  <span className="m-kv">bu hafta <b className={signClass(r.week_d_expected)}>{fmtDelta(r.week_d_expected, 2)}</b> kat.</span>
                </div>
                <div className="m-line">
                  <span className="m-kv">maç: bu hafta <b>{r.games_left}</b> · gelecek <b>{r.games_next}</b></span>
                  <span className="spacer" /><CategoryChips deltas={r.ros_dp} labels={labels} />
                </div>
                {r.replacement && <div className="m-line hint">Boşta ondan iyisi var: <b>{r.replacement.add.name}</b></div>}
              </li>
            ))}
          </ul>
        )}
        <div className={"table-wrap" + (mobile ? " only-desktop" : "")}>
          <table className="data">
            <thead><tr>
              <th className="l">Bırak</th>
              <th title="Ligdeki genel kalan sezon değer sırası">Sıra</th>
              <th title="Önerilen seçeneğe göre kalan sezonda haftalık ek kayıp (stratejinle, ortalama rakibe karşı kategori)">Kalan sezon</th>
              <th title="Bu haftanın beklenen kategori galibiyeti değişimi">Bu hafta Δ kat.</th>
              <th title="Haftayı kazanma P(5+) değişimi">Δ P(5+)</th>
              <th title="Bu haftanın kalan günlerinde / gelecek hafta NBA maçı">Maç</th>
              <th className="l" title="Bırakınca kalan sezonda en çok kaybettiğin kategoriler (puan)">Kaybedilen kategoriler</th>
              <th className="l" title="Kalan sezonda ondan iyi boştaki oyuncu">Boşta daha iyisi</th>
            </tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.player.id} className={rec.has(r.player.id) ? "rec" : ""}>
                  <td className="l"><PlayerName p={r.player} /><Tags r={r} rec={rec.has(r.player.id)} /></td>
                  <td>{r.player.rank != null ? `#${Math.round(r.player.rank)}` : "–"}</td>
                  <td className={extra(r) < 0.0005 ? "good" : deltaClass(-extra(r), 0.4)}>{extra(r) < 0.0005 ? "en az" : fmtDelta(-extra(r), 3)}</td>
                  <td className={deltaClass(r.week_d_expected, 0.15)}>{fmtDelta(r.week_d_expected, 3)}</td>
                  <td>{fmtDelta(r.week_d_p5 * 100, 1)}</td>
                  <td>{r.games_left} · {r.games_next}</td>
                  <td className="l"><CategoryChips deltas={r.ros_dp} labels={labels} /></td>
                  <td className="l">{r.replacement ? <PlayerName p={r.replacement.add} sub={false} /> : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="hint" style={{ padding: "0 14px 12px" }}>
          Kalan sezon: önerilen seçeneğe göre haftada kaç kategori daha fazla kaybettiğin (stratejinle, ligdeki ortalama rakibe karşı).
          Bu hafta: {data.opponent_name} eşleşmesinde beklenen kategori değişimi (kadroda yer yoksa oturan oyuncunun etkisi 0).
          Bırakılan oyuncu waiver'a düşer; değer sırası yüksekse başkası alabilir.
        </div>
      </div>
    </div>
  );
}
