import { useState } from "react";
import { fmtDelta, fmtPct } from "../format";

export interface ImpactRow {
  key: string;
  label: string;
  before: number;          // 0–1 olasılık
  after: number;
}

/** Kategori başına kazanma olasılığı değişimi (yüzde puan): sıfır merkezli iki yönlü yatay çubuklar.
 *  Değer her satırda sayı olarak yazılır; renk yalnızca yönü pekiştirir. */
export function CategoryImpact({ rows, scale }: { rows: ImpactRow[]; scale?: number }) {
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);
  const deltas = rows.map((r) => (r.after - r.before) * 100);
  const max = scale ?? Math.max(5, ...deltas.map((d) => Math.abs(d)));
  return (
    <div className="impact" onMouseLeave={() => setTip(null)}>
      {rows.map((r, i) => {
        const d = deltas[i];
        const w = Math.min(Math.abs(d) / max, 1) * 50;
        return (
          <div
            key={r.key}
            className="impact-row"
            onMouseMove={(e) =>
              setTip({ x: e.clientX + 12, y: e.clientY + 12,
                       text: `${r.label}: ${fmtPct(r.before)} → ${fmtPct(r.after)} (${fmtDelta(d, 1)} puan)` })}
          >
            <span className="lab">{r.label}</span>
            <div className="track">
              {Math.abs(d) >= 0.05 && <div className={"bar " + (d > 0 ? "pos" : "neg")} style={{ width: `${w}%` }} />}
            </div>
            <span className={"val " + (d >= 0.5 ? "good" : d <= -0.5 ? "bad" : "")}>{fmtDelta(d, 1)}</span>
          </div>
        );
      })}
      {tip && <div className="tip" style={{ left: tip.x, top: tip.y }}>{tip.text}</div>}
    </div>
  );
}
