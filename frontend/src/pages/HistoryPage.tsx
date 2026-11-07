import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBanner, Loading } from "../components/common";
import { fmtDate, fmtStat } from "../format";
import type { HistoryOut, HistoryRow, League, Meta } from "../types";

interface Props {
  meta: Meta;
  league: League;
  team: string;
  injuries: boolean;
}

/** Hafta toplamı: oranlar üç basamak, sayımlar tam sayı. */
const show = (key: string, v: number | null | undefined) =>
  v == null ? "–" : key === "FG_PCT" || key === "FT_PCT" ? fmtStat(key, v) : Math.round(v).toLocaleString("tr-TR");

/** Lig sırası → iki yönlü renk sınıfı (üst üçte bir yeşil, alt üçte bir kırmızı; ortası nötr). */
function rankClass(rank: number, n: number): string {
  if (n < 2) return "";
  const q = (rank - 1) / (n - 1);                     // 0 = en iyi, 1 = en kötü
  if (q <= 0.1) return "z3";
  if (q <= 0.22) return "z2";
  if (q <= 0.34) return "z1";
  if (q >= 0.9) return "zm3";
  if (q >= 0.78) return "zm2";
  if (q >= 0.66) return "zm1";
  return "";
}

function Result({ r }: { r: HistoryRow }) {
  if (!r.result) return null;
  const { wins: w, losses: l } = r.result;
  const tag = w == null || l == null ? "" : w > l ? "G" : w < l ? "M" : "B";
  return (
    <span className={tag === "G" ? "good" : tag === "M" ? "bad" : "muted"}
          title={r.partial ? "Süren hafta: şu ana kadarki kategori skoru" : "Biten haftanın kategori skoru"}>
      {w ?? "–"}–{l ?? "–"}{r.result.ties ? `–${r.result.ties}` : ""}{r.partial ? " (sürüyor)" : ` ${tag}`}
    </span>
  );
}

export function HistoryPage({ meta, league, team, injuries }: Props) {
  const [data, setData] = useState<HistoryOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.history(league.id, team, injuries).then((d) => { setData(d); setError(null); })
      .catch((e: Error) => setError(e.message));
  }, [league.id, team, injuries]);

  if (!data && !error) return <Loading text="Geçmiş haftalar yükleniyor…" />;
  if (!data) return <ErrorBanner error={error} />;
  const cell = (r: HistoryRow, key: (typeof meta.categories)[number]["key"]) => {
    const rank = r.ranks[key];
    const tip = `${meta.categories.find((c) => c.key === key)?.label}: ${show(key, r.values[key])} · lig ortancası ${show(key, r.median[key])}`
      + ` · en iyi ${show(key, r.best[key])} · ${r.n_teams} takımda ${rank}.`;
    return (
      <td key={key} className={"heat " + rankClass(rank, r.n_teams)} title={tip}>
        <div className="heat-rank">{rank}</div><div className="psub">{show(key, r.values[key])}</div>
      </td>
    );
  };

  return (
    <div className="stack">
      <p className="desc">{data.team}: her hafta kategori toplamın ve ligdeki sıran (1 = en iyi, TO'da en az). Biten haftalar Yahoo'daki
        kesin toplamlar; süren hafta şu ana kadarki toplam. Üzerine gel: değer, lig ortancası ve haftanın en iyisi.</p>
      {!data.weeks.length && <div className="banner">Henüz hafta sonucu yok. Üstten "Yahoo'dan güncelle" ile biten haftaların toplamları çekilir.</div>}
      {data.weeks.length > 0 && (
        <div className="card">
          <div className="card-h"><h3>Haftalık kategori sıralaman</h3>
            <span className="muted">renk: ligin üst üçte biri yeşil, alt üçte biri kırmızı</span></div>
          <div className="table-wrap">
            <table className="data heatmap">
              <thead><tr><th className="l">Hafta</th><th className="l">Rakip</th><th>Skor</th>
                {meta.categories.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
              <tbody>
                {data.weeks.map((r) => (
                  <tr key={r.week} className={r.partial ? "partial" : ""}>
                    <td className="l pname">{r.week}. hafta<div className="psub">{r.start ? `${fmtDate(r.start)}–${fmtDate(r.end)}` : ""}</div></td>
                    <td className="l">{r.result?.opponent_name ?? ""}</td>
                    <td><Result r={r} /></td>
                    {meta.categories.map((c) => cell(r, c.key))}
                  </tr>
                ))}
                {data.season && (
                  <tr className="total">
                    <td className="l pname">Sezon</td><td className="l muted">biten haftaların toplamı</td><td />
                    {meta.categories.map((c) => cell(data.season!, c.key))}
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="legend">
            <span>Lig sırası:</span>
            <span><i className="z3" />üst %10</span><span><i className="z2" />üst</span><span><i className="z1" />ortanın üstü</span>
            <span><i style={{ background: "var(--mid)" }} />orta</span><span><i className="zm1" />ortanın altı</span>
            <span><i className="zm2" />alt</span><span><i className="zm3" />alt %10</span>
          </div>
        </div>
      )}
    </div>
  );
}
