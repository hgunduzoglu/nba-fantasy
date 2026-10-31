import type { CategoryKey, Player } from "./types";

export const PCT_CATS: CategoryKey[] = ["FG_PCT", "FT_PCT"];

/** FG%/FT% Yahoo gibi ".478"; sayım kategorileri bir ondalık. */
export function fmtStat(cat: CategoryKey, v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  if (PCT_CATS.includes(cat)) return v.toFixed(3).replace(/^0/, "");
  return v.toFixed(1);
}

export function fmtNum(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return v.toFixed(digits);
}

export function fmtDelta(v: number | null | undefined, digits = 2, suffix = ""): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const s = v.toFixed(digits);
  return (v > 0 && Number(s) !== 0 ? "+" : "") + s + suffix;
}

export function fmtPct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return `%${(v * 100).toFixed(digits)}`;
}

/** z-skoru kademesi → hücre sınıfı (Elite ≥1.5 … Poor ≤−1.0); TO z'si zaten "iyi = pozitif". */
export function zClass(z: number | null | undefined): string {
  if (z === null || z === undefined || Number.isNaN(z)) return "";
  if (z >= 1.5) return "z3";
  if (z >= 1.0) return "z2";
  if (z >= 0.5) return "z1";
  if (z <= -1.0) return "zm3";
  if (z <= -0.5) return "zm2";
  if (z < -0.25) return "zm1";
  return "";
}

export function zLabel(z: number | null | undefined): string {
  if (z === null || z === undefined) return "";
  if (z >= 1.5) return "Elite";
  if (z >= 1.0) return "Great";
  if (z >= 0.5) return "Good";
  if (z <= -1.0) return "Poor";
  if (z <= -0.5) return "Below";
  return "Avg";
}

const MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"];

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const [, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]}`;
}

export function returnText(p: Player): string | null {
  const inj = p.injury;
  if (!inj) return null;
  if (inj.kind === "season") return "Sezon boyu yok";
  if (inj.kind === "out_until" && inj.return_date) return `Dönüş ~${fmtDate(inj.return_date)}`;
  if (inj.kind === "day_to_day") return "Gün gün";
  return inj.text || null;
}
