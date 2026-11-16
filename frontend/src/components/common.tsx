import { fmtDate, fmtDelta } from "../format";
import type { Acceptability, Availability, BriefPlayer, SeasonDelta, SuggestionComponents } from "../types";

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

/** Uygulanabilirlik ve belirsizlik rozetleri; bütün bileşenler (senin faydan, rakibin gerekçesi, piyasa dengesi,
 * uygulanabilirlik, belirsizlik) üstüne gelince. Sıralama bunlardan bağımsızdır: varsayılan senin faydan. */
export function ComponentBadges({ c }: { c?: SuggestionComponents }) {
  if (!c) return null;
  const f = c.feasibility, u = c.uncertainty;
  const n = (v: number, d = 3) => (v >= 0 ? "+" : "") + v.toFixed(d);
  const tip = [
    `Senin faydan: ${n(c.own.strategy_delta)} kategori/hafta, hızlı modelde haftayı kazanma ${n(c.own.win_delta * 100, 1)} puan`,
    `Rakibin gerekçesi: ${c.opponent.reasons.join(" · ")}`,
    `Piyasa dengesi: değer ${(c.market.value_balance * 100).toFixed(0)}%` + (c.market.their_view != null ? `, rakibin gözünde ${c.market.their_view.toFixed(2)}` : ""),
    `Uygulanabilirlik: ${f.adds} ekleme, ${f.drops} bırakma; bu hafta kalan alım hakkı ${f.adds_left}${f.adds_known ? "" : " (kullanım bilinmiyor, limit varsayıldı)"}`,
    `Belirsizlik: ${[u.injured.length ? `sakat/dönüş bekleyen ${u.injured.join(", ")}` : "", u.unmodeled.length ? `modellenemeyen ${u.unmodeled.join(", ")}` : "",
      u.timing_unknown.length ? `takvimi bilinmeyen ${u.timing_unknown.join(", ")}` : "", u.moves_dependent ? "kazanç bedava hamlelere bağlı" : ""].filter(Boolean).join(" · ") || "belirgin bir kaynak yok"}`,
  ].join("\n");
  return (
    <>
      <span className="badge" style={{ marginLeft: 0 }} title={tip}>ⓘ</span>
      {!f.fits_this_week && <span className="badge out" title={tip}>⚠ alım hakkı</span>}
      {u.injured.length > 0 && <span className="badge q" title={tip}>sakat {u.injured.length}</span>}
      {(u.unmodeled.length > 0 || u.timing_unknown.length > 0) && <span className="badge q" title={tip}>? veri</span>}
    </>
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

/** Hızlı puanda kazanç var ama günlük kadroyla kalan sezonda kayıp (README §13.47). */
export function LineupWarnBadge({ own, lineup }: { own: number; lineup?: number | null }) {
  if (lineup == null || !(lineup < 0 && own > 0)) return null;
  return <span className="badge out" title={`Hızlı puanda kazanç (${fmtDelta(own, 3)}) var ama günlük kadroyla kalan sezonda kayıp (${fmtDelta(lineup, 3)}): pozisyon ya da maç çakışması yüzünden alınan oyuncunun maçları bench'te kalıyor.`}>⚠ günlük kadro</span>;
}

/** Takas farkı ileriye dönük testteki eşiğin altında: tek haftalık sonuçlarda işaret isabeti yazı tura düzeyine yakın. */
export function SignalBadge({ signal }: { signal?: string | null }) {
  if (signal !== "weak") return null;
  return <span className="badge muted" title="Fark, ileriye dönük testte ölçülen geçici eşiğin (config/noise.yaml) altında: bu büyüklükteki farkların yönü tek bir haftanın gerçek sonuçlarında ancak %50–64 doğru çıktı. Eşik daha uzun pencerelerle yeniden ölçülecek; tek başına karar sebebi değil.">zayıf sinyal</span>;
}

/** Günlük kadroyla kalan normal sezon farkı hücresi (ölçülmediyse —). */
export function LineupCell({ d }: { d?: number | null }) {
  return <td className={d != null ? deltaClass(d, 0.3) : "muted"}>{d != null ? fmtDelta(d, 3) : "—"}</td>;
}

export function DecisionBadge({ decision, method }: { decision?: string; method?: string }) {
  if (!decision) return null;
  const label = decision === "mutual" ? "ikisi de kazanır" : decision === "own" ? "yalnız senin faydan" :
    decision === "loss" ? "olumsuz senaryo" : decision === "unmeasured" ? "koşullu · hızlı model" : null;
  if (!label) return null;
  return <span className={"badge " + (decision === "mutual" ? "fa" : decision === "loss" ? "out" : "q")}
    title={method === "lineup" ? "İki taraf aynı günlük kadro yöntemiyle değerlendirildi." :
      "Hızlı model değerlendirmesi; günlük kadroyla karşılıklı fayda doğrulanmadı."}>{label}</span>;
}

export function InlineBar({ value, max = 1 }: { value: number; max?: number }) {
  const w = Math.max(0, Math.min(1, value / max)) * 100;
  return <span className="ibar" aria-hidden="true"><span style={{ width: `${w}%` }} /></span>;
}
