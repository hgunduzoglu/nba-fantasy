import { useEffect, useState } from "react";
import { api } from "../api";
import { fmtStamp } from "../format";
import { AcceptBadge } from "./common";
import type { OfferOutcome, OfferRow, ReportedTrade, TradeIn } from "../types";

const OUTCOME: Record<OfferOutcome, { label: string; cls: string }> = {
  pending: { label: "cevap bekliyor", cls: "il" }, accepted: { label: "kabul", cls: "fa" },
  rejected: { label: "ret", cls: "out" }, countered: { label: "karşı teklif", cls: "q" },
};

const STATUS: Record<ReportedTrade["status"], { label: string; cls: string; tip: string }> = {
  confirmed: { label: "kadrolarda", cls: "fa", tip: "Güncel kadrolarda oyuncular yer değiştirmiş" },
  partial: { label: "kısmen", cls: "q", tip: "Oyuncuların yalnız bir kısmı yer değiştirmiş" },
  pending: { label: "bekliyor", cls: "il", tip: "Güncel kadrolarda henüz görünmüyor: yeni Yahoo güncellemesi gerekir" },
};

/** "Bu takası yaptım": takas kayda geçer (veri değişmez); sonraki içe aktarmada kadrolarla karşılaştırılır. */
export function ReportedTrades({ league, body }: { league: string; body: TradeIn | null }) {
  const [rows, setRows] = useState<ReportedTrade[] | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [offers, setOffers] = useState<OfferRow[] | null>(null);
  const load = () => {
    api.reportedTrades(league).then(setRows).catch(() => setRows(null));
    api.offers(league).then(setOffers).catch(() => setOffers(null));
  };
  useEffect(() => { load(); setMsg(null); }, [league]);  // eslint-disable-line react-hooks/exhaustive-deps

  const report = () => {
    if (!body) return;
    api.reportTrade(league, body)
      .then(() => { setMsg("Kaydedildi. Veri değişmedi; bir sonraki Yahoo güncellemesinde kadrolarla karşılaştırılır."); load(); })
      .catch((e: Error) => setMsg(`Kaydedilemedi: ${e.message}`));
  };
  const offer = () => {
    if (!body) return;
    api.offer(league, { ...body, outcome: "offered" })
      .then(() => { setMsg("Teklif kaydedildi; cevap gelince aşağıdaki listeden işaretle."); load(); })
      .catch((e: Error) => setMsg(`Kaydedilemedi: ${e.message}`));
  };
  const answer = (o: OfferRow, outcome: "accepted" | "rejected" | "countered") => {
    const trade = { team_a: o.team_a, team_b: o.team_b, give_a: o.give_a.map((p) => p.id), give_b: o.give_b.map((p) => p.id), auto_balance: true, injuries: true };
    api.offer(league, { ...trade, outcome, about: o.decision_id }).then(load)
      .catch((e: Error) => setMsg(`Kaydedilemedi: ${e.message}`));
  };
  return (
    <div className="reported">
      {body && (
        <button className="btn" onClick={report}
                title="Bu takası Yahoo'da yaptıysan kaydet. Analiz verisini değiştirmez; yeni kadrolar gelince durum güncellenir.">
          ✓ Bu takası yaptım
        </button>
      )}
      {body && (
        <button className="btn" onClick={offer} style={{ marginLeft: 8 }}
                title="Bu takası rakibe teklif ettiysen kaydet: o anki kabul gerekçesi ve rakibin gözündeki oran saklanır. Cevabı sonra işaretlersin; kayıtlar biriktikçe eşikler gerçek cevaplarla ayarlanabilir.">
          Teklif ettim
        </button>
      )}
      {msg && <span className="hint" style={{ marginLeft: 10 }}>{msg}</span>}
      {offers && offers.length > 0 && (
        <details style={{ marginTop: 8 }}>
          <summary>Tekliflerin ({offers.length}; {offers.filter((o) => o.outcome === "pending").length} cevap bekliyor)</summary>
          <ul className="reported-list">
            {offers.map((o) => (
              <li key={o.decision_id}>
                <span className={"badge " + OUTCOME[o.outcome].cls} style={{ marginLeft: 0 }}>{OUTCOME[o.outcome].label}</span>{" "}
                {o.give_a.map((p) => p.name).join(", ")} → {o.give_b.map((p) => p.name).join(", ")}
                {o.acceptability && <> · gerekçe <AcceptBadge level={o.acceptability} /></>}
                <span className="muted"> · {fmtStamp(o.created_at)}</span>
                {o.outcome === "pending" && (
                  <span style={{ marginLeft: 6 }}>
                    <button className="link-btn" onClick={() => answer(o, "accepted")}>kabul</button>{" · "}
                    <button className="link-btn" onClick={() => answer(o, "rejected")}>ret</button>{" · "}
                    <button className="link-btn" onClick={() => answer(o, "countered")}>karşı teklif</button>
                  </span>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
      {rows && rows.length > 0 && (
        <details style={{ marginTop: 8 }}>
          <summary>Bildirdiğin takaslar ({rows.length})</summary>
          <ul className="reported-list">
            {rows.map((r) => (
              <li key={r.decision_id}>
                <span className={"badge " + STATUS[r.status].cls} style={{ marginLeft: 0 }} title={STATUS[r.status].tip}>
                  {STATUS[r.status].label}</span>{" "}
                {r.give_a.map((p) => p.name).join(", ") || "—"} → {r.give_b.map((p) => p.name).join(", ") || "—"}
                <span className="muted"> · {fmtStamp(r.created_at)}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
