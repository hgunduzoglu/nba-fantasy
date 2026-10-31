import { useState } from "react";
import { fmtDate, fmtDelta, fmtNum, fmtPct } from "../format";
import type { FixtureTeam } from "../types";
import { deltaClass, probClass } from "./common";

/** Fikstürdeki her hafta için haftayı kazanma olasılığı: takassız → takaslı. Takım seçilebilir (varsayılan sen). */
export function FixtureImpact({ teams, me }: { teams: FixtureTeam[]; me: string }) {
  const [pick, setPick] = useState(me);
  const t = teams.find((x) => x.team_id === pick) ?? teams[0];
  if (!t) return null;
  const dw = t.wins_after - t.wins_before;
  return (
    <div>
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", marginBottom: 8 }}>
        {teams.length > 1 && (
          <div className="seg" role="group" aria-label="Fikstürü gösterilen takım">
            {teams.map((x) => (
              <button key={x.team_id} aria-pressed={x.team_id === t.team_id} onClick={() => setPick(x.team_id)}>
                {x.team}
              </button>
            ))}
          </div>
        )}
        <span className="pill" title="Kalan normal sezon haftalarında kazanma olasılıklarının toplamı (beklenen galibiyet)">
          Beklenen galibiyet {fmtNum(t.wins_before, 1)} → {fmtNum(t.wins_after, 1)}{" "}
          <b className={dw > 0.05 ? "good" : dw < -0.05 ? "bad" : ""}>({fmtDelta(dw, 2)})</b>
        </span>
      </div>
      <div className="table-wrap">
        <table className="mini" style={{ maxWidth: 820 }}>
          <thead><tr>
            <th className="l">Hafta</th><th className="l">Rakip</th>
            <th title="Haftayı kazanma olasılığı (5+ kategori)">Kazanma: önce</th><th>Sonra</th><th>Fark</th>
            <th title="Beklenen kategori galibiyeti">Kategori: önce → sonra</th>
          </tr></thead>
          <tbody>
            {t.weeks.map((w) => {
              const d = w.p_after - w.p_before;
              return (
                <tr key={w.week}>
                  <td className="l">{w.week}. hafta <span className="psub">{w.start ? fmtDate(w.start) : ""}</span></td>
                  <td className="l">{w.opponent_name}{w.partner && <span className="badge q" title="Bu rakip de takasta: onun kadrosu da değişti">takasta</span>}</td>
                  <td className={probClass(w.p_before)}>{fmtPct(w.p_before)}</td>
                  <td className={probClass(w.p_after)}>{fmtPct(w.p_after)}</td>
                  <td className={deltaClass(d, 0.15)}>{fmtDelta(d * 100, 1)}</td>
                  <td>{fmtNum(w.exp_before, 2)} → {fmtNum(w.exp_after, 2)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="hint">Haftalık nokta tahmini (Sezon Simülasyonu'ndaki fikstür tablosuyla aynı model): o haftanın NBA maç
        sayısı, sakatlık dönüşleri ve IL'den dönüşte kadrodan çıkacak oyuncu dahil. Fark puan cinsindendir.</p>
    </div>
  );
}
