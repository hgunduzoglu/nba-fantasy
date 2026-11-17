import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { setProtected, useProtected } from "../protected";
import type { IndexPlayer, League } from "../types";

/** Korunan oyuncular: aramalarda takasa konmaz (README §13.54). Ad yazıp seç; çip × ile kaldır. */
export function ProtectedPicker({ league, injuries }: { league: League; injuries: boolean }) {
  const chosen = useProtected(league.id);
  const [index, setIndex] = useState<IndexPlayer[]>([]);
  const [text, setText] = useState("");
  useEffect(() => {
    let live = true;
    api.playersIndex(league.id, injuries, 0).then((r) => { if (live) setIndex(r); }).catch(() => { if (live) setIndex([]); });
    return () => { live = false; };
  }, [league.id, injuries]);
  const team = (id: string | null) => league.teams.find((t) => t.id === id)?.name ?? "";
  const byLabel = useMemo(() => new Map(index.map((p) => [`${p.name} (${team(p.team_id)})`, p])), [index]);
  const pick = (v: string) => {
    const p = byLabel.get(v);
    if (p) { setProtected(league.id, p.id, p.name); setText(""); } else setText(v);
  };
  return (
    <div className="field" style={{ minWidth: 260 }}
         title="Menajerin satılık değil dediği ya da senin vermek istemediğin oyuncular: öneri ve tamamlama aramasında takasa konmaz">
      <span>Korunan oyuncular</span>
      <div>
        {Object.entries(chosen).map(([id, name]) => (
          <span key={id} className="chip">🔒 {name}<button aria-label="kaldır" onClick={() => setProtected(league.id, id, null)}>×</button></span>
        ))}
        <input className="select" list={`protect-${league.id}`} placeholder="Oyuncu ekle…" value={text}
               onChange={(e) => pick(e.target.value)} style={{ minWidth: 180 }} />
        <datalist id={`protect-${league.id}`}>{[...byLabel.keys()].map((k) => <option key={k} value={k} />)}</datalist>
      </div>
    </div>
  );
}
