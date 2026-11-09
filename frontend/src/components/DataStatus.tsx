import { useEffect, useState } from "react";
import { api } from "../api";
import { fmtStamp } from "../format";
import type { DecisionState, Freshness } from "../types";

const STATE: Record<DecisionState, { label: string; cls: string }> = {
  normal: { label: "güncel", cls: "fa" },
  conditional: { label: "koşullu", cls: "q" },
  hold: { label: "yenile", cls: "out" },
};
const BASIS: Record<string, string> = {
  captured: "", captured_on: " (dosya adındaki gün)", source: " (kaynak tarihi)", file: " (dosya zamanı; kaynak zamanı bilinmiyor)",
};
const ORDER = ["rosters", "player_stats", "live_week", "injuries", "news", "nba_logs", "results", "standings",
  "league_settings", "schedule", "preseason_projection", "adp", "draft"];

const age = (h: number | null) => (h == null ? "–" : h < 1 ? "<1 sa" : h < 48 ? `${Math.round(h)} sa` : `${Math.round(h / 24)} gün`);

/** Veri güncelliği: bileşen bazında yaş ve karar türüne göre durum (normal / koşullu / bekletilir). ``asOf``: kadro
 *  tarihi; ``inline``: telefondaki ayarlar panelinde açık liste. */
export function DataStatus({ asOf, inline = false }: { asOf: string; inline?: boolean }) {
  const [data, setData] = useState<Freshness | null>(null);
  const [open, setOpen] = useState(inline);
  useEffect(() => { api.freshness().then(setData).catch(() => setData(null)); }, [asOf]);
  const decisions = data ? Object.values(data.decisions) : [];
  const worst = (["hold", "conditional"] as DecisionState[]).find((s) => decisions.some((d) => d.state === s));
  const flagged = worst ? decisions.filter((d) => d.state === worst).map((d) => d.short).join(", ") : "";
  const panel = data && (
    <div className={inline ? "fresh" : "fresh sync-pop card"}>
      <div className="fresh-dec">
        {Object.entries(data.decisions).map(([k, d]) => (
          <div key={k}>
            <b>{d.label}</b> <span className={"badge " + STATE[d.state].cls}>{STATE[d.state].label}</span>
            {d.reasons.length > 0 && <div className="psub">{d.reasons.join(" · ")}</div>}
            {d.refresh.length > 0 && <div className="psub">→ {d.refresh.join(" · ")}</div>}
          </div>
        ))}
      </div>
      <table className="data fresh-tab">
        <tbody>
          {ORDER.filter((k) => data.components[k]).map((k) => {
            const c = data.components[k];
            return (
              <tr key={k} title={`${c.file}${BASIS[c.basis] ?? ""}`}>
                <td className="l wrap">{c.label}</td>
                <td>{age(c.age_hours)}</td>
                <td className="l muted">{c.as_of ? fmtStamp(c.as_of) : "–"}{c.basis === "file" ? " *" : ""}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="hint">* dosyada zaman kaydı yok, dosyanın değiştiği an. {data.assumption}</p>
      {!inline && <button className="btn" onClick={() => setOpen(false)}>Kapat</button>}
    </div>
  );
  if (inline) return panel || null;
  return (
    <div className="sync">
      <button className="link-btn muted" style={{ fontSize: 12, fontWeight: 400 }} onClick={() => setOpen((x) => !x)}
              title="Bileşen bazında veri güncelliği">
        Veri: {asOf}{worst && <span className={"badge " + STATE[worst].cls}>{flagged}: {STATE[worst].label}</span>}
      </button>
      {open && panel}
    </div>
  );
}

/** Karar sayfasının üstünde: veri bu karar için eskiyse ya da eksikse uyarı (normal durumda hiçbir şey). */
export function FreshnessBanner({ decision }: { decision: string }) {
  const [data, setData] = useState<Freshness | null>(null);
  useEffect(() => { api.freshness().then(setData).catch(() => setData(null)); }, []);
  const d = data?.decisions[decision];
  if (!d || d.state === "normal") return null;
  const head = d.state === "hold"
    ? `${d.label} için veri yetersiz; öneriler bekletilmeli`
    : `${d.label} önerileri koşullu: veri eski, oyuncu hâlâ boştaysa ve kadro aynıysa geçerli`;
  return (
    <div className={"banner " + (d.state === "hold" ? "err" : "warn")}>
      {head}. {d.reasons.join(" · ")}{d.refresh.length ? ` → ${d.refresh.join(" · ")}` : ""}
    </div>
  );
}
