import { useEffect, useState } from "react";
import { AcceptBadge, CategoryChips, ErrorBanner, MovesWarnBadge, SeasonDeltaCell, SeasonWarnBadge, deltaClass, seasonWarning } from "./common";
import { fmtDelta, fmtNum, fmtPct } from "../format";
import type { CompleteOut, CompletePlayer, CompleteRow, CompleteTier, SeasonEffect, SeasonManyOut } from "../types";

const TITLES: Record<CompleteOut["kind"], string> = {
  get: "Karşılığında ne isteyebilirsin",
  give: "Karşılığında ne verebilirsin",
  balance: "Dengeleme önerileri",
};

const TIER: Record<CompleteTier, { label: string; cls: string; tip: string }> = {
  mutual: { label: "ikisi de kazanır", cls: "fa", tip: "Seçilen stratejilerle iki takımın da kalan sezon puanı artıyor" },
  own: { label: "sen kazanırsın", cls: "q",
         tip: "Model rakibin kaybettiğini söylüyor; rakip kendi gözünde (draft fiyatı + bu sezon) eşit ya da fazla aldığı için kabul edebilir" },
  loss: { label: "sen kaybedersin", cls: "out", tip: "Bu eşiklerde senin puanın artmıyor" },
};

export const sameIds = (set: Set<string>, ids: string[]) => set.size === ids.length && ids.every((x) => set.has(x));

function Pkg({ players }: { players: CompletePlayer[] }) {
  return (
    <span className="pkg">
      {players.map((p) => (
        <span key={p.id} className={"chip" + (p.added ? " add" : "")} title={p.added ? "öneriyle eklenen" : "senin seçimin"}>
          {p.added ? "+ " : ""}{p.name}
        </span>
      ))}
    </span>
  );
}

function Tier({ t }: { t: CompleteTier }) {
  return <span className={"badge " + TIER[t].cls} title={TIER[t].tip}>{TIER[t].label}</span>;
}

type Order = "score" | "playoff" | "champion";

/** Takas ekranındaki seçimden tamamlama/dengeleme önerileri; "Uygula" paketi takas ekranına taşır. ``onSeason``
 * verilirse öneriler sezon simülasyonuyla (playoff, şampiyonluk) da değerlendirilip ona göre sıralanabilir. */
export function TradeComplete({ data, busy, error, base, oppName, labels, mobile, isApplied, onApply, onClose, onSeason }: {
  data: CompleteOut | null; busy: boolean; error: string | null; base: string; oppName: string;
  labels: Record<string, string>; mobile: boolean; isApplied: (r: CompleteRow) => boolean;
  onApply: (r: CompleteRow) => void; onClose: () => void;
  onSeason?: (rows: CompleteRow[]) => Promise<SeasonManyOut>;
}) {
  const [season, setSeason] = useState<{ effects: (SeasonEffect | "err")[]; n: number } | null>(null);
  const [seasonBusy, setSeasonBusy] = useState(false);
  const [seasonErr, setSeasonErr] = useState<string | null>(null);
  const [order, setOrder] = useState<Order>("score");
  const runSeason = () => {
    if (!data || !onSeason) return;
    setSeasonBusy(true);
    setSeasonErr(null);
    onSeason(data.suggestions)
      .then((out) => setSeason({ n: out.n_sims, effects: data.suggestions.map((_, i) => {
        const r = out.trades.find((t) => t.index === i);
        return r && "teams" in r ? r.teams.a : "err";
      }) }))
      .catch((e: Error) => setSeasonErr(e.message))
      .finally(() => setSeasonBusy(false));
  };
  // liste gelince sezon etkisi kendiliğinden hesaplanır (haftalık puan zamanlamayı görmez)
  useEffect(() => {
    setSeason(null); setSeasonErr(null); setOrder("score");
    if (data && data.suggestions.length && onSeason) runSeason();
  }, [data]);  // eslint-disable-line react-hooks/exhaustive-deps
  const eff = (i: number): SeasonEffect | "err" | undefined => season?.effects[i];
  const warn = (i: number, r: CompleteRow) => {
    const p = part(i, "playoff");
    return seasonWarning(r.own_delta, p === "err" ? undefined : p);
  };
  const part = (i: number, k: "playoff" | "champion") => {
    const e = eff(i);
    return e === "err" ? "err" : e?.[k];
  };
  const key = (i: number) => {
    const d = part(i, order === "playoff" ? "playoff" : "champion");
    return d && d !== "err" ? d.delta : -9;
  };
  const shown = data ? data.suggestions.map((r, i) => ({ r, i })) : [];
  if (season && order !== "score") shown.sort((x, y) => key(y.i) - key(x.i));
  const sign = (d: number) => (d > 0.005 ? "good" : d < -0.005 ? "bad" : "");
  const extras = (r: CompleteRow) => Object.values(r.adjustments).flatMap((a) => [
    ...a.move_to_il.map((x) => `${x} → IL`), ...a.drop.map((x) => `${x} bırakılır`), ...a.add.map((x) => `${x} boştan`)]);
  return (
    <div className="card complete-card">
      <div className="card-h">
        <h3>{data ? TITLES[data.kind] : "Öneriler"}</h3>
        <span className="muted">{base}</span>
        <span className="spacer" style={{ flex: 1 }} />
        {busy && <span className="spinner" aria-label="aranıyor" />}
        {season && (
          <div className="seg" role="group" aria-label="Sıralama">
            <button aria-pressed={order === "score"} onClick={() => setOrder("score")}
                    title="Kalan sezon kategori kazancı + haftalık galibiyet (varsayılan sıra)">Model puanı</button>
            <button aria-pressed={order === "playoff"} onClick={() => setOrder("playoff")}>Δ playoff</button>
            <button aria-pressed={order === "champion"} onClick={() => setOrder("champion")}>Δ şampiyonluk</button>
          </div>
        )}
        {onSeason && data && data.suggestions.length > 0 && !season && (
          <button className="btn" onClick={runSeason} disabled={seasonBusy}
                  title="Her öneri için kalan sezon ve playoff braketi simüle edilir (aynı çekilişlerle takassız/takaslı)">
            {seasonBusy ? <><span className="spinner" /> Sezon simüle ediliyor…</> : "Sezon etkisini hesapla"}
          </button>
        )}
        <button className="btn" onClick={onClose}>Kapat</button>
      </div>
      <div className="card-b">
        <ErrorBanner error={error} />
        <ErrorBanner error={seasonErr} />
        {!data && busy && <div className="muted">Paketler taranıyor…</div>}
        {data && (
          <>
            {data.current && (
              <div className="banner">
                Şu anki seçim: <Tier t={data.current.tier} /> · sen <b className={sign(data.current.own_delta)}>{fmtDelta(data.current.own_delta, 3)}</b>
                {" "}· {oppName} <b className={sign(data.current.other_delta)}>{fmtDelta(data.current.other_delta, 3)}</b>
                {" "}· değer dengesi <b>{fmtPct(data.current.fairness)}</b> · rakibin gözünde <b>{fmtNum(data.current.perceived_view, 2)}</b>
                {" "}· rakip için gerekçe <AcceptBadge level={data.current.acceptability} reasons={data.current.counterpart_reasons} />
              </div>
            )}
            {data.message && <div className="banner">{data.message}</div>}
            {mobile ? (
              <ul className="m-list">
                {shown.map(({ r, i }) => (
                  <li key={i} className="m-item">
                    <div className="m-line"><Tier t={r.tier} /><SeasonWarnBadge show={warn(i, r)} /><MovesWarnBadge own={r.own_delta} plain={r.own_delta_plain} /><span className="spacer" />
                      {isApplied(r) ? <span className="muted">seçili</span>
                        : <button className="btn" onClick={() => onApply(r)}>Uygula</button>}</div>
                    <div className="m-line"><span className="m-lbl drop">Ver</span><Pkg players={r.give_a} /></div>
                    <div className="m-line"><span className="m-lbl add">Al</span><Pkg players={r.give_b} /></div>
                    <div className="m-line">
                      <span className="m-kv">sen <b className={sign(r.own_delta)}>{fmtDelta(r.own_delta, 3)}</b></span>
                      <span className="m-kv">rakip <b className={sign(r.other_delta)}>{fmtDelta(r.other_delta, 3)}</b></span>
                      <span className="m-kv">denge <b>{fmtPct(r.fairness)}</b></span>
                      <span className="m-kv">gözünde <b>{fmtNum(r.perceived_view, 2)}</b></span>
                      <span className="m-kv">kabul <AcceptBadge level={r.acceptability} reasons={r.counterpart_reasons} /></span>
                      {(() => {
                        const po = part(i, "playoff"), ch = part(i, "champion");
                        if (!ch || ch === "err") return null;
                        return <span className="m-kv">playoff <b>{po && po !== "err" ? fmtDelta(po.delta * 100, 1) : "—"}</b>
                          {" "}şamp. <b>{fmtDelta(ch.delta * 100, 1)}</b></span>;
                      })()}
                    </div>
                    <div className="m-line"><CategoryChips deltas={r.my_categories} labels={labels} /></div>
                  </li>
                ))}
              </ul>
            ) : data.suggestions.length > 0 && (
              <div className="table-wrap">
                <table className="data">
                  <thead><tr>
                    <th className="l">Tür</th><th className="l">Veriyorsun</th><th className="l">Alıyorsun</th>
                    <th title="Senin stratejine göre kalan sezon puanı değişimi">Sen Δ</th>
                    <th title="Rakibin stratejisine göre">Rakip Δ</th>
                    <th title="Haftayı kazanma P(5+) değişimi, ortalama rakibe karşı">Sen P(5+)</th>
                    <th title="Küçük paket / büyük paket: modelin kalan sezon değerinde ya da menajerlerin algıladığı değerde (draft fiyatı + bu sezon), hangisi yüksekse">Değer dengesi</th>
                    <th title="Rakibin gözünden (bu sezon + isim değeri, yani draft fiyatı): aldığı / verdiği. 1 = eşit görür.">Rakibin gözünde</th>
                    <th title="Rakip için kabul gerekçesi: modelde kazanıyor mu, kendi gözünde eşit ya da fazla alıyor mu. İkisi yüksek, biri orta. Olasılık değil.">Kabul gerekçesi</th>
                    {season && <th title="Senin playoff olasılığı değişimi (puan), sezon simülasyonu">Playoff</th>}
                    {season && <th title="Senin şampiyonluk olasılığı değişimi (puan), sezon simülasyonu">Şamp.</th>}
                    <th className="l" title="Senin kategori kazanma olasılığı değişimi (puan)">Kategoriler</th><th />
                  </tr></thead>
                  <tbody>
                    {shown.map(({ r, i }) => (
                      <tr key={i} className={isApplied(r) ? "rec" : ""} title={extras(r).join(" · ") || undefined}>
                        <td className="l"><Tier t={r.tier} /><SeasonWarnBadge show={warn(i, r)} /><MovesWarnBadge own={r.own_delta} plain={r.own_delta_plain} /></td>
                        <td className="l wrap"><Pkg players={r.give_a} /></td>
                        <td className="l wrap"><Pkg players={r.give_b} /></td>
                        <td className={deltaClass(r.own_delta, 0.3)}>{fmtDelta(r.own_delta, 3)}</td>
                        <td className={deltaClass(r.other_delta, 0.3)}>{fmtDelta(r.other_delta, 3)}</td>
                        <td>{fmtDelta(r.own_win * 100, 1)}</td>
                        <td>{fmtPct(r.fairness)}</td>
                        <td>{fmtNum(r.perceived_view, 2)}</td>
                        <td><AcceptBadge level={r.acceptability} reasons={r.counterpart_reasons} /></td>
                        {season && <SeasonDeltaCell d={part(i, "playoff")} />}
                        {season && <SeasonDeltaCell d={part(i, "champion")} scale={0.05} />}
                        <td className="l"><CategoryChips deltas={r.my_categories} labels={labels} /></td>
                        <td>{isApplied(r) ? <span className="muted">seçili</span>
                          : <button className="btn" onClick={() => onApply(r)}>Uygula</button>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="hint">
              {data.examined} paket incelendi; değer dengesi en az %{Math.round(data.min_fairness * 100)} ve rakibin gözünde
              {" "}{fmtNum(data.min_view, 2)}–{fmtNum(data.max_view, 2)} arası olanlar listelenir (kabul edilebilirlik; üstü
              piyasa gözünde senin fazla ödemen{data.rejected_overpay ? `, ${data.rejected_overpay} paket` : ""}). Rakibin hem
              modelde hem kendi gözünde kaybettiği paketler (rakip için gerekçe yok) gösterilmez{data.rejected_reason ? ` (${data.rejected_reason} paket)` : ""}.
              Yeşil "+" oyuncular öneriyle eklenenler.
              "Uygula" paketi yukarıya taşır ve tam analizi açar; liste açık kalır, başka seçeneği de deneyebilirsin.
              {data.limit_reached ? " Tarama sınırına ulaşıldı." : ""}
              {season && ` Sezon etkisi: ${season.n} simülasyon, takassız ve takaslı sezon aynı çekilişlerle; "≈" farkın simülasyon
              hata payı içinde kaldığını gösterir. Kadrolar sezon boyu sabit, olasılıklar kalibre edilmedi; varsayılan sıra model puanıdır.`}
            </p>
          </>
        )}
      </div>
    </div>
  );
}
