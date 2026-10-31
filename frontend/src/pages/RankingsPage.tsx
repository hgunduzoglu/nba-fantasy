import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBanner, Loading, probClass } from "../components/common";
import { fmtNum, fmtPct, fmtStat } from "../format";
import type { League, Meta, RankingsOut, Source } from "../types";

/** Sıra hücresi: üst üçte bir iyi, alt üçte bir kötü (ligin büyüklüğüne göre). */
function rankClass(rank: number | null, n: number): string {
  if (rank === null) return "";
  const r = (rank - 1) / Math.max(1, n - 1);
  if (r <= 0.1) return "z3";
  if (r <= 0.25) return "z2";
  if (r <= 0.4) return "z1";
  if (r >= 0.9) return "zm3";
  if (r >= 0.75) return "zm2";
  if (r >= 0.6) return "zm1";
  return "";
}

export function RankingsPage({ meta, league, team, injuries }: { meta: Meta; league: League; team: string; injuries: boolean }) {
  const [source, setSource] = useState<Source>("ros");
  const [show, setShow] = useState<"ranks" | "totals" | "probs">("ranks");
  const [data, setData] = useState<RankingsOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    setBusy(true);
    api.rankings(league.id, source, injuries)
      .then((d) => { setData(d); setError(null); })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  }, [league.id, source, injuries]);

  useEffect(() => { if (source !== "ros" && show === "probs") setShow("ranks"); }, [source, show]);
  const n = data?.teams.length ?? 1;

  return (
    <div className="stack">
      <div className="toolbar" style={{ marginBottom: 0 }}>
        <div className="field"><span>Kaynak</span>
          <div className="seg">
            {(["ros", "season", "preseason"] as Source[]).map((s) => (
              <button key={s} aria-pressed={source === s} onClick={() => setSource(s)}>
                {s === "ros" ? "Kalan sezon" : s === "season" ? "Bu sezon" : "Sezon öncesi"}
              </button>
            ))}
          </div>
        </div>
        <div className="field"><span>Göster</span>
          <div className="seg">
            <button aria-pressed={show === "ranks"} onClick={() => setShow("ranks")}>Sıralar</button>
            <button aria-pressed={show === "totals"} onClick={() => setShow("totals")}>Toplamlar</button>
            {source === "ros" && <button aria-pressed={show === "probs"} onClick={() => setShow("probs")}>Kazanma olasılığı</button>}
          </div>
        </div>
        {busy && <span className="spinner" />}
      </div>
      <ErrorBanner error={error} />
      {!data && busy && <Loading />}
      {data && (
        <div className="card">
          <div className="table-wrap">
            <table className="data">
              <thead><tr>
                <th className="l">Takım</th>
                {meta.categories.map((c) => <th key={c.key}>{c.label}</th>)}
                <th>Ort. sıra</th>
                {source === "ros" && <><th title="Rakip başına beklenen kategori galibiyeti (tipik hafta)">ECW</th><th>P(5+)</th></>}
                <th title="Tam verili oyuncu / kadro">Kapsam</th>
              </tr></thead>
              <tbody>
                {data.teams.map((t) => (
                  <tr key={t.team_id} className={t.team_id === team ? "me" : ""}>
                    <td className="l pname">{t.team}</td>
                    {meta.categories.map((c) => {
                      if (show === "probs" && t.p) return <td key={c.key} className={probClass(t.p[c.key])}>{fmtPct(t.p[c.key])}</td>;
                      if (show === "totals") return <td key={c.key} className={rankClass(t.ranks[c.key], n)}>{c.key === "FG_PCT" || c.key === "FT_PCT" ? fmtStat(c.key, t.totals[c.key]) : fmtNum(t.totals[c.key], 0)}</td>;
                      return <td key={c.key} className={rankClass(t.ranks[c.key], n)}>{fmtNum(t.ranks[c.key], 0)}</td>;
                    })}
                    <td className="pname">{fmtNum(t.avg_rank)}</td>
                    {source === "ros" && <><td>{fmtNum(t.ecw, 2)}</td><td>{fmtPct(t.p5)}</td></>}
                    <td className="muted">{t.coverage.complete}/{t.coverage.roster}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="hint" style={{ padding: "0 14px 12px" }}>
            {data.mode_label}: mevcut kadroların oyuncu toplamları (bench ve IL dahil). 1 = en iyi; TO'da az olan iyidir. FG% = toplam FGM / toplam FGA.
          </div>
        </div>
      )}
    </div>
  );
}
