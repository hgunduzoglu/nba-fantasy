import { useMemo, useState } from "react";
import { fmtNum } from "../format";
import type { Player } from "../types";

/** Aranabilir oyuncu seçici (boştaki oyuncular vb.). Enter ilk sonucu seçer. */
export function PlayerPicker({ players, exclude, onPick, placeholder = "Oyuncu ara…" }: {
  players: Player[]; exclude: Set<string>; onPick: (p: Player) => void; placeholder?: string;
}) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const norm = (s: string) => s.toLocaleLowerCase("tr").normalize("NFD").replace(/[̀-ͯ]/g, "");
  const hits = useMemo(() => {
    const q = norm(text.trim());
    return players.filter((p) => !exclude.has(p.id) && (!q || norm(p.name).includes(q))).slice(0, 8);
  }, [players, exclude, text]);
  const choose = (p: Player) => {
    onPick(p);
    setText("");
    setOpen(false);
  };
  return (
    <div className="picker">
      <input className="picker-input" value={text} placeholder={placeholder}
             onChange={(e) => { setText(e.target.value); setOpen(true); }}
             onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)}
             onKeyDown={(e) => { if (e.key === "Enter" && hits[0]) choose(hits[0]); if (e.key === "Escape") setOpen(false); }} />
      {open && hits.length > 0 && (
        <ul className="picker-list" role="listbox">
          {hits.map((p) => (
            <li key={p.id} role="option" aria-selected={false} onMouseDown={() => choose(p)}>
              <span className="pname">{p.name}</span>
              <span className="psub"> {p.nba_team} · {p.positions.join(", ")}{p.status ? ` · ${p.status}` : ""}</span>
              <span className="psub" style={{ float: "right" }}>değer {fmtNum(p.value)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
