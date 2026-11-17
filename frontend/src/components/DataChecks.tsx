import { useEffect, useState } from "react";
import { api } from "../api";
import type { DataCheck } from "../types";

const LABEL: Record<DataCheck["check"], string> = {
  unmodeled: "modelsiz", filled: "dolduruldu", team: "takım", role: "rol", idle: "oynamıyor", il_slot: "IL slotu",
};

/** Seçili takımların kadrolarındaki veri bulguları (README §13.52): modelsiz oyuncu, rol ya da takım değişimi, IL slotunda
 *  uygun olmayan durum. ``players`` verilirse bu oyuncular (ör. takastakiler) önce ve vurgulu gösterilir. Bulgu yoksa
 *  hiçbir şey çizilmez. */
export function DataChecks({ league, teams, injuries, players }: {
  league: string; teams: string[]; injuries: boolean; players?: string[];
}) {
  const [rows, setRows] = useState<DataCheck[] | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    let live = true;
    api.dataChecks(league, injuries).then((d) => { if (live) setRows(d.rows); }).catch(() => { if (live) setRows(null); });
    return () => { live = false; };
  }, [league, injuries]);
  const mine = (rows ?? []).filter((r) => r.teams.some((t) => teams.includes(t.team_id)));
  if (!mine.length) return null;
  const hot = new Set(players ?? []);
  const sorted = [...mine].sort((a, b) => Number(hot.has(b.player_id)) - Number(hot.has(a.player_id))
    || Number(a.level !== "warn") - Number(b.level !== "warn"));
  const warn = mine.filter((r) => r.level === "warn").length;
  const inTrade = mine.filter((r) => hot.has(r.player_id) && r.level === "warn");
  return (
    <div className={"banner " + (inTrade.length ? "err" : warn ? "warn" : "")} style={{ marginBottom: 12 }}>
      <button className="link-btn" onClick={() => setOpen((x) => !x)} style={{ fontWeight: 600 }}>
        {inTrade.length
          ? `⚠ Takastaki ${inTrade.length} oyuncuda veri uyarısı: ${inTrade.map((r) => r.name).join(", ")}`
          : `Veri kontrolü: ${warn} uyarı${mine.length > warn ? `, ${mine.length - warn} bilgi` : ""}`}
        {open ? " ▴" : " ▾"}
      </button>
      {open && (
        <ul style={{ margin: "6px 0 0 18px" }}>
          {sorted.map((r) => (
            <li key={r.check + r.player_id} style={hot.has(r.player_id) ? { fontWeight: 600 } : undefined}>
              <span className={"badge " + (r.level === "warn" ? "q" : "fa")}>{LABEL[r.check]}</span>{" "}
              <b>{r.name}</b>
              <span className="muted"> ({r.teams.filter((t) => teams.includes(t.team_id)).map((t) => t.team_name).join(", ")})</span>: {r.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
