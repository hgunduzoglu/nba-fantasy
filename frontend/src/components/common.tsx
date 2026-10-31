import type { BriefPlayer } from "../types";

export function PlayerName({ p, sub = true }: { p: BriefPlayer; sub?: boolean }) {
  return (
    <span>
      <span className="pname">{p.name}</span>
      {p.status === "O" && <span className="badge out">O</span>}
      {(p.status === "Q" || p.status === "GTD" || p.status === "DTD") && <span className="badge q">{p.status}</span>}
      {p.status === "NA" && <span className="badge il">NA</span>}
      {sub && <span className="psub" style={{ marginLeft: 6 }}>{p.nba_team} · {p.positions.join(", ")}</span>}
    </span>
  );
}

export function ErrorBanner({ error }: { error: string | null }) {
  return error ? <div className="banner err">{error}</div> : null;
}

export function Loading({ text = "Hesaplanıyor…" }: { text?: string }) {
  return <div className="empty"><span className="spinner" /> {text}</div>;
}

/** Olasılık hücresi için iki yönlü (0.5 = nötr) arka plan sınıfı. */
export function probClass(p: number | null | undefined): string {
  if (p === null || p === undefined) return "";
  if (p >= 0.75) return "z3";
  if (p >= 0.62) return "z2";
  if (p >= 0.55) return "z1";
  if (p <= 0.25) return "zm3";
  if (p <= 0.38) return "zm2";
  if (p <= 0.45) return "zm1";
  return "";
}

/** Değişim hücresi (+ iyi, − kötü) için sınıf; ``scale`` tam doygunluk eşiği. */
export function deltaClass(d: number | null | undefined, scale: number): string {
  if (d === null || d === undefined) return "";
  const r = d / scale;
  if (r >= 0.66) return "z3";
  if (r >= 0.33) return "z2";
  if (r >= 0.08) return "z1";
  if (r <= -0.66) return "zm3";
  if (r <= -0.33) return "zm2";
  if (r <= -0.08) return "zm1";
  return "";
}

/** En büyük ``k`` kategori olasılığı değişimi (puan): "FT% +12 · REB −5". Tümü başlıkta (title). */
export function CategoryChips({ deltas, labels, k = 3 }: {
  deltas: Record<string, number>; labels: Record<string, string>; k?: number;
}) {
  const items = Object.entries(deltas).map(([c, d]) => ({ c, d: d * 100 })).sort((a, b) => Math.abs(b.d) - Math.abs(a.d));
  const all = items.map((x) => `${labels[x.c] ?? x.c} ${x.d > 0 ? "+" : ""}${x.d.toFixed(1)}`).join(" · ");
  return (
    <span className="catchips" title={`Kategori kazanma olasılığı değişimi (puan): ${all}`}>
      {items.slice(0, k).filter((x) => Math.abs(x.d) >= 0.5).map((x) => (
        <span key={x.c} className={x.d > 0 ? "good" : "bad"}>{labels[x.c] ?? x.c} {x.d > 0 ? "+" : "−"}{Math.abs(x.d).toFixed(0)}</span>
      ))}
    </span>
  );
}

export function InlineBar({ value, max = 1 }: { value: number; max?: number }) {
  const w = Math.max(0, Math.min(1, value / max)) * 100;
  return <span className="ibar" aria-hidden="true"><span style={{ width: `${w}%` }} /></span>;
}
