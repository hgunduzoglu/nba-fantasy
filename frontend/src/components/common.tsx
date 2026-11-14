import { fmtDate, fmtDelta } from "../format";
import type { Acceptability, Availability, BriefPlayer, SeasonDelta } from "../types";

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

/** Boştaki oyuncunun alınabilirliği: FA hemen; waiver'daysa serbest kaldığı gün. */
export function AvailBadge({ a }: { a?: Availability | null }) {
  if (!a) return null;
  if (a.kind === "FA") return <span className="badge fa" title="Serbest oyuncu: hemen alınabilir">FA</span>;
  return <span className="badge w" title="Waiver'da: bu günden itibaren kadroya girer (FAB ligde teklif gerekir)">W → {fmtDate(a.from)}</span>;
}

const ACCEPT: Record<Acceptability, { label: string; cls: string }> = {
  high: { label: "yüksek", cls: "fa" }, medium: { label: "orta", cls: "q" }, low: { label: "düşük", cls: "out" },
};

/** Rakip için kabul gerekçesi (kalibre olasılık değil): rozet + üstüne gelince gerekçeler. */
export function AcceptBadge({ level, reasons }: { level?: Acceptability; reasons?: string[] }) {
  if (!level) return null;
  const a = ACCEPT[level];
  return <span className={"badge " + a.cls} style={{ marginLeft: 0 }}
               title={`Rakip için gerekçe: ${(reasons ?? []).join(" · ")}. Kabul olasılığı değildir.`}>{a.label}</span>;
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

/** Sezon simülasyonu farkı (puan): gürültüden ayrılmayan fark (|Δ| < 2·SE) soluk ve "≈" ile gösterilir. */
export function SeasonDeltaCell({ d, scale = 0.1 }: { d?: SeasonDelta | null | "err"; scale?: number }) {
  if (d === "err") return <td className="muted">—</td>;
  if (!d) return <td />;
  const pts = (x: number) => (x * 100).toFixed(1);
  const tip = `önce %${pts(d.before)} → sonra %${pts(d.after)} · simülasyon hata payı ±${pts(2 * d.se)} puan` +
    (d.clear ? "" : " (fark bu payın içinde: takassızdan ayırt edilemiyor)");
  return (
    <td className={d.clear ? deltaClass(d.delta, scale) : "muted"} title={tip}>
      {d.clear ? "" : "≈"}{fmtDelta(d.delta * 100, 1)}
    </td>
  );
}

/** Haftalık kazanç pozitif ama sezon simülasyonunda playoff olasılığı açıkça düşüyorsa uyarı (zamanlama). */
export function seasonWarning(ownDelta: number, playoff?: SeasonDelta | null): boolean {
  return !!playoff && playoff.clear && playoff.delta < 0 && ownDelta > 0;
}

export function SeasonWarnBadge({ show }: { show: boolean }) {
  return show ? <span className="badge out" title="Haftalık kategori kazancın var ama sezon simülasyonunda playoff olasılığın açıkça düşüyor. Çoğu zaman zamanlamadan: uzun süre sakat bir oyuncu playoff yarışı bittikten sonra döner, ya da fikstür haftaları tutmaz. Haftalık ortalama sezon sonundaki katkıyı bugünkü kadar değerli sayar; bu takası bu açıdan kontrol et.">⚠ sezon</span> : null;
}

/** Kazanç yalnız bedava waiver hamleleri varsayımıyla mı var (hamlesiz farkı ≤ 0)? */
export function movesWarning(own: number, plain?: number | null): boolean {
  return own > 0.005 && plain !== undefined && plain !== null && plain <= 0;
}

export function MovesWarnBadge({ own, plain }: { own: number; plain?: number | null }) {
  if (!movesWarning(own, plain)) return null;
  return <span className="badge out" title={`Bu kazanç, iki takımın boştaki daha iyi oyuncuları bedavaya aldığı varsayımına bağlı. O hamleler yapılmazsa (kadrolar olduğu gibi kalırsa) takas sana kaybettiriyor. Boştaki oyuncuları gerçekten alacak mısın, ona göre karar ver. Hamlesiz fark: ${fmtDelta(plain ?? 0, 3)}.`}>⚠ hamle</span>;
}

export function InlineBar({ value, max = 1 }: { value: number; max?: number }) {
  const w = Math.max(0, Math.min(1, value / max)) * 100;
  return <span className="ibar" aria-hidden="true"><span style={{ width: `${w}%` }} /></span>;
}
