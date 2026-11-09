import { useEffect, useState } from "react";
import { api } from "../api";
import { fmtStamp } from "../format";
import type { ReportedTrade, TradeIn } from "../types";

const STATUS: Record<ReportedTrade["status"], { label: string; cls: string; tip: string }> = {
  confirmed: { label: "kadrolarda", cls: "fa", tip: "Güncel kadrolarda oyuncular yer değiştirmiş" },
  partial: { label: "kısmen", cls: "q", tip: "Oyuncuların yalnız bir kısmı yer değiştirmiş" },
  pending: { label: "bekliyor", cls: "il", tip: "Güncel kadrolarda henüz görünmüyor: yeni Yahoo güncellemesi gerekir" },
};

/** "Bu takası yaptım": takas kayda geçer (veri değişmez); sonraki içe aktarmada kadrolarla karşılaştırılır. */
export function ReportedTrades({ league, body }: { league: string; body: TradeIn | null }) {
  const [rows, setRows] = useState<ReportedTrade[] | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const load = () => api.reportedTrades(league).then(setRows).catch(() => setRows(null));
  useEffect(() => { load(); setMsg(null); }, [league]);  // eslint-disable-line react-hooks/exhaustive-deps

  const report = () => {
    if (!body) return;
    api.reportTrade(league, body)
      .then(() => { setMsg("Kaydedildi. Veri değişmedi; bir sonraki Yahoo güncellemesinde kadrolarla karşılaştırılır."); load(); })
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
      {msg && <span className="hint" style={{ marginLeft: 10 }}>{msg}</span>}
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
