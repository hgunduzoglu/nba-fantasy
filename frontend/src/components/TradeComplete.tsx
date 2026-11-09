import { CategoryChips, ErrorBanner, deltaClass } from "./common";
import { fmtDelta, fmtNum, fmtPct } from "../format";
import type { CompleteOut, CompletePlayer, CompleteRow, CompleteTier } from "../types";

const TITLES: Record<CompleteOut["kind"], string> = {
  get: "Karşılığında ne isteyebilirsin",
  give: "Karşılığında ne verebilirsin",
  balance: "Dengeleme önerileri",
};

const TIER: Record<CompleteTier, { label: string; cls: string; tip: string }> = {
  mutual: { label: "ikisi de kazanır", cls: "fa", tip: "Seçilen stratejilerle iki takımın da kalan sezon puanı artıyor" },
  own: { label: "sen kazanırsın", cls: "q",
         tip: "Model rakibin kaybettiğini söylüyor; ama değer ve rakibin gözündeki denge eşikleri geçtiği için kabul edebilir" },
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

/** Takas ekranındaki seçimden tamamlama/dengeleme önerileri; "Uygula" paketi takas ekranına taşır. */
export function TradeComplete({ data, busy, error, base, oppName, labels, mobile, isApplied, onApply, onClose }: {
  data: CompleteOut | null; busy: boolean; error: string | null; base: string; oppName: string;
  labels: Record<string, string>; mobile: boolean; isApplied: (r: CompleteRow) => boolean;
  onApply: (r: CompleteRow) => void; onClose: () => void;
}) {
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
        <button className="btn" onClick={onClose}>Kapat</button>
      </div>
      <div className="card-b">
        <ErrorBanner error={error} />
        {!data && busy && <div className="muted">Paketler taranıyor…</div>}
        {data && (
          <>
            {data.current && (
              <div className="banner">
                Şu anki seçim: <Tier t={data.current.tier} /> · sen <b className={sign(data.current.own_delta)}>{fmtDelta(data.current.own_delta, 3)}</b>
                {" "}· {oppName} <b className={sign(data.current.other_delta)}>{fmtDelta(data.current.other_delta, 3)}</b>
                {" "}· değer dengesi <b>{fmtPct(data.current.fairness)}</b> · rakibin gözünde <b>{fmtNum(data.current.perceived_view, 2)}</b>
              </div>
            )}
            {data.message && <div className="banner">{data.message}</div>}
            {mobile ? (
              <ul className="m-list">
                {data.suggestions.map((r, i) => (
                  <li key={i} className="m-item">
                    <div className="m-line"><Tier t={r.tier} /><span className="spacer" />
                      {isApplied(r) ? <span className="muted">seçili</span>
                        : <button className="btn" onClick={() => onApply(r)}>Uygula</button>}</div>
                    <div className="m-line"><span className="m-lbl drop">Ver</span><Pkg players={r.give_a} /></div>
                    <div className="m-line"><span className="m-lbl add">Al</span><Pkg players={r.give_b} /></div>
                    <div className="m-line">
                      <span className="m-kv">sen <b className={sign(r.own_delta)}>{fmtDelta(r.own_delta, 3)}</b></span>
                      <span className="m-kv">rakip <b className={sign(r.other_delta)}>{fmtDelta(r.other_delta, 3)}</b></span>
                      <span className="m-kv">denge <b>{fmtPct(r.fairness)}</b></span>
                      <span className="m-kv">gözünde <b>{fmtNum(r.perceived_view, 2)}</b></span>
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
                    <th title="Kalan sezon piyasa değeri: küçük paket / büyük paket">Değer dengesi</th>
                    <th title="Rakibin gözünden (bu sezon + isim değeri): aldığı / verdiği. 1 = eşit görür.">Rakibin gözünde</th>
                    <th className="l" title="Senin kategori kazanma olasılığı değişimi (puan)">Kategoriler</th><th />
                  </tr></thead>
                  <tbody>
                    {data.suggestions.map((r, i) => (
                      <tr key={i} className={isApplied(r) ? "rec" : ""} title={extras(r).join(" · ") || undefined}>
                        <td className="l"><Tier t={r.tier} /></td>
                        <td className="l wrap"><Pkg players={r.give_a} /></td>
                        <td className="l wrap"><Pkg players={r.give_b} /></td>
                        <td className={deltaClass(r.own_delta, 0.3)}>{fmtDelta(r.own_delta, 3)}</td>
                        <td className={deltaClass(r.other_delta, 0.3)}>{fmtDelta(r.other_delta, 3)}</td>
                        <td>{fmtDelta(r.own_win * 100, 1)}</td>
                        <td>{fmtPct(r.fairness)}</td>
                        <td>{fmtNum(r.perceived_view, 2)}</td>
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
              {data.examined} paket incelendi; değer dengesi en az %{Math.round(data.min_fairness * 100)} ve rakibin gözünde en az
              {" "}{fmtNum(data.min_view, 2)} olanlar listelenir (kabul edilebilirlik). Yeşil "+" oyuncular öneriyle eklenenler.
              "Uygula" paketi yukarıya taşır ve tam analizi açar; liste açık kalır, başka seçeneği de deneyebilirsin.
              {data.limit_reached ? " Tarama sınırına ulaşıldı." : ""}
            </p>
          </>
        )}
      </div>
    </div>
  );
}
