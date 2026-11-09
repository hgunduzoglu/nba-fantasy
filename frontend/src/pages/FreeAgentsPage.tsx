import { useEffect, useState } from "react";
import { api } from "../api";
import { AvailBadge, CategoryChips, ErrorBanner, Loading, PlayerName, deltaClass } from "../components/common";
import { useIsMobile } from "../hooks";
import { BALANCED, StrategyPicker, toStrategyIn, type StrategyChoice } from "../components/StrategyPicker";
import { GpCell, StatusBadges } from "../components/RosterTable";
import { fmtDelta, fmtStat, zClass } from "../format";
import type { League, Meta, WaiverOut } from "../types";

const POSITIONS = ["Hepsi", "PG", "SG", "G", "SF", "PF", "F", "C"];

/** Alım hakkı, FAB ve waiver kuralı (Yahoo senkronizasyonundan). */
export function WaiverInfo({ data }: { data: { adds_left: number | null; fab: number | null; synced: boolean;
  waiver_time: string | null; waiver_type: string | null } }) {
  const parts = [
    data.adds_left != null ? `Bu hafta ${data.adds_left} alım hakkın kaldı` : null,
    data.fab != null ? `FAB bütçen $${data.fab}` : null,
    data.waiver_time ? `Waiver süresi: ${data.waiver_time}${data.waiver_type ? ` (${data.waiver_type})` : ""}` : null,
  ].filter(Boolean);
  return (
    <div className="banner" style={{ marginTop: -6 }}>
      {parts.join(" · ")}{!data.synced && " · Yahoo senkronizasyonu yok: waiver durumu bilinmiyor, herkes FA sayıldı"}
    </div>
  );
}

export function FreeAgentsPage({ meta, league, team, injuries }: { meta: Meta; league: League; team: string; injuries: boolean }) {
  const mobile = useIsMobile();
  const labels = Object.fromEntries(meta.categories.map((c) => [c.key, c.label]));
  const [strategy, setStrategy] = useState<StrategyChoice>(BALANCED);
  const [pos, setPos] = useState("Hepsi");
  const [view, setView] = useState<"stats" | "impact">("stats");
  const [data, setData] = useState<WaiverOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    setBusy(true);
    api.waiver(league.id, team, toStrategyIn(strategy), injuries)
      .then((d) => { setData(d); setError(null); })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  }, [league.id, team, strategy, injuries]);

  const want = pos === "G" ? ["PG", "SG"] : pos === "F" ? ["SF", "PF"] : [pos];
  const rows = (data?.rows ?? []).filter((r) => pos === "Hepsi" || r.add.positions.some((p) => want.includes(p)));
  const maxDp = Math.max(0.02, ...rows.flatMap((r) => Object.values(r.dp).map((v) => Math.abs(v))));

  return (
    <div className="stack">
      <p className="desc">Kalan sezon için her boştaki oyuncu ve kadrondan en iyi bırakma eşi. Pozisyon kuralı korunur; IL'dekiler bırakılmaz.
        Havuz, yüklenen oyuncu sayfalarındakilerdir (Yahoo sıralamasında ilk ~750): "en iyi" yüklenen havuzda en iyidir; oyuncu
        hâlâ boştaysa ve waiver'da değilse geçerli.</p>
      {data && <WaiverInfo data={data} />}
      <div className="toolbar" style={{ marginBottom: 0 }}>
        <StrategyPicker meta={meta} value={strategy} onChange={setStrategy} label="Senin stratejin" />
        <div className="field"><span>Pozisyon</span>
          <div className="seg">{POSITIONS.map((p) => <button key={p} aria-pressed={pos === p} onClick={() => setPos(p)}>{p}</button>)}</div>
        </div>
        <div className={"field" + (mobile ? " only-desktop" : "")}><span>Görünüm</span>
          <div className="seg">
            <button aria-pressed={view === "stats"} onClick={() => setView("stats")}>İstatistik</button>
            <button aria-pressed={view === "impact"} onClick={() => setView("impact")}>Takımına etkisi</button>
          </div>
        </div>
        {busy && <span className="spinner" />}
      </div>
      <ErrorBanner error={error} />
      {!data && busy && <Loading />}
      {data && (
        <div className="card">
          {mobile && (
            <ul className="m-list">
              {rows.map((r) => (
                <li key={r.add.id} className="m-item">
                  <div className="m-line"><span className="m-lbl add">Al</span>
                    <span className="pname">{r.add.name}</span><AvailBadge a={r.add.availability} /><StatusBadges p={r.add} />
                    <span className="psub">{r.add.nba_team} · {r.add.positions.join(", ")}</span></div>
                  <div className="m-line"><span className="m-lbl drop">Bırak</span><PlayerName p={r.drop} sub={false} /></div>
                  <div className="m-line">
                    <span className={"m-big " + (r.score > 0.005 ? "good" : r.score < -0.005 ? "bad" : "")}>{fmtDelta(r.score, 3)}</span>
                    <span className="m-kv">strateji · ΔECW <b>{fmtDelta(r.delta_ecw, 3)}</b></span>
                    <span className="spacer" />
                    <span className="m-kv">maç: bu hafta <b>{r.games_this_week}</b> · gelecek <b>{r.games_next_week}</b></span>
                  </div>
                  <div className="m-line"><CategoryChips deltas={r.dp} labels={labels} k={4} /></div>
                </li>
              ))}
              {!rows.length && <li className="empty">Bu filtrede oyuncu yok</li>}
            </ul>
          )}
          <div className={"table-wrap" + (mobile ? " only-desktop" : "")}>
            <table className="data">
              <thead><tr>
                <th className="l">Al</th><th className="l">Bırak</th>
                <th title="Kalan sezonda rakip başına haftalık kategori değişimi (stratejinle)">Strateji Δ</th>
                <th title="Ağırlıksız">ΔECW</th>
                {meta.categories.map((c) => <th key={c.key}>{c.label}</th>)}
                <th title={`Bu haftanın kalan ${data.days_this_week} gününde`}>Bu hafta</th><th>Gelecek hafta</th><th>GP</th>
              </tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.add.id}>
                    <td className="l"><span className="pname">{r.add.name}</span><AvailBadge a={r.add.availability} /><StatusBadges p={r.add} />
                      <div className="psub">{r.add.nba_team} · {r.add.positions.join(", ")}</div></td>
                    <td className="l"><PlayerName p={r.drop} sub={false} /></td>
                    <td className={deltaClass(r.score, 0.25)}>{fmtDelta(r.score, 3)}</td>
                    <td>{fmtDelta(r.delta_ecw, 3)}</td>
                    {meta.categories.map((c) => view === "stats"
                      ? <td key={c.key} className={zClass(r.add.z[c.key])}>{fmtStat(c.key, r.add.stats[c.key])}</td>
                      : <td key={c.key} className={deltaClass(r.dp[c.key], maxDp)}>{fmtDelta(r.dp[c.key] * 100, 1)}</td>)}
                    <td>{r.games_this_week}</td><td>{r.games_next_week}</td><GpCell p={r.add} />
                  </tr>
                ))}
                {!rows.length && <tr><td colSpan={meta.categories.length + 7} className="empty">Bu filtrede oyuncu yok</td></tr>}
              </tbody>
            </table>
          </div>
          <div className="hint" style={{ padding: "0 14px 12px" }}>
            İstatistik: kalan sezon maç başı, renk seviyesi. Takımına etkisi: kategori kazanma olasılığındaki puan değişimi
            (ortalama rakibe karşı). FA hemen alınır; W → gün: waiver'dan o gün çıkar (Yahoo senkronizasyonu). Can't Cut doğrulanmadı.
          </div>
        </div>
      )}
      {data && data.drops.length > 0 && (
        <div className="card">
          <div className="card-h"><h3>Kadrondaki en kolay yerine konanlar</h3></div>
          <table className="data">
            <thead><tr><th className="l">Bırak</th><th className="l">Yerine en iyi</th><th>Strateji Δ</th></tr></thead>
            <tbody>{data.drops.map((d) => (
              <tr key={d.drop.id}><td className="l"><PlayerName p={d.drop} /></td><td className="l"><PlayerName p={d.best_add} /></td>
                <td className={deltaClass(d.score, 0.25)}>{fmtDelta(d.score, 3)}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
